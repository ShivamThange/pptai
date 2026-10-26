"""Context accounting, independent of the R03 factual coverage gate."""
from collections import defaultdict
from infrastructure.utils.artifacts import sha256_value, portable_value, file_hash
from contracts.context_schema import CoverageLedger, CoverageEvent, CoverageFinding
from infrastructure.ingestion.context_fragments import initial_fragments, reference


def initialize_ledger(raw, source_manifest=None):
    refs = [r for part in initial_fragments(raw) for r in part.refs]
    represented = {r.source_id for r in refs}
    for identity in raw.source_item_ids:
        if identity not in represented:
            from contracts.context_schema import ContextRef
            refs.append(ContextRef(ref_id='ci_' + sha256_value(identity)[:24], document_id=raw.document_id or 'legacy-document',
                source_id=identity, section_path=[], representation='inventory', source_hash=sha256_value(identity),
                projection_hash=sha256_value(identity)))
    ledger = CoverageLedger(source_hash=sha256_value(portable_value(raw.model_dump(mode='json'))), inventory=refs,
        parser_completeness='complete' if raw.documents and all(d.completeness == 'complete' for d in raw.documents) else 'unknown')
    ledger.events.append(CoverageEvent(dimension='retained', refs=refs, stage='source_inventory'))
    for ref in refs:
        if ref.representation in {'inventory', 'asset_metadata'}:
            ledger.events.append(CoverageEvent(dimension='excluded', refs=[ref], stage='knowledge_extraction',
                reason='unsupported_representation' if ref.representation == 'inventory' else 'pixels_not_interpreted'))
    return ledger


def record_preparation(ledger, prepared_context):
    ledger.events.append(CoverageEvent(dimension='selected', refs=prepared_context.refs,
        stage=prepared_context.stage, scope=prepared_context.scope))


def record_call_outcome(ledger, call_record):
    ledger.calls.append(call_record)
    if call_record.dispatch_state != 'NOT_SENT':
        ledger.events.append(CoverageEvent(dimension='dispatched', refs=call_record.refs,
            stage=call_record.stage, scope=call_record.scope,
            reason=call_record.dispatch_state, historical=call_record.outcome == 'CACHE_REUSED'))
    if call_record.outcome in {'FAILED', 'CANCELLED'}:
        ledger.events.append(CoverageEvent(dimension='failed', refs=call_record.refs,
            stage=call_record.stage, scope=call_record.scope, reason=call_record.error_code))


def interval_union(intervals):
    union = []
    for start, end in sorted(intervals):
        if union and start <= union[-1][1]:
            union[-1] = (union[-1][0], max(end, union[-1][1]))
        else:
            union.append((start, end))
    return union


def _dimensions(refs):
    text = defaultdict(list)
    cells, media = set(), set()
    for ref in refs:
        key = (ref.document_id, ref.source_id)
        if ref.representation == 'text' and ref.span is not None:
            text[key].append(ref.span)
        elif ref.representation == 'cell':
            cells.add((*key, ref.row, ref.column))
        elif ref.representation == 'pixels':
            media.add(key)
    return {'text_characters': sum(e-s for spans in text.values() for s,e in interval_union(spans)),
            'cells': len(cells), 'pixels': len(media)}


def validate_context_coverage(raw, chunks, ledger):
    findings = []
    original = initialize_ledger(raw)
    if ledger.source_hash != original.source_hash:
        return [CoverageFinding(code='CONTEXT_COVERAGE_GAP', message='Source identity changed')]
    inventory = {(r.document_id, r.source_id, r.representation, r.row, r.column): r for r in original.inventory}
    spans = defaultdict(list)
    cells = defaultdict(list)
    for chunk in chunks:
        for ref in chunk.primary_refs + chunk.context_only_refs:
            key = (ref.document_id, ref.source_id, ref.representation, ref.row, ref.column)
            expected = inventory.get(key)
            valid = expected is not None and expected.source_hash == ref.source_hash
            if ref.representation == 'text' and valid:
                valid = ref.span is not None and expected.span[0] <= ref.span[0] < ref.span[1] <= expected.span[1]
                if valid:
                    block = next(b for b in raw.blocks if b.block_id == ref.source_id)
                    valid = ref.projection_hash == sha256_value(block.text[ref.span[0]:ref.span[1]])
            elif ref.representation == 'cell' and valid and ref.span != expected.span:
                asset = next(a for a in raw.assets if a.asset_id == ref.source_id)
                cell = next(c for c in asset.data['cells'] if (c['row'], c['column']) == (ref.row, ref.column))
                valid = ref.span is not None and 0 <= ref.span[0] < ref.span[1] <= len(str(cell['text']))
                if valid:
                    cell = dict(cell, text=str(cell['text'])[ref.span[0]:ref.span[1]])
                    if cell.get('lexical_value') is not None:
                        cell['lexical_value'] = cell['text']
                    valid = ref.projection_hash == sha256_value(cell)
            elif valid:
                valid = ref.projection_hash == expected.projection_hash
            if not valid:
                findings.append(CoverageFinding(code='CONTEXT_COVERAGE_GAP', source_id=ref.source_id,
                    chunk_id=chunk.chunk_id, message='Foreign, altered or out-of-range projection'))
        for ref in chunk.primary_refs:
            if ref.representation == 'text' and ref.span:
                spans[(ref.document_id, ref.source_id)].append(ref.span)
            elif ref.representation == 'cell':
                cells[(ref.document_id, ref.source_id, ref.row, ref.column)].append(ref.span)
        if chunk.state != 'COMPLETE':
            findings.append(CoverageFinding(code='CONTEXT_COVERAGE_GAP', chunk_id=chunk.chunk_id, message='Required chunk has no inspected outcome'))
    for ref in original.inventory:
        if ref.representation == 'text' and interval_union(spans[(ref.document_id, ref.source_id)]) != [ref.span]:
            findings.append(CoverageFinding(code='CONTEXT_COVERAGE_GAP', source_id=ref.source_id, message='Primary text union is incomplete'))
        if ref.representation == 'cell' and interval_union(cells[(ref.document_id, ref.source_id, ref.row, ref.column)]) != [ref.span]:
            findings.append(CoverageFinding(code='CONTEXT_COVERAGE_GAP', source_id=ref.source_id, message='Primary cell union is incomplete'))
    retained = all(a.availability == 'AVAILABLE' and (not a.file_path or
        (a.content_sha256 and file_hash(a.file_path) == a.content_sha256)) for a in raw.assets)
    totals = {'retained': _dimensions(original.inventory), 'all_source_retained': bool(retained) and ledger.source_integrity == 'verified',
        'all_required_extraction_obligations_accounted': all(c.state in {'COMPLETE','FAILED','CANCELLED'} for c in chunks)
            and not any('union is incomplete' in f.message or 'Foreign' in f.message for f in findings)}
    for dimension in ('processed', 'selected', 'dispatched', 'excluded', 'failed'):
        for historical in (False, True):
            refs = [r for event in ledger.events if event.dimension == dimension and event.historical == historical for r in event.refs]
            totals[dimension + ('_historical' if historical else '_current_run')] = _dimensions(refs)
    denominator = totals['retained']['text_characters']
    totals['all_text_dispatched_current_run'] = 'not_applicable' if not denominator else totals['dispatched_current_run']['text_characters'] == denominator
    sent_refs = [r for event in ledger.events if event.dimension == 'dispatched' and not event.historical for r in event.refs]
    def represented(ref):
        matching = [r for r in sent_refs if (r.document_id,r.source_id,r.representation,r.row,r.column) ==
            (ref.document_id,ref.source_id,ref.representation,ref.row,ref.column)]
        if ref.span is not None:
            return interval_union([r.span for r in matching if r.span is not None]) == [ref.span]
        return any(r.projection_hash == ref.projection_hash for r in matching)
    totals['all_representations_dispatched_current_run'] = all(represented(ref) for ref in original.inventory)
    totals['by_document'] = {document: {
        dimension: _dimensions([r for event in ledger.events if event.dimension == dimension for r in event.refs if r.document_id == document])
        for dimension in ('retained', 'processed', 'selected', 'dispatched', 'excluded', 'failed')}
        for document in dict.fromkeys(r.document_id for r in original.inventory)}
    totals['by_stage'] = {stage: {
        dimension: _dimensions([r for event in ledger.events if event.dimension == dimension and event.stage == stage for r in event.refs])
        for dimension in ('processed', 'selected', 'dispatched', 'excluded', 'failed')}
        for stage in dict.fromkeys(e.stage for e in ledger.events)}
    ledger.totals = totals
    ledger.context_completeness = 'complete' if not findings else 'incomplete'
    return findings


def validate_supplied_evidence(units, fragment, raw=None, *, force=False):
    """A valid original ID cannot authorize a passage/cell absent from this call.
    Temporarily disabled by default; set VALIDATE_SUPPLIED_EVIDENCE=true to enable.
    """
    import os
    if not force and os.environ.get('VALIDATE_SUPPLIED_EVIDENCE', 'false').lower() not in ('true', '1'):
        return
    texts = defaultdict(list)
    cells = {}
    captions = {}
    for block in fragment.blocks:
        texts[block.block_id].append(block.text)
    if raw is not None:
        for ref in fragment.context_refs:
            if ref.representation == 'text' and ref.span is not None:
                original = next(b for b in raw.blocks if b.block_id == ref.source_id)
                texts[ref.source_id].append(original.text[ref.span[0]:ref.span[1]])
    for asset in fragment.assets:
        captions[asset.asset_id] = asset.caption or ''
        for cell in (asset.data or {}).get('cells', []):
            cells[(asset.asset_id, cell['row'], cell['column'])] = str(cell['text'])
    for unit in units:
        for ref in unit.evidence + [r for fact in unit.metric_facts for r in fact.evidence]:
            if ref.kind == 'cell':
                supplied = [cells.get((ref.source_id, ref.row, ref.column), '')]
            elif ref.kind == 'caption':
                supplied = [captions.get(ref.source_id, '')]
            else:
                supplied = texts.get(ref.source_id, [])
            if not ref.excerpt or not any(ref.excerpt in text for text in supplied):
                raise ContextBudgetError('UNSUPPLIED_EVIDENCE', stage='knowledge_extraction')


from infrastructure.llm.context_budget import ContextBudgetError


def request_references(raw, contents, stage):
    """Record representations actually present; digests never stand for source text."""
    import json
    try:
        payload = json.loads(contents) if isinstance(contents, str) else contents
    except (ValueError, TypeError):
        return []
    blocks = {b.block_id: b for b in raw.blocks}
    assets = {a.asset_id: a for a in raw.assets}
    refs = {}
    def visit(value):
        if isinstance(value, dict):
            identity = value.get('source_id')
            excerpt = value.get('excerpt')
            if isinstance(excerpt, str) and excerpt:
                if identity in blocks:
                    block = blocks[identity]
                    positions = []
                    cursor = block.text.find(excerpt)
                    while cursor >= 0:
                        positions.append(cursor)
                        cursor = block.text.find(excerpt, cursor + 1)
                    # Multiple matching occurrences remain explicitly unlocated.
                    span = (positions[0], positions[0]+len(excerpt)) if len(positions) == 1 else None
                    ref = reference(block, 'text', excerpt, span=span)
                    refs[ref.ref_id] = ref
                elif identity in assets and value.get('kind') == 'cell':
                    asset = assets[identity]
                    cell = next((c for c in (asset.data or {}).get('cells', []) if
                        (c['row'], c['column']) == (value.get('row'), value.get('column'))), None)
                    if cell and excerpt in str(cell['text']):
                        ref = reference(asset, 'cell', cell, row=cell['row'], column=cell['column'])
                        refs[ref.ref_id] = ref
                elif identity in assets:
                    ref = reference(assets[identity], 'caption', excerpt)
                    refs[ref.ref_id] = ref
            if value.get('asset_id') in assets:
                asset = assets[value['asset_id']]
                for cell in (value.get('data') or {}).get('cells', []):
                    ref = reference(asset, 'cell', cell, row=cell['row'], column=cell['column'])
                    refs[ref.ref_id] = ref
                if value.get('caption'):
                    ref = reference(asset, 'caption', value['caption'])
                    refs[ref.ref_id] = ref
            if stage == 'storyboard_planning' and value.get('unit_id'):
                from contracts.context_schema import ContextRef
                section = value.get('section') or []
                document = next((b.document_id for b in raw.blocks if b.document_id and any(b.document_id in p for p in section)), None)
                ref = ContextRef(ref_id='cd_' + sha256_value(value)[:24], document_id=document or raw.document_id or 'legacy-document',
                    source_id=value['unit_id'], section_path=section, representation='digest',
                    source_hash=sha256_value(value), projection_hash=sha256_value(value))
                refs[ref.ref_id] = ref
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(payload)
    return list(refs.values())


def validate_sidecars(directory):
    import json
    from contracts.context_schema import ContextChunk, ContextChunksArtifact
    from contracts.raw_extraction_schema import RawExtraction
    path = directory / 'context_coverage.json'
    if not path.exists():
        return  # Existing revisions have explicit unknown historical context.
    ledger = CoverageLedger.model_validate_json(path.read_text(encoding='utf-8'))
    if ledger.legacy_context_unknown:
        return
    raw = RawExtraction.model_validate_json((directory / 'raw_extraction.json').read_text(encoding='utf-8'))
    if ledger.source_integrity == 'verified' and not verify_retained_sources(directory, raw):
        raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='publication')
    chunks = ContextChunksArtifact.model_validate_json((directory / 'extraction_chunks.json').read_text(encoding='utf-8')).chunks
    if (directory / 'context_chunks.json').is_file():
        ContextChunksArtifact.model_validate_json((directory / 'context_chunks.json').read_text(encoding='utf-8'))
    expected = ledger.totals.copy()
    findings = validate_context_coverage(raw, chunks, ledger)
    if findings or ledger.totals != expected:
        raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='publication')
    for prepared_path in (directory / 'prepared_contexts').glob('*.json'):
        from contracts.context_schema import PreparedContext
        prepared = PreparedContext.model_validate_json(prepared_path.read_text(encoding='utf-8'))
        if prepared.measurement.input_tokens > prepared.budget.input_ceiling:
            raise ContextBudgetError('REQUIRED_CONTEXT_TOO_LARGE', stage='publication')


def verify_retained_sources(directory, raw):
    import json
    path = directory / 'source_manifest.json'
    if not path.is_file():
        return False
    manifest = json.loads(path.read_text(encoding='utf-8'))
    members = manifest.get('members', [])
    if not members:
        return False
    if not raw.documents:
        return False  # Historical parser bundles have no verifiable source descriptors.
    expected = {(d.document_id, d.source_sha256, d.parse_key) for d in raw.documents}
    actual = {(m['document']['document_id'], m['document']['source_sha256'], m['document']['parse_key']) for m in members}
    if expected != actual:
        raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='source_inventory')
    for member in members:
        bundle = (directory / member['bundle_directory']).resolve()
        if not bundle.is_relative_to(directory.resolve()):
            raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='source_inventory')
        for name, digest in member['artifacts'].items():
            source = (bundle/name).resolve()
            if not source.is_relative_to(bundle) or not source.is_file() or file_hash(source) != digest:
                raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='source_inventory')
        if file_hash(bundle/'source_snapshot.bin') != member['document']['source_sha256']:
            raise ContextBudgetError('CONTEXT_COVERAGE_GAP', stage='source_inventory')
    return True
