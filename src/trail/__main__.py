import argparse,json
from pathlib import Path
from . import segment,hazard,shuttle,report
from .store import connect

def main(argv=None):
    p=argparse.ArgumentParser(prog='trail');sp=p.add_subparsers(dest='command',required=True)
    for name in ('init','import-segment','import-patrol','import-shuttle','report','demo'):
        q=sp.add_parser(name);q.add_argument('--db',default='data/demo.sqlite')
        if name.startswith('import-'):q.add_argument('--input',required=True)
        if name=='report':q.add_argument('--as-of',required=True)
    a=p.parse_args(argv);db=connect(a.db)
    try:
        if a.command=='init':result={'initialized':True,'db':a.db}
        elif a.command.startswith('import-'):
            data=json.loads(Path(a.input).read_text(encoding='utf-8'))
            result={'import-segment':segment,'import-patrol':hazard,'import-shuttle':shuttle}[a.command].ingest(db,data)
        elif a.command=='report':result=report.decide(db,a.as_of)
        else:
            root=Path(__file__).resolve().parents[2]
            for name,mod in [('segment_good.json',segment),('patrol_clear.json',hazard),('shuttle_good.json',shuttle)]:
                mod.ingest(db,json.loads((root/'fixtures'/'trail'/name).read_text(encoding='utf-8')))
            result=report.decide(db,'2026-11-17T10:00:00Z')
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except (ValueError,KeyError) as e:print(json.dumps({'error':str(e)},ensure_ascii=False));return 2
    finally:db.close()

if __name__=='__main__':raise SystemExit(main())
