"""Build a basic offline map manifest from current route edges."""
import json
from . import segment,hazard
from .store import rows


def build(db, as_of):
    restricted = {h['segment_id'] for h in hazard.decisions(db,as_of) if h['decision']=='restricted'}
    network = segment.edges(db,as_of,restricted)
    shapes={}
    for e in network['available']:
        row=db.execute('SELECT coordinates FROM map_shape WHERE event_id=?',(e['event_id'],)).fetchone()
        if row:
            pts=json.loads(row['coordinates'])
            shapes[e['segment_id']]=pts[::2]+([pts[-1]] if pts and pts[-1] not in pts[::2] else [])
    manifest = {'as_of':as_of,'segments':[e['segment_id'] for e in network['available']],'shapes':shapes}
    db.execute('INSERT INTO map_bundle(as_of,manifest) VALUES (?,?)', (as_of,json.dumps(manifest,sort_keys=True)))
    return manifest

