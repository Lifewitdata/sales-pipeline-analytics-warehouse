"""Validate PBIR schemas, model references, keys and SQL-derived KPI baselines.
Requires jsonschema. Schema validation downloads Microsoft's official schemas.
Does not execute DAX, Power Query, or render Power BI visuals.
"""
import csv,json,urllib.request
from pathlib import Path
from functools import lru_cache
from jsonschema import Draft7Validator, RefResolver
ROOT=Path(__file__).resolve().parent
@lru_cache(None)
def fetch(url):
    # Some Microsoft embedded schemas identify themselves with .embedded
    # while their published URL uses -embedded. Resolve that URL alias.
    url=url.replace("schema.embedded.json", "schema-embedded.json")
    with urllib.request.urlopen(url,timeout=30) as r:return json.load(r)

def validate():
    paths=list((ROOT/'SalesPipeline.Report').rglob('*.json'))+[ROOT/'SalesPipeline.Report/definition.pbir']
    for p in paths:
        obj=json.loads(p.read_text());url=obj.get('$schema')
        if url:
            schema=fetch(url)
            Draft7Validator(schema,resolver=RefResolver(url,schema,handlers={'https':fetch})).validate(obj)
    model=json.loads((ROOT/'SalesPipeline.SemanticModel/model.bim').read_text())['model']
    rows={p.stem:list(csv.DictReader(p.open())) for p in (ROOT/'data').glob('*.csv')}
    for rel in model['relationships']:
        keys=[r[rel['toColumn']] for r in rows[rel['toTable']]]
        assert len(keys)==len(set(keys)) and all(keys),rel['name']
        assert all(not r[rel['fromColumn']] or r[rel['fromColumn']] in set(keys) for r in rows[rel['fromTable']]),rel['name']
    f=rows['fct_opportunity'];won=[r for r in f if r['deal_stage']=='Won'];closed=[r for r in f if r['deal_stage'] in ('Won','Lost')]
    expected=json.loads((ROOT/'expected_kpis.json').read_text())['values']
    assert len(f)==expected['opportunities']
    assert sum(float(r['revenue']) for r in won)==expected['won_revenue']
    assert abs(len(won)/len(closed)-expected['win_rate'])<1e-12
    # Reconcile segment revenue to overall; verify open records have no close date.
    agents={r['sales_agent_key']:r['regional_office'] for r in rows['dim_sales_agent']}
    offices={v for v in agents.values()}
    assert sum(sum(float(r['revenue']) for r in won if agents[r['sales_agent_key']]==o) for o in offices)==expected['won_revenue']
    assert all(not r['close_date'] for r in f if r['deal_stage'] in ('Engaging','Prospecting'))
    print(f'PASS: {len(paths)} PBIR documents; relationship keys; overall and office KPI reconciliation. DAX/Desktop execution pending.')
if __name__=='__main__':validate()
