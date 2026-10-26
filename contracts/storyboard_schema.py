"""Contracts separating deck-level narrative planning from slide composition."""

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


class TopicChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    unit_ids: List[str] = Field(min_length=1)
    asset_ids: List[str] = Field(default_factory=list)
    digest: str = Field(min_length=1)
    token_estimate: int = Field(ge=1)


class SlidePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: int = Field(ge=1)
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    narrative_role: Literal[
        "opening", "context", "problem", "idea", "method", "evidence", "implication", "closing"
    ]
    chunk_refs: List[str] = Field(min_length=1)
    source_unit_ids: List[str] = Field(min_length=1)
    candidate_asset_ids: List[str] = Field(default_factory=list)
    preferred_layouts: List[str] = Field(default_factory=list)


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_title: str = Field(min_length=1)
    lens: Literal["executive", "technical", "pitch", "academic"] = "executive"
    slides: List[SlidePlan] = Field(min_length=1)
