"""Local SQLite queue with ordered deck source membership. Every transaction is short lived."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path
from pydantic import TypeAdapter
from contracts.service_schema import JobRecord, JobKind, JobStatus, TERMINAL_STATUSES
from contracts.ingestion_schema import SourceSelection, ParseOptions, IngestionError

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, source_path TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 structural_ir_path TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decks (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 output_dir TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL,
 document_id TEXT REFERENCES documents(id), deck_id TEXT REFERENCES decks(id),
 status TEXT NOT NULL, request_json TEXT NOT NULL, stage TEXT, progress_json TEXT,
 result_json TEXT, error_json TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at, id);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


def _job(row):
    if row is None:
        return None
    values = dict(row)
    for name in ("request", "progress", "result", "error"):
        raw = values.pop(name + "_json")
        values[name] = json.loads(raw) if raw else None
    return JobRecord.model_validate(values)


class JobStore:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        with self.connection(immediate=True) as db:
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current > 1:
                raise ValueError("Database schema is newer than this application")
            if current == 0:
                backup = self.database.with_name(self.database.name + '.pre-f02.bak')
                if not backup.exists():
                    reader, target = sqlite3.connect(self.database), sqlite3.connect(backup)
                    try:
                        reader.backup(target)
                    finally:
                        reader.close(); target.close()
                columns = {r[1] for r in db.execute('PRAGMA table_info(documents)')}
                for column in ('upload_spec_json', 'last_parse_result_json'):
                    if column not in columns:
                        db.execute('ALTER TABLE documents ADD COLUMN ' + column + ' TEXT')
                db.execute('CREATE TABLE IF NOT EXISTS deck_documents (deck_id TEXT NOT NULL REFERENCES decks(id), '
                    'document_id TEXT NOT NULL REFERENCES documents(id), ordinal INTEGER NOT NULL, selection_json TEXT NOT NULL, '
                    'PRIMARY KEY(deck_id,document_id), UNIQUE(deck_id,ordinal))')
                for row in db.execute('SELECT id,document_id FROM decks').fetchall():
                    selection = self._capture(db, [SourceSelection(document_id=row['document_id'])])[0]
                    db.execute('INSERT OR IGNORE INTO deck_documents VALUES (?,?,0,?)',
                        (row['id'], row['document_id'], json.dumps(selection)))
                db.execute('PRAGMA user_version=1')

    @contextmanager
    def connection(self, *, immediate=False):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if immediate:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def document(self, document_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            return dict(row) if row else None

    def add_document(self, document_id, filename, source_path, source_sha256, size_bytes, upload_spec=None):
        with self.connection() as db:
            db.execute("INSERT INTO documents (id,filename,source_path,source_sha256,size_bytes,created_at,upload_spec_json) VALUES (?,?,?,?,?,?,?)",
                       (document_id, filename, str(source_path), source_sha256, size_bytes, now(),
                        json.dumps(upload_spec) if upload_spec else None))
        return self.document(document_id)

    def parse_outcome(self, document_id, result):
        with self.connection() as db:
            db.execute('UPDATE documents SET last_parse_result_json=? WHERE id=?', (json.dumps(result), document_id))

    def parsed(self, document_id, structural_ir_path):
        with self.connection() as db:
            db.execute("UPDATE documents SET structural_ir_path=? WHERE id=?", (str(structural_ir_path), document_id))

    def deck(self, deck_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
            return dict(row) if row else None

    def _enqueue(self, db, kind, request, document_id, deck_id):
        TypeAdapter(JobKind).validate_python(kind)
        request = dict(request)
        if 'sources' not in request:
            if kind == 'generate' and deck_id:
                request['sources'] = [json.loads(r['selection_json']) for r in db.execute(
                    'SELECT selection_json FROM deck_documents WHERE deck_id=? ORDER BY ordinal', (deck_id,))]
            elif kind == 'parse' and document_id:
                request['sources'] = self._capture(db, [SourceSelection(document_id=document_id,
                    selected_type=request.get('selected_type'), parse_options=request.get('parse_options', {}))])
        job_id = new_id()
        db.execute("INSERT INTO jobs (id,kind,document_id,deck_id,status,request_json,created_at) VALUES (?,?,?,?,?,?,?)",
                   (job_id, kind, document_id, deck_id, "queued", json.dumps(request), now()))
        return job_id

    def _capture(self, db, selections):
        from infrastructure.ingestion.detection import EXTENSIONS
        import codecs
        result, hashes = [], {}
        seen_uploads = set()
        for item in selections:
            selection = SourceSelection.model_validate(item)
            if selection.document_id in seen_uploads:
                raise IngestionError('DUPLICATE_UPLOAD_ID', 'Select each upload ID only once.')
            seen_uploads.add(selection.document_id)
            row = db.execute('SELECT * FROM documents WHERE id=?', (selection.document_id,)).fetchone()
            if not row:
                raise IngestionError('SOURCE_NOT_FOUND', 'A selected upload does not exist.', status=404)
            document = dict(row)
            spec = json.loads(document['upload_spec_json']) if document.get('upload_spec_json') else {}
            kind = spec.get('resolved_type') or EXTENSIONS.get(Path(document['filename']).suffix.lower())
            selected = selection.selected_type or spec.get('selected_type', 'auto')
            if selected == 'auto':
                kind = spec.get('detected_type') or kind
            elif kind in {'txt', 'markdown', 'csv'} and selected in {'txt', 'markdown', 'csv'}:
                kind = selected
            elif selected != kind:
                raise IngestionError('TYPE_MISMATCH', 'Select the detected file type or Auto.', details={'detected_type': kind})
            options = selection.parse_options.model_copy()
            try:
                options.for_type(kind)
                if kind in {'txt', 'markdown', 'csv'}:
                    options.encoding = codecs.lookup(spec.get('text_encoding', 'utf-8') if options.encoding == 'auto' else options.encoding).name
            except (ValueError, LookupError) as error:
                raise IngestionError('INVALID_PARSE_OPTIONS', str(error)) from None
            entry = {'document_id': selection.document_id, 'selected_type': selected, 'resolved_type': kind,
                'parse_options': options.model_dump(mode='json'), 'source_sha256': document['source_sha256'],
                'filename': document['filename'], 'source_path': document['source_path'],
                'size_bytes': document['size_bytes'], 'upload_spec': spec,
                'upload_ids': [selection.document_id], 'aliases': [document['filename']]}
            comparison = (kind, options.model_dump(mode='json'))
            if entry['source_sha256'] in hashes:
                first, first_options = hashes[entry['source_sha256']]
                if comparison != first_options:
                    raise IngestionError('DUPLICATE_SOURCE_OPTIONS', 'Identical source bytes have conflicting parse options.')
                first['upload_ids'].append(selection.document_id)
                if document['filename'] not in first['aliases']:
                    first['aliases'].append(document['filename'])
            else:
                hashes[entry['source_sha256']] = (entry, comparison)
                result.append(entry)
        return result

    def capture_sources(self, selections):
        with self.connection() as db:
            return self._capture(db, selections)

    def deck_sources(self, deck_id):
        with self.connection() as db:
            return [json.loads(row['selection_json']) for row in db.execute(
                'SELECT selection_json FROM deck_documents WHERE deck_id=? ORDER BY ordinal', (deck_id,))]

    def create_deck(self, document_id, output_dir, request, *, deck_id=None, sources=None):
        deck_id = deck_id or new_id()
        with self.connection(immediate=True) as db:
            captured = self._capture(db, sources or [SourceSelection(document_id=document_id)])
            primary = captured[0]['document_id']
            db.execute("INSERT INTO decks VALUES (?,?,?,?)", (deck_id, primary, str(output_dir), now()))
            for ordinal, selection in enumerate(captured):
                db.execute('INSERT INTO deck_documents VALUES (?,?,?,?)',
                           (deck_id, selection['document_id'], ordinal, json.dumps(selection)))
            job_id = self._enqueue(db, "generate", {**request, "sources": captured, "base_revision": None}, primary, deck_id)
        return self.get(job_id)

    def enqueue(self, kind, request, *, document_id=None, deck_id=None):
        with self.connection() as db:
            job_id = self._enqueue(db, kind, request, document_id, deck_id)
        return self.get(job_id)

    def get(self, job_id):
        with self.connection() as db:
            return _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def deck_jobs(self, deck_id):
        with self.connection() as db:
            return [_job(row) for row in db.execute("SELECT * FROM jobs WHERE deck_id=? ORDER BY created_at,id", (deck_id,))]

    def recent_jobs(self, limit=50):
        with self.connection() as db:
            return [_job(row) for row in db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(int(limit), 200)),))]

    def decks(self, limit=100):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM decks ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 500)),))]

    def claim(self):
        with self.connection(immediate=True) as db:
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',started_at=? WHERE id=?", (now(), row["id"]))
            return _job(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def progress(self, job_id, stage, counters):
        with self.connection() as db:
            db.execute("UPDATE jobs SET stage=?,progress_json=? WHERE id=? AND status='running'",
                       (stage, json.dumps(counters), job_id))

    def finish(self, job_id, status, *, result=None, error=None):
        TypeAdapter(JobStatus).validate_python(status)
        if status not in TERMINAL_STATUSES:
            raise ValueError("finish requires a terminal status")
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET status=?,result_json=?,error_json=?,finished_at=? WHERE id=? AND status='running'",
                                (status, json.dumps(result) if result is not None else None,
                                 json.dumps(error) if error is not None else None, now(), job_id)).rowcount
            if changed != 1:
                raise ValueError("Only a running job can finish")

    def cancel(self, job_id):
        with self.connection(immediate=True) as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            if row["status"] == "queued":
                db.execute("UPDATE jobs SET status='cancelled',cancel_requested=1,finished_at=? WHERE id=?", (now(), job_id))
            elif row["status"] == "running":
                db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
            return _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def fail_interrupted(self):
        with self.connection() as db:
            return db.execute("UPDATE jobs SET status='failed',finished_at=?,error_json=? WHERE status='running'",
                              (now(), json.dumps({"code": "WORKER_INTERRUPTED", "stage": None,
                               "message": "The worker stopped during this job. Inspect the active deck before resubmitting."}))).rowcount
