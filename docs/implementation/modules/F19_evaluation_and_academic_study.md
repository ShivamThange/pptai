# F19 — Six core evaluation metrics and academic study

Type: **Feature / repair** · Current capability: **Partial / unreliable** · Implementation: **NOT_STARTED** · Phase: **4**

Workflow references: 26. Dependencies: [R03](R03_grounding_validation_repair.md), [R04](R04_quality_gate_repair.md), [F11](F11_ir2_content_and_suggestions.md), [F13](F13_dynamic_geometry_and_layout.md).

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Current implementation

Both reference decks specify semantic similarity, concept coverage, faithfulness, functional flow, structural similarity, and visual quality. Existing code implements approximate versions; TF-IDF fallback changes scoring and reference creation shares IR1 omissions. R04 withholds the complete aggregate when factual checks fail or are unavailable; a separately labeled available-metrics diagnostic still renormalizes the available weights. Independent references, calibrated formal metrics, and the academic benchmark protocol remain F19 work.

## Objective and ownership

Preserve the named academic metric profile while correcting measurement and adding prompt compliance, extraction/data fidelity, edit isolation, and operational diagnostics. Thresholds/weights stated in the reference slides are starting configurations, not proven universal standards.

## Inputs, outputs, and contracts

EvaluationReport records backend/version, applicability, assessed/unknown counts, per-claim/per-object findings, six core scores, added diagnostics, optional aggregate profile, judge failures, and artifact hash. BenchmarkReference is independently annotated and conditioned on the brief.

## Implementation sequence

1. Retain MiniLM cosine/weighted coverage as explicitly named metrics; calibrate 0.65/0.45 thresholds against development labels and never silently reuse them for TF-IDF.
2. Verify claims against source evidence, including numeric/cell/chart/caption relationships; keep partially completed judgments.
3. Assess narrative roles and graph relationships against a brief-conditioned intended flow. Report source-order similarity as a descriptive metric, not a universal correctness gate.
4. Repair native geometry/typography extraction and include actual rendered-slide design/legibility assessment.
5. Run matched ablations and blinded human review with held-out sources, repeated runs, agreement, clustered confidence intervals, cost/latency, and failure rates.

## File map

- evalute/metrics/ (existing)
- evalute/reference/build_reference.py (existing)
- evalute/runner.py (existing)
- evalute/reporting/ (existing)
- benchmarks/ (new)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Show metric profile and completeness before any aggregate. Aggregates can compare only matched backend/metric profiles; a missing required dimension remains incomplete.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- All six core names appear in the report with explicit applicability/status.
- Unknown/failed faithfulness cannot produce a comparable full-success aggregate.
- Numeric/table/figure/formula omissions are visible.
- Audience-specific flow is not penalized merely for departing from paper order.
- Study reports include independent references, human rubric, repetitions, uncertainty, and operational cost.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q07: Keep the six metrics and provide detailed, mathematically sound definitions and implementation. Source slides: BTP Sem 5 slide 13 and Hardik BTP slide 11.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.


## Detailed mathematical specification

This section is the implementation specification for the six retained metrics. The formulas below are a proposed project-specific formalization, not a claim that the reference slides or a cited paper establish these exact scores. They provide bounded outputs, explicit denominators, and testable behavior. Embeddings and model judgments remain empirical approximations; mathematical normalization alone cannot prove factual correctness or aesthetic quality.

### 0. Evaluation objects, reference construction, and status

Let the candidate deck be ordered slides `D = (s_1,...,s_T)`. Preserve native text runs, bullet boundaries, table cells, chart categories/series, formula text/assets, figure captions, and graph nodes/edges. Recursively extract grouped objects. Rendered inspection supplements objects whose meaning/legibility is not recoverable from native extraction.

Build a brief-conditioned reference independently for academic testing:

- `C = {c_1,...,c_N}`: atomic relevant concepts/facets, each with actual source evidence and a priority weight `w_i > 0`.
- `P = {p_1,...,p_M}`: atomic visible candidate claims. A sentence with two independently checkable assertions becomes two claims. Not every heading is a factual claim.
- `G_ref`: independently reviewed conceptual relationship graph and permissible partial ordering for this audience/brief.
- `R_flow`: conditional narrative rules applicable to this brief.
- `O`: relevant visible objects, with semantic roles, intended containment, geometry, and rendered evidence.

Use weights 3/2/1 for core/important/minor reference concepts as the initial profile from the decks. Critical claims/requirements also carry a separate veto flag; numerical weights do not replace that gate. Gold annotations define inclusion in main slides versus allowed notes/appendix. **The user’s exact count is main-content count; cover/conclusion/appendix are tracked separately.** Putting required main content in extras does not automatically satisfy main-content coverage.

Default visible-content metrics evaluate visible slides; notes receive a separate declared profile. Report per-part coverage/counts for main, cover, conclusion, and appendix. Factual/visual checks apply to every exported part. Do not quietly include notes to make a missing visible explanation look covered.

In production, a canonical-IR1 reference is a useful automatic diagnostic. Label it `reference_origin=generated_ir1` and do not claim it independently measures facts the extraction itself omitted. Academic comparisons use `reference_origin=independent_gold` with its annotation version/source hashes.

Every metric returns:

```text
name, definition_version, reference_version, artifact_hash,
backend/model_revision, parameters, value, raw_value,
applicability, status, assessed_count, total_count,
unknown_count, per_item_findings, interval_if_incomplete
```

Statuses: `EVALUATED`, `PARTIAL`, `FAILED_TO_RUN`, `NOT_EVALUATED`, `NOT_APPLICABLE`, `INVALID_REFERENCE`. Non-applicability is determined from the task/reference, not because an evaluator crashed. An empty candidate with nonempty reference gets zero semantic/coverage/node retention and fails the product’s content requirements; missing gold input is an invalid reference, not a perfect score.

### 1. Semantic similarity

**Purpose:** measure global meaning alignment. It does not certify truth, concept completeness, or design.

Use one frozen sentence encoder `E` and cosine similarity. A compatible starting backend is the MiniLM encoder from the reference deck. Freeze its exact model revision, library version, language profile, segmentation, and normalization. Sentence Transformers documents the [embedding/cosine interface](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html).

For any nonzero embedding vector, define `e(x) = E(x) / ||E(x)||_2`. Split text at sentence/paragraph boundaries before the encoder’s actual `max_seq_length`; never silently truncate a long concept or slide. Encode long units in bounded windows, using each original token span once for pooling so overlap is not double-counted, then normalize their token-weighted pooled vector. Persist the segmentation map.

Let `e_i` be the embedding of reference concept `c_i`, and `f_j` the embedding of a unique visible candidate text unit. Exact duplicate/repeated footer text is removed from semantic pooling; factual error detection still examines every occurrence. Avoid stuffing headings/boilerplate into the pool.

```text
r = (sum_i w_i * e_i) / sum_i w_i
c = (sum_j v_j * f_j) / sum_j v_j
cos_raw = dot(r,c) / (norm(r) * norm(c))
S_semantic = max(0, min(1, cos_raw))
```

Set `v_j=1` per canonical candidate unit for the initial profile, so repeating a unit cannot gain extra weight. Different token/role weighting is a new named profile, not a hidden change. Retain raw cosine in `[-1,1]`; the bounded score uses negative similarity as zero. Do not describe it as a probability of correctness. If a pooled norm is numerically zero, return a computation status/diagnostic instead of division by zero.

Also report per-slide similarity and lowest-alignment reference items to explain a global score. Coverage supplies omission sensitivity. High cosine can coexist with a contradiction; faithfulness must catch that separately.

**Implementation:** `semantic.py` loads one encoder per worker, caches embeddings by text/model/segmentation hash, pools explicitly, and records `cos_raw` plus the profile. If the backend is unavailable, report `FAILED_TO_RUN`; optional TF-IDF is a separate named diagnostic with its own calibration. It cannot replace MiniLM under the same metric name or retain the same thresholds.

**Tests:** identical nonempty pooled vectors give 1; orthogonal vectors give 0; negative cosine clamps to 0; duplicate text is idempotent; a unit exceeding encoder capacity is segmented with every span represented; backend failure does not return a successful substitute score.

### 2. Concept coverage

**Purpose:** measure how much of the brief-relevant source meaning appears, independently of global cosine.

Annotate each concept as atomic or decompose it into facets first; do not let one keyword satisfy a concept requiring a mechanism and a result. Use the same frozen embedding profile to form candidate-window similarities. For reference concept/facet `i`:

```text
m_i = max_j cosine(e(c_i), e(candidate_window_j))
credit_i = 1       if m_i >= tau_full
         = 0.5    if tau_partial <= m_i < tau_full
         = 0      otherwise
S_coverage = sum_i w_i * credit_i / sum_i w_i
```

Empty candidate text has all credits 0. A concept can appear across several slides: bounded adjacent windows may be combined when the annotation defines a multi-part concept, with recorded matches. Prefer facet decomposition to concatenating arbitrary unrelated slides. One slide can legitimately cover multiple concepts; repeating the same concept gives at most one credit.

Initial `tau_full=0.65`, `tau_partial=0.45` reproduces the reference-deck starting configuration. These are **raw cosine** thresholds, not transformed scores or proven universal cutoffs. Calibrate them on development examples labeled absent/partial/full. Require `tau_partial < tau_full`; select the pair by predeclared weighted classification error or macro-F1, then freeze on held-out evaluation. Publish confusion matrices and threshold sensitivity.

Embedding-based presence remains imperfect. Record critical concept matches for independent source-aware review. An incorrect claim may share high semantic overlap; faithfulness is responsible for correctness. Report required/must-include miss counts and main/extra/notes credits separately rather than hiding them in the mean.

Example: concept weights `(3,2,1)` and credits `(1,0.5,0)` give `(3+1+0)/6 = 2/3`. Omitting the core concept while covering both others gives `3/6 = 1/2`. Repeating a covered concept does not change either score.

**Implementation:** `coverage.py` computes a cached similarity matrix and writes `concept_coverage.csv` with source evidence, weight, matched slide/object IDs, cosine, classification, location profile, and critical-miss flag.

**Tests:** full matching coverage=1; no concepts present=0; weights are positive; duplicate output cannot improve credit; notes-only coverage does not count as visible-main coverage; threshold equality is deterministic; thresholds from another backend are rejected.

### 3. Faithfulness and hallucination

**Purpose:** test whether candidate factual assertions are supported by the source, including captions, displayed metrics, tables, chart-derived comparisons, and diagram relations.

For each atomic claim, use declared evidence first. If absent/inadequate, retrieve source evidence with a fixed candidate budget; top-5 is an initial setting, not a guarantee of exhaustive support. Search failures or insufficient retrieval are not proof that a claim is false. Preserve `UNASSESSABLE` separately when evidence access failed; use `UNSUPPORTED` only after the configured assessment protocol has sufficient source access and finds no support. Positive numeric/cell checks can prove a typed fact but not an entire compound prose claim.

Labels and credit:

```text
SUPPORTED:    y_j = 1
PARTIAL:      y_j = 0.5
UNSUPPORTED:  y_j = 0
CONTRADICTED: y_j = 0
UNKNOWN / UNASSESSABLE: no completed label
```

Decompose compound claims before partial scoring wherever possible. Publish supported/partial/unsupported/contradicted counts so 0.5 is visibly a policy choice. Use `q_j=1` per atomic claim in the initial profile, with separate critical flags; priority weighting can be an explicitly versioned alternative.

Let `A` be assessed claims, `U` unassessed claims, `Q=sum_all q_j`, and `B=sum_A q_j*y_j`:

```text
S_faithfulness_assessed = B / sum_A q_j
assessment_completeness = sum_A q_j / Q
hallucination_rate = sum_A q_j * I(label in {UNSUPPORTED,CONTRADICTED}) / sum_A q_j
contradiction_rate = sum_A q_j * I(label=CONTRADICTED) / sum_A q_j
full-deck faithfulness interval = [ B/Q, (B + sum_U q_j)/Q ]
```

Worked example: two supported claims, one partial claim, one unsupported claim, and one unknown claim with equal weights give assessed faithfulness 2.5/4 = 0.625, assessed hallucination 1/4 = 0.25, completeness 4/5 = 0.8, and full-deck interval [2.5/5, 3.5/5] = [0.5, 0.7]. These are illustrative arithmetic checks, not observed project benchmark scores.

If no claim is assessed, do not divide by zero or return 1; the point estimate is unavailable and the interval is `[0,1]` for a nonempty factual claim set. If the task genuinely has no factual assertions, the metric is `NOT_APPLICABLE` with that reason, not perfect faithfulness. Hallucination rate is not simply `1-faithfulness` because partial credit exists.

Mandatory numeric checks compare **subject, measure, period, unit, and value**, not number presence. Convert units explicitly. For rounded numeric displays, accept only a predeclared tolerance from source/display precision and floating-point computation:

```text
abs(display_value - source_value) <= delta_source + delta_display + delta_float
```

Source precision is not a license to swap subjects/periods. Derived values require verified operands, unit-safe calculations, and a derivation trace. Relations such as “outperforms” must match the specific benchmark/period and comparator; the inspected 41.0 versus 41.16/41.29 case must fail a superiority claim for that comparison.

Use deterministic checks first, then evidence-scoped entailment/judging for unresolved prose/visual claims. Fix the judge version/rubric; record provenance and human adjudication on a sample. Generator-supplied confidence is not evaluation truth. [AlignScore](https://aclanthology.org/2023.acl-long.634/) is an optional independently named alignment baseline, not a numeric-verification replacement.

**Implementation:** `faithfulness.py` shares verification tools/gateway, batches claims, persists each completed batch, and writes `faithfulness_claims.csv`. Deep verification off or judge failure leaves appropriate unknowns; no weight renormalization makes the run fully assessed. Critical contradictory claims veto readiness.

**Tests:** profit/revenue swap fails; same number in a different period fails; unit conversions and derivations are audited; caption/table/graph claims are included; a judge failure preserves earlier labels; unknown claims widen the full-deck interval; no factual claims and no assessed claims are distinct cases.

### 4. Functional flow

**Purpose:** evaluate whether slides fulfill the presentation’s intended roles and logical prerequisites. There is no universal correct paper order or mandatory opening/closing formula for all briefs.

Build applicable rules `R_flow` from the brief and independently reviewed intent. Rules can require that necessary concepts/symbols be introduced before use, evidence appear before an unsupported recommendation, promised objectives be addressed in the main story, or required ending/action roles be present. A separate cover/ending/appendix is checked according to its selected extra-slide policy.

Infer roles from visible content and source-backed meaning, with a calibrated classifier/human validation when needed. Keyword rules may be a diagnostic fallback; a number alone must not label a slide an equation. Do not evaluate a generated role label as if it were independent gold.

Each applicable rule has fixed importance `a_r>0` and satisfaction `z_r in [0,1]`. Binary rules use 0/1; any graded rubric is declared before testing.

```text
S_flow = sum_r a_r * z_r / sum_r a_r
```

For a precedence rule `u before v`, use verified occurrence positions `(slide_index, within_slide_reading_order)`. Missing required occurrences fail the rule; optional absent nodes make only explicitly conditional rules inapplicable. Same-slide satisfaction is allowed if reading order genuinely introduces `u` before `v`. If a rule cannot be assessed, mark unknown and use the same weighted lower/upper interval principle as faithfulness.

For tasks with no applicable flow rules, return `NOT_APPLICABLE`. Keep exact-count compliance and role/objective violations as individually reported checks; do not let high transition scores compensate for missing required main content.

Example: three equal-weight prerequisite/ending rules with satisfaction `(1,0,1)` produce `2/3`; an unknown third rule gives an interval over the total applicable weight instead of assuming it passed.

**Implementation:** `functional.py` takes brief/reference constraints and independently checked candidate roles/occurrences, emits rule-by-rule rationale, and records classifier uncertainty. Subjective coherence ratings are separate auxiliary/human results rather than disguised deterministic facts.

**Tests:** a valid alternative teaching/executive order passes its own brief; using an undefined symbol fails; optional cover absence does not fail; required core content moved entirely to appendix fails its main-story rule; role-classifier failure remains unknown.

### 5. Structural similarity

**Purpose:** compare retained concepts and explicit semantic relationships, plus allowed relative ordering. Adjacency of unrelated concepts in a paper is not a semantic edge.

Reference graph `G_ref=(V_ref,E_ref)` contains brief-relevant canonical concepts and typed directed relations such as dependency, data flow, part-of, or causal relation supported by source evidence. A reviewed partial-order set `O_ref` specifies ordering where the presentation actually needs it. Alternate valid orders are allowed. Source-paper-order similarity can be reported separately as a descriptive diagnostic.

Extract candidate concepts and **asserted** relationships independently; co-occurrence or adjacent slides alone does not establish an edge. Collapse repeated mentions into canonical candidate nodes. Perform bounded one-to-one matching of candidate nodes to reference concepts using approved aliases, calibrated semantic scores, and manual checks for ambiguous matches. A maximum-weight bipartite matching prevents one vague node from being credited as many different reference nodes.

For nodes, let `TP_V` be matched reference weight, `FN_V` missed reference weight, and `FP_V` unmatched candidate weight under the fixed relevance annotation/profile. Match weights inherit reference priority; unmatched candidates use the predefined default weight. The gold graph must include acceptable relevant alternatives so source-backed optional content is not mislabeled as an error simply because one preferred outline omitted it.

```text
P_V = TP_V / (TP_V + FP_V)
R_V = TP_V / (TP_V + FN_V)
F_V = 2 * TP_V / (2*TP_V + FP_V + FN_V)
```

Construct edge counts analogously after endpoint alignment: a matched edge must have compatible type/direction and asserted source-supported meaning. `F_E = 2*TP_E/(2*TP_E+FP_E+FN_E)`. Use predeclared positive edge weights. Repeating nodes/edges produces no extra true-positive credit. Source-supported alternatives missing from gold indicate an annotation issue that must be adjudicated consistently, not selectively repaired only for one system.

For order, let `A_order` be reference precedence pairs whose endpoints are present; use fixed pair weights `b_uv`:

```text
S_order = sum_(u,v in A_order) b_uv * I(pos(u) < pos(v)) / sum_(u,v in A_order) b_uv
order_endpoint_completeness = weight(A_order) / weight(O_ref)
```

Missing endpoint retention is penalized by `F_V`; order completeness is always displayed so a deck omitting many concepts cannot boast a complete order assessment. If O_ref is nonempty but no endpoint pair is assessable, order is incomplete, not 1. If the task genuinely has no ordering constraints, mark that component not applicable.

For a fully applicable/assessed profile, retain the reference-slide weighting as the initial, declared configuration:

```text
S_structure = 0.5*F_V + 0.3*F_E + 0.2*S_order
```

Worked example: node weights TP=6, FP=1, FN=2 give F_V=12/15=0.8; edge weights TP=3, FP=1, FN=1 give F_E=6/8=0.75; three satisfied order pairs out of four give S_order=0.75. The declared 0.5/0.3/0.2 blend is 0.775.

For a graph with no annotated relationship/order task, omit only the mathematically inapplicable component and renormalize the declared remaining component weights **within this metric**, recording the effective profile. Do not omit failed/unassessed components to improve a score. Compare systems on the same case/profile and always retain the submetrics.

Empty candidate nodes with a nonempty reference produce `F_V=0`; missing all reference edges gives `F_E=0`. All-zero empty graph denominators are `NOT_APPLICABLE` only when the reference task truly contains none. Hard failures for invented/contradictory relationships remain in faithfulness even if aggregate graph retention is high.

**Implementation:** `structure.py` receives actual gold relationships/partial order, candidate assertions, and an auditable node mapping; it does not fabricate source edges from sequential indices. Write matched/missing/extra nodes/edges and order violations to CSV/JSON.

**Tests:** exact graph=1; duplicate mentions do not inflate credit; reversed directed edge fails; adjacency without an assertion is not an edge; permissible reorder passes; omitted endpoints lower node retention and order completeness; one vague candidate cannot match several unrelated concepts.

### 6. Visual quality

**Purpose:** measure spatial validity and readable presentation of actual final artifacts. Geometry scores do not prove aesthetic excellence; include rendered/human assessment separately.

Consider relevant visible content objects, excluding decorative background containers from content occupancy. Let box `B_k` have positive area, role weight `t_k>0`, and slide canvas `C`. Table cells, native chart labels, and grouped objects must be included at the meaningful inspection level without counting both a whole container and all children as independent content.

**Bounds.** Per-object outside-area fraction:

```text
b_k = 1 - area(B_k intersect C) / area(B_k)
S_bounds = 1 - sum_k t_k*b_k / sum_k t_k
```

Degenerate boxes are schema failures, not divisions by zero. Reserve title/footer/safe margins through separately specified constraints.

**Unintended overlap.** For each disallowed pair `(k,l)`, compute `o_kl=intersection_area/min(area_k,area_l)`. Exclude only declared intentional containment/background/connector relationships, not pairs merely because both contain text. Let `u_kl=(t_k+t_l)/2` and use a small fixed calibrated tolerance `tau_overlap`:

```text
p_kl = max(0, (o_kl - tau_overlap) / (1 - tau_overlap))
S_overlap = 1 - min(1, sum_disallowed_pairs u_kl*p_kl / sum_k t_k)
```

Store every offending pair. Fully coincident text is severe even when equal widths made the old checker ignore it. Render checks distinguish a visually clipped object from harmless bounding-box intersection.

**Typography.** For each text unit/cell/label, define role-specific floor `f_min,k` and actual resolved size `f_k`. Use `d_k=max(0,(f_min,k-f_k)/f_min,k)` and `S_type=1-sum t_k*d_k/sum t_k`. Actual reading clarity, clipped glyphs, equations, and image-embedded labels require rendered inspection. Requested theme exceptions must be explicit; automatic shrink cannot silently create a different floor.

**Alignment/spacing.** Evaluate only declared constraints/anchors. For constraint `h` with residual distance `d_h`, allowed tolerance `eps_h`, and severity scale `scale_h>0`, use `a_h=min(1,max(0,d_h-eps_h)/scale_h)` and `S_align=1-weighted_mean(a_h)`. Asymmetric/bento composition can be valid; do not force every box onto one arbitrary centerline.

**Density.** Let `d` be union area of nonduplicated content boxes divided by usable slide area. Use a role/composition-specific acceptable interval `[d_min,d_max]` calibrated on examples:

```text
penalty_density = (d_min-d)/d_min              if d < d_min
                = (d-d_max)/(1-d_max)         if d > d_max
                = 0                          otherwise
S_density = 1 - penalty_density
```

Boundary profiles with d_min=0/d_max=1 avoid the irrelevant zero-denominator branch. Union area, not summed overlapping areas, prevents double counting. Cover/conclusion/figure-led slides have different intervals. Density is a diagnostic for whitespace/overcrowding, not a requirement to fill empty space with decoration.

**Theme consistency.** Check permitted role/font/color/spacing tokens rather than penalizing purposeful layout diversity: `S_consistency = 1 - weighted_token_violations/weighted_applicable_checks`. Theme switching requested by the user changes the applicable specification, not the source facts.

With nonnegative declared dimension weights summing to 1:

```text
S_visual = alpha_b*S_bounds + alpha_o*S_overlap + alpha_t*S_type
         + alpha_a*S_align + alpha_d*S_density + alpha_c*S_consistency
```

Determine weights on development data using a constrained nonnegative fit to blinded human readability/design ratings, or preregister a simple initial equal-weight profile and disclose it as uncalibrated. Freeze before test evaluation. Genuinely inapplicable dimensions get an explicit effective profile; failed render/object inspection remains incomplete. Rendered clipping, missing required assets, and font-floor violations also have separate hard checks, so a high mean cannot hide a severe defect.

Report optional VLM/human 1–5 ratings separately with normalization `(rating-1)/4`. Judge rubric/version and rater agreement are mandatory metadata. This preserves the six core names without turning a subjective opinion into a deterministic geometric result. Native checks plus render evidence and human labels establish practical limits.

**Implementation:** `visual.py` consumes recursive native extraction plus scene intent; rendered inspection checks actual glyph/asset legibility and clipping. Estimates/OCR/VLM uncertainty must be recorded rather than claimed as exact measurements.

**Tests:** fully overlapping text fails; intentional containment passes; outside-area fractions stay bounded; tiny table fonts are included; decorative backgrounds do not inflate density; different valid layouts preserve consistency; zero-area boxes fail schemas; a failed renderer leaves visual completeness unresolved.

### 7. Aggregation, calibration, and academic comparison

Keep the six core scores visible. No universal weighted average is established by this design. An optional project aggregate is `S_total=sum_k beta_k*S_k`, with nonnegative predefined weights summing to 1, only when all required scores are assessed under the declared compatible profile. Record any task-level non-applicability before generation; failed/missing metrics do not trigger success-producing weight renormalization.

Use separate readiness gates: zero critical contradictions, valid required data/assets, required main-content compliance, preserved locks/count, no severe clipping, and native open/export success. An aggregate never overrides these. Optional deep verification off means basic-checked readiness and an unavailable full-faithfulness score, not a claim of fully verified academic quality.

Calibration protocol:

1. Independently annotate development/test concepts, roles, edges, partial orders, claim labels, and visual defects. Use source/brief-conditioned gold, not generated IR1 as the only reference.
2. Freeze encoder/judge/segmentation versions. Fit coverage thresholds and visual weights only on development data. Save config and calibration dataset hashes.
3. Check score ranges, denominator edge cases, idempotence to duplicated content, appropriate monotonicity when fixing a specific defect, and controlled sensitivity to removing critical content.
4. Use matched source/brief/model/count/budget comparisons and targeted ablations of enhancement, narrative, layouts, tools, and rendered critique. Renderer tests use identical content/scene graphs.
5. Repeat runs; use blinded human reviewers with a defined rubric. Report ordinal agreement, rank correlation between automated/human results, and paired confidence intervals resampled by document rather than pretending repeated slides are independent documents.
6. Report complete/partial/failed cases, latency/cost/cache/retry statistics, and per-part main/extras coverage. Never discard failed runs from the quality story without reporting their failure rate.

Suggested pilot: 6 sources × 2 briefs × 2 repetitions × 3 variants = 72 decks. Scale only after measuring generation/render/judgment cost. A larger matrix from BASE_PLAN is optional, not required to spend that budget.

The content/design/coherence framing is compatible with [PPTAgent/PPTEval](https://arxiv.org/abs/2501.03936), while the six exact project scores above are custom definitions. Use published frameworks as appropriately labeled comparison baselines and verify dataset/model licenses before reuse.

### 8. Concrete implementation order and outputs

1. Add versioned MetricResult/GoldReference/MetricsConfig contracts and a schema-validated report registry. Include part scopes, applicability, completeness, backend, and definition versions.
2. Repair candidate extraction, visual overlap, unknown-state handling, and the independent reference adapter. Add fixtures for every reproduced defect.
3. Implement/cache the encoder and semantic/coverage matrix with explicit segmentation and backend failures.
4. Implement deterministic metric/cell/derivation verification, then batched claim judgments and intervals.
5. Implement conditional flow constraints, reviewed graph matching/edge/order scoring, and visual dimensions.
6. Add calibration/experiment commands, CSV/JSON/HTML outputs, and the UI profile. Keep generation gates and offline evaluator shared.

Planned extension points: `evalute/metrics/semantic.py`, `coverage.py`, `faithfulness.py`, `functional.py`, `structure.py`, `visual.py`; `evalute/extract/pptx_extractor.py`; `evalute/reference/build_reference.py`; `evalute/runner.py`; `evalute/reporting/output.py`. New targets: `evalute/schemas.py`, `benchmarks/gold/`, `benchmarks/calibration/`, `benchmarks/run_experiments.py`, and `evalute/tests/test_metric_properties.py`.

Outputs include report.json/html, concept_coverage.csv, faithfulness_claims.csv, graph_matches.json, flow_constraints.csv, slide_metrics.csv, and operational_summary.csv. Each item carries source/slide/object/revision IDs so the metric can explain a problem and route a scoped repair. CLI names are proposed implementation targets, not commands claimed to exist today.
