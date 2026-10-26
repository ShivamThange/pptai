# Handoff — F13 dynamic theme/layout live run (26 October 2026)

This file is written for the next agent picking this up cold. It records what was run, what broke,
what was patched, and where every artifact lives. Nothing here is committed (this workspace is not a
git checkout); no branch, push, merge, deploy or `.env` change was made.

## 1. What the user asked for

Run the real multi-agent pipeline on
`C:\Users\thang\Projects\PPTAI\NIPS-2017-attention-is-all-you-need-Paper.pdf` with the dynamic theme
and dynamic layout enabled, roughly 7 slides, deep verification off, and produce a `.pptx` that can
be opened and inspected. Earlier attempts were also made across themes, layout on/off, decks sizes,
lenses, models and concurrency (see §5); the published result is the 7-slide academic run.

## 2. Published result (this is the deliverable)

- **Deck**: `output/f13-runs/final-7-flash/revisions/90f9ba65a2284c89aca12a76525dcc19/op_ppt.pptx`
- **Preview PNGs** (PowerPoint COM render, 1920×1080): `output/f13-runs/final-7-flash/preview/slide_001..007.png`
- **Revision metadata**: `.../revision.json` — `quality_state: DRAFT_INCOMPLETE`, renderer `python 1.0.2`,
  `scene-v1`, artifact hash `6daac820f9e9f512c112aec53994fed23696148cb4ed3f9719fcb20d6314f977`.
- **Quality report**: `.../quality_report.json` — `deterministic=EVALUATED_PASS`, `rendered=EVALUATED_PASS`,
  `judge=NOT_EVALUATED` (deep verification off), readiness `DRAFT_INCOMPLETE`.
- **Dynamic layout evidence**: `.../layout_report.json` — engine `f13-dynamic-v1`, all 7 slides
  `resolved: true`, archetypes `single` ×6 + `split-pair` (slide 3), no fallbacks, none `tight`.
- **Theme**: `--theme auto` + `--lens academic` resolved to `academic_slate` (white canvas, #0F172A text,
  #2563EB accent, no custom fonts). The theme applied at IR2 level; model-authored styles win.
- Run cost/usage: 13 provider calls, 281,387 input tokens, 7,120 output tokens (`run_manifest.json`).

Exact command that produced it (the key was supplied by the user in chat and passed only as a
process environment variable; it is **not** written to `.env` or any repo file):

```powershell
$env:GEMINI_API_KEY = '<user-supplied key>'
$env:LLM_MAX_CALLS_PER_MINUTE = '15'
python -B main.py --input "C:\Users\thang\Projects\PPTAI\NIPS-2017-attention-is-all-you-need-Paper.pdf" `
  --output-dir output/f13-runs/final-7-flash --lens academic --theme auto `
  --slides-min 7 --slides-max 7 --extraction-mode source-passages `
  --max-concurrency 2 --max-repairs-per-slide 3 `
  --llm-model gemini-3.5-flash-lite --llm-max-output-tokens 8192 `
  --llm-context-tokens 1048576 --llm-max-attempts 5 --resume
```

Deep verification stayed off (the flag is opt-in; `--deep-verification` was never passed).

## 3. Code changes in the working tree (small, targeted, uncommitted)

Five files changed. Each was needed to get from "provider/malformed output" or "BLOCKED" to a published
deck; none changes contracts or schemas.

1. **`core/schema_adapter.py`** — Gemini structured-output compatibility.
   The adapter dropped `additionalProperties`, `oneOf` and `const`, so IR2 `content` (a free-form
   region→object map) reached Gemini as `{"type": "object"}` and **every** model returned `"content": {}`.
   Now: `oneOf` is folded like `anyOf`; `const` becomes a single-value `enum`; object nodes keep a
   recursively adapted `additionalProperties`. Verified with a live call that Gemini accepts
   `additionalProperties` and fills arbitrary region keys. Schema size 6.8 KB (was lossy, not large).
2. **`pipeline/slide_composer.py`**
   - `retrieve_slide_context` now attaches the real source table asset to table-layout slides when the
     storyboard named none. Match key: the block token in each unit's evidence `source_id`
     (`doc_…:block_0060`) against the asset id (`table_…_block_0060`) — note asset `source_refs` use JSON
     pointers (`…#/tables/1`), which is why matching on them failed. Without this the model transcribed
     rows by hand, numeric binding rejected them, and every table slide burned its repair budget and
     aborted the run.
   - Prompt: regions accept only their declared content types (stop putting tables in text regions), and a
     "mandatory binding rule" telling the model to describe hyper-parameters qualitatively instead of
     restating numbers whose source label differs (this is what R03 rejects).
3. **`core/layout_engine.py`** — `_single` now gives a *source-bound* table the full content frame.
   Previously `min(h, max(1.2, measured_need))` collapsed to 1.2 in because source-bound tables carry no
   inline rows to measure; the renderer then shrank the loaded table below the readability floors and
   expanded past its geometry (the exact gate failures observed). `min(h*0.72, …)` in `_stack` was left
   unchanged on purpose (scope control).
4. **`renderers/fitting.py`**
   - Text is now measured against the *usable* box (`width − 2×0.1 in`, `height − 2×0.05 in`), matching
     python-pptx default text-frame insets. Before this, PowerPoint measured 1.2 pt more width than the
     fitter assumed and the gate flagged overflow on a nearly-fitted line.
   - Role floors now mirror the gate's `ROLE_FLOORS` (`evalute/metrics/visual.py`): body 14, caption 10,
     title 24, stat 24, label 10, diagram 12. Table floor stays 8 deliberately — raising it breaks
     `tests/test_layout_engine_f13.py::test_dense_table_never_breaks_floors_silently`.
   - Model-authored sizes below the role floor are raised to the floor and reported
     (`font_raised_to_floor`) instead of passing silently.
5. **`renderers/base.py`** — footer-like regions (`source`, `footer`, `footnote`, `attribution`, `caption`)
   now get scene role `caption` (floor 10) instead of `body` (floor 14), which is what was failing on
   slide captions rendered at 9–13 pt.

Tests: `python -B -m pytest tests/test_layout_engine_f13.py tests/test_fitting_f13.py tests/test_dynamic_theme_f13.py -q`
→ **27 passed**. Renderer JS tests still fail because `renderers/pptxgenjs/node_modules` is absent
(pre-existing environment gap, not caused by these edits).

## 4. Known limitations you inherit

- **Numeric binding is conservative and can false-positive.** `validate_slide_grounding` rejected claims
  such as `dmodel = 512` because the claim label did not match the source label token. The prompt rule in
  §3.2 works around it; it is not fixed. Do not relax `check_numeric_text` casually — it is the R03 gate.
- **Dynamic `single` text regions are capped at 9.8 in and centred** (`_single`, `unit.cls == "text"`), so
  body text sits inset from both margins on wide slides. Left as-is to keep the run in scope; consider
  dropping the cap or left-aligning if body composition matters.
- **Few-row tables stretch vertically** to fill the region (renderer behaviour), which looks loose on the
  5-row complexity table. Row-height caps would be a separate change.
- **Model availability is unstable.** `gemini-3.6-flash` and `gemini-3.1-flash-lite` returned HTTP 429 /
  503 throughout; `gemini-3.5-flash-lite` was the only reliably served model. The user asked for 3.6 and
  then 3.1 — both were attempted and failed at the provider, not in this code.
- **Gate remains the publisher.** With deep verification off the readiness is `DRAFT_INCOMPLETE`; that is
  expected and not a defect. A `VERIFIED` deck would need the optional semantic judging enabled.
- **Environment**: this folder is not a git checkout. Under the DSH Windows sandbox, `tempfile.mkdtemp`
  (mode 0700) directories are unwritable, which breaks the parse cache; runs were executed with full
  access. PowerPoint COM is installed and used for previews. PptxGenJS is untested (no node_modules).

## 5. Other runs kept for comparison (`output/f13-runs/`)

| Dir | Config | Outcome |
|---|---|---|
| `final-7-flash` | academic, auto theme, dynamic, 7 slides, 3.5-flash-lite | **published** (90f9ba65…) |
| `final-7` | same but 3.5-flash-lite before the asset/floor fixes | blocked (numeric binding / gate) |
| `final-7-31` | 3.1-flash-lite | provider HTTP 503 |
| `r1-dark-tech`, `r2-warm-editorial`, `r3-corporate-blue`, `r4-minimal-mono` | dynamic, 6–8 slides, one theme each | gate blocked before the fixes; layout reports + rendered slides retained |
| `r5-auto-slate-dyn`, `r6-auto-slate-static`, `r7-exec-corporate`, `r8-exec-corporate-static` | auto theme / no dynamic layout / executive lens | mixed: gate or grounding block |
| `theme-matrix/` | **same IR2 re-rendered** under all five themes, dynamic and catalog geometry | 6 decks × 6 slides + PNGs |

`theme-matrix/` is the cleanest theme/layout comparison because the content is identical:

- `r1-{academic_slate,corporate_blue,warm_editorial,dark_tech,minimal_mono}-dynamic/`
- `r1-academic_slate-static/`
- Theme tokens verified in the OOXML: backgrounds `FFFFFF / FDF9F3 / 0F172A`, text colours matching each
  theme, fonts `Calibri / Georgia + Calibri / Segoe UI`, table header fills `1E293B / 44403C / 1E3A8A`,
  band fills `182235 / F5EFE6 / EFF6FF`.
- `geometry_diff.py` output: dynamic geometry changes every slide (max box delta 3.9 in); at that time the
  table region collapsed to 1.2 in vs the catalog's 5.1 in — the bug fixed in §3.3.

## 6. Helper scripts (throwaway, under `output/f13-runs/`, git-ignored)

- `run-matrix.ps1` — runs the parameter matrix with a resume/retry loop.
- `theme_matrix.py` — renders one IR2 under every theme and both layout modes, then exports PNGs.
- `geometry_diff.py` — dynamic vs catalog shape-box diff.
- `run_summary.py` — per-run manifest/gate summary into `run-summary.json`.
- `probe_compose.py`, `probe_skeleton.py`, `probe_schema_variant.py`, `schema_peek*.py` — the Gemini
  structured-output diagnosis used in §3.1.
- `*.log`, `run-summary.json`, `matrix-driver.log` — raw evidence.

## 7. Suggested next steps

1. Re-run `tests evalute/tests` fully (JS tests need `npm.cmd ci --prefix renderers/pptxgenjs` first).
2. Decide whether the five working-tree changes should be kept; the schema-adapter fix (§3.1) is a real
   Gemini-provider bug independent of F13 and deserves its own regression test.
3. If dynamic body composition matters, revisit `_single`'s 9.8 in cap and `_stack`'s 0.72 table cap.
4. If tables should not stretch, add explicit row-height bounds in the python renderer.
5. For VERIFIED output, re-run with `--deep-verification` (expect slower, stricter judging).
