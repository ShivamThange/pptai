from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.llm.llm_client import LLMClient

from ..metrics.semantic import similarities
from ..util import sentences


PROMPT = (Path(__file__).parents[1] / "prompts" / "claim_judge.txt").read_text(encoding="utf-8")


class ClaimVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
    explanation: str
    evidence_block_ids: list[str] = Field(default_factory=list)


def _claims(slides):
    return [
        {"claim_id": f"CL{i:03d}", "slide_no": slide["slide_no"], "claim": sentence}
        for i, (slide, sentence) in enumerate(
            (
                (slide, sentence)
                for slide in slides
                for sentence in sentences(slide["text"])
                if any(ch.isdigit() for ch in sentence) or len(sentence.split()) > 7
            ),
            1,
        )
    ]


def summarize(records, claim_count):
    """Assessed point score plus the full-deck interval [B/Q, (B+U)/Q].

    Unassessed claims keep weight in Q, so a partial run can never present its
    assessed mean as a deck-wide faithfulness value.
    """
    assessed, credit = len(records), sum(x["support_credit"] for x in records)
    unassessed = claim_count - assessed
    if assessed:
        score = credit / assessed
        interval = [credit / claim_count, (credit + unassessed) / claim_count]
        hallucination = sum(x["label"] in {"UNSUPPORTED", "CONTRADICTED"} for x in records) / assessed
        contradiction = sum(x["label"] == "CONTRADICTED" for x in records) / assessed
    else:
        score, hallucination, contradiction = None, None, None
        interval = [0.0, 1.0] if claim_count else [0.0, 0.0]
    return {"score": score, "hallucination_rate": hallucination, "contradiction_rate": contradiction,
            "assessment_completeness": assessed / claim_count if claim_count else None,
            "interval": interval, "claim_count": claim_count, "evaluated_claim_count": assessed}


def evaluate(slides, chunks, config, enabled=True, *, caller=None):
    if not enabled or not config["faithfulness"]["enabled"]: return [], {"status": "SKIPPED_DISABLED"}
    claims = _claims(slides)
    if not claims: return [], {"status": "NOT_APPLICABLE", "reason": "No factual assertions extracted",
                               "score": None, "hallucination_rate": None, "claim_count": 0}
    records = []
    try:
        if not chunks:
            raise ValueError("No source evidence available for factual assessment")
        matrix, _ = similarities([x["claim"] for x in claims], [x["text"] for x in chunks], config["embedding"]["model"])
        client = caller or LLMClient.for_evaluation(provider=config["faithfulness"].get("judge_provider"),
                                                   model=config["faithfulness"].get("judge_model"))
        for i, item in enumerate(claims):
            indices = matrix[i].argsort()[-config["faithfulness"]["top_k_evidence"]:][::-1]
            evidence = [{**chunks[j], "retrieval_score": round(float(matrix[i, j]), 5)} for j in indices]
            text = "\n\n".join(f"[{x['chunk_id']}] {x['text']}" for x in evidence)
            verdict = client.generate_structured(
                stage="faithfulness_judging",
                system_prompt=PROMPT.format(claim="the claim in the user payload", evidence="the evidence in the user payload"),
                user_payload={"claim": item["claim"], "evidence": text},
                output_model=ClaimVerdict,
                temperature=config["faithfulness"]["temperature"],
            )
            label = verdict.label
            records.append({**item, "weight": 1.0, "label": label, "support_credit": {"SUPPORTED": 1, "PARTIALLY_SUPPORTED": .5}.get(label, 0), "evidence": evidence, "judge_explanation": verdict.explanation})
    except Exception as exc:
        usage = getattr(locals().get("client"), "usage", None)
        return records, {"status": "FAILED", "reason": str(exc), "usage": usage.as_dict() if usage else None,
                    **summarize(records, len(claims)),
                    "error_class": getattr(exc, "error_class", type(exc).__name__)}
    return records, {"status": "COMPLETED", **summarize(records, len(claims)),
                     "provider": getattr(client, "provider", "external-caller"), "model": getattr(client, "model", "external-caller"),
                     "usage": client.usage.as_dict() if getattr(client, "usage", None) else None}
