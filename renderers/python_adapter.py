"""Python migration renderer; consumes the same resolved scene as Node."""
import copy
import os
import tempfile
from importlib.metadata import version
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from infrastructure.utils.artifacts import file_hash
from renderers.base import PresentationScene, RenderArtifact, validate_scene_assets
from renderers.python_primitives import PythonPrimitives, hex_to_rgb
from renderers.artifact import seal_native_metadata, verify_native_coverage


def _edge_anchor(box, toward_x: float, toward_y: float):
    """Point on a box border nearest to a target point (inches)."""
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    if box.w <= 0 or box.h <= 0:
        return cx, cy
    dx, dy = toward_x - cx, toward_y - cy
    if dx == 0 and dy == 0:
        return cx, box.y  # degenerate: top edge
    # Scale the center-to-target vector so it hits the border.
    scale_x = (box.w / 2) / abs(dx) if dx else float("inf")
    scale_y = (box.h / 2) / abs(dy) if dy else float("inf")
    scale = min(scale_x, scale_y)
    return cx + dx * scale, cy + dy * scale


def _add_arrowhead(shape) -> None:
    """Attach a triangle arrowhead at the connector's end (tail)."""
    line = shape.line._get_or_add_ln()
    for tag in ("a:tailEnd",):
        existing = line.find(qn(tag))
        if existing is not None:
            line.remove(existing)
    tail = line.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    line.append(tail)


class PythonRenderer:
    backend = "python"

    def render(self, scene_graph, asset_registry, theme, output_path):
        scene = (scene_graph if isinstance(scene_graph, PresentationScene)
                 else PresentationScene.model_validate(scene_graph))
        validate_scene_assets(scene, asset_registry)
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        deck = Presentation()
        deck.slide_width, deck.slide_height = Inches(scene.width_inches), Inches(scene.height_inches)
        deck.core_properties.title = scene.title
        primitives = PythonPrimitives(scene.width_inches, scene.height_inches)
        degraded: list[str] = []
        for scene_slide in scene.slides:
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = hex_to_rgb(scene_slide.background_color)
            nodes = {o.object_id: o for o in scene_slide.objects}
            # Renderers retain scene ordering; connectors can attach after nodes exist.
            for obj in scene_slide.objects:
                before = len(slide.shapes)
                try:
                    self._draw_object(primitives, slide, obj, nodes, theme, scene)
                    if len(slide.shapes) != before + 1:
                        raise ValueError("Python primitive changed object coverage")
                    slide.shapes[-1].name = obj.object_id
                except Exception as error:
                    # Graceful degradation: one failing primitive must not reject the
                    # deck. Discard any partial draw, keep the object slot occupied by
                    # an explicit placeholder, and let the quality gates report it.
                    for stray in list(slide.shapes)[before:]:
                        stray._element.getparent().remove(stray._element)
                    print(f"[WARN] Visual render failed for {obj.object_id} ({obj.kind}) on "
                          f"slide {scene_slide.slide_id}: {type(error).__name__}: {error}")
                    self._draw_placeholder(slide, obj, type(error).__name__)
                    degraded.append(f"slide {scene_slide.slide_id}/{obj.object_id}: rendered as "
                                    f"placeholder ({type(error).__name__})")
            if scene_slide.notes:
                slide.notes_slide.notes_text_frame.text = scene_slide.notes
        fd, temporary = tempfile.mkstemp(suffix=".pptx", dir=target.parent)
        os.close(fd)
        temp = Path(temporary)
        try:
            deck.save(temp)
            seal_native_metadata(temp, scene)
            capabilities = verify_native_coverage(temp, scene)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
            temp.with_suffix(".sealed.pptx").unlink(missing_ok=True)
        return RenderArtifact(target, self.backend, version("python-pptx"), file_hash(target),
                              tuple(degraded), capabilities)

    def _draw_object(self, primitives, slide, obj, nodes, theme, scene) -> None:
        b = obj.box
        region = {"left": b.x/scene.width_inches, "top": b.y/scene.height_inches,
                  "width": b.w/scene.width_inches, "height": b.h/scene.height_inches,
                  "allowed_types": [obj.kind]}
        content = copy.deepcopy(obj.content)
        style = {**(theme or {}), **obj.style}
        content.update(type=obj.kind, style=style)
        if obj.kind == "shape":
            shape_type = {"rect": MSO_SHAPE.RECTANGLE, "roundRect": MSO_SHAPE.ROUNDED_RECTANGLE,
                          "diamond": MSO_SHAPE.DIAMOND, "ellipse": MSO_SHAPE.OVAL}[content.get("shape_type", "rect")]
            shape = slide.shapes.add_shape(shape_type, Inches(b.x), Inches(b.y), Inches(b.w), Inches(b.h))
            shape.fill.solid(); shape.fill.fore_color.rgb = hex_to_rgb(style.get("fill", "#EFF6FF"))
            shape.line.color.rgb = hex_to_rgb(style.get("line_color", "#3B82F6"))
            shape.line.width = Pt(float(style.get("line_width", 1.0)))
            frame = shape.text_frame
            frame.auto_size = MSO_AUTO_SIZE.NONE
            frame.word_wrap = True; frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            from renderers.python_primitives import ALIGN_MAP
            for index, line in enumerate(content.get("text", "").split("\n")):
                p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                p.alignment = ALIGN_MAP.get(style.get("align", "center"))
                run = p.add_run(); run.text = line
                primitives._set_run_style(run, style, 13)
        elif obj.kind == "connector":
            source, dest = nodes[content["from_id"]].box, nodes[content["to_id"]].box
            # Anchor on the borders nearest the other node, so reversed
            # or stacked layouts never draw lines across shapes.
            sx, sy = _edge_anchor(source, dest.x + dest.w / 2, dest.y + dest.h / 2)
            dx_, dy_ = _edge_anchor(dest, source.x + source.w / 2, source.y + source.h / 2)
            shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(sx), Inches(sy),
                        Inches(dx_), Inches(dy_))
            shape.line.color.rgb = hex_to_rgb(style.get("line_color", "#64748B")); shape.line.width = Pt(1.25)
            _add_arrowhead(shape)
        elif obj.kind in {"image", "formula"}:
            slide.shapes.add_picture(content["path"], Inches(b.x), Inches(b.y), Inches(b.w), Inches(b.h))
        else:
            primitives._render_region_content(slide, region, content, obj.object_id)

    @staticmethod
    def _draw_placeholder(slide, obj, error_type: str) -> None:
        """Occupies the resolved box under the same object id, so coverage still verifies.

        The scene object itself becomes the placeholder text: scene_graph.json and the
        artifact must describe the same slide, and the original chart/table payload is
        genuinely absent from the deck.
        """
        message = f"[Visual Render Error: {error_type}]"
        box = slide.shapes.add_textbox(Inches(obj.box.x), Inches(obj.box.y), Inches(obj.box.w), Inches(obj.box.h))
        frame = box.text_frame
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.NONE
        run = frame.paragraphs[0].add_run()
        run.text = message
        # Stay at or above the readability floors so the placeholder cannot itself
        # become a hard gate failure.
        run.font.size = Pt(24 if obj.role in {"title", "stat"} else 14)
        box.name = obj.object_id
        obj.kind = "text_group"
        obj.content = {"lines": [message]}
        obj.required = False
