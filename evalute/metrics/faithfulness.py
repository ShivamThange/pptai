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


def evaluate(slides, chunks, config, enabled=True, *, caller=None):
    if not enabled or not config["faithfulness"]["enabled"]: return [], {"status": "SKIPPED_DISABLED"}
    claims = _claims(slides)
    if not claims: return [], {"status": "COMPLETED", "score": None, "hallucination_rate": None, "claim_count": 0}
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
                    "claim_count": len(claims), "evaluated_claim_count": len(records), "score": None,
                    "error_class": getattr(exc, "error_class", type(exc).__name__)}
    total = len(records) or 1
    return records, {"status": "COMPLETED", "score": sum(x["support_credit"] for x in records)/total,
                     "hallucination_rate": sum(x["label"] in {"UNSUPPORTED", "CONTRADICTED"} for x in records)/total,
                     "contradiction_rate": sum(x["label"] == "CONTRADICTED" for x in records)/total, "claim_count": len(records),
                     "provider": getattr(client, "provider", "external-caller"), "model": getattr(client, "model", "external-caller"),
                     "usage": client.usage.as_dict() if getattr(client, "usage", None) else None}
