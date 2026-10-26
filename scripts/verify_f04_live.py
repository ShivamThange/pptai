"""Representative configured-provider interpretation; failure stays unavailable."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from core.artifacts import atomic_json,file_hash,sha256_value
from core.revisions import copy_bundle
from schemas.raw_extraction_schema import RawExtraction
from schemas.asset_schema import AssetOptions
from pipeline.asset_interpreter import interpret_assets,asset_insights_to_units
from config.settings import resolve_environment,get_multi_agent_settings
from core.llm_client import LLMClient,LLMRequestError
from core.builder import PresentationBuilder
from verify_r06_native import catalog,slides,render_checked


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    output=Path(args.output).resolve();copy_bundle(Path(args.source).resolve(),output)
    raw=RawExtraction.model_validate_json((output/'raw_extraction.json').read_text(encoding='utf-8'))
    selected=[]
    for kind in ['table','figure','formula']:
        found=next((a for a in raw.assets if a.content and a.content.kind==kind and a.availability=='AVAILABLE' and
            (kind!='table' or a.content.row_count==3 and a.content.column_count==2 and a.data['headers']) and
            (kind!='formula' or a.content.transcription_status=='SOURCE_LITERAL')),None)
        if found:selected.append(found)
    raw.assets=selected;raw.asset_semantic_coverage=[]
    for a in raw.assets:a.content.interpretation=None
    env=resolve_environment(ROOT.parent/'BTPs5/.env');settings=get_multi_agent_settings(env)
    client=LLMClient(settings=settings,api_key=env.get('OPENROUTER_API_KEY' if settings.provider=='openrouter' else 'GEMINI_API_KEY'))
    evidence={'fixture_sources':True,'fixture_model_answers':False,'model':client.model,'source_raw_sha256':file_hash(output/'raw_extraction.json'),
              'status':'unavailable','rendered_text':[]}
    try:
        interpret_assets(raw,AssetOptions(mode='structured'),output,caller=client)
        units=asset_insights_to_units(raw)
        evidence['status']='completed';evidence['coverage']=[c.model_dump(mode='json') for c in raw.asset_semantic_coverage]
        evidence['interpretations']=[a.content.interpretation.model_dump(mode='json') for a in raw.assets if a.content.interpretation]
        if units:
            pptx=output/'live-findings.pptx'
            PresentationBuilder(catalog()).build(slides([{'type':'text_group','text':u.summary} for u in units]),pptx)
            evidence['render']=render_checked(pptx,output/'live-render');evidence['rendered_text']=[u.summary for u in units]
        atomic_json(output/'live-raw.json',raw.model_dump(mode='json'))
    except LLMRequestError as error:
        evidence['error_class']=error.error_class
    evidence['usage']=client.usage.as_dict()
    atomic_json(output/'live_acceptance.json',evidence)
    print(json.dumps({'status':evidence['status'],'error_class':evidence.get('error_class'),'accepted_units':len(evidence['rendered_text'])}))


if __name__=='__main__':main()
