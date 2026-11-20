from trail import segment,mapbundle
from trail.store import connect


def _event(sid,frm,to,shape,event_id=None,direction='both',layer=0):
    return {'event_id':event_id or sid.lower(),'event_time':'2026-01-01T08:00:00','op':'segment',
            'segment_id':sid,'from_node':frm,'to_node':to,'version':1,'direction':direction,
            'status':'open','shape':shape,'layer':layer}


def test_map_bundle(tmp_path):
    db=connect(tmp_path/'map.sqlite')
    segment.ingest(db,[_event('S1','A','B',[[0,0],[1,0],[2,0]])])
    manifest=mapbundle.build(db,'2026-01-01T09:00:00')
    assert manifest['segments']==['S1']
    assert manifest['levels']['full']['decision']=='published'
    assert mapbundle.latest_manifest(db)['map_version']==manifest['map_version']
