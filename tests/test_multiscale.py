"""Multi-scale map package construction and topology certification.

Acceptance scenarios:
* ridge fake overlap (S1/S2) must not become a transfer;
* a real shared junction J (S3/S4) survives at different input vertex orders;
* a bridge over an under-bridge road crosses in projection but stays split
  by height layer in the hit index;
* one-way edge direction is carried into every level;
* the survey and schematic contracts are adjudicated independently;
* tight size caps are refused with the offending segments named;
* repeated builds produce the same stable summary and map version.
"""
from trail import segment, mapbundle
from trail.store import connect
import pytest

AS_OF = '2026-01-01T09:00:00'
HANDHELD = [{'level': 'handheld', 'tolerance': 1.1, 'max_points': 100, 'min_gap': 0.5}]


def _event(sid, frm, to, shape, event_id=None, direction='both', layer=0):
    return {'event_id': event_id or ('e-' + sid), 'event_time': '2026-01-01T08:00:00',
            'op': 'segment', 'segment_id': sid, 'from_node': frm, 'to_node': to,
            'version': 1, 'direction': direction, 'status': 'open',
            'shape': shape, 'layer': layer}


def _ridge_network(db):
    # Two roads separated by a ridge, no formal junction. Naive thinning
    # flattens both onto the y=0 line — a fake transfer.
    segment.ingest(db, [
        _event('S1', 'A', 'B', [[0, 0], [1, 1], [2, 0]]),
        _event('S2', 'C', 'D', [[0, 0], [1, -1], [2, 0]]),
    ])


def test_ridge_fake_overlap_is_repaired_not_published_as_transfer(tmp_path):
    db = connect(tmp_path / 'ridge.sqlite')
    _ridge_network(db)
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    level = manifest['levels']['handheld']
    assert level['decision'] == 'published'
    bundle = manifest['bundles']['handheld']
    # The ridge peaks are restored so the two shapes never share a screen cell.
    assert bundle['shapes']['S1'][1] == [1.0, 1.0]
    assert bundle['shapes']['S2'][1] == [1.0, -1.0]
    assert level['repair_rounds'] >= 1
    assert level['fake_intersections'] == []
    # A tap on the flattened line position no longer hits both roads at once.
    hits = mapbundle.hit_query(manifest, 1, 0, radius=0.4, level='handheld')
    assert hits == []
    # Each road is still independently hittable and traces back to itself.
    top = mapbundle.hit_query(manifest, 1, 1, radius=0.4, level='handheld')
    assert {h['segment_id'] for h in top} == {'S1'}
    assert top[0]['original_vertex_order'] == [0, 1, 2]


def test_shared_junction_quantizes_to_one_node_across_vertex_orders(tmp_path):
    db = connect(tmp_path / 'junction.sqlite')
    # J is the *last* vertex of S3 but the *first* vertex of S4.
    segment.ingest(db, [
        _event('S3', 'I', 'J', [[0, 0], [1, 0], [2, 1]], event_id='e-s3'),
        _event('S4', 'J', 'K', [[2, 1], [3, 1], [4, 2]], event_id='e-s4'),
    ])
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    bundle = manifest['bundles']['handheld']
    j1 = bundle['shapes']['S3'][-1]
    j2 = bundle['shapes']['S4'][0]
    assert j1 == j2 == [2.0, 1.0]
    junction = next(j for j in bundle['junctions'] if j['node'] == 'J')
    assert set(junction['segments']) == {'S3', 'S4'}
    # Vertex-order traceback is per segment, pointing at the J position in each.
    assert bundle['hit_index']['S3']['original_vertex_order'][-1] == 2
    assert bundle['hit_index']['S4']['original_vertex_order'][0] == 0


def test_bridge_and_under_bridge_keep_separate_layers_and_hits(tmp_path):
    db = connect(tmp_path / 'bridge.sqlite')
    segment.ingest(db, [
        _event('S7', 'P', 'Q', [[0, 0], [5, 0]], event_id='e-s7', layer=2),       # bridge
        _event('S8', 'R', 'T', [[2.5, -2], [2.5, 2]], event_id='e-s8', layer=0),  # under-bridge
    ])
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    level = manifest['levels']['handheld']
    assert level['decision'] == 'published'
    crossing = level['grade_separated_crossings']
    assert len(crossing) == 1
    assert set(crossing[0]['segments']) == {'S7', 'S8'}
    assert crossing[0]['layers'] == [0, 2]
    assert level['fake_intersections'] == []
    # The crossing point returns both segments, on distinct layers, never a merge.
    hits = mapbundle.hit_query(manifest, 2.5, 0, radius=0.3, level='handheld')
    assert {h['segment_id'] for h in hits} == {'S7', 'S8'}
    assert len({h['layer'] for h in hits}) == 2
    assert all(h['map_version'] == manifest['map_version'] for h in hits)


def test_one_way_direction_is_preserved_in_every_level(tmp_path):
    db = connect(tmp_path / 'oneway.sqlite')
    segment.ingest(db, [
        _event('S9', 'U', 'V', [[0, 0], [1, 1], [2, 2]], event_id='e-s9', direction='forward'),
        _event('S10', 'V', 'W', [[2, 2], [3, 3]], event_id='e-s10', direction='both'),
    ])
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    level = manifest['levels']['handheld']
    assert level['one_way_edges'] == ['S9']
    assert manifest['bundles']['handheld']['hit_index']['S9']['direction'] == 'forward'
    assert manifest['bundles']['handheld']['hit_index']['S10']['direction'] == 'both'


def _counterexample(db):
    # Shared source counterexample: S5's peak must survive a survey contract;
    # S6 is a distant, non-intersecting two-point road. Four-point budget.
    segment.ingest(db, [
        _event('S5', 'E', 'F', [[0, 0], [1, 1], [2, 0]], event_id='e-s5'),
        _event('S6', 'G', 'H', [[0, 3], [2, 3]], event_id='e-s6'),
    ])


def test_survey_contract_refuses_under_size_cap_but_schematic_publishes(tmp_path):
    levels = [{'level': 'handheld', 'tolerance': 0.1, 'max_points': 4, 'min_gap': 0.5}]
    db = connect(tmp_path / 'survey.sqlite')
    _counterexample(db)
    survey = mapbundle.build(db, AS_OF, contract=mapbundle.SURVEY, levels=levels)
    s_level = survey['levels']['handheld']
    assert s_level['decision'] == 'not_published'
    assert s_level['reason'] == 'package_size_exceeded'
    assert 'S5' in s_level['offending_segments']
    assert s_level['size_detail'] == {'points_required': 5, 'points_allowed': 4}
    # A refused level ships no geometry — no plausible-but-wrong map.
    assert survey['bundles'] == {}

    # The same source, independently adjudicated under the schematic contract.
    schematic_levels = [{'level': 'handheld', 'tolerance': 1.1, 'max_points': 4, 'min_gap': 0.5}]
    schematic = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC,
                                levels=schematic_levels)
    h_level = schematic['levels']['handheld']
    assert h_level['decision'] == 'published'
    bundle = schematic['bundles']['handheld']
    assert bundle['point_count'] == 4
    assert bundle['shapes']['S5'] == [[0.0, 0.0], [2.0, 0.0]]
    assert bundle['shapes']['S6'] == [[0.0, 3.0], [2.0, 3.0]]
    assert h_level['fake_intersections'] == []
    # Contracts are labelled and can never be relabelled as one another.
    assert survey['contract'] == 'survey'
    assert schematic['contract'] == 'schematic'


def test_contracts_are_independent_and_endpoints_are_never_deleted(tmp_path):
    db = connect(tmp_path / 'indep.sqlite')
    _counterexample(db)
    survey = mapbundle.build(
        db, AS_OF, contract=mapbundle.SURVEY,
        levels=[{'level': 'handheld', 'tolerance': 0.1, 'max_points': 100, 'min_gap': 0.5}])
    assert survey['levels']['handheld']['decision'] == 'published'
    bundle = survey['bundles']['handheld']
    # Even at full detail the endpoints are intact.
    assert bundle['shapes']['S5'][0] == [0.0, 0.0]
    assert bundle['shapes']['S5'][-1] == [2.0, 0.0]
    assert bundle['hit_index']['S5']['original_vertex_order'][0] == 0
    assert bundle['hit_index']['S5']['original_vertex_order'][-1] == 2


def test_repeated_builds_have_stable_summary_and_version(tmp_path):
    db = connect(tmp_path / 'stable.sqlite')
    _ridge_network(db)
    first = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    second = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    assert mapbundle.stable_summary(first) == mapbundle.stable_summary(second)
    assert first['map_version'] == second['map_version']
    summary = mapbundle.stable_summary(first)
    assert summary['contract'] == 'schematic'
    row = summary['levels'][0]
    assert set(row) == {'level', 'decision', 'point_count', 'max_error',
                        'break_points', 'fake_intersections',
                        'grade_separated_crossings', 'repair_rounds',
                        'offending_segments'}
    assert row['decision'] == 'published'
    assert row['point_count'] == 6


def test_report_carries_points_errors_layers_and_traceback(tmp_path):
    db = connect(tmp_path / 'report.sqlite')
    _ridge_network(db)
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    level = manifest['levels']['handheld']
    assert level['point_count'] == 6
    assert level['max_error'] <= 1.1
    assert set(level['errors']) == {'S1', 'S2'}
    assert level['layers'] == {'S1': 0, 'S2': 0}
    assert level['break_points'] == 4  # A, B, C, D — no invented junction
    trace = level['segment_trace']['S1']
    assert trace['segment_id'] == 'S1'
    assert trace['event_id'] == 'e-S1'
    assert trace['original_vertex_order'] == [0, 1, 2]
    assert trace['original_point_count'] == 3
    assert trace['map_version'] == manifest['map_version']


def test_junction_inputs_at_different_vertex_orders_and_noisy_coordinates(tmp_path):
    db = connect(tmp_path / 'noisy.sqlite')
    segment.ingest(db, [
        _event('S3', 'I', 'J', [[0, 0], [1, 0], [2.01, 1.01]], event_id='e-s3'),
        _event('S4', 'J', 'K', [[1.99, 0.99], [3, 1], [4, 2]], event_id='e-s4'),
    ])
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=[
        {'level': 'z', 'tolerance': 1.1, 'max_points': 50, 'min_gap': 0.5}])
    bundle = manifest['bundles']['z']
    assert bundle['shapes']['S3'][-1] == bundle['shapes']['S4'][0] == [2.0, 1.0]
    # J is the last vertex of S3 but the first of S4; order traces differ.
    assert bundle['hit_index']['S3']['original_vertex_order'][-1] == 2
    assert bundle['hit_index']['S4']['original_vertex_order'][0] == 0


def test_invalid_shape_and_layer_are_rejected(tmp_path):
    db = connect(tmp_path / 'invalid.sqlite')
    bad = _event('S1', 'A', 'B', [[0, 0]])
    with pytest.raises(ValueError):
        segment.ingest(db, [bad])
    bad_layer = dict(_event('S1', 'A', 'B', [[0, 0], [1, 1]]), layer='up')
    with pytest.raises(ValueError):
        segment.ingest(db, [bad_layer])


def test_bundle_persists_and_reopens_with_hit_index(tmp_path):
    path = tmp_path / 'persist.sqlite'
    db = connect(path)
    _ridge_network(db)
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    db.close()
    reopened = connect(path)
    loaded = mapbundle.latest_manifest(reopened, AS_OF)
    assert loaded['map_version'] == manifest['map_version']
    hits = mapbundle.hit_query(loaded, 1, 1, radius=0.4, level='handheld')
    assert {h['segment_id'] for h in hits} == {'S1'}
    assert hits[0]['map_version'] == manifest['map_version']


def test_unsatisfiable_topology_is_refused_with_segments_and_level(tmp_path):
    db = connect(tmp_path / 'unsat.sqlite')
    # Distinct layers can never be merged by simplification: even if two
    # same-layer roads were forced onto one cell with no restorable vertex,
    # the level must be refused rather than drawn. Construct the impossible
    # case with identical two-point shapes under different node names.
    segment.ingest(db, [
        _event('S11', 'M', 'N', [[0, 0], [4, 0]], event_id='e-s11'),
        _event('S12', 'O', 'P', [[0, 0], [4, 0]], event_id='e-s12'),
    ])
    manifest = mapbundle.build(db, AS_OF, contract=mapbundle.SCHEMATIC, levels=HANDHELD)
    level = manifest['levels']['handheld']
    assert level['decision'] == 'not_published'
    assert level['reason'] == 'topology_constraints_unsatisfiable'
    assert set(level['offending_segments']) == {'S11', 'S12'}
    assert manifest['bundles'] == {}
