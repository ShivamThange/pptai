"""One admission policy for all provider-ready requests; no guessed capacity."""
import math
from dataclasses import dataclass
from typing import Any
from core.artifacts import sha256_value
from schemas.context_schema import StageBudget, TokenMeasurement, PreparedContext


class ContextBudgetError(RuntimeError):
    def __init__(self, code, *, stage=None, required=None, available=None):
        super().__init__(code + (f' (required={required}, available={available})' if required is not None else ''))
        self.code = self.error_class = code
        self.stage = stage
        self.required, self.available = required, available
        self.status_code = self.retry_after = None


def resolve_stage_budget(settings, capabilities, stage, model, task_budget, *, provider=None, certainty='estimated'):
    capacity = capabilities.context_tokens
    origin = 'declared'
    if capacity is None:
        if settings.unknown_context_policy == 'error' or settings.unknown_context_tokens is None:
            raise ContextBudgetError('CONTEXT_CAPACITY_REQUIRED', stage=stage)
        capacity, origin = settings.unknown_context_tokens, 'configured_unknown'
    if task_budget.max_output_tokens > capabilities.max_output_tokens:
        raise ContextBudgetError('output_budget', stage=stage)
    margin = max(512, math.ceil(capacity * (.05 if certainty == 'counted' else .10)))
    ceiling = capacity - task_budget.max_output_tokens - margin
    cap = settings.stage_input_tokens.get('LLM_' + stage.upper() + '_INPUT_TOKENS')
    ceiling = min([ceiling] + [n for n in (capabilities.input_tokens, cap) if n is not None])
    if ceiling <= 0:
        raise ContextBudgetError('CONTEXT_FIXED_OVERHEAD_TOO_LARGE', stage=stage)
    return StageBudget(stage=stage, provider=provider or settings.provider, model=model,
        profile_version=capabilities.version, declared_context_limit=capabilities.context_tokens,
        declared_input_limit=capabilities.input_tokens, effective_context_limit=capacity,
        capacity_origin=origin, input_ceiling=ceiling, output_reserve=task_budget.max_output_tokens,
        margin=margin, stage_input_cap=cap, counter_policy=settings.context_count_mode)


def measure_request(payload, *, media_tokens=0, fingerprint=None):
    """Estimate request tokens from character counts.

    UTF-8 byte counting (the previous policy) inflated CJK-free requests by
    roughly 4x and starved slides of context. For English/JSON text a token
    averages ~4 characters, so characters/4 with a small framing constant is
    a far better estimate and stays deliberately conservative for code-like
    JSON keys (which tokenize denser than prose).
    """
    import json
    text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    # Count characters (not bytes): CJK chars tokenize ~1/char, Latin ~1/4.
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff' or '\uac00' <= ch <= '\ud7af')
    latin = len(text) - cjk
    tokens = -(-latin // 4) + cjk + 256
    return TokenMeasurement(input_tokens=tokens + media_tokens,
        method='hybrid_estimate' if media_tokens else 'char_estimate', certainty='estimated',
        counter_version='f13-chars-v2', included_components=['system', 'contents', 'schema', 'framing', 'generation_settings'],
        estimated_components=['system', 'contents', 'schema', 'framing'] + (['media'] if media_tokens else []),
        request_fingerprint=fingerprint or sha256_value(payload), media_tokens=media_tokens)


def assert_fits(prepared_request, stage_budget, measurement):
    if measurement.input_tokens > stage_budget.input_ceiling:
        raise ContextBudgetError('REQUIRED_CONTEXT_TOO_LARGE', stage=stage_budget.stage,
            required=measurement.input_tokens, available=stage_budget.input_ceiling)


@dataclass(frozen=True)
class PreparedRequest:
    context: PreparedContext
    payload: dict[str, Any]
    contents: Any
    schema: dict[str, Any]
    system_prompt: str
    output_model: Any
    task_budget: Any
    temperature: float
    capabilities: Any
    media_hashes: dict[str, str]

    def fingerprint(self):
        from dataclasses import asdict
        return sha256_value({'payload': self.payload, 'profile': asdict(self.capabilities),
            'budget': asdict(self.task_budget), 'policy': self.context.budget.model_dump(),
            'media': list(self.media_hashes.values()), 'projection': self.context.projection_version,
            'counter': self.context.measurement.counter_version})
