import os
import json
from pathlib import Path

def verify_structural_ir(ir_path: str = "output/ir.json") -> bool:
    """Quality Gate checkpoint verifying all extracted assets exist on disk and emitting validation_report.json."""
    if not os.path.exists(ir_path):
        raise FileNotFoundError(f"Structural IR not found at {ir_path}")

    ir_file = Path(ir_path).resolve()
    with open(ir_file, "r", encoding="utf-8") as f:
        ir = json.load(f)

    # Initialize validation statistics
    blocks = ir.get("blocks", [])
    assets = ir.get("assets", [])
    
    counts = {
        "blocks": len(blocks),
        "total_assets": len(assets),
        "images": sum(1 for a in assets if str(a.get("type", "")).lower() in {"image", "diagram"}),
        "tables": sum(1 for a in assets if str(a.get("type", "")).lower() == "table"),
        "formulas": sum(1 for a in assets if str(a.get("type", "")).lower() == "formula"),
        "charts": sum(1 for a in assets if str(a.get("type", "")).lower() == "chart"),
    }

    missing_assets = []
    base_dir = ir_file.parent

    for asset in assets:
        kind = str(asset.get("type") or asset.get("kind") or "").lower()
        # Check files referenced by asset
        for field in ["file_path", "json_path", "csv_path"]:
            p_val = asset.get(field)
            if p_val and asset.get("availability") != "MISSING":
                p = Path(p_val)
                if not p.is_absolute():
                    p = base_dir / p
                if not p.is_file():
                    missing_assets.append({"asset_id": asset.get("asset_id"), "field": field, "path": str(p)})

    status = "valid"
    findings = []
    if missing_assets:
        status = "invalid"
        findings.append(f"Missing {len(missing_assets)} asset files on disk.")
    elif ir.get("findings"):
        findings = [f.get("message", str(f)) if isinstance(f, dict) else str(f) for f in ir.get("findings")]
        if any("incomplete" in f.lower() or "partial" in f.lower() for f in findings):
            status = "partial"

    # For v3 schema, run typed ingestion validation
    if str(ir.get("schema_version")) == "3":
        from pipeline.ingestion.validation import validate_ingestion
        try:
            validate_ingestion(str(ir_file), require_complete=False)
        except Exception as e:
            status = "invalid"
            findings.append(str(e))

    report = {
        "schema_version": "validation-report-v1",
        "document_name": ir.get("document_name", "document"),
        "status": status,
        "counts": counts,
        "missing_assets": missing_assets,
        "findings": findings,
    }

    report_path = base_dir / "validation_report.json"
    try:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    if status == "invalid":
        print(f"[FAIL] Quality Gate failed! Missing assets or invalid IR: {missing_assets}")
        return False

    print(f"[PASS] Quality Gate passed! Status: {status}. Total blocks: {counts['blocks']}, Total assets: {counts['total_assets']}")
    return True
