"""Deterministic, bounded source chunks for slide-level retrieval."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from contracts.ir1_schema import KnowledgeUnit, ValidatedIR1
from contracts.storyboard_schema import TopicChunk


def _estimate_tokens(value: object) -> int:
    return max(1, len(json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')) + 256)


def _digest(section: str, units: list[KnowledgeUnit]) -> str:
    return section + ': ' + '; '.join(unit.title[:160] for unit in units[:3])


def _document(unit):
    import re
    for text in [*unit.section_path, *(e.source_id for e in unit.evidence)]:
        match = re.search(r'doc_[0-9a-f]{64}', text)
        if match:
            return match.group(0)
    return 'legacy-document'


def build_chunks(ir1: ValidatedIR1, *, max_tokens: int = 1800, min_units: int = 2, context_policy=None) -> list[TopicChunk]:
    if max_tokens < 1 or min_units < 1:
        raise ValueError('Chunk targets must be positive')
    groups = []
    def related(units):
        sources = {e.source_id for u in units for e in u.evidence}
        paths = {tuple(u.section_path) for u in units}
        docs = {_document(u) for u in units}
        def asset_path(asset):
            path = list(asset.section_path)
            if asset.document_id and not path[0].startswith(asset.document_id + ' / '):
                path[0] = asset.document_id + ' / ' + path[0]
            return tuple(path)
        return [a.asset_id for a in ir1.assets if a.asset_id in sources or
            (asset_path(a) in paths and (a.document_id or 'legacy-document') in docs)]
    def size(units):
        assets = related(units)
        return _estimate_tokens({'units': [u.model_dump() for u in units],
            'assets': [{'asset_id': a.asset_id, 'kind': a.kind, 'section': a.section_path,
                        'caption': a.caption} for a in ir1.assets if a.asset_id in assets]})
    for unit in ir1.units:
        if unit.validation_status != 'VALIDATED':
            continue
        if groups and _document(groups[-1][0]) == _document(unit):
            same_section = groups[-1][-1].section_path == unit.section_path
            sparse = len(groups[-1]) < min_units
            if (same_section or sparse) and size(groups[-1] + [unit]) <= max_tokens:
                groups[-1].append(unit)
                continue
        # A unit remains whole even if above the soft topic target. Final required
        # stage admission is the authority; no invented replacement facts.
        groups.append([unit])
    chunks = []
    for units in groups:
        assets = related(units)
        identity = {'units': [u.unit_id for u in units], 'assets': assets, 'sections': [u.section_path for u in units]}
        from infrastructure.utils.artifacts import sha256_value
        chunks.append(TopicChunk(chunk_id='chunk_' + sha256_value(identity)[:24],
            label=' / '.join(units[0].section_path), unit_ids=[u.unit_id for u in units],
            asset_ids=assets, digest=_digest(' / '.join(units[0].section_path), units), token_estimate=size(units)))
    if not chunks:
        raise ValueError('Cannot build slide chunks from an IR1 without validated knowledge units.')
    return chunks


from infrastructure.ingestion.context_fragments import plan_extraction_chunks


def pack_context_chunks(fragments, request_factory, budget=None):
    """Merge adjacent projections only after whole-request remeasurement."""
    from infrastructure.ingestion.context_fragments import combine
    from infrastructure.llm.context_budget import ContextBudgetError
    packed = []
    for fragment in fragments:
        if packed and packed[-1].chunk().document_ids == fragment.chunk().document_ids:
            candidate = combine([packed[-1], fragment])
            cells = [(r.source_id, r.row, r.column) for r in candidate.refs if r.representation == 'cell']
            if len(cells) == len(set(cells)):
                try:
                    prepared = request_factory(candidate, estimate_only=True)
                    if 1280 + 256 * len(candidate.refs) <= prepared.task_budget.max_output_tokens:
                        packed[-1] = candidate
                        continue
                except ContextBudgetError as error:
                    if error.code != 'REQUIRED_CONTEXT_TOO_LARGE':
                        raise
        packed.append(fragment)
    return packed

def write_chunks(chunks: list[TopicChunk], output_dir: str | Path, *, ir1=None) -> None:
    """Persist the intentionally list-shaped chunk artifact after validation."""

    target = Path(output_dir) / "chunks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps([chunk.model_dump() for chunk in chunks], ensure_ascii=False, indent=2), encoding="utf-8")
    [TopicChunk.model_validate(item) for item in json.loads(temporary.read_text(encoding="utf-8"))]
    os.replace(temporary, target)

    if ir1 is not None:
        from infrastructure.utils.artifacts import atomic_json, sha256_value
        from contracts.context_schema import ContextChunk, ContextRef
        unit_map = {u.unit_id: u for u in ir1.units}
        sidecars = []
        for chunk in chunks:
            units = [unit_map[key] for key in chunk.unit_ids]
            refs = [ContextRef(ref_id='cd_' + u.unit_id, document_id=_document(u), source_id=u.unit_id,
                section_path=u.section_path, representation='digest', source_hash=sha256_value(u.model_dump()),
                projection_hash=sha256_value(u.title)) for u in units]
            sidecars.append(ContextChunk(chunk_id=chunk.chunk_id, purpose='retrieval',
                document_ids=list(dict.fromkeys(_document(u) for u in units)), section_paths=[u.section_path for u in units],
                primary_refs=refs, unit_ids=chunk.unit_ids, asset_ids=chunk.asset_ids,
                source_ids=list(dict.fromkeys(e.source_id for u in units for e in u.evidence)),
                projection_hash=sha256_value(chunk.model_dump()), digest=chunk.digest, state='COMPLETE').model_dump(mode='json'))
        atomic_json(Path(output_dir) / 'context_chunks.json', {'schema_version': 'f07-v1', 'chunks': sidecars})
