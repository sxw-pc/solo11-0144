"""Capacity-constrained transfer demand and time-window assignment."""
from .sources import record
from .store import rows


def ingest(db,events):
    made=0
    with db:
        for e in events:
            if e['op']=='trip':
                if e['seats']<0 or e['departs_at']>=e['arrives_at']:raise ValueError('invalid trip')
                if record(db,e,'trip',e['trip_id']):
                    db.execute('INSERT INTO shuttle_trip VALUES (?,?,?,?,?,?,?,?)',(e['event_id'],e['trip_id'],e['from_node'],e['to_node'],e['departs_at'],e['arrives_at'],e['seats'],e['status']));made+=1
            elif e['op']=='demand':
                if e['people']<=0:raise ValueError('demand people must be positive')
                if record(db,e,'demand',e['demand_id']):
                    db.execute('INSERT INTO transfer_demand VALUES (?,?,?,?,?,?)',(e['event_id'],e['demand_id'],e['from_node'],e['to_node'],e['people'],e['latest_exit']));made+=1
            else:raise ValueError('unknown shuttle op '+e['op'])
    return {'imported':made,'demands':len(rows(db,'SELECT DISTINCT demand_id FROM transfer_demand'))}


def current_demands(db,as_of):
    records=rows(db,'SELECT d.*,e.event_time FROM transfer_demand d JOIN evidence e USING(event_id) WHERE e.event_time<=? ORDER BY e.event_time DESC,d.event_id DESC',(as_of,))
    out={}
    for r in records:out.setdefault(r['demand_id'],r)
    return list(out.values())


def current_trips(db,as_of):
    records=rows(db,'SELECT t.*,e.event_time FROM shuttle_trip t JOIN evidence e USING(event_id) WHERE e.event_time<=? ORDER BY e.event_time DESC,t.event_id DESC',(as_of,))
    out={}
    for r in records:out.setdefault(r['trip_id'],r)
    return [r for r in out.values() if r['status']=='active' and r['departs_at']>=as_of]


def allocate(db,as_of,needs):
    trips=current_trips(db,as_of);remaining={t['trip_id']:t['seats'] for t in trips}
    db.execute('DELETE FROM seat_reservation');db.execute('DELETE FROM evacuation_plan')
    out={}
    for d in sorted(needs,key=lambda x:(x['latest_exit'],x['demand_id'])):
        left=d['people'];assigned=[]
        candidates=[t for t in trips if t['from_node']==d['from_node'] and t['to_node']==d['to_node'] and t['arrives_at']<=d['latest_exit']]
        for trip in sorted(candidates,key=lambda x:(x['arrives_at'],x['trip_id'])):
            taken=min(left,remaining[trip['trip_id']])
            if taken:
                db.execute('INSERT INTO seat_reservation VALUES (?,?,?,?)',(d['demand_id'],trip['trip_id'],taken,'reserved'))
                assigned.append({'trip_id':trip['trip_id'],'seats':taken});left-=taken;remaining[trip['trip_id']]-=taken
            if not left:break
        covered=d['people']-left;decision='covered' if left==0 else 'partial' if covered else 'uncovered'
        reason='within_deadline' if left==0 else 'capacity_or_window_shortfall'
        db.execute('INSERT INTO evacuation_plan VALUES (?,?,?,?,?)',(d['demand_id'],covered,left,decision,reason))
        out[d['demand_id']]={'decision':decision,'covered':covered,'uncovered':left,'assigned':assigned,'reason':reason}
    return out
