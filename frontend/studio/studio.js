/* PPTAI Studio — pipeline runner UI (vanilla JS, no build step). */
'use strict';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const state = {
  formats: null, config: null,
  docs: new Map(),      // document_id -> {view, status, parseJobId, findings[], removed}
  jobs: new Map(),      // job_id -> {card, es, poll, terminal, status, kind}
  decks: [],
  selectedDeck: null,
  uploading: false,
  decksLoading: false,
  decksError: false,
};

/* ---------------- API helper ---------------- */
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data = null;
  try { data = await response.json(); } catch { /* non-JSON error body */ }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = detail && (detail.message || (typeof detail === 'string' ? detail : JSON.stringify(detail)));
    const error = new Error(message || `Request failed (${response.status})`);
    error.code = detail && detail.code;
    error.status = response.status;
    throw error;
  }
  return data;
}
const jsonBody = (payload) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

/* ---------------- toasts ---------------- */
function toast(message, kind = 'error') {
  const node = el('div', `toast ${kind}`, message);
  $('toast-root').append(node);
  setTimeout(() => { node.style.opacity = '0'; node.style.transition = 'opacity .3s'; }, 5200);
  setTimeout(() => node.remove(), 5600);
}

/* ---------------- worker / config ---------------- */
async function pollWorker() {
  try {
    const status = await api('/api/worker/status');
    const pill = $('worker-pill');
    pill.className = `status-pill state-${status.state}`;
    const labels = { alive: 'worker online', busy: 'worker busy', stale: 'worker stale — restart it', offline: 'worker offline' };
    $('worker-state').textContent = labels[status.state] || status.state;
    pill.title = status.age_seconds !== null ? `heartbeat ${status.age_seconds}s ago (pid ${status.pid ?? '?'})` : 'no heartbeat yet';
  } catch { /* transient */ }
}

async function loadConfig() {
  try {
    state.config = await api('/api/config');
    const chip = $('model-chip');
    const c = state.config;
    let text = `${c.provider} · ${c.model} · ${c.max_calls_per_minute}/min · out ${c.max_output_tokens} tok`;
    if (c.context_tokens) text += ` · ctx ${c.context_tokens}`;
    chip.textContent = text;
    chip.title = `strict coverage: ${c.strict_section_coverage ? 'on' : 'off'} · concurrency ${c.max_concurrency}`;
    chip.classList.toggle('nokey', !c.api_key_present);
    if (!c.api_key_present) chip.title += ' · API key missing';
    populateThemes();
  } catch (error) { $('model-chip').textContent = 'config unavailable'; }
}

function populateThemes() {
  const select = $('theme');
  if (!select || !state.config || !state.config.themes) return;
  const current = select.value || 'auto';
  const lensMap = state.config.lens_theme_map || {};
  const options = ['<option value="auto">Auto — follows the lens</option>'];
  for (const [id, theme] of Object.entries(state.config.themes)) {
    const auto = lensMap[$('lens').value] === id ? ' · default for this lens' : '';
    options.push(`<option value="${id}">${theme.name}${auto} — ${theme.description}</option>`);
  }
  select.innerHTML = options.join('');
  select.value = [...select.options].some(o => o.value === current) ? current : 'auto';
}

async function loadFormats() {
  try {
    state.formats = await api('/api/input-formats');
    const ok = state.formats.formats.filter(f => f.adapter_available).map(f => f.type);
    $('formats-hint').textContent = ok.length ? `supported: ${ok.join(', ')}` : 'no format adapters installed';
    const accept = state.formats.formats.flatMap(f => f.extensions).join(',');
    $('file-input').accept = accept;
    if (ok.length) $('dz-formats').textContent = ok.join(', ');
  } catch { $('formats-hint').textContent = 'format check failed'; }
}

/* ---------------- stage rail ---------------- */
/* Communicates real client state only — no fabricated progress. */
function updateStages() {
  const docs = [...state.docs.values()];
  const parsed = docs.filter(d => d.status === 'parsed').length;
  const inFlight = docs.filter(d => d.status === 'uploading' || d.status === 'parsing').length;
  const failedDocs = docs.filter(d => d.status === 'failed').length;
  const jobs = [...state.jobs.values()];
  const genJobs = jobs.filter(j => j.kind === 'generate');
  const activeJobs = jobs.filter(j => !j.terminal).length;
  const doneGen = genJobs.filter(j => j.terminal && j.status === 'completed').length;
  const failedJobs = jobs.filter(j => j.terminal && j.status === 'failed').length;

  const setStage = (id, { current = false, done = false, num, note }) => {
    const li = $(id);
    if (!li) return;
    li.classList.toggle('is-current', current);
    li.classList.toggle('is-done', done);
    if (current) li.setAttribute('aria-current', 'step');
    else li.removeAttribute('aria-current');
    const numEl = li.querySelector('.stage-num');
    if (numEl) numEl.textContent = done ? '\u2713' : num;
    const noteEl = li.querySelector('.stage-note');
    if (noteEl && note !== undefined) noteEl.textContent = note;
  };

  let sourceNote;
  if (parsed) sourceNote = inFlight ? `${parsed} parsed · ${inFlight} in flight` : `${parsed} parsed source${parsed > 1 ? 's' : ''}`;
  else if (inFlight) sourceNote = `${inFlight} file${inFlight > 1 ? 's' : ''} uploading / parsing…`;
  else if (failedDocs) sourceNote = 'upload failed — check the row for details';
  else sourceNote = 'select and parse a document';
  setStage('stage-source', { current: parsed === 0, done: parsed > 0, num: '01', note: sourceNote });

  const configureDone = genJobs.length > 0;
  let configureNote;
  if (configureDone) configureNote = doneGen ? 'settings submitted — deck generated' : 'settings submitted';
  else if (parsed) configureNote = 'ready — generate when configured';
  else configureNote = 'narrative, extraction, visuals, limits';
  setStage('stage-configure', { current: parsed > 0 && !configureDone, done: configureDone, num: '02', note: configureNote });

  let reviewNote;
  const parts = [];
  if (activeJobs) parts.push(`${activeJobs} active`);
  if (failedJobs) parts.push(`${failedJobs} failed`);
  if (!parts.length && doneGen) parts.push(`${doneGen} completed`);
  if (!parts.length && state.decks.length) parts.push(`${state.decks.length} deck${state.decks.length > 1 ? 's' : ''}`);
  reviewNote = parts.length ? parts.join(' · ') : 'jobs, decks and exports';
  setStage('stage-review', { current: jobs.length > 0, done: doneGen > 0, num: '03', note: reviewNote });
}

/* ---------------- upload + parse ---------------- */
function extLabel(filename) {
  const ext = (filename.split('.').pop() || '').toLowerCase();
  return ext.slice(0, 4) || 'doc';
}
function fmtBytes(n) {
  if (n > 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n > 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}

const DOC_LABELS = { uploading: 'uploading', parsing: 'parsing', parsed: 'parsed', failed: 'failed' };

function renderDoc(entry) {
  const row = entry.row;
  row.replaceChildren();
  row.className = `doc status-${entry.status}`;

  const ext = el('span', 'doc-ext', extLabel(entry.view.filename));
  ext.title = 'file type';

  const info = el('div', 'doc-info');
  info.append(el('span', 'doc-name', entry.view.filename));
  const metaBits = [];
  if (typeof entry.view.size_bytes === 'number') metaBits.push(fmtBytes(entry.view.size_bytes));
  const detected = entry.view.upload && entry.view.upload.detected_type;
  if (detected) metaBits.push(`type ${detected}`);
  info.append(el('span', 'doc-meta', metaBits.join(' · ')));

  const status = el('span', 'doc-status');
  if (entry.status === 'uploading' || entry.status === 'parsing') {
    const spinner = el('span', 'spinner');
    spinner.setAttribute('aria-hidden', 'true');
    status.append(spinner, el('span', 'status-text', DOC_LABELS[entry.status]));
  } else {
    const mark = el('span', 'status-mark', entry.status === 'parsed' ? '\u2713' : '\u2715');
    status.append(mark, el('span', 'status-text', DOC_LABELS[entry.status]));
  }

  const remove = el('button', 'doc-remove', '\u00d7');
  remove.type = 'button';
  remove.setAttribute('aria-label', `Remove ${entry.view.filename} from the source set`);
  remove.title = 'Remove from this source set (the upload itself is kept server-side)';
  remove.onclick = () => {
    entry.removed = true;
    if (entry.view.id && state.docs.has(entry.view.id)) state.docs.delete(entry.view.id);
    row.remove();
    updateGenerateButton();
  };

  row.append(ext, info, status, remove);
  if (entry.findings && entry.findings.length) {
    const note = el('div', 'doc-findings');
    note.textContent = entry.findings.join(' · ');
    row.append(note);
  }
  updateGenerateButton();
}

async function uploadFiles(files) {
  state.uploading = true;
  updateGenerateButton();
  try {
    for (const file of files) {
      await uploadOne(file);
    }
  } finally {
    state.uploading = false;
    updateGenerateButton();
  }
}

async function uploadOne(file) {
  // Optimistic row: shows the upload state before the first response arrives.
  const entry = {
    view: { filename: file.name, size_bytes: file.size, upload: null, id: null },
    status: 'uploading', parseJobId: null, findings: [], removed: false,
    row: el('li', 'doc'),
  };
  $('doc-list').prepend(entry.row);
  renderDoc(entry);

  const form = new FormData();
  form.append('file', file);
  form.append('selected_type', 'auto');
  let view;
  try {
    view = await api('/api/documents', { method: 'POST', body: form });
  } catch (error) {
    if (entry.removed) return;
    entry.status = 'failed';
    entry.findings.push(`upload failed: ${error.message}`);
    renderDoc(entry);
    toast(`Upload failed: ${error.message}`, 'error');
    updateStages();
    return;
  }
  if (entry.removed) return; // removed while the request was in flight
  entry.view = view;
  entry.status = 'parsing';
  state.docs.set(view.id, entry);
  renderDoc(entry);
  updateStages();
  try {
    const submitted = await api(`/api/documents/${view.id}/parse`, { method: 'POST', ...jsonBody({}) });
    entry.parseJobId = submitted.job_id;
    followJob(submitted, { kindLabel: 'parse', docId: view.id });
  } catch (error) {
    entry.status = 'failed';
    entry.findings.push(error.message);
    renderDoc(entry);
    toast(`Parse submission failed: ${error.message}`);
    updateStages();
  }
}

function onParseUpdate(docId, job) {
  const entry = state.docs.get(docId);
  if (!entry) return;
  if (job.status === 'completed') {
    entry.status = 'parsed';
    const outcome = job.result && job.result.parse_result;
    if (outcome && outcome.findings) {
      entry.findings = outcome.findings.filter(f => f.severity === 'warning' || f.severity === 'error').map(f => f.message).slice(0, 2);
    }
  } else if (job.status === 'failed') {
    entry.status = 'failed';
    entry.findings.push((job.error && job.error.message) || 'parse failed');
  } else if (job.status === 'cancelled') {
    entry.status = 'failed';
    entry.findings.push('parse cancelled');
  }
  renderDoc(entry);
  updateStages();
}

function parsedDocs() {
  return [...state.docs.values()].filter(d => d.status === 'parsed');
}

function updateGenerateButton() {
  const count = parsedDocs().length;
  const ready = count > 0;
  $('generate').disabled = !ready || state.uploading;
  if ($('resume-generate')) $('resume-generate').disabled = !ready || state.uploading;
  $('generate-sub').textContent = state.uploading
    ? 'waiting for uploads to finish'
    : (ready ? `${count} parsed source${count > 1 ? 's' : ''} ready` : 'upload and parse a source first');
  if ($('resume-sub')) {
    $('resume-sub').textContent = ready ? 'reuse cache / checkpoints' : 'upload a source first';
  }
  updateStages();
}

/* ---------------- generation ---------------- */
function collectGenerationPayload(overrides = {}) {
  const sources = parsedDocs().map(d => ({ document_id: d.view.id }));
  const payload = {
    sources,
    lens: $('lens').value,
    extraction_mode: $('extraction_mode').value,
    polish: $('polish').value,
    renderer: $('renderer').value,
    asset_options: $('asset_understanding').value === 'structured'
      ? { mode: 'structured', semantic_understanding: 'auto' }
      : { mode: 'legacy', semantic_understanding: 'off' },
    min_slides: Math.max(1, +$('min_slides').value || 5),
    max_slides: Math.max(1, +$('max_slides').value || 10),
    max_repairs_per_slide: Math.max(0, +$('max_repairs_per_slide').value || 0),
    max_concurrency: Math.max(1, +$('max_concurrency').value || 2),
    theme: $('theme').value || 'auto',
    dynamic_layout: $('dynamic_layout').checked,
    deep_verification: $('deep_verification').checked,
    instruction: $('instruction').value.trim(),
    resume: Boolean($('resume_cache') && $('resume_cache').checked),
    ...overrides,
  };
  if (payload.min_slides > payload.max_slides) [payload.min_slides, payload.max_slides] = [payload.max_slides, payload.min_slides];
  return payload;
}

async function generate(options = {}) {
  const payload = collectGenerationPayload(options);
  if (!payload.sources.length) return;
  try {
    const submitted = await api('/api/decks', { method: 'POST', ...jsonBody(payload) });
    toast(payload.resume ? 'Generation with resume queued' : 'Generation queued', 'ok');
    followJob(submitted, { kindLabel: 'generate' });
  } catch (error) {
    toast(`Could not queue generation: ${error.message}`);
  }
  updateStages();
}

async function resumeDeck(deckId) {
  const payload = collectGenerationPayload({ resume: true });
  const { sources, ...genOptions } = payload;
  try {
    const submitted = await api(`/api/decks/${deckId}/generate`, { method: 'POST', ...jsonBody(genOptions) });
    toast(`Deck generation resumed for ${deckId.slice(0, 8)}`, 'ok');
    followJob(submitted, { kindLabel: 'generate' });
  } catch (error) {
    toast(`Could not resume deck: ${error.message}`);
  }
}

async function resumeDeckJob(job) {
  const deckId = job.deck_id || (job.result && job.result.deck_id);
  if (!deckId) {
    toast('Cannot resume: no deck associated with this task', 'warn');
    return;
  }
  await resumeDeck(deckId);
}

/* ---------------- job following (SSE + polling fallback) ---------------- */
const STAGE_LABELS = {
  parsing: 'Parsing source document',
  'structural validation': 'Validating structure',
  'knowledge extraction': 'Extracting knowledge units',
  'asset understanding': 'Interpreting figures, formulas and tables',
  composition: 'Composing slides',
  build: 'Rendering PPTX',
  'quality checks': 'Quality gate + visual audit',
  publication: 'Publishing revision',
};

const JOB_LABELS = { queued: 'queued', running: 'running', completed: 'completed', failed: 'failed', cancelled: 'cancelled' };
const JOB_MARKS = { queued: '\u25cb', running: '\u25d0', completed: '\u2713', failed: '\u2715', cancelled: '\u2013' };

function jobRow(job, kindLabel) {
  const row = el('article', 'job');
  const head = el('div', 'job-head');
  const kind = el('span', 'job-kind', kindLabel || job.kind || 'job');
  const id = el('span', 'job-id', (job.id || '').slice(0, 10));
  const statusWrap = el('span', 'job-status');
  const actions = el('span', 'job-actions');
  head.append(kind, id, statusWrap, actions);
  const stage = el('div', 'job-stage');
  const progress = el('div', 'job-progress');
  progress.hidden = true;
  row.append(head, stage, progress);
  return { row, head, kind, id, statusWrap, actions, stage, progress };
}

function drawJob(card, job) {
  card.row.dataset.status = job.status;

  /* status: mark + text, never color alone */
  card.statusWrap.replaceChildren();
  const mark = el('span', 'status-mark', JOB_MARKS[job.status] ?? '\u00b7');
  if (job.status === 'running') {
    mark.textContent = '';
    mark.className = 'status-mark spinner';
    mark.setAttribute('aria-hidden', 'true');
  }
  card.statusWrap.append(mark, el('span', 'status-text', JOB_LABELS[job.status] || job.status));

  /* stage line */
  if (job.status === 'running') {
    const spinner = el('span', 'spinner');
    spinner.setAttribute('aria-hidden', 'true');
    card.stage.replaceChildren(spinner, el('span', undefined, `${STAGE_LABELS[job.stage] || job.stage || 'running'}…`));
  } else if (job.status === 'queued') {
    card.stage.textContent = job.cancel_requested
      ? 'cancellation requested — waiting for worker'
      : 'waiting for an available worker';
  } else {
    const doneWord = job.status === 'completed' ? 'finished' : JOB_LABELS[job.status];
    card.stage.textContent = job.stage ? `${STAGE_LABELS[job.stage] || job.stage} — ${doneWord}` : doneWord;
  }

  /* progress: determinate bar only when the backend reports a trustworthy total */
  const progress = job.progress || {};
  const total = typeof progress.total === 'number' && progress.total > 0 ? progress.total : 0;
  if (total && (job.status === 'running' || job.status === 'completed')) {
    const completed = typeof progress.completed === 'number'
      ? Math.max(0, Math.min(progress.completed, total)) : 0;
    card.progress.hidden = false;
    card.progress.replaceChildren();
    const track = el('div', 'progress-track');
    const fill = el('div', 'progress-fill');
    fill.style.width = job.status === 'completed' ? '100%' : `${Math.round((completed / total) * 100)}%`;
    track.append(fill);
    card.progress.append(track, el('span', 'progress-num', job.status === 'completed' ? `${total}/${total}` : `${completed}/${total}`));
  } else {
    card.progress.hidden = true;
  }

  /* actions */
  card.actions.replaceChildren();
  if ((job.status === 'running' || job.status === 'queued') && !job.cancel_requested) {
    const cancel = el('button', 'btn-mini danger', 'cancel');
    cancel.type = 'button';
    cancel.onclick = async () => {
      cancel.disabled = true;
      cancel.textContent = 'cancelling…';
      try { await api(`/api/jobs/${job.id}/cancel`, { method: 'POST' }); }
      catch (e) { cancel.disabled = false; cancel.textContent = 'cancel'; toast(e.message); }
    };
    card.actions.append(cancel);
  } else if ((job.status === 'running' || job.status === 'queued') && job.cancel_requested) {
    card.actions.append(el('span', 'job-cancel-note', 'cancelling'));
  }
  const isDeckJob = (job.kind === 'generate') || Boolean(job.deck_id);
  if (isDeckJob && ['failed', 'cancelled', 'completed'].includes(job.status)) {
    const resumeBtn = el('button', 'btn-mini accent', 'resume');
    resumeBtn.type = 'button';
    resumeBtn.title = 'Resume this deck generation task from checkpoints';
    resumeBtn.onclick = () => resumeDeckJob(job);
    card.actions.append(resumeBtn);
  }
  if (job.status === 'completed' && job.result && job.result.deck_id) {
    const open = el('a', 'btn-mini accent', 'view deck');
    open.href = '#';
    open.onclick = (event) => { event.preventDefault(); openDeck(job.result.deck_id); };
    card.actions.append(open);
  }

  /* expandable error details */
  let errBox = card.row.querySelector('.job-error');
  if (job.error && job.error.message) {
    if (!errBox) { errBox = el('details', 'job-error'); card.row.append(errBox); }
    const summary = el('summary');
    summary.append(
      el('span', 'err-mark', '\u2715'),
      el('span', 'err-code', job.error.code || 'ERROR'),
      el('span', 'err-short', job.error.message),
    );
    summary.title = job.error.message;
    const full = el('pre', 'err-full', `${job.error.code || 'ERROR'}: ${job.error.message}${job.error.stage ? `\nstage: ${job.error.stage}` : ''}`);
    errBox.replaceChildren(summary, full);
  } else if (errBox) errBox.remove();
}

function followJob(submitted, opts = {}) {
  const jobId = submitted.job_id || submitted.id;
  if (!jobId || state.jobs.has(jobId)) return;
  // Normalize: API submissions use job_id; job records use id.
  submitted = { ...submitted, id: jobId, job_id: jobId };
  const kind = opts.kindLabel || submitted.kind || 'job';
  const card = jobRow({ ...submitted, kind });
  state.jobs.set(jobId, { card, terminal: false, status: submitted.status || 'queued', kind });
  const container = $('jobs');
  container.querySelector('.empty-state')?.remove();
  container.prepend(card.row);
  drawJob(card, submitted);
  updateStages();

  const finish = (job) => {
    drawJob(card, job);
    if (['completed', 'failed', 'cancelled'].includes(job.status)) {
      const tracked = state.jobs.get(job.id || jobId);
      if (tracked) { tracked.terminal = true; tracked.status = job.status; }
      if (job.es) job.es.close();
      if (job.poll) clearInterval(job.poll);
      if (opts.docId) onParseUpdate(opts.docId, job);
      if (job.status === 'completed' && job.result && job.result.deck_id) refreshDecks().then(() => openDeck(job.result.deck_id));
      if (job.status === 'failed') toast(`Job failed: ${(job.error && job.error.message) || 'unknown error'}`);
      updateStages();
    }
  };

  const handle = (job) => {
    const tracked = state.jobs.get(job.id || jobId);
    if (tracked && tracked.terminal) return;
    if (tracked) tracked.status = job.status;
    finish(job);
  };

  // SSE stream for live updates…
  try {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.addEventListener('progress', (event) => { try { handle(JSON.parse(event.data)); } catch { /* ignore */ } });
    es.onerror = () => { /* closed by server on terminal state */ };
    state.jobs.get(jobId).es = es;
  } catch { /* EventSource unavailable */ }
  // …and a polling safety net (also covers SSE failures).
  const poll = setInterval(async () => {
    const tracked = state.jobs.get(jobId);
    if (!tracked || tracked.terminal) { clearInterval(poll); return; }
    try {
      const job = await api(`/api/jobs/${jobId}`);
      handle({ ...job, poll: undefined });
      if (['completed', 'failed', 'cancelled'].includes(job.status)) clearInterval(poll);
    } catch { /* transient */ }
  }, 2000);
  state.jobs.get(submitted.job_id).poll = poll;
}

async function resumeInProgress() {
  try {
    const jobs = await api('/api/jobs?limit=30');
    for (const job of jobs) {
      if (['queued', 'running'].includes(job.status)) {
        followJob(job, { kindLabel: job.kind });
      }
    }
  } catch { /* ignore */ }
}

/* ---------------- decks ---------------- */
async function refreshDecks() {
  if (state.decksLoading) return;
  state.decksLoading = true;
  state.decksError = false;
  renderDeckList();
  try {
    state.decks = await api('/api/decks');
  } catch (error) {
    state.decksError = true;
    state.decks = [];
  } finally {
    state.decksLoading = false;
    renderDeckList();
    updateStages();
  }
}

function renderDeckList() {
  const container = $('decks');
  container.replaceChildren();

  if (state.decksLoading) {
    container.setAttribute('aria-busy', 'true');
    for (let i = 0; i < 3; i += 1) container.append(el('div', 'skeleton-row'));
    return;
  }
  container.removeAttribute('aria-busy');

  if (state.decksError) {
    const box = el('div', 'empty-state is-error');
    box.append(
      el('p', 'empty-title', 'Could not load decks'),
      el('p', 'empty-sub', 'Check the API connection, then press Refresh.'),
    );
    container.append(box);
    return;
  }

  if (!state.decks.length) {
    const box = el('div', 'empty-state');
    box.append(
      el('p', 'empty-title', 'No decks yet'),
      el('p', 'empty-sub', 'Generated decks are published here with revisions, checks and downloads.'),
    );
    container.append(box);
    return;
  }

  for (const deck of state.decks) {
    const row = el('button', `deck-row${deck.id === state.selectedDeck ? ' selected' : ''}`);
    row.type = 'button';
    const name = el('span', 'deck-name', deck.filename || `deck ${deck.id.slice(0, 8)}`);
    const when = new Date(deck.created_at);
    const time = Number.isNaN(when.getTime()) ? '' : ` · ${when.toLocaleString()}`;
    const meta = el('span', 'deck-meta',
      `${deck.active_revision ? `rev ${deck.active_revision.slice(0, 8)}` : 'no revision yet'}${time}`);
    const stateLabel = el('span', `deck-state${deck.active_revision ? '' : ' none'}`,
      deck.active_revision ? 'published' : 'pending');
    row.append(name, meta, stateLabel);
    row.setAttribute('aria-label', `Open deck ${deck.filename || deck.id}`);
    row.onclick = () => openDeck(deck.id);
    container.append(row);
  }
}

async function openDeck(deckId) {
  state.selectedDeck = deckId;
  renderDeckList();
  const detail = $('deck-detail');
  detail.hidden = false;
  detail.replaceChildren();
  const loading = el('div', 'detail-loading');
  loading.append(el('span', 'spinner'), el('span', undefined, 'Loading deck…'));
  detail.append(loading);
  let deck;
  try {
    deck = await api(`/api/decks/${deckId}`);
  } catch (error) {
    detail.replaceChildren(el('p', 'detail-error', `Could not load deck: ${error.message}`));
    return;
  }
  detail.replaceChildren();
  const active = deck.active_revision;

  const head = el('div', 'detail-head');
  head.append(
    el('h3', 'detail-title', (deck.sources[0] && deck.sources[0].filename) || `Deck ${deckId.slice(0, 8)}`),
    el('div', 'detail-meta', `deck ${deckId.slice(0, 12)} · created ${new Date(deck.created_at).toLocaleString()}`),
  );
  detail.append(head);

  if (!active) {
    detail.append(el('p', 'notice', 'This deck has no published revision yet — its job may still be running or failed.'));
    const actions = el('div', 'detail-actions');
    const resumeBtn = el('button', undefined, 'Resume generation');
    resumeBtn.type = 'button';
    resumeBtn.title = 'Resume deck generation with cache checkpoints';
    resumeBtn.onclick = () => resumeDeck(deckId);
    actions.append(resumeBtn);
    detail.append(actions);
    return;
  }

  const actions = el('div', 'detail-actions');
  const download = el('a', undefined, 'Download .pptx');
  download.href = active.pptx_url;
  download.setAttribute('download', '');
  const resumeBtn = el('button', undefined, 'Resume generation');
  resumeBtn.type = 'button';
  resumeBtn.title = 'Resume or re-run deck generation reusing cached checkpoints';
  resumeBtn.onclick = () => resumeDeck(deckId);
  actions.append(download, resumeBtn);
  detail.append(actions);

  const checks = el('div', 'checks');
  const checkMarks = {
    PASSED: ['ok', '\u2713'], EVALUATED_PASS: ['ok', '\u2713'],
    FAILED_TO_RUN: ['bad', '\u2715'], EVALUATED_FAIL: ['bad', '\u2715'],
    PARTIAL: ['warn', '!'], NOT_EVALUATED: ['none', '\u2013'],
  };
  for (const [name, status] of Object.entries(active.checks || {})) {
    const [cls, glyph] = checkMarks[status] || ['none', '\u00b7'];
    const row = el('div', 'check-row');
    row.append(
      el('span', `mark ${cls}`, glyph),
      el('span', 'check-name', name),
      el('span', 'check-status', status),
    );
    checks.append(row);
  }
  const readinessRow = el('div', 'check-row');
  const readinessCls = active.readiness === 'PASSED' ? 'ok' : 'warn';
  readinessRow.append(
    el('span', `mark ${readinessCls}`, readinessCls === 'ok' ? '\u2713' : '!'),
    el('span', 'check-name', 'readiness'),
    el('span', 'check-status', active.readiness),
  );
  checks.append(readinessRow);
  detail.append(checks);

  if (active.missing_checks && active.missing_checks.length) {
    detail.append(el('p', 'missing-checks', `Missing checks: ${active.missing_checks.join(', ')}`));
  }

  if (active.previews && active.previews.length) {
    const grid = el('div', 'preview-grid');
    for (const preview of active.previews) {
      const slideCard = el('div', 'slide-card');
      const img = el('img');
      img.loading = 'lazy';
      img.src = preview.url;
      img.alt = `Slide ${preview.slide} preview`;
      const cap = el('div', 'cap');
      cap.append(el('span', undefined, `slide ${preview.slide}`), el('span', undefined, 'rendered'));
      slideCard.append(img, cap);
      grid.append(slideCard);
    }
    detail.append(grid);
  } else {
    detail.append(el('p', 'notice', 'No rendered previews available for this revision (rendering may have been unavailable on this machine).'));
  }
}

/* ---------------- wiring ---------------- */
function wireUpload() {
  const zone = $('dropzone');
  const input = $('file-input');
  zone.onclick = () => input.click();
  zone.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } };
  input.onchange = () => { uploadFiles([...input.files]); input.value = ''; };
  ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation(); zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation(); zone.classList.remove('dragging');
  }));
  zone.addEventListener('drop', (event) => {
    const files = [...event.dataTransfer.files];
    if (files.length) uploadFiles(files);
  });
}

function wireSettings() {
  $('generate').onclick = () => generate();
  if ($('resume-generate')) {
    $('resume-generate').onclick = () => {
      if ($('resume_cache')) $('resume_cache').checked = true;
      generate({ resume: true });
    };
  }
  $('refresh-decks').onclick = () => { refreshDecks(); toast('Deck list refreshed', 'info'); };
  $('lens').addEventListener('change', populateThemes);
}

async function init() {
  wireUpload();
  wireSettings();
  try {
    await Promise.all([loadConfig(), loadFormats()]);
  } catch (error) {
    toast(`Could not load server configuration: ${error.message}`);
  }
  pollWorker();
  setInterval(pollWorker, 5000);
  refreshDecks();
  resumeInProgress();
  updateGenerateButton();
  updateStages();
}

init();
