from pathlib import Path
import json
from infrastructure.utils.artifacts import parse_document_cached
from infrastructure.ingestion.source_adapter import build_raw_extraction
from infrastructure.ingestion.collection import retain_sources
from infrastructure.ingestion.asset_adapters import enrich_assets
from contracts.asset_schema import AssetOptions, AssetInsight, AssetEvidenceAnchor
from infrastructure.ingestion.asset_interpreter import InterpretationDraft

FIXTURES=Path(__file__).parent/'fixtures/assets'


class AssetCaller:
    model='f04-fixture'
    cache_version='f04-tests-v1'
    def __init__(self):self.calls=[]
    def generate_structured(self, *, prompt, **kwargs):
        data=json.loads(prompt)['SOURCE_DATA'];self.calls.append(data)
        insights=[]
        if data['content']['kind']=='table' and any(c.get('column_header') and c['text']=='Accuracy (%)' for c in data['content']['cells']):
            insights=[AssetInsight(asset_id=data['asset_id'],kind='comparison',statement='Candidate calculation',basis='calculated',
                anchors=[AssetEvidenceAnchor(asset_id=data['asset_id'],source_sha256=data['source_sha256'],row=1,column=1)],
                context_refs=[b['source_id'] for b in data['context']],calculation={'operation':'difference','cells':[[1,1],[2,1]]})]
        return InterpretationDraft(role='evidence',summary='Fixture asset interpretation',insights=insights)
    def generate_multimodal_structured(self, *, image_paths, prompt, **kwargs):
        data=json.loads(prompt)['SOURCE_DATA'];self.calls.append(data)
        return InterpretationDraft(role='comparison',summary='Fixture visual observation',insights=[AssetInsight(
            asset_id=data['asset_id'],kind='trend',statement='the right bar is taller than the left bar',basis='visual_observation',
            qualification='a qualitative reading of the supplied figure',context_refs=[b['source_id'] for b in data['context']],
            anchors=[AssetEvidenceAnchor(asset_id=data['asset_id'],source_sha256=data['source_sha256'],region=(0,0,900,450))])])


def enriched(name,tmp_path,caller=None,understanding='off'):
    structural=parse_document_cached(FIXTURES/name,tmp_path/'parse',resume=True,parse_options={})
    root=tmp_path/'work';root.mkdir(exist_ok=True)
    retain_sources(structural,root)
    raw=build_raw_extraction(structural,root)
    return enrich_assets(raw,structural,root,AssetOptions(mode='structured',semantic_understanding=understanding),caller=caller),root,structural
