# R01 — LLM gateway and provider failure repair

Type: **Repair** · Current capability: **Repaired gateway** · Implementation: **VERIFIED (R01 scope)** · Phase: **0**

Workflow references: 12, 13, 19. Dependencies: None.

Read [project context](../PROJECT_CONTEXT.md), [current state](../CURRENT_STATE.md), and [decisions](../DECISIONS.md) first. This is the single implementation document for this module; current code and proposed work are distinguished below. Paths in the file map resolve under the repository root documented in PROJECT_CONTEXT.

## Historical implementation before R01

The gateway reserves 8,192 OpenRouter output tokens for every task, sends one user message, retries HTTP 402, omits provider.require_parameters, and counts successful usage only. The prior audit observed a credit failure; 13 tests passed and one provider-flag test failed.

## Implemented and verified on 8 October 2026

- OpenRouter sends separate system/user messages and defaults to `require_parameters=true`, `allow_fallbacks=false`. Gemini uses `system_instruction`, a JSON response schema, and an explicit output limit. SDK retries are disabled so all attempts belong to the gateway. Routing settings and actual upstream provider/model are recorded. The flag follows [OpenRouter's endpoint compatibility guidance](https://openrouter.ai/docs/guides/features/structured-outputs).
- JSON schemas and local references are checked before transport. Optional strict mode closes fixed objects and rejects unsupported open dictionaries without silently changing the canonical contracts. General schema mode remains the default because current IR1/IR2 include open maps; every response still passes Pydantic validation. Knowledge draft kinds/priorities now reuse canonical enum types: live testing found that an unconstrained `kind="Knowledge"` was previously accepted by the gateway then discarded by extraction.
- HTTP 402 raises a terminal `LLMBudgetError`; auth and invalid requests are terminal. Transient transport/HTTP failures and malformed structured output have bounded attempts, Retry-After handling, and a total deadline including quota/retry waits. Slide repair propagates gateway failures instead of submitting terminal requests again. Limiter waits happen outside its lock.
- Task/batch output budgets replace the fixed reservation. Usage schema v2 records each failed/successful/cancelled attempt, estimates, observed tokens/cost when supplied, unknown observations, timing, routing policy, and error classes. Provider response bodies, prompts, and API keys are excluded. Generation/edit manifests persist attempts and terminal status while completed artifacts remain available. Legacy success-only usage is preserved in a hashed original manifest snapshot by the explicit v1-to-v2 observability adapter.
- Evaluator judging uses the same gateway and central provider/model configuration. The multi-agent path stays explicit with `--pipeline multi-agent`; the legacy pipeline default and its direct Gemini implementation are outside this repair.

### Configuration and compatibility

The typed response-schema argument is the existing Pydantic `output_model`; new callers can supply `system_prompt`, `user_payload`, and `task_budget=TaskBudget(...)`. Existing `prompt` callers remain supported. Production multi-agent extraction/storyboarding/composition now put task rules in system instructions and source data in the user payload.

- `LLM_MAX_ATTEMPTS=3`, `LLM_DEADLINE_SECONDS=120`, `LLM_REQUEST_TIMEOUT_SECONDS=60`; the legacy `max_retries` constructor parameter retains its historical meaning of total attempts.
- Default output ceiling: 4,096 tokens. Extraction: `min(4096, 1280 + 256*blocks)`; storyboard: `min(4096, 512 + 320*max_slides)`; composition/repair: 2,048; vision: 512 per image; judging: 768. `LLM_<STAGE>_OUTPUT_TOKENS` overrides a task budget within the ceiling. `LLM_MAX_OUTPUT_TOKENS` supersedes the legacy `OPENROUTER_MAX_TOKENS` setting.
- Declared/versioned deployment capabilities: `LLM_CAPABILITIES_VERSION`, `LLM_CONTEXT_TOKENS`, `LLM_SUPPORTS_STRUCTURED_OUTPUTS`, `LLM_SUPPORTS_SYSTEM_INSTRUCTIONS`, `LLM_SUPPORTS_MULTIMODAL`, `LLM_STRICT_SCHEMA`. Limits are never guessed from a model name. Unknown context capacity remains unknown. Text input estimates conservatively include system/schema overhead; with a declared context limit, multimodal callers must supply a complete `TaskBudget.estimated_input_tokens` estimate. F07 still owns context selection.
- Routing policy: `OPENROUTER_REQUIRE_PARAMETERS` and `OPENROUTER_ALLOW_FALLBACKS`. No automatic cross-provider/model switch is implemented. `LLM_PROVIDER` and provider model variables select generation; `EVAL_LLM_PROVIDER`/`EVAL_LLM_MODEL` default to generation configuration, with explicit evaluator YAML/CLI overrides.
- CLI overrides: `--llm-provider`, `--llm-model`, `--llm-max-output-tokens`, `--llm-max-attempts`, `--llm-deadline-seconds`, `--eval-llm-provider`, `--eval-llm-model`. Gemini runtime needs the tested `google-genai>=2.8,<3`; local schema checks require `jsonschema>=4,<5`.
- Async cancellation stops quota/retry waits cooperatively, joins an already-started synchronous transport within its configured timeout, discards its output, and persists cancellation before observer teardown.

### Verification evidence

Base commit: `24e8a3a1d8e9a2684348194ae4149a2c8c263107` on `multi-agent`; implementation is an **uncommitted working-tree change**, not a new tested commit. Exact tested source/artifact hashes are recorded in `C:/Users/thang/Projects/PPTAI/audit-artifacts/r01/verification.json`.

- Automated acceptance: `python -m pytest tests evalute/tests -q -p no:cacheprovider --basetemp .pytest_tmp/r01-verified-final` — **50 passed**. Includes the original provider-flag regression plus injected 402/401/403/400/422, 429/503, both Retry-After formats, malformed/missing content, schema/capability incompatibility, limits, cancellation, concurrent manifest writes, legacy observation preservation, Gemini SDK options, evaluator routing, and terminal-error propagation through composition/orchestration. CLI help and `git diff --check` also pass.
- Live OpenRouter probe: validated `answer="ok"`, 128 output-token budget, one successful attempt; 38 input / 6 output tokens. `live-probe.json` and `live-probe-manifest.json` are under the evidence directory.
- Live complete one-slide pipeline: `live-pipeline-final/` contains validated IR1, storyboard, IR2, PPTX, deterministic quality report, and terminal `PASSED` manifest. Five actual attempts: extraction and storyboard succeeded; two malformed composition responses were recorded before the third succeeded within the configured three-attempt budget. Observed totals: 9,737 input / 543 output tokens; provider-reported cost 0.00368406. The output opens through `python-pptx` as one slide.
- PPTX SHA-256: `a6551e609cb7fca9fd4f1e256e55a10ab9d97068ef0619727db8902019e9d15a`. Live manifest SHA-256: `99581f1d8c677f4718811f033ef2727b8f51281c77d3d0ac8cf48c330d5441e4`. Tested source bundle SHA-256: `95dbd3bd0541835999dbbc08dd6525fa41a6094f0145dcc7e54f26ddfa2f1ddb`.
- Limits: live Gemini endpoint, native PowerPoint/LibreOffice rendering, and a full uploaded-document benchmark were not run. Gemini adaptation is verified with the installed SDK and an injected client. Renderer code is unchanged. Earlier exploratory failures and their manifests remain in the evidence directory; they are not counted as successful runs.

Verification is scoped to R01 transport/configuration/observability. It does not mark provenance, grounding, renderer quality, cache/revision correctness, UI, or other modules complete.

## Objective and ownership

Make existing execution reliable and observable before adding generation stages. Own transport, provider schemas, retries, quotas, and per-call output budgets; F07 owns selection of source context.

## Inputs, outputs, and contracts

generate_structured(system_prompt, user_payload, response_schema, task_budget) -> validated result; CallAttempt records stage, provider/model, estimated/observed usage, status, error class, and elapsed time. Provider capability limits are configured/versioned, not inferred from marketing names.

## Implementation sequence

1. Restore require_parameters for compatible OpenRouter endpoints and validate schemas locally; adapt Gemini system instructions through the same gateway.
2. Distinguish terminal billing/auth/invalid-request errors from bounded transient failures. Honor retry-after and deadlines; do not sleep under the limiter lock.
3. Set output budgets by task and batch size; record input/output observations and failed attempts. Propagate a budget error instead of repeating the same unaffordable request.
4. Centralize generation and evaluator provider configuration. Keep CLI defaults explicit until the repaired path passes.
5. Add injected transport fixtures for 402, 429, 503, malformed structured responses, schema incompatibility, and cancellation.

## File map

- core/llm_client.py (existing)
- config/settings.py (existing)
- main.py (existing)
- tests/test_multi_agent_contracts.py (existing)
- core/llm_run.py; tests/test_llm_gateway_reliability.py (new)
- pipeline/orchestrator.py, pipeline/slide_editor.py, pipeline/slide_composer.py, pipeline/knowledge_extractor.py, pipeline/storyboard_planner.py, pipeline/visual_reviewer.py; schemas/ir1_schema.py (integration points)
- evalute/config.py, evalute/config.yaml, evalute/metrics/faithfulness.py; requirements.txt and evalute/requirements.txt (shared evaluator gateway/dependencies)

Existing files are extension points, not instructions to preserve their current bugs. New names are proposed implementation targets. Shared validators/contracts have one owner and are reused by dependents.

## Failure, migration, and rollback

Keep completed artifacts when a provider fails. Do not return invented fallback results. Provider switching uses the configured compatibility policy and is recorded.

Migrate existing artifacts through an explicit versioned adapter where compatible. Preserve original artifacts for reproduction. Roll out the changed path behind explicit capability/configuration selection until its acceptance checks pass; do not create a second fact store or independent UI generation pipeline.

## Acceptance and verification

- The failing provider-flag test passes.
- A billing error causes one terminal attempt; transient retries stop at the configured budget.
- Failed attempts and terminal stage state appear in the manifest without leaking API keys.
- System instructions and user data are separate provider fields/messages.

Use meaningful fixtures and rendered integration checks where relevant. Do not mark the module done from file existence or a mocked success path alone. Record exact tested commit/artifact hashes and any unavailable checks in CURRENT_STATE and MODULE_STATUS.

## User decisions and validation questions

- Confirmed Q12: LLM/provider undecided. Use configurable task budgets and discover/declare capabilities for the chosen provider later; log actual runtime/cost.

The central DECISIONS file is authoritative for answers; wording here may describe an earlier pending state. Pending preference questions do not imply unapproved work or block unrelated progress.
