"""Declared per-model request quotas, enforced by the gateway limiter and listed by the Studio.

Limits are declared for exact model ids and never inferred from a model name.
A model that is absent from the table is still usable, but only the process-wide
caps from configuration guard it, and the Studio labels it "quota not declared".
`LLM_MODEL_QUOTAS` declares a model the table has not caught up with, so a new
model id does not require a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

MINUTE_SECONDS = 60.0
DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class ModelQuota:
    label: str
    rpm: int
    tpm: int
    rpd: int

    def as_public(self) -> dict[str, object]:
        return {"label": self.label, "rpm": self.rpm, "tpm": self.tpm, "rpd": self.rpd}


GEMINI_QUOTAS: Mapping[str, ModelQuota] = {
    "gemini-3-flash": ModelQuota("Gemini 3 Flash", rpm=5, tpm=250_000, rpd=20),
    "gemini-3.6-flash": ModelQuota("Gemini 3.6 Flash", rpm=5, tpm=250_000, rpd=20),
    "gemini-3.8-flash": ModelQuota("Gemini 3.8 Flash", rpm=5, tpm=250_000, rpd=20),
    "gemini-3.1-flash-lite": ModelQuota("Gemini 3.1 Flash Lite", rpm=15, tpm=250_000, rpd=500),
    "gemini-3.5-flash-lite": ModelQuota("Gemini 3.5 Flash Lite", rpm=15, tpm=250_000, rpd=500),
}

QUOTAS_BY_PROVIDER: Mapping[str, Mapping[str, ModelQuota]] = {"gemini": GEMINI_QUOTAS, "openrouter": {}}


def normalize_model(value: str) -> str:
    """Map the id spellings a provider accepts onto the declared table key."""
    text = (value or "").strip().lower()
    for prefix in ("models/", "publishers/google/models/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.split("@", 1)[0].split(":", 1)[0]
    return text.removesuffix("-latest") if text.endswith("-latest") else text


def parse_env_quotas(raw: str) -> dict[str, ModelQuota]:
    """`model:rpm:tpm:rpd[,…]` -> declared quotas, failing loudly on a malformed entry."""
    declared: dict[str, ModelQuota] = {}
    for item in (part.strip() for part in (raw or "").split(",")):
        if not item:
            continue
        fields = item.split(":")
        if len(fields) != 4:
            raise ValueError("LLM_MODEL_QUOTAS entries must be model:rpm:tpm:rpd, got " + item)
        model = normalize_model(fields[0])
        try:
            rpm, tpm, rpd = (int(value) for value in fields[1:])
        except ValueError as error:
            raise ValueError("LLM_MODEL_QUOTAS limits must be integers, got " + item) from error
        if min(rpm, tpm, rpd) < 1:
            raise ValueError("LLM_MODEL_QUOTAS limits must be positive, got " + item)
        declared[model] = ModelQuota(model, rpm=rpm, tpm=tpm, rpd=rpd)
    return declared


def declared_models(provider: str, environ=None) -> dict[str, ModelQuota]:
    env = os.environ if environ is None else environ
    declared = dict(QUOTAS_BY_PROVIDER.get(provider, {}))
    declared.update(parse_env_quotas(env.get("LLM_MODEL_QUOTAS", "")))
    return declared


def quota_for(provider: str, model: str, environ=None) -> ModelQuota | None:
    declared = declared_models(provider, environ)
    return declared.get(normalize_model(model)) or declared.get((model or "").strip())
