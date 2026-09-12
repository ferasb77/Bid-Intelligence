"""Operational commissioning runner using raw corpus and production components only.

No fixtures, replay, synthetic publications, or inferred governed bindings.
Raw source-reference counts are reported separately from governed references.
"""
import json, os, sys, time, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import argparse
parser=argparse.ArgumentParser(description='Fresh Bank of Canada commissioning; stop at the first failed boundary.')
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--strict', dest='strict', action='store_true', default=True,
                     help='Pass fail_on_first_error=True to Stage A/D (diagnostic; disables bounded recovery/retry).')
parser.add_argument('--no-strict', dest='strict', action='store_false',
                     help='Use true production defaults: fail_on_first_error is not set, so Stage A recovery and the Stage D 2-attempt retry behave exactly as app.py exercises them.')
args=parser.parse_args()
OUT=args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
 raise ValueError('Commissioning artifacts must remain outside the repository')
OUT.mkdir(parents=True, exist_ok=False)
os.environ['CHECKPOINT_MODE']='required'
os.environ['CHECKPOINT_ROOT']=str(OUT/'checkpoints')
records=[]
def save(name, value):
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')

from config import get_api_key
from stage_d_checkpoints import pack_preprocessed
from extractor import extract_document_with_metadata, extract_document_facts, normalize_package_facts, reconcile_package_facts, synthesize_bid_brief
from procurement_evidence_adapter import adapt_procurement_corpus
from evidence_publication import publish_evidence, validate_evidence_publication
from canonical_opportunity_publication import publish_canonical_opportunity
CORPUS=ROOT/'evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus'
MANIFEST=json.loads((ROOT/'evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json').read_text(encoding='utf-8'))
ACQ=json.loads((ROOT/'evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json').read_text(encoding='utf-8'))
SOURCE={'source_id':'source:bank-of-canada-procurement','publisher_name':'Bank of Canada','base_url':'https://www.bankofcanada.ca/'}
current='initialization'; started=time.monotonic()
save('run.json', {'run':'05','mode':'fresh production calls','reuse':False,'strict':args.strict})
def emit(boundary,status,t0,objects=0,snapshots=0,references=0,**extra):
 record={'boundary':boundary,'status':status,'elapsed_seconds':round(time.monotonic()-t0,3),'objects_created':objects,'snapshots_created':snapshots,'governed_references_created':references,**extra}
 records.append(record)
 save('boundaries.json',records)
 print(json.dumps(record,sort_keys=True),flush=True)
def refs(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k=='source_refs' and isinstance(x,list): yield from x
   yield from refs(x)
 elif isinstance(v,list):
  for x in v: yield from refs(x)
try:
 key=get_api_key()
 if not key: raise RuntimeError('ANTHROPIC_API_KEY is unavailable')
 current='Procurement Corpus'; t=time.monotonic()
 paths=sorted(p for p in CORPUS.rglob('*') if p.is_file())
 package=[(p.relative_to(CORPUS).as_posix(),p.read_bytes()) for p in paths]
 if len(package)!=16 or {n for n,_ in package}!={x['path'] for x in MANIFEST['files']}: raise RuntimeError('corrected corpus identity mismatch')
 save('source-manifest.json',MANIFEST)
 emit(current,'PASS',t,objects=len(package),validation='manifest membership and file count')
 current='Procurement Evidence Adapter'; t=time.monotonic()
 metadata={'files':[],'doc_metadata':{},'doc_texts':{}}
 for name,payload in package:
  text,meta=extract_document_with_metadata(payload,name)
  metadata['files'].append(name); metadata['doc_metadata'][name]=meta; metadata['doc_texts'][name]=text
 save('preprocessed-inputs.json',pack_preprocessed(metadata))
 evidence_snapshot=adapt_procurement_corpus(package,metadata,MANIFEST,ACQ,SOURCE)
 emit(current,'PASS',t,objects=len(evidence_snapshot.objects),snapshots=1,validation='adapter construction and Evidence snapshot validation',snapshot_id=evidence_snapshot.snapshot_id)
 current='Evidence Publication'; t=time.monotonic()
 evidence_publication=validate_evidence_publication(publish_evidence(evidence_snapshot))
 emit(current,'PASS',t,objects=len(evidence_publication.snapshot.objects),snapshots=1,references=len(evidence_publication.references),validation='publication manifest, identities, digests, snapshot, references',snapshot_id=evidence_publication.snapshot.snapshot_id)
 current='Stage A'; t=time.monotonic(); document_facts=[]
 for i,(name,_) in enumerate(package,1):
  print(json.dumps({'progress':'Stage A','document':i,'of':len(package),'name':name}),flush=True)
  document_facts.append(extract_document_facts(metadata['doc_texts'][name],name,key,fail_on_first_error=args.strict))
  save(f'stage-a-document-{i:02d}.json',document_facts[-1])
  save('stage-a-document-facts.json',document_facts)
 emit(current,'PASS',t,objects=len(document_facts),references=0,source_reference_occurrences=sum(1 for x in refs(document_facts)),validation='production response parsing and source-reference validation')
 current='Stage B'; t=time.monotonic()
 normalized=normalize_package_facts(document_facts,metadata)
 save('stage-b-normalized-facts.json',normalized)
 count=sum(len(v) for v in normalized.values() if isinstance(v,list))
 emit(current,'PASS',t,objects=count,references=0,source_reference_occurrences=sum(1 for x in refs(normalized)),validation='production normalization and canonical construction')
 current='Stage C'; t=time.monotonic()
 conflicts=reconcile_package_facts(normalized,metadata['files'])
 save('stage-c-conflicts.json',conflicts)
 save('stage-c-normalized-facts.json',normalized)
 emit(current,'PASS',t,objects=len(conflicts),references=0,source_reference_occurrences=sum(1 for x in refs(conflicts)),validation='production reconciliation and conflict validation')
 current='Stage D'; t=time.monotonic()
 synthesis=synthesize_bid_brief(normalized,conflicts,key,fail_on_first_error=args.strict)
 save('stage-d-synthesis.json',synthesis)
 emit(current,'PASS',t,objects=1,references=len(synthesis.get('_citation_ledger',[])) if isinstance(synthesis,dict) else 0,validation='projection, provider schema, pointer registry, citations, authority reapplication, assembly')
 from extractor import _assemble_procurement_result
 current='Procurement Assembly'; t=time.monotonic()
 result=_assemble_procurement_result(synthesis,normalized,conflicts)
 save('procurement-result.json',result)
 emit(current,'PASS',t,objects=1,validation='production authoritative assembly')
 current='Canonical Opportunity'; t=time.monotonic()
 canonical=normalized.get('_canonical_opportunity')
 if not isinstance(canonical,dict) or not canonical.get('input_digest'): raise RuntimeError('canonical opportunity absent')
 emit(current,'PASS',t,objects=len(canonical.get('observations',[]))+len(canonical.get('conflicts',[]))+len(canonical.get('resolved',{})),validation='canonical state present with input digest',input_digest=canonical['input_digest'])
 current='Canonical Opportunity Publication'; t=time.monotonic()
 # No production publisher of observation bindings exists in this checkout.
 # An empty declaration set is submitted unchanged; publication must fail closed.
 publication=publish_canonical_opportunity(canonical,opportunity_id='opportunity:bank-of-canada-rfp-2026-026',observation_bindings=())
 emit(current,'PASS',t,objects=len(publication.snapshot.objects),snapshots=1,references=len(publication.references),validation='publication validation')
except Exception as exc:
 emit(current,'FAIL',locals().get('t',started),exception_type=type(exc).__name__,exception=str(exc),traceback=traceback.format_exc())
 save('completion.json',{'status':'FAIL','boundary':current,'elapsed_seconds':round(time.monotonic()-started,3)})
 sys.exit(1)
