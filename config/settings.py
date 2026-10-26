"""Central configuration for the multi-agent path; CLI values remain authoritative."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from dotenv import dotenv_values


def _positive_int(name: str, default: int, environ=None) -> int:
    raw = (os.environ if environ is None else environ).get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from error
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value


def _bool(name: str, default: bool, environ=None) -> bool:
    value = (os.environ if environ is None else environ).get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1"}


@dataclass(frozen=True)
class TaskBudget:
    max_output_tokens: int
    max_attempts: int = 3
    deadline_seconds: float = 120.0
    estimated_input_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1 or self.max_attempts < 1 or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError("Task output, attempt, and deadline budgets must be positive")
        if self.estimated_input_tokens is not None and self.estimated_input_tokens < 1:
            raise ValueError("Estimated input tokens must be positive")


@dataclass(frozen=True)
class ProviderCapabilities:
    # These are declared deployment limits, never guesses based on model names.
    version: str = "configured-v1"
    max_output_tokens: int = 8192
    context_tokens: int | None = None
    input_tokens: int | None = None
    # No universal image-token constant. A deployment may declare a tested profile.
    image_tokens: int | None = None
    image_counter_version: str | None = None
    structured_outputs: bool = True
    system_instructions: bool = True
    multimodal: bool = True
    strict_schema: bool = False
    require_parameters: bool = True
    allow_fallbacks: bool = False

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1 or any(n is not None and n < 1 for n in (self.context_tokens, self.input_tokens, self.image_tokens)):
            raise ValueError("Declared provider limits must be positive")
        if self.image_tokens is not None and not self.image_counter_version:
            raise ValueError('Image estimates require a versioned deployment profile')


def get_provider_model(provider: str, environ=None) -> str:
    # Defaults match the models documented in README.md; both are real, currently served models.
    defaults = {"openrouter": "google/gemini-2.5-flash-lite", "gemini": "gemini-3.1-flash-lite"}
    return (os.environ if environ is None else environ).get("OPENROUTER_MODEL" if provider == "openrouter" else "GEMINI_MODEL", defaults[provider])


@dataclass(frozen=True)
class MultiAgentSettings:
    provider: str
    model: str
    max_calls_per_minute: int
    max_concurrency: int
    ir1_batch_input_char_budget: int
    max_section_retries: int
    max_repairs_per_slide: int
    capabilities: ProviderCapabilities
    max_attempts: int
    deadline_seconds: int
    request_timeout_seconds: int
    evaluator_provider: str
    evaluator_model: str
    stage_output_tokens: Mapping[str, int] = field(default_factory=dict)
    stage_input_tokens: Mapping[str, int] = field(default_factory=dict)
    context_policy: str = 'progressive'
    unknown_context_policy: str = 'configured'
    unknown_context_tokens: int | None = None
    context_count_mode: str = 'auto'
    source_target_tokens: int = 6000
    text_overlap_tokens: int = 0
    max_split_depth: int = 32
    run_max_generation_calls: int | None = None
    run_max_reserved_tokens: int | None = None
    max_tokens_per_minute: int | None = None
    strict_section_coverage: bool = False
    model_profiles: Mapping[str, ProviderCapabilities] = field(default_factory=dict)

    def __post_init__(self):
        if self.context_policy not in {'legacy', 'progressive'} or self.unknown_context_policy not in {'configured', 'error'}:
            raise ValueError('Invalid context policy')
        if self.context_count_mode not in {'auto', 'estimate', 'provider_required'}:
            raise ValueError('Invalid context count mode')
        if any(n is not None and n < 1 for n in (self.unknown_context_tokens, self.source_target_tokens,
            self.max_split_depth, self.run_max_generation_calls, self.run_max_reserved_tokens, self.max_tokens_per_minute)):
            raise ValueError('Context limits must be positive')
        if not 0 <= self.text_overlap_tokens <= self.source_target_tokens // 2:
            raise ValueError('Overlap must be at most half the source target')

    def context_snapshot(self):
        from dataclasses import asdict
        return {key: value for key, value in asdict(self).items() if key in {
            'stage_input_tokens', 'context_policy', 'unknown_context_policy', 'unknown_context_tokens',
            'context_count_mode', 'source_target_tokens', 'text_overlap_tokens', 'max_split_depth',
            'run_max_generation_calls', 'run_max_reserved_tokens', 'max_tokens_per_minute', 'model_profiles'}}

    def task_budget(self, stage: str, batch_size: int = 1) -> TaskBudget:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        defaults = {
            "knowledge_extraction": min(4096, 1280 + 256 * batch_size),
            "storyboard_planning": min(4096, 512 + 320 * batch_size),
            "slide_composition": 6144,
            "slide_repair": 6144,
            "vision_audit": 512 * batch_size,
            "faithfulness_judging": 768,
            "claim_verification": min(4096, 256 * batch_size),
        }
        env_name = "LLM_" + stage.upper() + "_OUTPUT_TOKENS"
        tokens = self.stage_output_tokens.get(env_name, defaults.get(stage, 6144))
        return TaskBudget(min(tokens, self.capabilities.max_output_tokens), self.max_attempts, self.deadline_seconds)


def resolve_environment(env_path=None, overrides=None):
    """CLI > process environment > repository .env > defaults; never mutate os.environ."""
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().parents[1] / ".env"
    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    values.update(os.environ)
    values.update({k: str(v) for k, v in (overrides or {}).items() if v is not None})
    return values


def get_multi_agent_settings(environ=None) -> MultiAgentSettings:
    env = os.environ if environ is None else environ
    provider = env.get("LLM_PROVIDER", "openrouter").strip().lower()
    if provider not in {"openrouter", "gemini"}:
        raise ValueError("LLM_PROVIDER must be 'openrouter' or 'gemini'.")
    model = get_provider_model(provider, env)
    evaluator_provider = env.get("EVAL_LLM_PROVIDER", provider).strip().lower()
    if evaluator_provider not in {"openrouter", "gemini"}:
        raise ValueError("EVAL_LLM_PROVIDER must be 'openrouter' or 'gemini'.")
    evaluator_default = model if evaluator_provider == provider else get_provider_model(evaluator_provider, env)
    context = env.get("LLM_CONTEXT_TOKENS")
    def optional(name):
        return _positive_int(name, 1, env) if env.get(name, '').strip() else None
    stages = {'knowledge_extraction', 'storyboard_planning', 'slide_composition', 'slide_repair',
              'vision_audit', 'faithfulness_judging', 'claim_verification'}
    for key in env:
        if key.startswith('LLM_') and key.endswith('_INPUT_TOKENS') and key != 'LLM_MAX_INPUT_TOKENS':
            if key[4:-13].lower() not in stages:
                raise ValueError('Unknown stage input ceiling: ' + key)
    output_setting = "LLM_MAX_OUTPUT_TOKENS" if "LLM_MAX_OUTPUT_TOKENS" in env else "OPENROUTER_MAX_TOKENS"
    return MultiAgentSettings(
        provider=provider,
        model=model,
        max_calls_per_minute=_positive_int("LLM_MAX_CALLS_PER_MINUTE", 30, env),
        max_concurrency=_positive_int("LLM_MAX_CONCURRENCY", 2, env),
        ir1_batch_input_char_budget=_positive_int("IR1_BATCH_INPUT_CHAR_BUDGET", 24000, env),
        max_section_retries=_positive_int("MAX_SECTION_RETRIES", 1, env),
        max_repairs_per_slide=_positive_int("MAX_REPAIRS_PER_SLIDE", 2, env),
        capabilities=ProviderCapabilities(
            version=env.get("LLM_CAPABILITIES_VERSION", "configured-v1"),
            max_output_tokens=_positive_int(output_setting, 8192, env),
            context_tokens=_positive_int("LLM_CONTEXT_TOKENS", 1, env) if context else None,
            input_tokens=optional('LLM_MAX_INPUT_TOKENS'),
            structured_outputs=_bool("LLM_SUPPORTS_STRUCTURED_OUTPUTS", True, env),
            system_instructions=_bool("LLM_SUPPORTS_SYSTEM_INSTRUCTIONS", True, env),
            multimodal=_bool("LLM_SUPPORTS_MULTIMODAL", True, env),
            strict_schema=_bool("LLM_STRICT_SCHEMA", False, env),
            require_parameters=_bool("OPENROUTER_REQUIRE_PARAMETERS", True, env),
            allow_fallbacks=_bool("OPENROUTER_ALLOW_FALLBACKS", False, env),
        ),
        max_attempts=_positive_int("LLM_MAX_ATTEMPTS", 3, env),
        deadline_seconds=_positive_int("LLM_DEADLINE_SECONDS", 120, env),
        request_timeout_seconds=_positive_int("LLM_REQUEST_TIMEOUT_SECONDS", 60, env),
        evaluator_provider=evaluator_provider,
        evaluator_model=env.get("EVAL_LLM_MODEL", evaluator_default),
        stage_output_tokens={key: _positive_int(key, 2048, env) for key in env
                             if key.startswith("LLM_") and key.endswith("_OUTPUT_TOKENS") and key != "LLM_MAX_OUTPUT_TOKENS"},
        stage_input_tokens={key: _positive_int(key, 1, env) for key in env
                            if key.startswith('LLM_') and key.endswith('_INPUT_TOKENS') and key != 'LLM_MAX_INPUT_TOKENS'},
        context_policy=env.get('LLM_CONTEXT_POLICY', 'progressive'),
        unknown_context_policy=env.get('LLM_UNKNOWN_CONTEXT_POLICY', 'configured'),
        unknown_context_tokens=optional('LLM_UNKNOWN_CONTEXT_TOKENS'),
        context_count_mode=env.get('LLM_CONTEXT_COUNT_MODE', 'auto'),
        source_target_tokens=_positive_int('IR1_SOURCE_TARGET_TOKENS', 6000, env),
        text_overlap_tokens=int(env.get('CONTEXT_TEXT_OVERLAP_TOKENS', '0')),
        max_split_depth=_positive_int('CONTEXT_MAX_SPLIT_DEPTH', 32, env),
        run_max_generation_calls=optional('LLM_RUN_MAX_GENERATION_CALLS'),
        run_max_reserved_tokens=optional('LLM_RUN_MAX_RESERVED_TOKENS'),
        max_tokens_per_minute=optional('LLM_MAX_TOKENS_PER_MINUTE'),
        strict_section_coverage=_bool('STRICT_SECTION_COVERAGE', False, env),
    )
