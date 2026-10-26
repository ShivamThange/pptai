def evaluate(concepts, slides, matrix, config):
    c = config["coverage"]
    records = []
    for i, concept in enumerate(concepts):
        scores = matrix[i] if matrix.shape[1] else []
        best_index = int(scores.argmax()) if len(scores) else None
        score = float(scores[best_index]) if best_index is not None else 0.0
        status = "COVERED" if score >= c["covered_threshold"] else "PARTIALLY_COVERED" if score >= c["partial_threshold"] else "MISSING"
        credit = 1 if status == "COVERED" else c["partial_credit"] if status == "PARTIALLY_COVERED" else 0
        records.append({"concept_id": concept["concept_id"], "title": concept["title"], "weight": concept["weight"],
                        "best_slide": slides[best_index]["slide_no"] if best_index is not None else None, "cosine": round(score, 5),
                        "status": status, "weighted_contribution": credit * concept["weight"],
                        "matched_text": slides[best_index]["text"] if best_index is not None else ""})
    total = sum(r["weight"] for r in records) or 1
    metrics = {"weighted": sum(r["weighted_contribution"] for r in records) / total,
               "strict_weighted": sum(r["weight"] for r in records if r["status"] == "COVERED") / total,
               "unweighted": sum(r["status"] != "MISSING" for r in records) / max(1, len(records)),
               "counts": {s: sum(r["status"] == s for r in records) for s in ["COVERED", "PARTIALLY_COVERED", "MISSING"]}}
    return records, metrics
