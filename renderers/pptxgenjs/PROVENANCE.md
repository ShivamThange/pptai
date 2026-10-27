# R06 renderer port

Selected input: `rkrrish/BTPs5`, `origin/hardik-pptxgenjs`, commit
`e534ff1c6b9d6e6846b1508a39f0bd2add5e60df` (refetched 9 October 2026).
Its `core/builder.js` is unchanged from `f9a50e4`; original file SHA-256:
`3c5c0a0ff4785d020fb601f402a7d678d687002ffb695edb120e5f0d439b31f1`.

`builder.js` adapts its color, text, native table and chart helpers. The old
planner/layout dispatch is replaced by resolved `scene-v1` objects. Placeholder
media/diagrams and silently skipped content are removed. Tables use `middle`
as documented by the [PptxGenJS table API](https://gitbrent.github.io/PptxGenJS/docs/api-tables/).
Horizontal bars specify `barDir: "bar"`; negative values use automatic axes.
Native diagram shapes/connections and real raster assets come from the shared
Python scene adapter, which also validates provenance and required coverage.

The tested dependency baseline is **exactly 3.12.0**, matching the source branch
lockfile. `package-lock.json` locks its dependency tree; no upgrade is included.
The isolated worker is internal; `index.js` is the public Node wrapper over the
same validator/renderer boundary as `python -m renderers`. There is no separate
generation pipeline, implicit renderer fallback, or model-authored code format.

Local post-adaptation deltas (F13 theme elevation, recorded for provenance):
table header text color, connector color/width/arrowhead, rounded-corner radius
and outer shadows now read the shared theme style keys (`header_text`,
`line_color`, `line_width`, `radius_in`, `shadow*`) exactly like the Python
backend; unknown keys keep the original hardcoded fallbacks.
