import argparse

from .config import load
from .reference.build_reference import build
from .runner import evaluate_presentation


def main():
    parser = argparse.ArgumentParser(description="Evaluate generated PPTX decks")
    sub = parser.add_subparsers(dest="command", required=True)
    ref = sub.add_parser("prepare-reference"); ref.add_argument("--ir", required=True); ref.add_argument("--ir1", required=True); ref.add_argument("--out", required=True); ref.add_argument("--config")
    ev = sub.add_parser("evaluate"); ev.add_argument("--reference", required=True); ev.add_argument("--pptx", required=True); ev.add_argument("--tool-name", required=True); ev.add_argument("--run-id", required=True); ev.add_argument("--out", required=True); ev.add_argument("--config"); ev.add_argument("--no-ai-judging", action="store_true")
    args = parser.parse_args(); config = load(args.config)
    if args.command == "prepare-reference":
        profile = build(args.ir, args.ir1, args.out); print(f"[OK] Cached {len(profile['concepts'])} concepts at {args.out}")
    elif args.command == "evaluate":
        report = evaluate_presentation(args.reference, args.pptx, args.tool_name, args.run_id, args.out, config, not args.no_ai_judging); print(f"[OK] Readiness: {report['readiness']}; overall score: {report['metrics']['automated_overall']}")


if __name__ == "__main__": main()
