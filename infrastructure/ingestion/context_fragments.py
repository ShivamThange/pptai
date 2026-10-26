"""Lossless source projections used by the existing extractor, never a fact store."""
import re
from dataclasses import dataclass
from infrastructure.utils.artifacts import sha256_value, portable_value
from infrastructure.llm.context_budget import ContextBudgetError
from contracts.context_schema import ContextRef, ContextChunk
from contracts.raw_extraction_schema import SourceBlock, SourceAsset


def reference(item, representation, value, *, span=None, row=None, column=None):
    identity = item.block_id if isinstance(item, SourceBlock) else item.asset_id
    document = item.document_id or 'legacy-document'
    original = item.text if isinstance(item, SourceBlock) else portable_value(item.model_dump(mode='json'))
    source_hash = item.content_sha256 or sha256_value(original)
    if representation == 'cell' and span is None:
        span = (0, len(str(value['text'])))
    projection_hash = sha256_value(value)
    fields = dict(document_id=document, source_id=identity, section_path=item.section_path,
        representation=representation, source_hash=source_hash, span=span, row=row, column=column,
        locations=[loc.model_dump(mode='json') for loc in item.locations], projection_hash=projection_hash)
    return ContextRef(ref_id='cf_' + sha256_value(fields)[:24], **fields)


@dataclass
class Fragment:
    refs: list[ContextRef]
    blocks: list[SourceBlock]
    assets: list[SourceAsset]
    context_refs: list[ContextRef]
    depth: int = 0
    parent_ids: list[str] = None
    omitted_context_refs: list[ContextRef] = None

    def chunk(self):
        digest = sha256_value([r.model_dump(mode='json') for r in self.refs + self.context_refs])
        return ContextChunk(chunk_id='cx_' + digest[:24], purpose='extraction',
            document_ids=list(dict.fromkeys(r.document_id for r in self.refs)),
            section_paths=list(dict.fromkeys(tuple(r.section_path) for r in self.refs)), primary_refs=self.refs,
            context_only_refs=self.context_refs, source_ids=list(dict.fromkeys(r.source_id for r in self.refs)),
            asset_ids=[a.asset_id for a in self.assets], parent_ids=self.parent_ids or [], projection_hash=digest,
            findings=['optional_context_over_budget:' + r.ref_id for r in self.omitted_context_refs or []])


def initial_fragments(raw):
    fragments = []
    for block in raw.blocks:
        fragments.append(Fragment([reference(block, 'text', block.text, span=(0, len(block.text)))], [block], [], []))
    for asset in raw.assets:
        if asset.kind == 'table' and asset.data and asset.data.get('cells'):
            # Only cells are dispatched; rows/headers remain original registry data.
            cells = asset.data['cells']
            headers = [c for c in cells if c.get('column_header') or c.get('row_header')]
            header_refs = [reference(asset, 'cell', c, row=c['row'], column=c['column']) for c in headers]
            rows = {}
            for cell in cells:
                rows.setdefault(cell['row'], []).append(cell)
            for row in rows.values():
                repeated = [c for c in headers if c not in row and (c.get('column_header') or c['row'] == row[0]['row'])]
                projection = asset.model_copy(update={'data': {'cells': row + repeated, 'rows': [], 'headers': []}})
                fragments.append(Fragment([reference(asset, 'cell', c, row=c['row'], column=c['column']) for c in row], [],
                    [projection], [ref for c, ref in zip(headers, header_refs) if c in repeated]))
        else:
            representation = 'formula_text' if asset.kind == 'formula' and asset.data else 'asset_metadata'
            value = {'kind': asset.kind, 'caption': asset.caption, 'data': asset.data}
            fragments.append(Fragment([reference(asset, representation, value)], [], [asset], []))
    return fragments


def combine(parts):
    # Multiple projections of the same table become one cell projection.
    assets = {}
    for part in parts:
        for asset in part.assets:
            if asset.asset_id not in assets:
                assets[asset.asset_id] = asset.model_copy(deep=True)
            elif asset.kind == 'table':
                cells = {(c['row'], c['column']): c for c in assets[asset.asset_id].data['cells'] + asset.data['cells']}
                assets[asset.asset_id].data['cells'] = list(cells.values())
    return Fragment([r for p in parts for r in p.refs], [b for p in parts for b in p.blocks], list(assets.values()),
        list({r.ref_id: r for p in parts for r in p.context_refs}.values()), max(p.depth for p in parts),
        [p.chunk().chunk_id for p in parts], list({r.ref_id:r for p in parts for r in p.omitted_context_refs or []}.values()))


def subdivide(fragment, raw, policy):
    if fragment.depth >= policy.max_split_depth:
        raise ContextBudgetError('INDIVISIBLE_CONTEXT_TOO_LARGE', stage='knowledge_extraction')
    parent = fragment.chunk().chunk_id
    if len(fragment.refs) > 1:
        # Partition cells or merged groups. Repeat original headers with actual coordinates.
        middle = len(fragment.refs) // 2
        results = []
        for selected in (fragment.refs[:middle], fragment.refs[middle:]):
            block_ids = {r.source_id for r in selected if r.representation == 'text'}
            blocks = [next(b for b in raw.blocks if b.block_id == r.source_id).model_copy(update={
                'text': next(b for b in raw.blocks if b.block_id == r.source_id).text[r.span[0]:r.span[1]]})
                for r in selected if r.representation == 'text']
            assets = []
            ctx = list(fragment.context_refs)
            for asset in fragment.assets:
                refs = [r for r in selected if r.source_id == asset.asset_id]
                if not refs:
                    continue
                if asset.kind == 'table':
                    coordinates = {(r.row, r.column) for r in refs}
                    cells = [c for c in asset.data['cells'] if (c['row'], c['column']) in coordinates]
                    repeat = [c for c in asset.data['cells'] if c not in cells and (c.get('column_header') or c.get('row_header'))]
                    ctx.extend(reference(next(a for a in raw.assets if a.asset_id == asset.asset_id), 'cell', c,
                        row=c['row'], column=c['column']) for c in repeat)
                    assets.append(asset.model_copy(update={'data': {'cells': cells + repeat, 'rows': [], 'headers': []}}))
                else:
                    assets.append(asset)
            results.append(Fragment(selected, blocks, assets, ctx, fragment.depth + 1, [parent]))
        return results
    ref = fragment.refs[0]
    if ref.representation == 'cell':
        asset = next(a for a in raw.assets if a.asset_id == ref.source_id)
        original = next(c for c in asset.data['cells'] if (c['row'], c['column']) == (ref.row, ref.column))
        left, right = ref.span
        text = str(original['text'])[left:right]
        if len(text) < 2 or original.get('formula') or re.search(r'\d', text):
            raise ContextBudgetError('INDIVISIBLE_CONTEXT_TOO_LARGE', stage='knowledge_extraction')
        boundaries = [m.end() for m in re.finditer(r'\s+', text) if 0 < m.end() < len(text)]
        cut = left + (min(boundaries, key=lambda n: abs(n-len(text)/2)) if boundaries else len(text)//2)
        result = []
        for start, end in ((left, cut), (cut, right)):
            cell = dict(original, text=str(original['text'])[start:end])
            if cell.get('lexical_value') is not None:
                cell['lexical_value'] = cell['text']
            projection = asset.model_copy(update={'data': {'cells': [cell], 'headers': [], 'rows': []}})
            result.append(Fragment([reference(asset, 'cell', cell, row=ref.row, column=ref.column, span=(start,end))],
                [], [projection], [], fragment.depth+1, [parent]))
        return result
    if ref.representation != 'text':
        # A single cell/formula stays intact; subject/number bindings cannot be guessed.
        raise ContextBudgetError('INDIVISIBLE_CONTEXT_TOO_LARGE', stage='knowledge_extraction')
    original = next(b for b in raw.blocks if b.block_id == ref.source_id)
    start, end = ref.span
    text = original.text[start:end]
    if len(text) < 2 or original.kind in {'formula', 'equation'}:
        raise ContextBudgetError('INDIVISIBLE_CONTEXT_TOO_LARGE', stage='knowledge_extraction')
    # Prefer exact clause/line boundaries. Numeric clauses are indivisible.
    boundaries = [m.end() for m in re.finditer(r'(?:\r?\n|[.!?](?=\s))', text) if 0 < m.end() < len(text)]
    if not boundaries:
        if re.search(r'\d', text):
            raise ContextBudgetError('INDIVISIBLE_CONTEXT_TOO_LARGE', stage='knowledge_extraction')
        boundaries = [m.end() for m in re.finditer(r'\s+', text) if 0 < m.end() < len(text)]
    cut = min(boundaries, key=lambda n: abs(n - len(text) / 2)) if boundaries else len(text) // 2
    cut += start
    result = []
    for left, right in ((start, cut), (cut, end)):
        primary = original.text[left:right]
        block = original.model_copy(update={'text': primary})
        refs = [reference(original, 'text', primary, span=(left, right))]
        ctx = []
        # Labeled byte-based overlap, with code-point endpoints. It is separate from primary.
        allowance = policy.text_overlap_tokens
        lo, hi = left, right
        while lo > 0 and len(original.text[lo-1:left].encode('utf-8')) <= allowance:
            lo -= 1
        while hi < len(original.text) and len(original.text[right:hi+1].encode('utf-8')) <= allowance:
            hi += 1
        if lo < left:
            ctx.append(reference(original, 'text', original.text[lo:left], span=(lo, left)))
        if right < hi:
            ctx.append(reference(original, 'text', original.text[right:hi], span=(right, hi)))
        result.append(Fragment(refs, [block], [], ctx, fragment.depth + 1, [parent]))
    return result


def plan_extraction_chunks(raw, request_factory, budget, policy, *, lineage=None):
    """Search with cheap estimates; only final candidates use provider counting."""
    queue = initial_fragments(raw)
    planned = []
    while queue:
        fragment = queue.pop(0)
        try:
            prepared = request_factory(fragment, estimate_only=True)
            # Uncapped output heuristic prevents input-fit/output-risk bulk extraction.
            obligations = len(fragment.refs)
            if 1280 + 256 * obligations > prepared.task_budget.max_output_tokens and obligations > 1:
                raise ContextBudgetError('OUTPUT_INCOMPLETE')
            if len(str(fragment.blocks).encode('utf-8')) > policy.source_target_tokens * 2:
                raise ContextBudgetError('REQUIRED_CONTEXT_TOO_LARGE')
        except ContextBudgetError as error:
            if error.code not in {'REQUIRED_CONTEXT_TOO_LARGE', 'OUTPUT_INCOMPLETE'}:
                raise
            if error.code == 'REQUIRED_CONTEXT_TOO_LARGE' and any(r.representation == 'text' for r in fragment.context_refs):
                parent = fragment.chunk()
                fragment.omitted_context_refs = [r for r in fragment.context_refs if r.representation == 'text']
                fragment.context_refs = [r for r in fragment.context_refs if r.representation != 'text']
                fragment.parent_ids = [parent.chunk_id]
                if lineage is not None:
                    parent.state = 'SUPERSEDED'
                    parent.child_ids = [fragment.chunk().chunk_id]
                    lineage.append(parent)
                queue.insert(0, fragment)
                continue
            children = subdivide(fragment, raw, policy)
            if lineage is not None:
                parent = fragment.chunk()
                parent.state = 'SUPERSEDED'
                parent.findings = [error.code]
                parent.child_ids = [child.chunk().chunk_id for child in children]
                lineage.append(parent)
            queue[:0] = children
            continue
        if planned:
            candidate = combine([planned[-1], fragment])
            coordinates = [(r.source_id, r.row, r.column) for r in candidate.refs if r.representation == 'cell']
            if candidate.chunk().document_ids == planned[-1].chunk().document_ids and len(coordinates) == len(set(coordinates)):
                try:
                    merged = request_factory(candidate, estimate_only=True)
                    if 1280 + 256 * len(candidate.refs) <= merged.task_budget.max_output_tokens:
                        if lineage is not None:
                            for parent in (planned[-1].chunk(), fragment.chunk()):
                                parent.state = 'SUPERSEDED'
                                parent.child_ids = [candidate.chunk().chunk_id]
                                lineage.append(parent)
                        planned[-1] = candidate
                        continue
                except ContextBudgetError as error:
                    if error.code != 'REQUIRED_CONTEXT_TOO_LARGE':
                        raise
        planned.append(fragment)
    return planned


def projected_raw(raw, fragment):
    """Local grounding sees exactly supplied snippets/headers, including overlap."""
    blocks = {}
    for block in fragment.blocks:
        blocks.setdefault(block.block_id, []).append(block.text)
    for ref in fragment.context_refs:
        if ref.representation == 'text' and ref.span is not None:
            original = next(b for b in raw.blocks if b.block_id == ref.source_id)
            blocks.setdefault(ref.source_id, []).append(original.text[ref.span[0]:ref.span[1]])
    return raw.model_copy(update={'blocks': [next(b for b in raw.blocks if b.block_id == identity).model_copy(
        update={'text': '\n'.join(texts)}) for identity,texts in blocks.items()], 'assets': fragment.assets})
