"""Combine independent route, field safety and shuttle decisions."""
import json
from . import segment,hazard,shuttle
from .store import rows


def decide(db,as_of):
    with db:
        hazards=hazard.decisions(db,as_of)
        restricted={h['segment_id'] for h in hazards if h['decision']=='restricted'}
        network=segment.edges(db,as_of,restricted)
        demand=shuttle.current_demands(db,as_of)
        walking={d['demand_id']:segment.route(network['available'],d['from_node'],d['to_node']) for d in demand}
        needs=[d for d in demand if walking[d['demand_id']] is None]
        transfers=shuttle.allocate(db,as_of,needs)
        results=[]
        for d in demand:
            path=walking[d['demand_id']]
            if path is not None:decision='open';reason='walkable_route';covered=d['people'];uncovered=0
            else:
                transfer=transfers[d['demand_id']];covered=transfer['covered'];uncovered=transfer['uncovered']
                decision='shuttle_only' if uncovered==0 else 'closed';reason=transfer['reason']
            outcome={'demand_id':d['demand_id'],'decision':decision,'reason':reason,'people':d['people'],'covered':covered,'uncovered':uncovered,'route':path,'latest_exit':d['latest_exit']}
            db.execute('INSERT INTO access_receipt(demand_id,as_of,decision,reason,evidence) VALUES (?,?,?,?,?)',(d['demand_id'],as_of,decision,reason,json.dumps(outcome,sort_keys=True)))
            results.append(outcome)
        db.execute('INSERT INTO network_release VALUES (?,?,?,?) ON CONFLICT(as_of) DO UPDATE SET edges_json=excluded.edges_json,decision=excluded.decision,reason=excluded.reason',
                   (as_of,json.dumps([e['segment_id'] for e in network['available']]),'available' if network['available'] else 'closed','hazard_and_notice_applied'))
        return {'as_of':as_of,'network':network,'hazards':hazards,'transfers':transfers,'access':results}
