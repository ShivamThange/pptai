"""Synchronous application operations shared by CLI and the local worker."""
from infrastructure.utils.artifacts import parse_document_cached
from application.jobs.job_context import check, report
from infrastructure.llm.llm_client import LLMClient
from infrastructure.ingestion.stage2_quality_gate import verify_structural_ir
from application.pipeline.orchestrator import run_multi_agent_pipeline, UNSPECIFIED_BASE
from application.services.slide_editor import edit_multi_agent_slide
from renderers.factory import validate_renderer_runtime


def parse_source(source_path, parse_root, *, use_gpu=False, resume=True, context=None, on_parsed=None,
                 selected_type=None, parse_options=None, upload_spec=None, limits=None):
    report(context, "parsing")
    path = parse_document_cached(source_path, parse_root, use_gpu=use_gpu, resume=resume,
        selected_type=selected_type, parse_options=parse_options, upload_spec=upload_spec, context=context, limits=limits)
    if on_parsed:
        on_parsed(path)
    import json
    from pathlib import Path
    result_path = Path(path).parent / 'parse_result.json'
    details = None
    if result_path.is_file():
        from contracts.ingestion_schema import ParseResult
        result = ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public()
        result['upload_id'] = (upload_spec or {}).get('upload_id')
        details = {'files_completed': 1, 'files_total': 1, 'current_document_id': result['upload_id'], 'outcomes': [result]}
    report(context, "parsing", 1, 1, details)
    return path


def generate_deck(source_path, parse_root, options, *, context=None, caller=None,
                  settings=None, api_key=None, expected_base_revision=UNSPECIFIED_BASE, on_parsed=None,
                  parse_resume=None, selected_type=None, parse_options=None, upload_spec=None, limits=None,
                  source_selection=None):
    check(context)
    validate_renderer_runtime(options.renderer)
    structural = parse_source(source_path, parse_root, use_gpu=getattr(options, "use_gpu", False),
                              resume=options.resume if parse_resume is None else parse_resume,
                              context=context, on_parsed=on_parsed, selected_type=selected_type,
                              parse_options=parse_options, upload_spec=upload_spec, limits=limits)
    import json
    from pathlib import Path
    from contracts.ingestion_schema import IngestionError
    if Path(structural).is_file():
        data = json.loads(Path(structural).read_text(encoding='utf-8'))
        if str(data.get('schema_version')) == '3':
            if not data.get('blocks'):
                raise IngestionError('SOURCE_CONTENT_UNAVAILABLE', 'No text/data supported by current knowledge extraction is available.')
            if source_selection:
                from infrastructure.ingestion.collection import assemble
                result = json.loads((Path(structural).parent / 'parse_result.json').read_text(encoding='utf-8'))
                structural = assemble([{'path': structural, 'result': result,
                    'upload_ids': source_selection.get('upload_ids', []), 'aliases': source_selection.get('aliases', [])}], options.output_dir)
    report(context, "structural validation")
    if not verify_structural_ir(str(structural)):
        raise ValueError("Structural IR validation failed")
    report(context, "structural validation", 1, 1)
    client = caller or LLMClient(settings=settings, api_key=api_key,
                               cancel_event=context.cancel_event if context else None)
    return run_multi_agent_pipeline(structural, options, caller=client, context=context,
                                   expected_base_revision=expected_base_revision,
                                   job_id=context.job_id if context else None)


def parse_sources(sources, parse_root, *, use_gpu=False, resume=True, context=None, limits=None,
                  on_outcome=None, on_member_parsed=None):
    """Evaluate every member; ordinary file failures never remove source membership."""
    import json
    import logging
    import sqlite3
    from pathlib import Path
    from infrastructure.utils.artifacts import file_hash
    from contracts.ingestion_schema import IngestionError
    outcomes, members = [], []
    for index, source in enumerate(sources):
        check(context)
        upload_id = source.get('document_id')
        report(context, 'parsing', index, len(sources), {'files_completed': index,
            'files_total': len(sources), 'current_document_id': upload_id, 'outcomes': outcomes})
        try:
            path = Path(source['source_path'])
            if source.get('source_sha256') and file_hash(path) != source['source_sha256']:
                raise IngestionError('SOURCE_INTEGRITY_ERROR', 'Stored source bytes changed; replace the upload.')
            parsed = parse_source(path, source.get('parse_root') or Path(parse_root) / (upload_id or file_hash(path)),
                selected_type=source.get('selected_type'), parse_options=source.get('parse_options'),
                upload_spec=source.get('upload_spec'), use_gpu=use_gpu, resume=resume, context=context, limits=limits)
            result_path = parsed.parent / 'parse_result.json'
            if result_path.is_file():
                from contracts.ingestion_schema import ParseResult
                result = ParseResult.model_validate_json(result_path.read_text(encoding='utf-8')).public()
            else:
                result = {'document_id': 'doc_' + file_hash(path), 'parse_key': parsed.parent.name,
                          'status': 'complete', 'completeness': 'unknown', 'findings': []}
            result['upload_id'] = upload_id
            members.append({'path': parsed, 'result': result, 'upload_ids': source.get('upload_ids', []),
                            'aliases': source.get('aliases', [path.name])})
            if on_member_parsed:
                on_member_parsed(upload_id, parsed)
        except sqlite3.Error:
            raise
        except Exception as error:
            if getattr(error, 'error_class', None) == 'cancelled':
                raise
            logging.getLogger(__name__).exception('Source %s failed', upload_id)
            result = getattr(error, 'result', None) or {'document_id': 'doc_' + source.get('source_sha256', ''),
                'status': 'failed', 'completeness': 'unknown', 'findings': [{'code': getattr(error, 'code', 'CORRUPT_SOURCE'),
                'severity': 'error', 'message': str(error) if isinstance(error, IngestionError) else 'Source parsing failed; inspect the local log.',
                'blocks_generation': True}]}
            result['upload_id'] = upload_id
        check(context)
        outcomes.append(result)
        if on_outcome:
            for identifier in source.get('upload_ids') or [upload_id]:
                on_outcome(identifier, {**result, 'upload_id': identifier})
        report(context, 'parsing', index + 1, len(sources), {'files_completed': index + 1,
            'files_total': len(sources), 'current_document_id': upload_id, 'outcomes': outcomes})
    # Step 2.1: a single corrupt source must not abort the whole deck.
    # Keep every member whose parse completed; drop (but still report) the
    # failed ones so downstream stages proceed with valid files only.
    valid_members = []
    valid_outcomes = []
    failed_outcomes = []

    for member, outcome in zip(members, outcomes):
        if outcome['status'] == 'complete':
            valid_members.append(member)
            valid_outcomes.append(outcome)
        else:
            failed_outcomes.append(outcome)
            logging.getLogger(__name__).warning(
                f"Skipping failed source: {outcome.get('upload_id', 'unknown')}. "
                f"Reason: {outcome.get('findings', [])}")

    if not valid_members:
        raise IngestionError('SOURCE_SET_INCOMPLETE',
                             'All provided sources failed to parse. Check file integrity.',
                             result={'sources': outcomes})

    members = valid_members
    outcomes = valid_outcomes + failed_outcomes
    return members, outcomes


def generate_deck_from_sources(sources, parse_root, options, *, context=None, caller=None, settings=None, api_key=None,
        expected_base_revision=UNSPECIFIED_BASE, on_parsed=None, on_outcome=None, on_member_parsed=None, limits=None,
        parse_resume=True):
    from infrastructure.ingestion.collection import assemble
    from contracts.ingestion_schema import IngestionError
    check(context)
    validate_renderer_runtime(options.renderer)
    members, outcomes = parse_sources(sources, parse_root, use_gpu=options.use_gpu, resume=parse_resume,
        context=context, limits=limits, on_outcome=on_outcome, on_member_parsed=on_member_parsed)
    structural = assemble(members, options.output_dir)
    if on_parsed:
        on_parsed(structural)
    report(context, 'structural validation')
    if not verify_structural_ir(str(structural)):
        raise IngestionError('SOURCE_SET_INCOMPLETE', 'Collection validation failed.', result={'sources': outcomes})
    import json
    if not json.loads(structural.read_text(encoding='utf-8')).get('blocks'):
        raise IngestionError('SOURCE_CONTENT_UNAVAILABLE', 'These sources have no text/data supported by current knowledge extraction.', result={'sources': outcomes})
    client = caller or LLMClient(settings=settings, api_key=api_key, cancel_event=context.cancel_event if context else None)
    return run_multi_agent_pipeline(structural, options, caller=client, context=context,
        expected_base_revision=expected_base_revision, job_id=context.job_id if context else None)


def edit_slide(output_dir, layouts_path, slide_index, instruction, base_revision, *,
               max_repairs=1, context=None, caller=None, settings=None, api_key=None, renderer=None):
    check(context)
    return edit_multi_agent_slide(output_dir=output_dir, layouts_path=layouts_path, slide_index=slide_index,
                                 instruction=instruction, base_revision=base_revision, max_repairs=max_repairs,
                                 caller=caller, settings=settings, api_key=api_key, renderer=renderer,
                                 context=context, job_id=context.job_id if context else None)
