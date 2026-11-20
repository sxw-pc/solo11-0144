"""Build a basic offline map manifest from current route edges."""
import json
from . import segment,hazard
from .store import rows


def build(db, as_of):
    restricted = {h['segment_id'] for h in hazard.decisions(db,as_of) if h['decision']=='restricted'}
    network = segment.edges(db,as_of,restricted)
    manifest = {'as_of':as_of,'segments':[e['segment_id'] for e in network['available']]}
    db.execute('INSERT INTO map_bundle(as_of,manifest) VALUES (?,?)', (as_of,json.dumps(manifest,sort_keys=True)))
    return manifest
