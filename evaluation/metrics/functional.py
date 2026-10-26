import re


KEYWORDS = {"INTRO": ["introduction", "overview", "agenda"], "MOTIVATION": ["motivation", "problem", "challenge"],
            "SUMMARY": ["summary", "conclusion", "takeaway"], "METHOD": ["method", "approach", "procedure"],
            "RESULT": ["result", "evaluation", "performance"], "EXAMPLE": ["example", "case study"], "FORMULA": ["equation", "formula"]}


def evaluate(slides):
    roles, warnings = [], []
    for slide in slides:
        text = slide["text"].lower()
        role = next((r for r, terms in KEYWORDS.items() if any(t in text for t in terms)), "CONCEPT" if text else "OTHER")
        if re.search(r"[=≈≤≥]\s*\d|\\frac|\^", text): role = "FORMULA"
        if any(s["table"] for s in slide["shapes"]): role = "TABLE"
        roles.append(role)
    if len(slides) > 5 and not any(r in roles[:2] for r in ["INTRO", "MOTIVATION"]): warnings.append("No opening/context slide detected")
    if len(slides) > 5 and "SUMMARY" not in roles[-2:]: warnings.append("No closing summary detected")
    if len(slides) > 2 and roles[0] == "SUMMARY": warnings.append("Summary appears at the start")
    score = max(0, 1 - .2 * len(warnings))
    return roles, {"functional_sequence_score": score, "role_sequence": roles, "warnings": warnings}
