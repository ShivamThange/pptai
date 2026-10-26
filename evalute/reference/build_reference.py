from collections import defaultdict

from ..util import clean, sha256, read_json, write_json


def build(ir_path, ir1_path, out_path):
    ir, ir1 = read_json(ir_path), read_json(ir1_path)
    chunks = [{"chunk_id": b.get("block_id", f"block_{i:04d}"), "section": (str(b.get("document_id")) + " / " if ir.get("collection_id") else "") + b.get("section", "Root"), "text": clean(b.get("text", ""))}
              for i, b in enumerate(ir.get("blocks", []), 1) if clean(b.get("text", ""))]
    # Table assets become evidence chunks too: slide tables (tab-joined cell
    # text) could never retrieve support from prose-only chunks, which skewed
    # table decks toward UNSUPPORTED in faithfulness judging.
    for asset in ir.get("assets", []) or []:
        if str(asset.get("type") or asset.get("kind", "")).lower() != "table":
            continue
        data = asset.get("data") or {}
        headers, rows = data.get("headers") or [], data.get("rows") or []
        lines = [" | ".join(str(cell) for cell in headers)] if headers else []
        lines += [" | ".join(str(cell) for cell in row) for row in rows]
        text = clean("\n".join(lines))
        if text:
            chunks.append({"chunk_id": asset.get("asset_id", f"table_{len(chunks):04d}"),
                           "section": (str(asset.get("document_id")) + " / " if ir.get("collection_id") else "") + str(asset.get("section", "Root")),
                           "text": text})
    summary = clean(ir1.get("executive_summary", "")).lower()
    concepts = []
    for i, concept in enumerate(ir1.get("concepts", []), 1):
        title, desc = clean(concept.get("title", "")), clean(concept.get("summary", ""))
        bullets = [clean(x) for x in concept.get("bullets", [])]
        text = clean(" ".join([title, desc, *bullets]))
        words = set(title.lower().split())
        weight = 3 if words and words.intersection(summary.split()) else (1 if len(text.split()) < 12 else 2)
        ids = concept.get("source_block_ids", [])
        section = next((c["section"] for c in chunks if c["chunk_id"] in ids), "Root")
        concepts.append({"concept_id": f"C{i:03d}", "title": title, "reference_text": text, "weight": weight,
                         "weight_reason": "summary_overlap" if weight == 3 else "length_rule", "source_block_ids": ids, "source_section": section})
    edges = []
    for i in range(len(concepts) - 1): edges.append([concepts[i]["concept_id"], concepts[i + 1]["concept_id"], "adjacent"])
    by_section = defaultdict(list)
    for c in concepts: by_section[c["source_section"]].append(c["concept_id"])
    for ids in by_section.values():
        for a, b in zip(ids, ids[1:]):
            edge = [a, b, "same_section"]
            if edge not in edges: edges.append(edge)
    profile = {"reference_id": f"sha256:{sha256(ir_path)}:{sha256(ir1_path)}", "document_title": ir1.get("document_title", ir.get("document_name", "Untitled")),
               "concepts": concepts, "source_chunks": chunks, "source_graph": {"nodes": [c["concept_id"] for c in concepts], "edges": edges}}
    write_json(out_path, profile)
    return profile
