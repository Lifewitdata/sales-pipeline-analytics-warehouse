"""Export tested warehouse marts and author a portable Power BI project.
Run from any directory after dbt build. No Power BI engine is invoked here.
"""
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
BASE = 'https://developer.microsoft.com/json-schemas/fabric/item/'

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')

MEASURES = [
 ('Opportunities', 'COUNTROWS(fct_opportunity)', '#,0'),
 ('Won Deals', 'CALCULATE([Opportunities], KEEPFILTERS(fct_opportunity[deal_stage] = "Won"))', '#,0'),
 ('Closed Deals', 'CALCULATE([Opportunities], KEEPFILTERS(fct_opportunity[deal_stage] IN {"Won", "Lost"}))', '#,0'),
 ('Won Revenue', 'CALCULATE(SUM(fct_opportunity[revenue]), KEEPFILTERS(fct_opportunity[deal_stage] = "Won"))', '$#,0;($#,0);$0'),
 ('Win Rate', 'DIVIDE([Won Deals], [Closed Deals])', '0.0%'),
 ('Average Won Deal', 'DIVIDE([Won Revenue], [Won Deals])', '$#,0.00'),
 ('Average Won Sales Cycle Days', 'CALCULATE(AVERAGE(fct_opportunity[sales_cycle_days]), KEEPFILTERS(fct_opportunity[deal_stage] = "Won"))', '0.0'),
 ('Open Opportunities', 'CALCULATE([Opportunities], REMOVEFILTERS(dim_date), KEEPFILTERS(fct_opportunity[deal_stage] IN {"Prospecting", "Engaging"}))', '#,0'),
 ('Average Open Age Days', 'CALCULATE(AVERAGE(fct_opportunity[days_open_at_snapshot]), REMOVEFILTERS(dim_date), KEEPFILTERS(fct_opportunity[deal_stage] IN {"Prospecting", "Engaging"}))', '0.0'),
 ('Missing Account Opportunities', 'CALCULATE([Opportunities], KEEPFILTERS(fct_opportunity[is_account_missing] = TRUE()))', '#,0'),
 ('Missing Account Rate', 'DIVIDE([Missing Account Opportunities], [Opportunities])', '0.0%'),
 ('Revenue Previous Month', 'CALCULATE([Won Revenue], DATEADD(dim_date[date_day], -1, MONTH))', '$#,0'),
 ('Revenue MoM Change', 'VAR PreviousRevenue = [Revenue Previous Month] RETURN IF(NOT ISBLANK(PreviousRevenue), DIVIDE([Won Revenue] - PreviousRevenue, PreviousRevenue))', '0.0%'),
]

def build():
    con = duckdb.connect(str(REPO/'warehouse/crm_warehouse.duckdb'), read_only=True)
    specs = {}
    tables = []
    for name in ['fct_opportunity','dim_sales_agent','dim_product','dim_account','dim_date']:
        info = con.execute(f'DESCRIBE marts.{name}').fetchall()
        info = [x for x in info if x[0] != '_loaded_at']
        columns = ', '.join('"'+x[0]+'"' for x in info)
        dest = ROOT/'data'/f'{name}.csv'; dest.parent.mkdir(exist_ok=True)
        con.execute(f"COPY (SELECT {columns} FROM marts.{name} ORDER BY 1) TO '{dest.as_posix()}' (HEADER, DELIMITER ',')")
        cols=[]; casts=[]
        for col,typ,*_ in info:
            if typ == 'BOOLEAN': dt,mt='boolean','type logical'
            elif typ.startswith(('DATE','TIMESTAMP')): dt,mt='dateTime','type date'
            elif any(t in typ for t in ['INT','DECIMAL','DOUBLE','FLOAT']):
                dt,mt=('double','type number') if any(t in typ for t in ['DECIMAL','DOUBLE','FLOAT']) else ('int64','Int64.Type')
            else: dt,mt='string','type text'
            cols.append({'name':col,'dataType':dt,'sourceColumn':col,'summarizeBy':'none'})
            casts.append('{"'+col+'", '+mt+'}')
        m='let\n Source = Csv.Document(File.Contents(DataFolder & "/'+name+'.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n Nulls = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),\n Typed = Table.TransformColumnTypes(Nulls, {'+', '.join(casts)+'}, "en-US")\nin Typed'
        t={'name':name,'columns':cols,'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':m.splitlines()}}]}
        if name=='fct_opportunity': t['measures']=[{'name':n,'expression':e,'formatString':f,'displayFolder':'Sales KPIs'} for n,e,f in MEASURES]
        tables.append(t);specs[name]={c['name'] for c in cols}
    relations=[]
    for dim,key in [('dim_sales_agent','sales_agent_key'),('dim_product','product_key'),('dim_account','account_key'),('dim_date','date_day')]:
        relations.append({'name':'fact_to_'+dim,'fromTable':'fct_opportunity','fromColumn':'close_date' if dim=='dim_date' else key,'toTable':dim,'toColumn':key,'crossFilteringBehavior':'oneDirection','fromCardinality':'many','toCardinality':'one','isActive':True})
    model={'name':'SalesPipeline','compatibilityLevel':1600,'model':{'culture':'en-US','defaultPowerBIDataSourceVersion':'powerBI_V3','expressions':[{'name':'DataFolder','kind':'m','expression':'"C:/REPLACE_WITH_REPO/powerbi/data" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}],'tables':tables,'relationships':relations}}
    write(ROOT/'SalesPipeline.SemanticModel/model.bim',model)
    write(ROOT/'SalesPipeline.SemanticModel/definition.pbism',{'version':'1.0','settings':{}})
    write(ROOT/'SalesPipeline.pbip',{'version':'1.0','artifacts':[{'report':{'path':'SalesPipeline.Report'}}],'settings':{'enableAutoRecovery':True}})
    report=ROOT/'SalesPipeline.Report'
    write(report/'definition.pbir',{'$schema':BASE+'report/definitionProperties/2.0.0/schema.json','version':'4.0','datasetReference':{'byPath':{'path':'../SalesPipeline.SemanticModel'}}})
    write(report/'definition/report.json',{'$schema':BASE+'report/definition/report/1.0.0/schema.json','layoutOptimization':'None','themeCollection':{}})
    pages=['executive','pipeline','quality']
    write(report/'definition/pages/pages.json',{'$schema':BASE+'report/definition/pagesMetadata/1.0.0/schema.json','pageOrder':pages,'activePageName':pages[0]})
    measures={n for n,_,_ in MEASURES}
    def proj(table,col,measure=False):
        assert col in (measures if measure else specs[table])
        return {'field':{('Measure' if measure else 'Column'):{'Expression':{'SourceRef':{'Entity':table}},'Property':col}},'queryRef':table+'.'+col,'nativeQueryRef':col}
    def visual(page,n,typ,x,y,w,h,roles,title):
        literal=lambda value: {'expr': {'Literal': {'Value': value}}}
        v={'$schema':BASE+'report/definition/visualContainer/2.0.0/schema.json',
           'name':page+'_'+str(n),
           'position':{'x':x,'y':y,'z':n,'width':w,'height':h,'tabOrder':n},
           'visual':{'visualType':typ,
                     'query':{'queryState':{role:{'projections':ps} for role,ps in roles.items()}},
                     'visualContainerObjects':{'title':[{'properties':{'show':literal('true'),'text':literal("'"+title+"'")}}]}}}
        write(report/f'definition/pages/{page}/visuals/{page}_{n}/visual.json',v)
    mp=lambda n:proj('fct_opportunity',n,True)
    for page,title in zip(pages,['Sales performance | Closed-deal date','Pipeline snapshot | All close dates','Data quality | Source coverage']):
        write(report/f'definition/pages/{page}/page.json',{'$schema':BASE+'report/definition/page/1.0.0/schema.json','name':page,'displayName':title,'displayOption':'FitToPage','height':720,'width':1280})
        visual(page,0,'slicer',20,10,280,65,{'Values':[proj('dim_sales_agent','regional_office')]},'Office')
        visual(page,1,'slicer',320,10,280,65,{'Values':[proj('dim_product','product_series')]},'Product series')
    visual('executive',2,'slicer',620,10,620,65,{'Values':[proj('dim_date','month_start')]},'Close month (closed-deal metrics)')
    for i,n in enumerate(['Won Revenue','Win Rate','Average Won Deal','Average Won Sales Cycle Days']):visual('executive',3+i,'card',20+310*i,90,290,110,{'Values':[mp(n)]},n)
    visual('executive',7,'lineChart',20,220,760,260,{'Category':[proj('dim_date','month_start')],'Y':[mp('Won Revenue')]},'Won revenue by close month')
    visual('executive',8,'clusteredBarChart',800,220,440,260,{'Category':[proj('dim_sales_agent','regional_office')],'Y':[mp('Won Revenue')]},'Won revenue by office')
    visual('executive',9,'tableEx',20,500,1220,200,{'Values':[proj('dim_sales_agent','agent_name'),mp('Won Revenue'),mp('Win Rate'),mp('Average Won Sales Cycle Days')]},'Sales representative performance')
    for i,n in enumerate(['Open Opportunities','Average Open Age Days','Opportunities']):visual('pipeline',2+i,'card',20+410*i,90,390,110,{'Values':[mp(n)]},n)
    visual('pipeline',5,'clusteredBarChart',20,220,570,260,{'Category':[proj('fct_opportunity','deal_stage')],'Y':[mp('Opportunities')]},'Current stage counts — not sequential conversion')
    visual('pipeline',6,'clusteredBarChart',620,220,620,260,{'Category':[proj('dim_sales_agent','regional_office')],'Y':[mp('Open Opportunities')]},'Open opportunities by office')
    visual('pipeline',7,'tableEx',20,500,1220,200,{'Values':[proj('dim_sales_agent','agent_name'),mp('Open Opportunities'),mp('Average Open Age Days')]},'Open age at source snapshot; prospecting dates may be blank')
    for i,n in enumerate(['Opportunities','Missing Account Opportunities','Missing Account Rate']):visual('quality',2+i,'card',20+410*i,90,390,110,{'Values':[mp(n)]},n)
    visual('quality',5,'clusteredBarChart',20,220,590,460,{'Category':[proj('dim_sales_agent','regional_office')],'Y':[mp('Missing Account Opportunities')]},'Missing account attribution by office')
    visual('quality',6,'tableEx',640,220,600,460,{'Values':[proj('fct_opportunity','deal_stage'),mp('Opportunities'),mp('Missing Account Opportunities'),mp('Missing Account Rate')]},'Coverage by stage — null accounts retained')
    query='EVALUATE ROW(\n'+',\n'.join('    "'+n+'", ['+n+']' for n,_,_ in MEASURES[:11])+'\n)\n'
    qpath=ROOT/'SalesPipeline.SemanticModel/DAXQueries/Acceptance.dax';qpath.parent.mkdir(exist_ok=True);qpath.write_text(query)
    (ROOT/'measures.dax').write_text('// Reference copy; measures are already installed in model.bim\n\n'+'\n\n'.join(n+' =\n'+e for n,e,_ in MEASURES)+'\n')
    sql="SELECT count(*) opportunities, sum(revenue) won_revenue, count(*) FILTER (WHERE is_won) won_deals, count(*) FILTER (WHERE is_closed) closed_deals, count(*) FILTER (WHERE is_open) open_opportunities, avg(sales_cycle_days) FILTER (WHERE is_won) average_won_sales_cycle_days, count(*) FILTER (WHERE is_account_missing) missing_account_opportunities FROM marts.fct_opportunity"
    cur=con.execute(sql);expected=dict(zip([d[0] for d in cur.description],cur.fetchone()));expected['win_rate']=expected['won_deals']/expected['closed_deals'];expected['average_won_deal']=expected['won_revenue']/expected['won_deals']
    assert expected['opportunities']==8800 and expected['won_revenue']==10005534 and expected['open_opportunities']==2089
    write(ROOT/'expected_kpis.json',{'validation':'SQL baseline; DAX engine and Desktop refresh not executed','values':expected})
    print(json.dumps(expected,indent=2))

if __name__=='__main__':build()
