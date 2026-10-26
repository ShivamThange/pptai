# Renderer contract

`Renderer.render(scene_graph, asset_registry, theme, output_path)` returns a
`RenderArtifact` with actual backend/version/hash, warnings and capabilities.
`scene-v1` is data-only, uses inch boxes and stable slide/object IDs, and rejects
unknown types, ragged tables, mismatched chart lengths, nonfinite values, missing
assets, invalid graph edges, and content loss in the actual native package.

The explicit `ir2-layout-v1` adapter resolves today's layout catalog and expands
stats/diagrams/captions into primitives. A future solver supplies scene boxes
directly. F13 layout solving and F14 Mermaid/Dagre parsing are separate work.
Original raster formulas are embedded images; they are not editable equations.
Native text, tables, charts, graph cards and connectors remain editable.
Both adapters preserve resolved font sizes. Dense content is checked for fit
and repaired by the pipeline rather than silently shrunk below readability
floors inside a renderer.

Install the locked JS baseline from the repository root:

```powershell
npm.cmd ci --prefix renderers/pptxgenjs --ignore-scripts --no-fund --no-audit
python main.py --pipeline multi-agent --renderer pptxgenjs --input source.pdf
```

Python remains the migration default. `--renderer python` selects it explicitly.
Edits retain their revision backend; changing backend requires regeneration.
Failures retain the prior artifact and never substitute another backend.
R05 revisions include `scene_graph.json` and exact renderer metadata.

Direct resolved scene rendering (no layout catalog or LLM):

```powershell
python -m renderers scene.json output.pptx --renderer python
node renderers/pptxgenjs/index.js scene.json output.pptx
```

Set `PPTAI_PYTHON` for the Node wrapper if Python has a nonstandard executable
name. Both paths use the same validator. The worker deadline is 60 seconds.

Reproduce contract/counterexample tests with `python -m pytest tests
evalute/tests -q -p no:cacheprovider --basetemp .pytest_tmp/r06`. Real PowerPoint
acceptance uses `python scripts/verify_r06_native.py --output-dir <directory>`;
it writes table/parity fixtures, native renders, edit round trips, and hashes.
This requires installed Microsoft PowerPoint and pywin32. No LLM is called.
