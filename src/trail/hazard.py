"""Hazard cases, remediation evidence and independent field review."""
from .sources import record
from .store import rows


def ingest(db,events):
    made=0
    with db:
        for e in events:
            op=e['op']
            if op=='hazard':
                if record(db,e,'hazard',e['case_id']):
                    db.execute('INSERT INTO hazard_case VALUES (?,?,?,?,?,?)',(e['event_id'],e['case_id'],e['segment_id'],e['severity'],e['status'],e['reporter']));made+=1
            elif op=='remediation':
                if record(db,e,'remediation',e['case_id']):
                    db.execute('INSERT INTO remediation_order VALUES (?,?,?,?,?)',(e['event_id'],e['case_id'],e['worker'],e['photo_hash'],e['status']));made+=1
            elif op=='review':
                if record(db,e,'review',e['case_id']):
                    db.execute('INSERT INTO patrol_witness VALUES (?,?,?,?,?)',(e['event_id'],e['case_id'],e['reviewer'],e['photo_hash'],e['decision']));made+=1
            else:raise ValueError('unknown hazard op '+op)
    return {'imported':made,'cases':len(rows(db,'SELECT DISTINCT case_id FROM hazard_case'))}


def decisions(db,as_of):
    cases=rows(db,'SELECT h.*,e.event_time FROM hazard_case h JOIN evidence e USING(event_id) WHERE e.event_time<=? ORDER BY e.event_time DESC,h.event_id DESC',(as_of,))
    latest={}
    for h in cases:latest.setdefault(h['case_id'],h)
    out=[]
    for h in latest.values():
        work=db.execute('SELECT w.*,e.event_time FROM remediation_order w JOIN evidence e USING(event_id) WHERE w.case_id=? AND e.event_time<=? ORDER BY e.event_time DESC,w.event_id DESC LIMIT 1',(h['case_id'],as_of)).fetchone()
        review=db.execute('SELECT r.*,e.event_time FROM patrol_witness r JOIN evidence e USING(event_id) WHERE r.case_id=? AND e.event_time<=? ORDER BY e.event_time DESC,r.event_id DESC LIMIT 1',(h['case_id'],as_of)).fetchone()
        if h['status']=='cancelled':decision='cancelled';reason='hazard_retracted'
        elif not work or work['status']!='done' or not work['photo_hash']:decision='restricted';reason='remediation_incomplete'
        elif not review or review['decision']!='clear':decision='restricted';reason='no_clear_review'
        elif review['reviewer']==work['worker']:decision='restricted';reason='self_review'
        elif review['photo_hash']!=work['photo_hash']:decision='restricted';reason='photo_mismatch'
        else:decision='cleared';reason='independent_field_review'
        out.append({'case_id':h['case_id'],'segment_id':h['segment_id'],'severity':h['severity'],'decision':decision,'reason':reason})
    return sorted(out,key=lambda x:x['case_id'])
