from trail import segment,mapbundle
from trail.store import connect


def test_map_bundle(tmp_path):
    db=connect(tmp_path/'map.sqlite')
    event={'event_id':'s1','event_time':'2026-01-01T08:00:00','op':'segment','segment_id':'S1','from_node':'A','to_node':'B','version':1,'direction':'both','status':'open'}
    segment.ingest(db,[event])
    assert mapbundle.build(db,'2026-01-01T09:00:00')['segments']==['S1']
