"""F06 Verification contracts and schemas.

Defines verification profiles, claim check records, and revision-bound verification reports.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from contracts.ir1_schema import EvidenceRef

VerificationProfile = Literal["basic", "deep"]
VerificationStatus = Literal["VERIFIED", "BASIC_CHECKED", "REJECTED", "FAILED_TO_RUN", "UNKNOWN", "NOT_EVALUATED"]


class ClaimCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str
    claim_sha256: str
    evidence_sha256: str
    citation_status: Literal["CHECKED", "FAILED", "UNKNOWN"] = "UNKNOWN"
    numeric_status: Literal["CHECKED", "FAILED", "UNKNOWN", "NOT_APPLICABLE"] = "NOT_APPLICABLE"
    semantic_status: Literal["CHECKED", "FAILED", "UNKNOWN", "NOT_EVALUATED"] = "NOT_EVALUATED"
    overall_status: VerificationStatus = "UNKNOWN"
    reasons: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source_refs: list[EvidenceRef] = Field(default_factory=list)


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["f06-v1"] = "f06-v1"
    profile: VerificationProfile = "basic"
    verifier_version: str = "f06-v1"
    total_claims: int = 0
    verified_claims: int = 0
    rejected_claims: int = 0
    unknown_claims: int = 0
    readiness: Literal["VERIFIED", "BASIC_CHECKED", "DRAFT_INCOMPLETE", "BLOCKED"] = "BASIC_CHECKED"
    checks: list[ClaimCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
