"""Versioned trail edges, closure windows and route reachability."""
import json
from collections import deque
from .sources import record
from .store import rows


def ingest(db,events):
    made=0
    with db:
        for e in events:
            if e['op']=='segment':
                if e['direction'] not in ('forward','both'):raise ValueError('invalid trail direction')
                if record(db,e,'segment',e['segment_id']):
                    db.execute('INSERT INTO segment_revision VALUES (?,?,?,?,?,?,?)',
                               (e['event_id'],e['segment_id'],e['from_node'],e['to_node'],e['version'],e['direction'],e['status']));made+=1
            elif e['op']=='closure':
                if e['starts_at']>=e['ends_at']:raise ValueError('closure window is empty')
                if record(db,e,'closure',e['segment_id']):
                    db.execute('INSERT INTO closure_notice VALUES (?,?,?,?,?)',(e['event_id'],e['segment_id'],e['starts_at'],e['ends_at'],e['decision']));made+=1
            else:raise ValueError('unknown segment op '+e['op'])
    return {'imported':made,'segments':len(rows(db,'SELECT DISTINCT segment_id FROM segment_revision'))}


def edges(db,as_of,restricted=()):
    records=rows(db,'SELECT s.*,e.event_time FROM segment_revision s JOIN evidence e USING(event_id) WHERE e.event_time<=? ORDER BY s.version DESC,e.event_time DESC,s.event_id DESC',(as_of,))
    by_segment={}
    for r in records:by_segment.setdefault(r['segment_id'],[]).append(r)
    restricted=set(restricted);available=[];blocked=[]
    for sid,versions in sorted(by_segment.items()):
        top=[x for x in versions if x['version']==versions[0]['version']]
        if len({(x['from_node'],x['to_node'],x['direction'],x['status']) for x in top})>1:
            blocked.append({'segment_id':sid,'reason':'same_version_conflict'});continue
        edge=top[0]
        if edge['status']!='open':blocked.append({'segment_id':sid,'reason':'retired'});continue
        notices=rows(db,'SELECT c.*,e.event_time FROM closure_notice c JOIN evidence e USING(event_id) WHERE c.segment_id=? AND c.starts_at<=? AND c.ends_at>? AND e.event_time<=? ORDER BY e.event_time DESC,c.event_id DESC',(sid,as_of,as_of,as_of))
        if notices and notices[0]['decision']=='close':blocked.append({'segment_id':sid,'reason':'public_closure'});continue
        if sid in restricted:blocked.append({'segment_id':sid,'reason':'unresolved_hazard'});continue
        available.append(edge)
    return {'available':available,'blocked':blocked}


def route(edges,origin,destination):
    if origin==destination:return []
    graph={}
    for e in edges:
        graph.setdefault(e['from_node'],[]).append((e['to_node'],e['segment_id']))
        if e['direction']=='both':graph.setdefault(e['to_node'],[]).append((e['from_node'],e['segment_id']))
    queue=deque([(origin,[])]);seen={origin}
    while queue:
        node,path=queue.popleft()
        for nxt,sid in sorted(graph.get(node,[])):
            if nxt==destination:return path+[sid]
            if nxt not in seen:seen.add(nxt);queue.append((nxt,path+[sid]))
    return None
