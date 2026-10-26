import csv
import html
from pathlib import Path

from ..util import write_json


def _csv(path, rows):
    rows = list(rows)
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys); writer.writeheader(); writer.writerows(rows)


def write(report, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    write_json(out / "report.json", report)
    metric = report["metrics"]
    _csv(out / "summary.csv", [{"run_id": report["run"]["run_id"], "tool_name": report["run"]["tool_name"], "overall": metric["automated_overall"], **{k: v.get("score") if isinstance(v, dict) else v for k, v in metric.items() if k != "automated_overall"}}])
    _csv(out / "concept_coverage.csv", report["concepts"])
    _csv(out / "claims.csv", [{k: (str(v) if isinstance(v, (list, dict)) else v) for k, v in x.items()} for x in report["claims"]])
    _csv(out / "slide_metrics.csv", report["slides"])
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in metric.items())
    missing = "".join(f"<li>{html.escape(x['concept_id'])}: {html.escape(x['title'])}</li>" for x in report["concepts"] if x["status"] == "MISSING") or "<li>None</li>"
    (out / "report.html").write_text(f"<!doctype html><meta charset='utf-8'><title>PPT Evaluation</title><style>body{{font:16px Arial;margin:2rem}}table{{border-collapse:collapse}}td,th{{padding:.4rem;border:1px solid #ccc;text-align:left}}</style><h1>PPT evaluation: {html.escape(report['run']['tool_name'])}</h1><table>{rows}</table><h2>Missing concepts</h2><ul>{missing}</ul><h2>Warnings</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in report['warnings'])}</ul>", encoding="utf-8")
