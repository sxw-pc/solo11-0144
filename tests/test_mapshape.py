from trail import segment,mapbundle
from trail.store import connect


def test_shape_enters_bundle(tmp_path):
    db=connect(tmp_path/'shape.sqlite')
    e={'event_id':'s1','event_time':'2026-01-01T08:00:00','op':'segment','segment_id':'S1','from_node':'A','to_node':'B','version':1,'direction':'both','status':'open','shape':[[0,0],[1,1],[2,0]]}
    segment.ingest(db,[e])
    bundle=mapbundle.build(db,'2026-01-01T09:00:00')
    assert bundle['shapes']['S1']==[[0,0],[2,0]]
