"""End-to-end theme smoke: render the chrome deck with all five themes on both
backends and print the chrome report, warnings and object counts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.jobs.builder import PresentationBuilder
from domain.rendering.theme_engine import available_themes, load_theme

LAYOUTS = Path("config/ppt_default_layouts.json")
OUT = Path("/home/z/my-project/download/theme-smoke")
OUT.mkdir(parents=True, exist_ok=True)

DECK = {"title": "Quarterly Engineering Review", "slides": [
    {"layout": "TITLE_CENTERED", "content": {
        "title": {"type": "heading", "text": "Quarterly Engineering Review"},
        "subtitle": {"type": "text_group", "text": "Platform reliability and velocity"}}},
    {"layout": "HEADER_WITH_BODY", "content": {
        "header": {"type": "heading", "text": "Reliability improved across every service"},
        "body": {"type": "bullets", "items": [
            "Error budget consumption fell 38% quarter over quarter",
            "p99 latency held under 200ms through peak traffic",
            "Zero customer-incident escalations in September"]}}},
    {"layout": "SECTION_DIVIDER", "content": {
        "section_title": {"type": "heading", "text": "Velocity"},
        "section_subtitle": {"type": "text_group", "text": "Delivery throughput and review health"}}},
    {"layout": "METRIC_CALLOUT_3_GRID", "content": {
        "header": {"type": "heading", "text": "Delivery at a glance"},
        "card_1": {"type": "metric_card", "value": "214", "label": "Merges per week", "trend": "+18%"},
        "card_2": {"type": "metric_card", "value": "4.2h", "label": "Median review time"},
        "card_3": {"type": "card", "title": "Rollbacks", "text": "Down to 1.1% of releases.",
                   "metric": {"value": "1.1%", "label": "of releases"}}}},
    {"layout": "QUOTE_CALLOUT", "content": {
        "quote": {"type": "quote", "text": "The platform team ships faster with fewer incidents than any quarter on record."},
        "attribution": {"type": "text_group", "text": " VP of Engineering"}}},
    {"layout": "TABLE_FULL_WIDTH", "content": {
        "header": {"type": "heading", "text": "Service-level results"},
        "table": {"type": "table", "headers": ["Service", "Uptime", "p99"],
                  "rows": [["API gateway", "99.98%", "148ms"], ["Checkout", "99.95%", "184ms"],
                           ["Search", "99.91%", "196ms"]]},
        "source": {"type": "text_group", "text": "Source: internal SRE dashboards, Q3."}}},
    {"layout": "CLOSING_SLIDE", "content": {
        "title": {"type": "heading", "text": "Thank you"},
        "message": {"type": "text_group", "text": "Full runbooks and dashboards are linked in the appendix."},
        "contact": {"type": "text_group", "text": "platform-eng@example.com"}}},
]}

failures = []
for theme_id in sorted(available_themes()):
    theme = load_theme(theme_id)
    for backend in ("python", "pptxgenjs"):
        try:
            builder = PresentationBuilder(LAYOUTS, backend=backend, theme=theme, dynamic_layout=True)
            target = OUT / f"{theme_id}_{backend}.pptx"
            warnings = builder.build(json.loads(json.dumps(DECK)), str(target))
            report = builder.chrome_report
            decor = sum(1 for slide in builder.last_scene.slides for obj in slide.objects
                        if "//decor-" in obj.object_id)
            status = "OK " if not warnings and not report["failures"] else "WARN"
            print(f"[{status}] {theme_id:16s} {backend:10s} decor={decor:2d} "
                  f"warnings={len(warnings)} failures={len(report['failures'])} -> {target.name}")
            if warnings or report["failures"]:
                failures.append((theme_id, backend, warnings, report["failures"]))
        except Exception as error:
            failures.append((theme_id, backend, [], [str(error)]))
            print(f"[FAIL] {theme_id} {backend}: {type(error).__name__}: {error}")

if failures:
    print("\nDETAIL:")
    print(json.dumps(failures, indent=2, default=str))
    sys.exit(1)
print("\nAll 10 renders clean (5 themes x 2 backends).")
