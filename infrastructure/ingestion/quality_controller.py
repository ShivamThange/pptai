"""Artifact-bound quality reports and readiness; critical failures never average away."""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from evaluation.config import load
from evaluation.extract.pptx_extractor import extract
from evaluation.metrics.functional import evaluate as evaluate_functional
from evaluation.metrics.visual import evaluate as evaluate_visual
from infrastructure.ingestion.slide_renderer import render_pptx_slides
from infrastructure.ingestion.visual_reviewer import audit_slide_images

CheckStatus = Literal['FAILED_TO_RUN', 'NOT_EVALUATED', 'EVALUATED_FAIL', 'EVALUATED_PASS']


def artifact_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class QualityCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: CheckStatus
    reason: str | None = None
    artifact_hash: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['2'] = '2'
    artifact_hash: str | None
    revision_id: str | None
    status: CheckStatus
    readiness: Literal['BLOCKED', 'DRAFT_INCOMPLETE', 'BASIC_CHECKED', 'VERIFIED']
    deterministic: QualityCheck
    factual: QualityCheck = Field(default_factory=lambda: QualityCheck(status='NOT_EVALUATED', reason='No grounding assessment supplied'))
    rendered: QualityCheck = Field(default_factory=lambda: QualityCheck(status='NOT_EVALUATED', reason='No render requested'))
    judge: QualityCheck = Field(default_factory=lambda: QualityCheck(status='NOT_EVALUATED', reason='Optional visual judging disabled'))
    visual: dict[str, Any] = Field(default_factory=dict)
    functional: dict[str, Any] = Field(default_factory=dict)
    slides: list[dict[str, Any]] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# Compatibility name; legacy unbound JSON must use the explicit adapter below.
DeterministicQualityReport = QualityReport


def write_quality_report(report, output_dir):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'quality_report.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(report.model_dump_json(indent=2), encoding='utf-8')
    QualityReport.model_validate_json(temporary.read_text(encoding='utf-8'))
    temporary.replace(path)


def adapt_legacy_quality_report(legacy, pptx_path, output_dir):
    """Recheck the actual file; a legacy PASSED never grants artifact-bound approval."""
    if legacy.get('schema_version') == '2':
        report = QualityReport.model_validate(legacy)
        if report.artifact_hash != artifact_hash(pptx_path):
            raise ValueError('Quality report belongs to a different artifact')
        return report
    return run_deterministic_quality_checks(pptx_path, output_dir, raise_on_failure=False)


def run_deterministic_quality_checks(pptx_path, output_dir, *, config_path=None, raise_on_failure=True, force_accept=False):
    digest = artifact_hash(pptx_path) if Path(pptx_path).is_file() else None
    report = QualityReport(artifact_hash=digest, revision_id='sha256:' + digest if digest else None,
                           status='FAILED_TO_RUN', readiness='BLOCKED',
                           deterministic=QualityCheck(status='FAILED_TO_RUN', artifact_hash=digest))
    try:
        candidate = extract(pptx_path, tool_name='multi-agent')
        rows, visual = evaluate_visual(candidate['slides'], candidate['slide_width'], candidate['slide_height'], load(config_path))
        _, functional = evaluate_functional(candidate['slides'])
        failures, warnings = [], list(functional['warnings'])
        if not candidate['slides'] or candidate['image_flattened_candidate']:
            failures.append('No extractable native content; blank/flattened candidates cannot pass the native quality gate.')
        for slide, row in zip(candidate['slides'], rows):
            if not slide['text'].strip():
                failures.append(f"Slide {row['slide_no']}: no extractable required content")
            if row['out_of_bounds_count'] or row['suspicious_overlap_count'] or any(f['required'] for f in row['font_findings']):
                failures.append(f"Slide {row['slide_no']}: {'; '.join(row['warnings'])}")
            warnings.extend(row['warnings'])
        report.visual, report.functional, report.slides = visual, functional, rows
        report.hard_failures, report.warnings = failures, warnings
        report.deterministic = QualityCheck(status='EVALUATED_FAIL' if failures else visual['status'], artifact_hash=digest,
                                           details={'geometry': 'APPROXIMATE_NATIVE_BOUNDS', 'readability': 'ROLE_FONT_FLOORS'})
        report.status = report.deterministic.status
        report.readiness = 'BLOCKED' if failures else ('DRAFT_INCOMPLETE' if visual['status'] == 'NOT_EVALUATED' else 'BASIC_CHECKED')
    except Exception as error:
        report.deterministic.reason = str(error)
        report.hard_failures.append('Native extraction/checks failed: ' + str(error))
    write_quality_report(report, output_dir)
    if report.hard_failures and force_accept:
        print("[WARN] Quality gate bypassed: " + " | ".join(report.hard_failures))
        report.warnings.extend(report.hard_failures)
        report.hard_failures = []
        report.deterministic.details['force_accept'] = 'BYPASSED'
        if report.status in {'EVALUATED_FAIL', 'FAILED_TO_RUN'} and report.readiness == 'BLOCKED':
            report.deterministic.status = 'EVALUATED_PASS'
            report.status = 'EVALUATED_PASS'
            report.readiness = 'BASIC_CHECKED'
    elif report.hard_failures and raise_on_failure:
        raise ValueError('Deterministic PPTX quality gate failed: ' + ' | '.join(report.hard_failures))
    return report


def factual_check(ir1, ir2, digest, *, deep_verification=False):
    if ir1 is None or ir2 is None:
        return QualityCheck(status='NOT_EVALUATED', artifact_hash=digest, reason='No grounding assessment supplied')
    rows = [row for slide in ir2.slides for row in slide.grounding.values()]
    failed = [row for row in rows if row.status == 'REJECTED' or 'FAILED' in
              {row.citation_exists, row.numeric_binding, row.semantic_support}]
    details = {'ir1_completeness': ir1.completeness, 'visible_claims': len(rows),
               'unknown_semantic_claims': sum(row.semantic_support == 'UNKNOWN' for row in rows),
               'deep_verification': deep_verification}
    if failed:
        return QualityCheck(status='EVALUATED_FAIL', artifact_hash=digest, details=details, reason='Critical visible factual failure/contradiction')
    from infrastructure.ingestion.slide_composer import visible_claims
    from infrastructure.utils.artifacts import sha256_value
    claims_match = all(set(slide.grounding) == set(visible_claims(slide)) and
                       all(slide.grounding[key].claim_sha256 == sha256_value(claim)
                           for key, claim in visible_claims(slide).items()) for slide in ir2.slides)
    basic_complete = bool(rows) and claims_match and all(row.citation_exists == 'CHECKED' and row.numeric_binding in {'CHECKED', 'NOT_APPLICABLE'} for row in rows)
    complete = basic_complete and ir1.completeness == 'VERIFIED' and all(row.status == 'VERIFIED' and row.semantic_support == 'CHECKED' for row in rows)
    details['completeness'] = 'VERIFIED' if complete else ('BASIC_CHECKED' if basic_complete and ir1.completeness != 'INCOMPLETE' else 'INCOMPLETE')
    if not basic_complete or ir1.completeness == 'INCOMPLETE':
        return QualityCheck(status='NOT_EVALUATED', artifact_hash=digest, details=details, reason='Grounding assessment is incomplete')
    if deep_verification and not complete:
        unavailable = any(row.semantic_support == 'UNKNOWN' and any('unavailable' in reason.lower() for reason in row.reason) for row in rows)
        return QualityCheck(status='FAILED_TO_RUN' if unavailable else 'NOT_EVALUATED', artifact_hash=digest,
                            details=details, reason='Required deep factual assessment is unavailable' if unavailable else 'Required deep factual assessment is incomplete')
    return QualityCheck(status='EVALUATED_PASS', artifact_hash=digest, details=details)


def resolve_readiness(report):
    checks = (report.deterministic, report.factual, report.rendered, report.judge)
    if report.deterministic.status == 'FAILED_TO_RUN':
        report.status, report.readiness = 'FAILED_TO_RUN', 'BLOCKED'
    elif report.hard_failures or any(check.status == 'EVALUATED_FAIL' for check in checks):
        report.status, report.readiness = 'EVALUATED_FAIL', 'BLOCKED'
    elif any(check.status == 'FAILED_TO_RUN' for check in checks) or any(check.status == 'NOT_EVALUATED' for check in (report.deterministic, report.factual, report.rendered)):
        report.status, report.readiness = 'NOT_EVALUATED', 'DRAFT_INCOMPLETE'
    else:
        report.status = 'EVALUATED_PASS'
        report.readiness = ('VERIFIED' if report.factual.details.get('completeness') == 'VERIFIED' and report.factual.details.get('deep_verification')
                            and report.judge.status == 'EVALUATED_PASS' else 'BASIC_CHECKED')
    return report


def assess_final_artifact(pptx_path, output_dir, *, ir1=None, ir2=None, caller=None, judge_enabled=False, deep_verification=False, force_accept=False):
    """Each invocation renders this exact candidate, including accepted repairs."""
    report = run_deterministic_quality_checks(pptx_path, output_dir, raise_on_failure=False, force_accept=force_accept)
    digest = report.artifact_hash
    report.factual = factual_check(ir1, ir2, digest, deep_verification=deep_verification)
    if report.factual.status == 'EVALUATED_FAIL':
        report.hard_failures.append(report.factual.reason)
    render = render_pptx_slides(pptx_path, Path(output_dir) / 'rendered_slides' / digest)
    report.rendered = QualityCheck(status=render.status, reason=render.reason, artifact_hash=render.artifact_hash,
                                  details={'backend': render.backend, 'images': [str(p) for p in render.image_paths],
                                           'image_hashes': render.image_hashes, 'text_bounds_status': render.text_bounds_status,
                                           'findings': render.findings})
    if render.artifact_hash != digest or not Path(pptx_path).is_file() or artifact_hash(pptx_path) != digest:
        report.rendered.status = 'FAILED_TO_RUN'
        report.rendered.reason = 'Artifact changed or render belongs to a different artifact'
    if report.rendered.status == 'EVALUATED_PASS' and len(render.image_paths) != len(report.slides):
        report.rendered.status = 'FAILED_TO_RUN'
        report.rendered.reason = 'Incomplete rendered slide set'
    if render.findings and report.rendered.status != 'FAILED_TO_RUN':
        descriptions = {"POWERPOINT_MEASURED_OUT_OF_BOUNDS": "native object extends beyond the slide",
                        "POWERPOINT_MEASURED_GEOMETRY_CHANGE": "native object expanded beyond its declared geometry"}
        report.hard_failures.extend(f"Slide {f['slide_no']}: {descriptions.get(f.get('check'), 'measured text overflows its allocated box')} (object {f['shape_id']})" for f in render.findings if f.get('required', True))
        if any(f.get('required', True) for f in render.findings):
            report.rendered.status = 'EVALUATED_FAIL'
    if judge_enabled:
        if report.rendered.status in {'EVALUATED_PASS', 'EVALUATED_FAIL'}:
            vision = audit_slide_images([str(p) for p in render.image_paths], caller, artifact_hash=digest,
                                        expected_slide_count=len(report.slides))
            report.judge = QualityCheck(status=vision.status, reason=vision.reason, artifact_hash=digest,
                                       details={'audits': [audit.model_dump() for audit in vision.audits]})
            if any(not p.is_file() or artifact_hash(p) != render.image_hashes.get(str(p)) for p in render.image_paths):
                report.judge.status = 'FAILED_TO_RUN'
                report.judge.reason = 'Rendered images changed during visual judging'
            for audit in vision.audits:
                if not audit.passed:
                    report.hard_failures.append(f'Slide {audit.slide_id}: {audit.actionable_feedback or audit.critique_summary}')
        else:
            report.judge = QualityCheck(status='FAILED_TO_RUN', artifact_hash=digest, reason='Rendering unavailable; visual audit could not run')
    if force_accept:
        # The deterministic bypass cannot cover failures recorded after it ran, so a
        # measured text overflow still reached PIPELINE_REJECTED with an emptied reason.
        failing = [check for check in (report.deterministic, report.factual, report.rendered, report.judge)
                   if check.status == 'EVALUATED_FAIL']
        if report.hard_failures or failing:
            detail = " | ".join(report.hard_failures) or ", ".join(
                name for name, check in (("deterministic", report.deterministic), ("factual", report.factual),
                                         ("rendered", report.rendered), ("judge", report.judge)) if check in failing)
            print("[WARN] Final quality gate bypassed: " + detail)
            report.warnings.extend(report.hard_failures)
            report.hard_failures = []
            for check in failing:
                check.status = 'EVALUATED_PASS'
                check.details['force_accept'] = 'BYPASSED'
    report = resolve_readiness(report)
    report.visual['rendered_clipping_status'] = report.judge.status
    for row in report.slides:
        row['rendered_clipping_status'] = report.judge.status
        bounds = report.rendered.details.get('text_bounds_status', 'NOT_EVALUATED')
        if bounds == 'EVALUATED_FAIL':
            bounds = 'EVALUATED_FAIL' if any(f['slide_no'] == row['slide_no'] for f in render.findings) else 'EVALUATED_PASS'
        row['rendered_text_bounds_status'] = bounds
    if report.readiness in {'VERIFIED', 'BASIC_CHECKED'} and render.text_bounds_status != 'EVALUATED_PASS' and report.judge.status != 'EVALUATED_PASS':
        report.status, report.readiness = 'NOT_EVALUATED', 'DRAFT_INCOMPLETE'
    write_quality_report(report, output_dir)
    return report
