import argparse,json
from pathlib import Path
from . import segment,hazard,shuttle,report,mapbundle
from .store import connect

def main(argv=None):
    p=argparse.ArgumentParser(prog='trail');sp=p.add_subparsers(dest='command',required=True)
    for name in ('init','import-segment','import-patrol','import-shuttle','report','build-map','hit-map','demo'):
        q=sp.add_parser(name);q.add_argument('--db',default='data/demo.sqlite')
        if name.startswith('import-'):q.add_argument('--input',required=True)
        if name in ('report','build-map'):q.add_argument('--as-of',required=True)
        if name=='build-map':
            q.add_argument('--contract',choices=mapbundle.CONTRACTS,default=mapbundle.SURVEY)
            q.add_argument('--levels',help='JSON file with per-level tolerance/max_points/min_gap')
        if name=='hit-map':
            q.add_argument('--as-of')
            q.add_argument('--x',type=float,required=True);q.add_argument('--y',type=float,required=True)
            q.add_argument('--radius',type=float);q.add_argument('--level')
    a=p.parse_args(argv);db=connect(a.db)
    try:
        if a.command=='init':result={'initialized':True,'db':a.db}
        elif a.command.startswith('import-'):
            data=json.loads(Path(a.input).read_text(encoding='utf-8'))
            result={'import-segment':segment,'import-patrol':hazard,'import-shuttle':shuttle}[a.command].ingest(db,data)
        elif a.command=='report':result=report.decide(db,a.as_of)
        elif a.command=='build-map':
            levels=json.loads(Path(a.levels).read_text(encoding='utf-8')) if a.levels else None
            manifest=mapbundle.build(db,a.as_of,contract=a.contract,levels=levels)
            result=mapbundle.stable_summary(manifest)
        elif a.command=='hit-map':
            manifest=mapbundle.latest_manifest(db,a.as_of)
            if manifest is None:raise KeyError('no map bundle found')
            result={'hits':mapbundle.hit_query(manifest,a.x,a.y,radius=a.radius,level=a.level)}
        else:
            root=Path(__file__).resolve().parents[2]
            for name,mod in [('segment_good.json',segment),('patrol_clear.json',hazard),('shuttle_good.json',shuttle)]:
                mod.ingest(db,json.loads((root/'fixtures'/'trail'/name).read_text(encoding='utf-8')))
            result=report.decide(db,'2026-11-17T10:00:00Z')
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except (ValueError,KeyError) as e:print(json.dumps({'error':str(e)},ensure_ascii=False));return 2
    finally:db.close()

if __name__=='__main__':raise SystemExit(main())
