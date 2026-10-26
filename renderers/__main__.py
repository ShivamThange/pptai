"""Portable CLI over the canonical boundary: python -m renderers scene.json out.pptx."""
import argparse
import json
from pathlib import Path
from renderers.base import PresentationScene
from renderers.factory import get_renderer


def main():
    parser = argparse.ArgumentParser(description="Render a validated scene-v1 presentation")
    parser.add_argument("scene")
    parser.add_argument("output")
    parser.add_argument("--renderer", choices=["python", "pptxgenjs"], required=True)
    args = parser.parse_args()
    scene = PresentationScene.model_validate_json(Path(args.scene).read_text(encoding="utf-8"))
    result = get_renderer(args.renderer).render(scene, None, {}, args.output)
    print(json.dumps(result.metadata()))


if __name__ == "__main__":
    main()
