import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import trail
from trail import segment,hazard,shuttle,report
from trail.store import connect
print('imported module:',trail.__file__)
assert Path(trail.__file__).resolve().is_relative_to(ROOT)

def fixture(name):return json.loads((ROOT/'fixtures'/'trail'/name).read_text(encoding='utf-8'))

def closure(event_id='close-s2',time='2026-11-17T09:40:00Z'):
    return {'event_id':event_id,'op':'closure','segment_id':'s2','starts_at':'2026-11-17T09:30:00Z','ends_at':'2026-11-17T12:00:00Z','decision':'close','event_time':time}

class TrailCases(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def good(self):
        segment.ingest(self.db,fixture('segment_good.json'))
        hazard.ingest(self.db,fixture('patrol_clear.json'))
        shuttle.ingest(self.db,fixture('shuttle_good.json'))

    def test_three_ledgers_open_walkable_route(self):
        self.good();r=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual((r['hazards'][0]['decision'],r['access'][0]['decision'],r['access'][0]['route']),('cleared','open',['s1','s2']))

    def test_stale_segment_revision_does_not_retire_new_edge(self):
        self.good();segment.ingest(self.db,fixture('segment_stale.json'))
        self.assertEqual(report.decide(self.db,'2026-11-17T10:00:00Z')['access'][0]['decision'],'open')

    def test_closure_reassigns_real_demand_to_shuttle(self):
        self.good();segment.ingest(self.db,[closure()])
        r=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual((r['access'][0]['decision'],r['transfers']['d1']['covered']),('shuttle_only',3))
        self.assertEqual(self.db.execute("SELECT seats FROM seat_reservation WHERE demand_id='d1'").fetchone()[0],3)

    def test_unresolved_hazard_overrides_open_notice(self):
        self.good();hazard.ingest(self.db,fixture('patrol_conflict.json'))
        r=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual((r['hazards'][0]['reason'],r['access'][0]['decision']),('self_review','shuttle_only'))

    def test_full_or_cancelled_shuttle_with_closure_revokes_access(self):
        self.good();segment.ingest(self.db,[closure()]);shuttle.ingest(self.db,fixture('shuttle_full.json'))
        r=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual((r['access'][0]['decision'],r['access'][0]['covered'],r['access'][0]['uncovered']),('closed',2,1))

    def test_late_cancellation_preserves_historical_access(self):
        self.good();segment.ingest(self.db,[closure()]);shuttle.ingest(self.db,fixture('shuttle_full.json'))
        earlier=report.decide(self.db,'2026-11-17T09:50:00Z')
        current=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual((earlier['access'][0]['decision'],current['access'][0]['decision']),('shuttle_only','closed'))

    def test_wrong_station_trip_cannot_cover_demand(self):
        self.good();segment.ingest(self.db,[closure()])
        wrong=dict(fixture('shuttle_full.json')[0],event_id='trip-wrong',status='active',from_node='B')
        cancel=dict(fixture('shuttle_full.json')[0],event_id='cancel-current')
        shuttle.ingest(self.db,[cancel,wrong])
        self.assertEqual(report.decide(self.db,'2026-11-17T10:00:00Z')['access'][0]['decision'],'closed')

    def test_arrival_after_deadline_does_not_count(self):
        self.good();segment.ingest(self.db,[closure()])
        demand=dict(fixture('shuttle_good.json')[1],event_id='demand-short',latest_exit='2026-11-17T10:25:00Z',event_time='2026-11-17T09:45:00Z')
        shuttle.ingest(self.db,[demand])
        self.assertEqual(report.decide(self.db,'2026-11-17T10:00:00Z')['access'][0]['decision'],'closed')

    def test_capacity_competition_preserves_uncovered_people(self):
        self.good();segment.ingest(self.db,[closure()])
        other=dict(fixture('shuttle_good.json')[1],event_id='need-2',demand_id='d2',people=2,event_time='2026-11-17T09:50:00Z')
        shuttle.ingest(self.db,[other])
        r=report.decide(self.db,'2026-11-17T10:00:00Z')
        self.assertEqual(sum(x['covered'] for x in r['access']),3)
        self.assertEqual(sum(x['uncovered'] for x in r['access']),2)

    def test_duplicate_id_with_changed_payload_rolls_back(self):
        self.good();e=dict(fixture('shuttle_good.json')[0],seats=100)
        with self.assertRaises(ValueError):shuttle.ingest(self.db,[dict(e,event_id='new-trip'),e])
        self.assertIsNone(self.db.execute("SELECT event_id FROM evidence WHERE event_id='new-trip'").fetchone())

    def test_self_review_remains_restricted_without_photo_change(self):
        segment.ingest(self.db,fixture('segment_good.json'))
        hazard.ingest(self.db,fixture('patrol_clear.json')[:2]+fixture('patrol_conflict.json'))
        self.assertEqual(hazard.decisions(self.db,'2026-11-17T10:00:00Z')[0]['decision'],'restricted')

if __name__=='__main__':unittest.main()
