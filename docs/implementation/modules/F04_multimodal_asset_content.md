# F04 — Images, tables, charts, formulas, and asset content

Type: **Feature** · Current capability: **Structured assets / semantic adapter** · Implementation: **IMPLEMENTED_UNVERIFIED** · Phase: **2**

Workflow references: **6, 17**. Dependencies: [F02](F02_uploads_and_docling_routing.md), [R02](R02_provenance_and_assets_repair.md). Reuse the implemented R01 gateway, R03 grounding, R04 artifact gate, R05 revisions and R06 renderer adapters.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), [branch strategy](../BRANCH_STRATEGY.md), [decisions](../DECISIONS.md), [module status](../MODULE_STATUS.md) and [workflow cross-check](../WORKFLOW_CROSSCHECK.md) first. This is F04's single implementation document. Paths resolve under `C:/Users/thang/Projects/PPTAI/BTPs5`.

**Expanded on 13 October 2026 against the current working tree on `multi-agent`, HEAD `2fa462dbc775ebba6868e1df5fc08196783549cb`, including uncommitted F02 work. Documentation only: no F04 runtime implementation or verification is claimed.** Engineering defaults below are proposals, not newly confirmed user decisions.

**Confirmed scope addition, 13 October 2026 (Q22):** AI must understand assets in their original document context and extract the results, findings and semantic meaning they contribute. Supported asset-derived knowledge must influence final presentation text and narrative, including when the asset itself is not displayed. Caption linkage and optional alt-text descriptions alone do not satisfy F04.

## 1. Current implementation and exact gaps

| Extension point | Observed behavior | F04 change |
|---|---|---|
| `pipeline/stage1_docling_parser.py` | R02 retains item/caption references, crops, dimensions and table-cell spans. PDF audit retained 4 tables, 3 figures and 6 formula crops. Table display projection still uses a dataframe. | Build faithful content from original cells/items; preserve source crops and caption binding. |
| `pipeline/ingestion/adapters/` | F02 handles all eight Q05 formats and retains source bytes/parser records. Markdown fetching is disabled. | Enrich existing evidence after parsing; no second intake/parser pipeline. |
| `adapters/xlsx.py` | Retains A1/sparse/hidden-sheet cells, merged-range inventory, lexical numbers, types/formats, formulas and `unknown/cached_unverified` results; 200-row projections. Charts/drawings/chart sheets are inventories. | Resolve internal package media/chart references and retain original worksheet coordinates. |
| `adapters/image.py` | Preserves pixels/hash/EXIF metadata; OCR coordinates map to unrotated pixels. | Typed orientation/crop transforms plus separate display derivatives. |
| `schemas/raw_extraction_schema.py` | `SourceAsset.kind` accepts `image/table/formula`; table cells already carry spans, lexemes and formula metadata. | Extend contracts through explicit migration. |
| `core/asset_registry.py` | Checks source/caption/cell membership, run-local files/hashes and table-file equality. Non-table files are assumed raster images. | Representation-specific availability, derivation checks, chart datasets and rich table selections. |
| IR2 and `renderers/base.py` | Charts accept inline floats; bound tables require full exact rows; both renderers embed real raster formulas/images. | Bind reconstructed charts, preserve table merges/selections, describe editability accurately. |
| `pipeline/service.py` | Textless sources fail generation with `SOURCE_CONTENT_UNAVAILABLE`. | Keep this guard until F05 provides validated visual-evidence knowledge. |

F02's recorded baseline is **362 tests plus 13 DOM checks passing**. These are historical evidence, not tests rerun during this plan edit. Generated math, semantic descriptions, native chart recovery and full F04 inspection remain unimplemented.

## 2. Objective, scope and ownership

Give every usable asset typed content, real evidence, contextual semantic interpretation and an explicit data/rendering/editability state. F04 owns deterministic enrichment, source/derived representations, AI interpretation of meaningful assets, local math rendering, verified chart binding and inspection. It also owns the adapter/checks that make accepted interpretations usable by the current knowledge extraction and slide-text path; this contribution must not be deferred entirely to F05.

| In scope | Boundary |
|---|---|
| Table headers/spans, lexical/display values, units and footnotes | No general OCR correctness, full Excel formatting emulation or arbitrary table understanding claim. |
| Embedded raster figures/source crops, captions/transforms/previews | No remote/local linked-file fetching; unsupported vectors retain original parts and limitations. |
| Source-backed mathematical expressions/crops | No full `.tex` ingestion, arbitrary TeX execution, symbolic computation or editable Office equations. |
| Supported native DOCX/XLSX charts and explicitly mapped source tables | F14 owns native diagrams; chart-image digitization and spreadsheet recalculation are deferred. |
| Published-revision asset API/tools | F15–F17 own review/chat UI; no independent frontend generation workflow. |
| Contextual asset understanding and findings | Source-grounded observations/results/meaning feed IR1 and slide text; uncertain hypotheses stay labeled. F06 owns optional deeper verification. Visual interpretation does not authorize invented chart numbers. |

Q05 confirms formats, Q04 mandatory basic checks, Q12 configurable provider, Q08 Windows-first portable API. Q11 workload is pending; configurable defaults below are not workload promises or approval gates.

## 3. Pipeline, artifacts and configuration

Keep F02 structural `ir.json` **schema 3**, `parse_record.json`, `parse_result.json`, `adapter_raw.json`, Docling JSON and `source_snapshot.bin` immutable. Add enrichment after structural validation/base raw extraction and before knowledge extraction:

```text
F02 complete source/collection + retained bundles
  -> source_adapter -> raw_extraction_base.json (raw-v3)
  -> enrich_assets(raw, source bundles, AssetOptions)
  -> interpret meaningful assets with original document context
  -> baseline-check asset insights and record coverage
  -> raw_extraction.json (raw-v4 with typed content and interpretation candidates)
  -> accepted source-grounded asset knowledge in existing IR1
  -> retrieval/narrative/composition of both slide text and visuals
  -> registry-validated scene -> Python/PptxGenJS -> R04 -> R05
```

Base raw is an input snapshot; enriched raw is the downstream authority. IR1 assets are its projections carrying identical content hashes. `asset_enrichment.json` stores options, input/output hashes, attempts and findings; it is not another fact store.

1. Resolve retained single-source/collection bundles and verify parser-record/source/artifact hashes.
2. Stage files under the candidate revision with R05 copy/rebase helpers. IDs never become unchecked path components.
3. Record every discovered asset, including unsupported/missing objects; process independently with typed outcomes.
4. Validate and atomically write enriched raw. Recheck source membership/files on IR1 load, composition, rendering and publication.
5. Report `asset enrichment` through `core/job_context.py` with object counts/document IDs/bounded findings. Cancellation preserves checkpoints and old published revisions.
6. Contextual interpretation uses recorded R01 attempts with incremental checkpoints and semantic coverage; no inference in upload handlers, inspection GETs or parser-cache lookup. Optional alt-text descriptions are independent of required semantic understanding.

Add `AssetOptions` (`asset-options-v1`) to `MultiAgentOptions`, `GenerationRequest`, queued request JSON and revision manifests. Proposed fields/defaults: `mode=legacy` (`legacy|structured`) during rollout, `semantic_understanding=auto` (`auto|off`), optional `describe_assets=false` for alt text, math style/DPI, per-call semantic/description bounds and minimum PPI. In structured mode, `auto` processes all meaningful assets through bounded calls; `off` is an explicit compatibility/debug path that reports semantic understanding as disabled and does not meet Q22 acceptance. Validate finite positive bounds/duplicate-free IDs; resolve IDs at execution. Expose matching `main.py` CLI flags through the shared service.

Structured mode requires enrichment; legacy mode preserves raw-v3 behavior. Promote structured mode explicitly only after acceptance. Edits inherit pinned asset options; changed enrichment requires a new generation candidate. No new queue/table/worker pool or provider/renderer default change.

Public configuration is explicit: `GenerationRequest.asset_options` contains typed options; CLI flags are `--asset-mode`, `--asset-understanding`, `--describe-assets`, repeatable `--description-asset-id`, `--formula-dpi` and `--asset-min-ppi`. Remaining bounds/style fields use shared configuration. Submission captures resolved options; inspection cannot change them. There is no implicit eight-asset cap on semantic understanding: budgets determine batch sizes and explicit incomplete outcomes, not silent omission.

## 4. Exact proposed contracts

Create `schemas/asset_schema.py` using discriminated Pydantic models, `extra='forbid'` and finite numbers. Extend current `SourceAsset/TableCell/SourceLocation`; reuse existing evidence/validation contracts, avoiding circular imports.

### Common models and identities

Add `SourceAsset.content: AssetContent | None` and envelope `kind=chart`. Payload discriminator `content.kind` is `table/figure/formula/chart`; envelope `image` maps to `figure`. Retain original IDs/provenance fields.

| Model | Fields and invariants |
|---|---|
| `AssetContent` common fields | `schema_version='asset-content-v1'`, kind, `origin=source|derived`, parent IDs, source hash, representations, findings and optional typed `interpretation`. |
| `AssetRepresentation` | ID, role (`original/source_crop/display_png/formula_svg/table_json/chart_data_json/preview`), relative artifact path, SHA-256, media type, pixel dimensions where applicable, editability (`raster/native_table/native_chart/vector_source`), availability (`available/missing/unsupported`), reason. Available files exist/hash-match. |
| `AssetFinding` | Stable code, severity, document/asset ID, optional locator, message, `blocks_required_use`. Separate parser completeness, enrichment capability and deck readiness. |
| `AssetSourceItem` | Genuine OOXML evidence extension: source/document ID, original package hash, part, namespace-qualified XML path/ordinal, snippet hash, relationship chain, embedded-part hash when applicable. Must resolve from retained original bytes. |
| `AssetDescription` | Text, origin (`source_caption/ocr/vlm_observation`), refs/locations, input representation hashes, status (`SOURCE_BACKED/UNVERIFIED/FAILED/NOT_REQUESTED`), optional model/prompt fingerprint. Direct textual support does not imply deep verification. |
| `AssetInterpretation` | `schema_version='asset-interpretation-v1'`, asset ID, original-context refs/hash, input representation/data hashes, kind/role, semantic summary, atomic insights, unresolved questions, completeness and model/prompt/budget fingerprint. Summary is a navigation digest, not independent evidence. |
| `AssetInsight` | Stable insight ID, asset ID, kind (`observation/result/comparison/trend/relationship/formula_meaning/limitation/implication`), atomic statement, basis (`source_reported/source_data/calculated/visual_observation/contextual_interpretation`), source/region/cell/expression refs, linked source-context refs, original subject/unit/period, optional calculation trace, qualification, validation and `eligibility=FACTUAL_TEXT|QUALIFIED_TEXT|SUGGESTION_ONLY|REJECTED`. |
| `AssetEvidenceAnchor` | Original asset/source item ID and hash, optional source-pixel region or panel ID, series/point/cell refs, original expression span, accompanying source excerpt refs. Display derivatives map regions back to original evidence coordinates. Generated insight text is never its own evidence. |
| `AssetSemanticCoverage` | Per asset `pending/processed/no_supported_findings/decorative/unsupported/failed/disabled`, covered and unprocessed regions/cells, accepted/rejected insight IDs, reason. Every discovered asset has a record; partial analysis stays explicit. |

Enriched raw uses **schema 4**, with explicit readers/migrations for raw **1/2/3**. Add `RawExtraction.asset_source_items`, `asset_semantic_coverage` and `semantic_completeness=complete|partial|unavailable|disabled`; add `SourceLocation.kind=ooxml_item` with `package_part/xml_path/relationship_id`. Unknown DOCX page/bbox remain null. F02 structural-v3 artifacts remain unchanged.

New native source IDs: `doc_<source hash>:ooxml:<part>:<XML path digest>`, registered only after resolving a real source node/target. Derived IDs: `<parent asset ID>:derived:<transform digest>`, citing original items; generated files never become uploaded evidence. Validate parent graphs as acyclic. File-cache reuse never collapses document/occurrence provenance.

### Tables

`TableAssetContent`: row/column counts; ordered header rows; source-backed row/column labels; cells; merged ranges; unit/footnote annotations; optional sheet name/index, original worksheet range and projection origin. Table-grid offsets are zero based, including headers; original A1/CSV locators remain intact. Legacy `headers/rows` are derived renderer views.

Extend `TableCell` with:

- Existing `text/lexical_value/raw_value/value_type/formula/cached_value/cached_state/number_format` preserved.
- `display_text`, `display_origin=source_text|source_lexeme|formatted`, decimal-string `normalized_value`, `normalized_type=number|text|boolean|date|blank|error|unknown`, `numeric_state=SOURCE_LITERAL|CACHED_UNVERIFIED|UNKNOWN|NOT_NUMERIC`.
- Unit/footnote reference IDs. Units retain exact source label, optional deterministic canonical unit/scale and scope (cell/row/column/table); ambiguity stays unknown.
- Merge-anchor/continuation metadata; no duplicate continuation values; distinguish explicit blanks from absent sparse cells.

Validate positive spans/bounds/non-overlap. Preserve `001`, `1.2300`, zero, negatives, blank/duplicate headers and quoted newlines. Normalize only unambiguous numerics with explicit type/options; no identifier coercion, locale guessing, blank-as-zero or formula constants as facts.

`TableSelection` specifies asset ID, ordered source row/column indices, header rows and footnote/unit refs. It copies exact cells without editing values; cutting a merged range is invalid. Digest binds source hash plus selection. Normalization serves binding/arithmetic, never display replacement.

### Figures and formulas

`FigureAssetContent`: dimensions, EXIF orientation, original/crop representation IDs, bbox/unit/origin, display transform, caption/binding/refs, OCR refs, descriptions and optional class (`figure/chart_picture/photo/diagram/unknown`) with origin/status.

`PixelTransform`: source/destination dimensions, 3x3 affine matrix and operation order (origin conversion/point-to-pixel mapping, orientation, crop). Original pixels/hash and original OCR coordinates stay unchanged. Chart-picture classification cannot create editable data.

`FormulaAssetContent`: original expression/refs, format (`latex/mathtext/plain/omml/unknown`), transcription status (`SOURCE_LITERAL/UNVERIFIED/UNKNOWN`), separate normalized render expression, original OMML/snippet representation, crop, render result and raster export editability. XLSX `=SUM(...)` remains a table computation, not automatically a mathematical equation. Rendering does not verify transcription.

### Charts

`ChartAssetContent`: source picture/native refs, package locator, original type/encoding, `data_origin=native_cells|native_literals|selected_table|image_only`, `data_state=VERIFIED_SOURCE_DATA|CACHED_UNVERIFIED|UNAVAILABLE`, `reconstruction_status=EDITABLE|IMAGE_ONLY|UNSUPPORTED`, categories/series and point bindings. Image-only requires real pixels; absent data/pixels is unsupported/unavailable.

`ChartPointBinding`: series/category indices, label/subject/unit/period refs, original lexical value, canonical decimal value, value evidence refs and validation result. Series names/categories have their own refs. Editable values/order/labels must match exact original cells/native literals. Verified source data denotes deterministic binding, not semantic/VLM verification.

Editable subset: simple **2D single-axis column/bar/line/area/pie**, matching current renderers. Combo, 3D, scatter/bubble, secondary/log axes, pivot/dynamic references or unpreservable encodings stay unsupported. Pie requires one nonnegative nonzero series. Never silently substitute types.

## 5. Format-specific algorithms

| Input | Required behavior | Fallback/limit |
|---|---|---|
| PDF | Enrich original Docling cells/spans/captions/pictures/formula crops with real pages/bboxes/IDs. | Chart pictures remain images; ambiguous captions/transcriptions stay unknown. |
| DOCX | Read-only OOXML supplement for embedded media/charts, merges/footnotes and OMML alongside Docling. | No invented physical pages; preserve unsupported XML/crop or explicit limitation. |
| TXT/Markdown | Closed bounded math spans with exact decoded offsets; structural tables. | Ambiguous currency stays text; linked images remain unresolved. |
| CSV | Original lexical cells/record/physical-line spans; explicit table-to-chart mapping. | No guessed locale/units/headers or proximity-based chart association. |
| XLSX | Original worksheet cells/merges and embedded drawings; supported native chart relationships/cells/literals. | External links/formula caches/dynamic names/pivots cannot become verified numeric evidence. |
| PNG/JPEG | Original plus oriented display PNG and available OCR refs. | No digitization or bypass of textless-generation guard. |

### Tables and annotations

1. Construct canonical grids from original cells, not dataframe-inferred headers/types. Compare old display projection and record differences without overwriting source files.
2. Merge XLSX A1 records with the original merge inventory. Preserve spans across 200-row projection boundaries at worksheet level; selections include full merges.
3. Use explicit Docling/OOXML header flags or captured CSV options; unspecified spreadsheet headers stay unspecified until explicit selection.
4. Resolve unit/footnote relationships from exact parser/package refs. Geometry-only links remain candidates; annotation text and numeric scale are separate.
5. Write hashed rich table JSON; retain legacy files. Registry compares rich payload/file and exact selected cell display views.
6. Native merges: Python native cell merges; locked JS `rowspan/colspan` on anchor cells. Shared scene carries spans/continuations without repeated values. If either backend cannot preserve a selected merge, fail required use explicitly.

### Figures and captions

1. Preserve R02 `DIRECT/SHARED_PANEL_GEOMETRY` binding/refs/status; ambiguous nearby captions remain `UNKNOWN`.
2. Resolve document/sheet -> drawing -> image relationships from original ZIP. Internal normalized parts only, rejecting escapes/external targets; retain hashes/chains. Byte equality alone cannot merge separate source occurrences.
3. Create orientation/crop derivatives separately. Convert coordinates before clipping; reject empty/invalid crops. Keep full-original display available.
4. Decode dimensions from bytes; aspect-preserving previews; upscaling does not recover information.
5. Keep source caption, OCR text and VLM observation separate. No invented captions.

### Mathematical expressions

Initial renderer dependency: **`matplotlib==3.10.8`**, matching the installed local version, subject to fixture verification. Use headless Agg, `text.usetex=False` and `mathtext.math_to_image` for a supported subset, producing PNG plus optional SVG. The API supports cropped image output and Mathtext uses its own parser. References: [math_to_image API](https://matplotlib.org/3.10.8/api/mathtext_api.html), [Mathtext syntax](https://matplotlib.org/3.10.8/users/explain/text/mathtext.html).

Proposed style: DejaVu Sans math, **24 pt**, **300 DPI**, `#0F172A`, transparent background, **8 px padding**. Preserve original bytes; normalize only matched outer delimiters/line endings in a separate field. Fixture subset: superscripts/subscripts, Greek, fractions, roots, sums, integrals. Unknown commands/custom macros/environments/matrices return unsupported, never silently dropped terms.

Bound a subprocess to **10 seconds**, **4,096 expression characters**, **16 megapixels**. No shell/TeX/network/model-authored code. Verify nonempty pixels/alpha bounds, pad/hash. Both renderers embed PNG; SVG is retained until separately supported. Unverified transcription prefers a source crop; rendering failure uses a legible crop or explicit unavailable status.

OMML conversion supports fixture-backed runs, fractions, superscript/subscript and radicals only; any unhandled node rejects the entire conversion. Retain original XML/converter version. Detect `$...$`, `$$...$$`, `\(...\)` and `\[...\]` only when closed/bounded and outside escaped delimiters/code blocks. Currency-like dollar spans require recognizable math syntax; ambiguous spans remain plain text.

### Native and table-derived charts

1. Retain chart XML/relationship hashes, type/title/series/category/axis metadata. Hash/retain DOCX embedded workbook before reading cells.
2. Resolve bounded internal A1 ranges (including quoted sheet names) or native literals. Preserve indices/order; reject duplicate/missing/unresolved indices, unequal lengths, ambiguous categories and unsupported encoding. Chart sheets use the same resolver.
3. Worksheet literals outrank caches. Formula results remain cached-unverified even when a chart repeats them. Cache-only references are not verified. `numLit/strLit` data are native source literals with exact point locators.
4. Require `ChartMapping` for table-derived charts: table/selection ID, category column, ordered series columns, source rows, chart type. Models may propose mappings; deterministic code resolves all values/refs.
5. Selected blanks/errors/bools/nonfinite/unverified values prevent editable reconstruction; no silent omissions/zero substitutions. Different explicit selections record omitted rows.
6. Compare decimals exactly before float conversion. Reject nonfinite results or round-trip error above half the final represented decimal place; zero requires exact zero. Record conversion precision and preserve lexemes/units.
7. Write hashed chart-data JSON; registry validates every point/label/period. Source-bound IR2 resolves registry values; inline overrides/reordering must match or fail.
8. Use picture fallback only when genuine pixels exist. Unsupported native XML without a picture reports a limitation, never a fabricated fallback.

### Contextual semantic understanding (required structured-mode behavior)

Use new `pipeline/asset_interpreter.py` through existing R01 structured/multimodal calls. Tables, recovered chart data and readable formulas use structured text/data; figure/chart pictures and diagrams use the source image plus original context. A captioned asset still needs interpretation when its content contributes findings.

1. **Build the original context packet.** Include the asset, caption, section path, verified units/legend/axes/variable definitions, surrounding source paragraphs and explicit in-document references such as “Figure 3” or “Table 2”. Reference matching stays within the source document and disambiguates duplicate labels. Neighboring text is context, not automatic support for every insight. Bound actual requests using F07 policy, including image/output overhead; retrieve more referenced passages when needed and record examined/unexamined refs.
2. **Classify source role.** Record evidence/result/comparison/method/architecture/illustration/decorative/unknown and its rationale. Repeated branding/explicit decoration may be excluded from interpretation with a coverage reason; never silently drop an uncaptioned scientific figure as decorative.
3. **Extract content and contribution separately.** Identify what is shown, what observations/results it supports, and how it adds to the source argument (supports, elaborates, qualifies, contrasts, or provides method detail). Link each contribution to specific original context refs. Audience-independent insights go into IR1; the brief controls later selection and wording.
4. **Emit atomic candidates.** Separate source-reported findings, exact calculations, visual readings and contextual implications. Preserve alternatives/uncertainty. Prompt forbids inferring causal mechanisms, statistical significance, application outcomes or external facts solely from appearance. An architecture arrow means the labeled relationship, not proven performance; formula variable meaning requires source definitions.
5. **Apply baseline eligibility checks.** Verify original source/region refs, claim/evidence hashes, subject/unit/period and exact numeric bindings. Calculations use verified operands and existing calculation traces. An extractor's confidence/self-assessment never promotes a claim to verified. See eligibility rules below.
6. **Preserve coverage and failures.** Process all meaningful assets with bounded per-asset/panel/table batches and resumable checkpoints. If a provider, capacity or ambiguity prevents completion, retain the assets and explicitly report incomplete semantic coverage; a completed parse/caption extraction cannot substitute for interpretation success. Required provider failures follow R01 terminal handling, without silent downgrade or extra billing/auth retries.
7. **Promote accepted knowledge and use it.** Adapt accepted candidates into existing IR1 finding/comparison/workflow/concept/limitation units, metric facts when applicable, with `origin_asset_ids` and `origin_insight_ids`. Candidate interpretations remain derivations; units cite original evidence. Retrieval and narrative planning consider asset-derived units alongside prose-derived units.

| Asset | Required semantic contribution examples | Binding/limit |
|---|---|---|
| Table/native chart | Winners/losers, comparisons, changes, outliers, trade-offs and stated limitations relevant to source context | Exact cell/point/label/unit/period refs; derived differences/ratios need checked calculations. |
| Chart image without numeric data | Readable qualitative ordering/trend/shape and how it relates to the reported experiment | Original panel/axes/legend and context; no precise values/percentages or editable dataset from pixels. Ambiguous labels/ordering yield no supported finding. |
| Diagram/architecture/workflow image | Components, labeled connections, sequence, feedback and described design purpose | Region/label/edge anchors; no invented connections or performance/causal conclusions. Interpretation is distinct from F14 native diagram rendering. |
| Formula | Meaning of the relationship, terms/variables and role in the source method/objective | Original expression/definition/context refs; unreadable symbols or missing definitions stay unresolved, not supplied from unstated assumptions. |
| Photo/illustration | Relevant visible features and its documented evidentiary/illustrative role | Source regions and accompanying context; no speculative diagnoses, identities or measured outcomes. |

**Eligibility for slide text is explicit.** `FACTUAL_TEXT` requires a source-reported statement with actual source support, a checked source-data relation, or a checked calculation. `QUALIFIED_TEXT` permits a narrowly anchored qualitative visual observation/contextual reading using calibrated wording such as “the figure indicates…” or “this suggests…”, provided baseline checks pass and no unsupported numeric/causal/statistical claim is introduced. Semantic support may remain `UNKNOWN` with deep verification off and must be recorded as such; never label the inference verified. Unclear readings/unbacked implications are `SUGGESTION_ONLY` or rejected, not silent facts. Required deeper checking follows F06 when selected.

Do not invent an “impact” merely to populate a field. The meaning may be a methodological detail, a limitation, a contradiction needing review or no supported new finding. A direct finding need not have separate prose stating it: verified table data and sufficiently clear, bounded visual evidence can contribute knowledge under the rules above.

**Concrete source-data example:** a labeled fixture table reports Method A = 80% and Method B = 90% under the same measure/conditions. Record the supported comparison and checked difference of **10 percentage points**, not an unqualified “10% improvement”. IR1 must expose that result so the deck can use a headline/bullet about it even if the table is omitted. Without source support, do not claim the improvement was caused by a particular design.

Optional `tools/asset_description.py` remains for short alt text only. Its `describe_assets=false` default and selection limits do not disable or cap required semantic interpretation. Description output is not a replacement for typed insights or their validation.

## 6. Integration interfaces and renderer behavior

```python
# pipeline/ingestion/asset_adapters.py
load_source_bundles(structural_path, run_root) -> SourceBundleIndex
enrich_assets(raw, bundles, options, *, caller=None, context=None) -> AssetEnrichmentResult

# pipeline/asset_interpreter.py
build_asset_context(raw, asset_id, *, source_index, budget) -> AssetContextPacket
interpret_asset(asset, source_context, *, caller, budget, context=None) -> AssetInterpretation
validate_asset_insights(interpretation, source_catalog) -> ValidatedAssetInsights
asset_insights_to_units(validated_insights, raw) -> AssetKnowledgeProjection

# core/asset_registry.py: extend existing authority
require_representation(asset_id, role) -> AssetRepresentation
select_table(asset_id, selection) -> BoundTableSelection
resolve_chart(asset_id) -> BoundChartData
validate_derivation(asset_id) -> None

# core/formula_renderer.py
render_formula(expression, style, cache_root, *, context=None) -> FormulaRenderResult

# tools/asset_inspection.py: pure bounded reads
inspect_asset(registry, asset_id, *, display_box=None) -> AssetInspection
list_assets(registry, *, kind=None, offset=0, limit=50) -> AssetInspectionPage
```

- Keep existing `require(asset_id, kind)` compatibility; share membership/hash checks and dispatch representation-specific validation. Native chart data need not have pixels; a verified-expression PNG can supply a formula without a crop.
- Extend `validate_asset_content` for source charts/table selections. Reuse it in composition/edit/IR2 adaptation/direct-scene/render boundaries; no inline/path override bypass.
- Preserve rich assets in `VisualAsset/ValidatedIR1`, chunking/retrieval/evaluator projections. Use **IR1 schema 4** for rich output, with explicit v3 migration/loading; existing R03 fact states remain unchanged. Descriptions are not evidence excerpts automatically.
- IR1-v4 retains the raw document descriptors and `asset_source_items` as hash-bound catalog projections. Retrieved asset contexts include only their required source items/parent representations; edited revisions retain the complete catalog. Registry constructors accept this catalog to resolve new OOXML refs against the pinned original package. R03 evidence lookup must distinguish source excerpts/cells from representation-only figure/formula/chart references; only actual source text/values may support numeric claims.
- Add optional `ChartContent.source_asset_id` and typed `TableContent.selection`. Structured-source generation requires bound chart IDs; old inline charts remain only through the explicit compatibility path. Resolve values before native dispatch.
- Add source-binding/merge fields to `scene-v1` content validation while retaining flat-scene semantics. Both adapters advertise `rich-assets-v1` capability/fingerprints; incapable adapters reject rich content. Version any incompatible change.
- Shared scene code owns raster fitting/aspect/captions. Expressions stay metadata, not executable renderer input; model-authored visible captions retain R03 checks.
- Retain text/data service guards; F05 owns visual-only units/coverage. F04 inspection/rendering acceptance does not certify textless-source deck generation.

### Required effect on final presentation text

- Add `origin_asset_ids/origin_insight_ids` to asset-derived knowledge and per-object usage. Planner/composer retrieval must return eligible insights and their original evidence, not just asset paths/captions or an unvalidated summary.
- Feed accepted findings into current storyboard purposes/takeaways and content composition. The planned F10/F11 contracts must preserve them for headlines, bullets, explanations, notes and conclusions. Do not require an image to be selected/rendered before its supported knowledge can be used.
- Selection uses the presentation objective/audience and existing count constraints; no forced extra slide or claim per image. A relevant asset finding can support a text-only slide, be paired with its visual, or stay in the source-backed editing reserve.
- Preserve qualifications during paraphrase. R03's final text validation resolves the underlying insight/evidence for each factual object rather than treating model-generated interpretation text as a new source. Keep original citation/numeric checks active with deep verification off.
- Usage records distinguish `TEXT_CLAIM`, `VISUAL_DISPLAY` and `BOTH`; absence of a displayed image does not drop its claim citations. Dedup can combine duplicate prose/asset findings while retaining both evidence paths; ambiguous source contradictions stay separate for review.
- F04 integration must demonstrate accepted asset findings reaching current IR1 -> retrieval -> storyboard -> composed text. F05/F09/F10/F11 extend this path later; they are not a reason to postpone all semantic influence beyond F04.

## 7. Inspection API and resolution checks

Add published-revision GETs under the existing `/api` router:

| Route | Contract |
|---|---|
| `/decks/{deck_id}/revisions/{revision_id}/assets?kind=&offset=0&limit=50` | Stable asset-ID order, total/next offset; max limit 100. |
| `/decks/{deck_id}/revisions/{revision_id}/assets/detail?asset_id=...` | Typed detail plus max 20 preview table rows/chart points, counts and explicit truncation. IDs in query avoid path interpretation. |
| `/decks/{deck_id}/revisions/{revision_id}/assets/file?asset_id=...&representation_id=...` | Allowlisted hash-verified representation stream; no arbitrary path argument. |

Reuse `pinned()/published_revision()` and R05 verification. Unknown/unpublished/foreign revision or ID returns **404**; corrupt/missing published bytes returns **409**. Public data omits absolute paths/credentials/raw provider errors. GETs never parse, generate math or call providers. Legacy revisions migrate in memory for honest summaries, never byte rewriting. Retained executable/embedded objects are reproduction evidence, not executable previews.

Inspection includes kind/subtype, caption/provenance status, dimensions/aspect, source locator, representations/editability, data/formula state, contextual summary, bounded atomic insights with eligibility/qualification/evidence, unresolved questions and semantic coverage. Counts separate discovered/usable/unsupported/missing/interpreted/with-accepted-insights/described; parsing does not equal semantic understanding. Preview truncation must not imply all rows/regions were semantically examined.

For display box inches compute `ppi=min(pixel_width/display_width, pixel_height/display_height)`. Proposed label-bearing raster minimum **150 PPI**, configurable with actual values recorded. Re-render verified formulas at needed scale; enlarging source pixels does not recover labels. Label legibility stays unknown until actual preview inspection supports it; PPI alone never certifies readability. R04 blocks required unreadable labels; F13 owns alternate layout sizing.

## 8. Cache, revisions, migration and failure rules

- F02 owns parser-cache identity. Enrichment keys bind source/parser-record hashes, schema/adapter/mapping/code versions, options, representation/embedded package hashes and math/font identity; descriptions also bind model/prompt and resized-image hashes.
- Formula cache keys include expression/style/format, Matplotlib version and actual font-file hash. File reuse retains distinct source-linked representations; description cache hits remain unverified.
- Interpretation keys bind original-context refs/text/hash, crop/region mapping, data, interpreter prompt/model, validation version and actual request budget. The same image in different source contexts cannot blindly reuse a finding. Cache original hashes/eligibility/coverage without upgrading model observations; changed source text invalidates interpretation and dependent slide text even when image bytes are unchanged.
- Validate schemas/bytes on cache hits. Recompute corrupt derived caches; corrupted original evidence blocks use. Cache completed typed results only; failed/cancelled attempts retain diagnostics without successful status.
- Add F04 options/files/versions to explicit raw/IR1/slide fingerprints; `runtime_dependencies()` already sweeps Python. Math/font identity and JS capabilities need explicit inclusion. Invalidate dependent stages; retain unaffected complete parser members.
- R05 verifies every representation, parent/source locator, enrichment artifact and hash. Copy/rebase paths with existing utilities; edit/resume/download revalidate; old revision bytes/hashes stay unchanged.
- Migrate raw/IR1 v3 conservatively with rich values or `content=None`. Legacy missing provenance stays unknown. Never verify cached formulas, chart pictures or missing captions through migration.
- Rollback selects legacy mode for new runs, retaining original evidence and published rich revisions. Unsupported optional objects may remain unused; required objects cannot be silently omitted.

| Code | Outcome |
|---|---|
| `ASSET_INTEGRITY_ERROR/INVALID_ASSET_PROVENANCE` | Block required use; source-set integrity blocks generation; retain prior revisions/diagnostics. |
| `TABLE_SPAN_INVALID/TABLE_SELECTION_INVALID/UNIT_AMBIGUOUS` | Reject invalid selection/spans; preserve strings; ambiguity cannot support numeric transforms. |
| `FORMULA_UNSUPPORTED/FORMULA_RENDER_TIMEOUT/FORMULA_RENDER_UNAVAILABLE` | Legible source crop or unavailable status; no altered terms. |
| `CHART_DATA_UNVERIFIED/CHART_REFERENCE_UNRESOLVED/CHART_ENCODING_UNSUPPORTED` | Genuine picture or explicit limitation; no invented values/cache verification. |
| `ASSET_DESCRIPTION_UNAVAILABLE` | Optional failure/unknown status; deterministic content stays usable. |
| `ASSET_SEMANTICS_UNAVAILABLE/ASSET_SEMANTICS_INCOMPLETE` | Retain failed/unexamined outcomes and partial coverage; caption-only extraction cannot count as semantic completion. |
| `ASSET_INSIGHT_UNSUPPORTED/ASSET_INSIGHT_CONTEXT_MISMATCH` | Reject or retain labeled suggestion; never promote an irrelevant/contradicted/unsupported implication to facts. |
| `ASSET_RESOLUTION_LOW/ASSET_LABELS_UNREADABLE` | Actual display box/PPI and R04 required-label checks. |
| Uninterpreted optional object/cancellation | Preserve source/limitation or checkpoints; no partial candidate publication. |

## 9. Ordered implementation packages and file map

No calendar estimates. Existing files are extension points; new names are proposed targets.

| Step | Files | Deliverable and gate |
|---|---|---|
| 1. Contracts/migrations | New `schemas/asset_schema.py`, `core/asset_migration.py`; extend raw/IR1/IR2 schemas and source adapter | Versioned round trips, conservative legacy loading, actual locators/stable IDs. |
| 2. Adapters | New `pipeline/ingestion/asset_adapters.py`, `asset_adapters_tables.py`, `asset_adapters_ooxml.py` in the same directory; bundle helpers in ingestion validation/collection | Real grids/annotations/figures/package occurrences/transforms; immutable F02 records. |
| 3. Math | New `core/formula_renderer.py`; verified Matplotlib pin in requirements | PNG/SVG/cache/crop fallback and bounded failures. |
| 4. Charts | New `tools/chart_binding.py`; registry and `tools/claim_verification.py` hooks | Exact point/label/unit binding; cache-only/image-only rejection. |
| 5. Semantic understanding and pipeline | New `pipeline/asset_interpreter.py`, `tests/test_asset_semantics_f04.py`; orchestrator/service/extractor/chunker/composer/editor, artifacts/revisions, evaluator reference projection | Contextual insights/eligibility/coverage; accepted asset units affect slide text; atomic artifacts, retrieval/edit/resume and context-sensitive invalidation. |
| 6. Renderers | `renderers/base.py`, Python primitives/adapter, JS builder and capabilities | Identical source selection/merge/chart/math behavior on both backends. |
| 7. Description/inspection/config | New description/inspection tools; API routes/service schema/worker/main/service artifact views | Captured options, bounded calls, path-free inspection/downloads without inference. |
| 8. Verification/docs | Tests/fixtures/scripts below; README/status only after runtime evidence | Regressions, actual PowerPoint acceptance and scoped completion. |

No wholesale old-branch pipeline import, second fact store/revision manager or UI service.

The existing-file changes in steps 5–7 resolve to `pipeline/orchestrator.py`, `pipeline/service.py`, `pipeline/knowledge_extractor.py`, `pipeline/chunker.py`, `pipeline/slide_composer.py`, `pipeline/slide_editor.py`, `core/artifacts.py`, `core/revisions.py`, `evalute/reference/build_reference.py`, `renderers/python_primitives.py`, `renderers/python_adapter.py`, `renderers/pptxgenjs_adapter.py`, `renderers/pptxgenjs/builder.js`, `api/routes.py`, `schemas/service_schema.py`, `workers/local.py`, `main.py` and `core/service_artifacts.py`. Source bundle validation/helpers stay in `pipeline/ingestion/validation.py` and `pipeline/ingestion/collection.py`. Central configuration defaults belong in `config/settings.py`, with service-supplied limits passed through rather than duplicated.

## 10. Acceptance and evidence

Create `tests/fixtures/assets/manifest.json` and `scripts/build_f04_fixtures.py` with input hashes/exact expected cell/expression/caption/relationship locators/status. Synthetic test values are labeled fixture-file contents, never production fallback data.

| Case | Required assertion |
|---|---|
| PDF/DOCX table with merges/units/footnotes | Original display/spans/refs survive raw -> IR1 -> selected native table -> edit/resume; invalid spans/ambiguous links rejected. |
| CSV/XLSX lexical edges | `001`, `1.2300`, zero/blank/negative/newline/duplicate headers/date/error/localized ambiguity preserve type/state/text. |
| Sparse/hidden XLSX, row-200 merge | Original A1/visibility/full span; projection indices resolve original cells; cut merge rejected. |
| Native charts/table mappings | Real type/order/value/unit binding; formula caches/external refs/missing indices/unsupported axes cannot be editable. |
| Binding counterexamples | Subject/series swap, numeric change, category reorder, unit mismatch, blank-as-zero and float precision loss fail. |
| Chart picture without data | Image-only/no verified data; zero invented native series. |
| Clearly labeled qualitative chart picture | Anchored qualified takeaway reaches text without exact numeric reconstruction; ambiguity cannot become a factual improvement percentage. |
| Table-only result with no prose stating the finding | Checked comparison/calculation becomes an IR1 unit and takeaway/bullet even when its visual is omitted. |
| Diagram/formula with contextual definitions | Labeled relationships/variable roles and method contribution reach explanatory text; no invented edges/undefined variables/causal performance. |
| Same image in different source contexts | Insights/caches remain context-specific; wrong-context significance rejected. |
| More than eight meaningful assets/panels | Every asset has coverage; progressive calls record pending/unsupported regions with no hard cap/silent omission. |
| Uncertainty or prose-asset contradiction | Qualifications/unresolved states survive retrieval and edits; generated summaries cannot become evidence. |
| EXIF 1–8/repeated embedded media | Correct transforms; original hash/OCR coordinates and occurrence provenance intact. |
| Crop/Markdown/TXT currency/OMML | Real supported pixels; currency stays text; unsupported/timeout/unverified transcription gives crop or limitation. |
| Missing/tampered files/forged refs/parents | Required-use/direct-scene/edit/resume/publication reject; derived cache cannot mask original tampering. |
| VLM off/on/failure/injection | Zero calls off; mocked responses remain unverified; foreign/numeric content cannot establish facts; accounting/cancellation preserved. |
| API inspection | Pagination/bounds/legacy summaries/hash downloads; no paths/foreign or staged revisions/provider work on GET. |
| Cache/revisions | Unchanged inputs reuse without parser/math/provider calls; expression/style/font/options/data changes invalidate dependencies; prior hashes valid. |

Add `tests/test_asset_contracts_f04.py`, `test_asset_enrichment_f04.py`, `test_formula_renderer_f04.py`, `test_chart_binding_f04.py`, `test_asset_semantics_f04.py` and `test_asset_inspection_f04.py` in that directory. Reuse existing provenance/ingestion/renderer/revision/service tests.

Required future commands (**not run by this plan update**):

```powershell
python -B -m pytest tests/test_asset_contracts_f04.py tests/test_asset_enrichment_f04.py tests/test_formula_renderer_f04.py tests/test_chart_binding_f04.py tests/test_asset_semantics_f04.py tests/test_asset_inspection_f04.py -q -p no:cacheprovider --basetemp ../audit-artifacts/f04/focused
python -B -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp ../audit-artifacts/f04/regression --junitxml=../audit-artifacts/f04/pytest-final.xml
python -B scripts/verify_f04_native.py --output ../audit-artifacts/f04/native
python -B main.py --help
git diff --check
```

Create `scripts/verify_f04_native.py` with this `--output` interface and existing native helpers. Run real parsing/enrichment/binding/rendering/R04/R05; no mocked successful extraction/publication. Typed grounded narrative answers may make selection deterministic but must be labeled fixtures.

Native deck: merged/unit-bearing table with footnote; selected CSV/worksheet table preserving lexemes; oriented captioned figure; generated fraction/sum equation; unsupported equation source crop; image-only source chart; verified editable native chart. Run **Python and locked PptxGenJS**, open/save/rerender with actual **PowerPoint COM**, inspect labels/captions/math and edit native table/chart cells to prove editability. Office probes are distinct from application grounding acceptance; arbitrary test edits create no new supported facts.

Semantic acceptance additionally requires a table-derived finding used in a text-only slide and a chart/diagram takeaway visibly used in a headline/bullet with object-level evidence. Deterministic fixtures test adapters/validation/composition/rendering and counterexamples. Run actual configured AI interpretation on representative source table/chart/diagram or formula fixtures; record prompt/context/source/response hashes, eligibility and rendered text. If live calls are unavailable, leave AI semantic verification explicitly unavailable; mocked interpreter outputs alone cannot certify Q22.

Also verify shared API/CLI mixed-source generation, source-preserving slide edit, pinned asset/PPTX downloads and unchanged resume with zero new generation/enrichment/interpretation calls. With optional deep/vision judging off, readiness remains `BASIC_CHECKED`; source-asset multimodal interpretation is separate from optional final-slide vision judging. Unavailable optional judging never counts as success. General OCR/semantic accuracy, capacity benchmarks and non-Windows/other-Office checks require separate evidence.

Record `../audit-artifacts/f04/verification.json`: exact base commit/working-tree source/config/fixture hashes, dependency/font identity, commands/results, raw/IR1/scene/PPTX/preview hashes, both native renderer/edit outcomes, fixture declarations and unavailable checks. Advance CURRENT_STATE, MODULE_STATUS and `modules.json` only after code plus required acceptance. Documentation leaves **NOT_STARTED**.

## 11. Decisions and handoff

Q22 confirms contextual AI asset understanding and contribution to final PPT text. The optional-description-only approach is superseded. Structured-mode interpretation defaults to auto; optional alt text remains off. Other defaults are proposals; Q11 scale stays open without blocking bounded verification. Provider stays configurable; full `.tex` ingestion remains excluded.

F04 supplies contextual insights and their adapter into current source knowledge/text composition. F05 extends typed knowledge/visual-only coverage; F06 adds deeper checks; F09 retrieves findings/evidence independently of visual selection; F10/F11 use findings in flow/visible text/reserve; F13 sizes displays; F15–F17 expose review/edit controls. Image-only charts may contribute qualified meaning without becoming editable numeric data. Unsupported implications/cached values never become verified facts merely because F04 displays them.

## 12. Runtime handoff — 13 October 2026

Implemented in the separate `feature/f04-multimodal-assets` worktree at base `6c9c8c1`. The original plan observations above are historical. Current code and acceptance evidence are recorded in [CURRENT_STATE](../CURRENT_STATE.md), [MODULE_STATUS](../MODULE_STATUS.md) and `C:/Users/thang/Projects/PPTAI/audit-artifacts/f04/verification.json`.

417 regressions and 94 final targeted grounding/contract/semantic checks pass. Real parsing/enrichment, both native renderers, PowerPoint COM table/chart edit round trips, asset inspection/downloads, source-preserving editing and zero-call resume pass with explicitly declared fixture model answers. Structured mode remains opt-in. Actual configured AI interpretation returned HTTP 404 on one terminal attempt; live Q22 acceptance and the remaining native/accuracy/capacity cases listed in CURRENT_STATE are unverified. Overall status stays IMPLEMENTED_UNVERIFIED rather than claiming complete live semantic certification.
