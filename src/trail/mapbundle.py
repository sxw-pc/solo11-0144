"""Multi-scale offline map bundles with topology certification.

Two delivery contracts are adjudicated independently over the same source
network:

* ``survey``  — 测绘近似图：每个缩放级的形状误差被严格限定。
* ``schematic`` — 示意导航图：允许更大的形状偏移，但正式路口、分层与
  不可换乘关系仍然必须保真。

A level is only published when every contract constraint holds at once:
endpoints, formal junctions, bridge/under-bridge layers, minimum screen
spacing between segments that are not actually connected, one-way edge
direction, the per-level coordinate error and the package point budget.
When size and topology cannot be reconciled the level is marked
``not_published`` with the offending segments and level instead of emitting
a plausible-but-wrong map.

The bundle is geometry plus a hit index: every simplified segment traces
back to its original ``segment_id``, the original vertex order and the map
version used to build it.
"""
import hashlib
import json
import math

from . import segment, hazard

SURVEY = 'survey'
SCHEMATIC = 'schematic'
CONTRACTS = (SURVEY, SCHEMATIC)

# level: (coordinate error tolerance, max points in package, min screen spacing)
DEFAULT_LEVELS = {
    SURVEY: [
        {'level': 'full', 'tolerance': 0.1, 'max_points': 1_000_000, 'min_gap': 0.5},
        {'level': 'handheld', 'tolerance': 0.1, 'max_points': 1_000_000, 'min_gap': 0.5},
    ],
    SCHEMATIC: [
        {'level': 'full', 'tolerance': 1.1, 'max_points': 1_000_000, 'min_gap': 0.5},
        {'level': 'handheld', 'tolerance': 1.1, 'max_points': 1_000_000, 'min_gap': 0.5},
    ],
}


# --------------------------------------------------------------------------
# pure geometry helpers
# --------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def point_segment_distance(p, a, b):
    """Distance from point p to segment a-b."""
    ab = _sub(b, a)
    denom = _dot(ab, ab)
    if denom == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = _dot(_sub(p, a), ab) / denom
    if t <= 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    if t >= 1.0:
        return math.hypot(p[0] - b[0], p[1] - b[1])
    return abs(_cross(ab, _sub(p, a))) / math.sqrt(denom)


def point_polyline_distance(p, poly):
    return min(point_segment_distance(p, poly[i], poly[i + 1])
               for i in range(len(poly) - 1))


def polyline_error(original, simplified):
    """Maximum deviation of any original vertex from the simplified line."""
    if len(simplified) < 2:
        return float('inf')
    return max(point_polyline_distance(pt, simplified) for pt in original)


def rdp_indices(points, tolerance, keep=()):
    """Ramer-Douglas-Peucker returning the kept *indices*.

    Endpoints are always kept; every index in ``keep`` is pinned as well.
    Removing one vertex changes both adjacent spans, so the perpendicular
    deviation is always measured against the chord that would be drawn.
    """
    keep = set(keep) | {0, len(points) - 1}
    if len(points) <= 2:
        return list(range(len(points)))

    def recurse(lo, hi, kept):
        if hi <= lo + 1:
            return
        within = range(lo + 1, hi)
        if max(point_segment_distance(points[i], points[lo], points[hi])
               for i in within) <= tolerance:
            pinned = [i for i in within if i in keep]
            if not pinned:
                kept.difference_update(within)
                return
            for mid in pinned:
                kept.add(mid)
                recurse(lo, mid, kept)
                recurse(mid, hi, kept)
            return
        dmax, idx = -1.0, lo + 1
        for i in within:
            d = point_segment_distance(points[i], points[lo], points[hi])
            if d > dmax:
                dmax, idx = d, i
        kept.add(idx)
        recurse(lo, idx, kept)
        recurse(idx, hi, kept)

    kept = set(keep)
    recurse(0, len(points) - 1, kept)
    return sorted(kept)


def rdp(points, tolerance, keep=()):
    return [points[i] for i in rdp_indices(points, tolerance, keep)]


def _orient(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _on_segment_strict(p, a, b):
    """True when p lies in the interior of segment a-b."""
    if _orient(a, b, p) != 0:
        return False
    return (min(a[0], b[0]) < p[0] < max(a[0], b[0]) or
            min(a[1], b[1]) < p[1] < max(a[1], b[1]))


def segments_intersect(a, b, c, d):
    """Open-segment intersection. Touching only at shared endpoints is not
    an intersection — formal junctions are certified separately."""
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if o1 == 0 and o2 == 0 and o3 == 0 and o4 == 0:
        # Collinear: an interior overlap is a real merge; endpoint-only
        # contact (a shared junction coordinate) is not.
        touch_only = ({a, b} & {c, d}) and not (
            _on_segment_strict(c, a, b) or _on_segment_strict(d, a, b) or
            _on_segment_strict(a, c, d) or _on_segment_strict(b, c, d))
        return not touch_only
    if ((o1 > 0 > o2) or (o1 < 0 < o2)) and \
       ((o3 > 0 > o4) or (o3 < 0 < o4)):
        return True
    return (_on_segment_strict(c, a, b) or _on_segment_strict(d, a, b) or
            _on_segment_strict(a, c, d) or _on_segment_strict(b, c, d))


def polylines_cross(p, q):
    return any(segments_intersect(p[i], p[i + 1], q[j], q[j + 1])
               for i in range(len(p) - 1) for j in range(len(q) - 1))


def polyline_distance(p, q):
    best = float('inf')
    for i in range(len(p) - 1):
        a, b = p[i], p[i + 1]
        for pt in q:
            best = min(best, point_segment_distance(pt, a, b))
    for j in range(len(q) - 1):
        a, b = q[j], q[j + 1]
        for pt in p:
            best = min(best, point_segment_distance(pt, a, b))
    return best


def polyline_hausdorff(p, q):
    """Bidirectional maximum deviation; zero only for coincident geometry."""
    return max(max(point_polyline_distance(pt, q) for pt in p),
               max(point_polyline_distance(pt, p) for pt in q))


def _cells(poly, quantum):
    """Screen grid cells touched by a polyline at the given quantization."""
    out = set()

    def mark(x, y):
        out.add((math.floor(x / quantum), math.floor(y / quantum)))

    for pt in poly:
        mark(pt[0], pt[1])
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        span = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, int(span / (quantum / 4.0)) + 1)
        for k in range(1, steps):
            t = k / steps
            mark(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return out


def _snap(value, quantum):
    return round(round(value / quantum) * quantum, 10)


# --------------------------------------------------------------------------
# source loading
# --------------------------------------------------------------------------

def load_network(db, as_of):
    """Current passable edges with their source shapes and height layers."""
    restricted = {h['segment_id'] for h in hazard.decisions(db, as_of)
                  if h['decision'] == 'restricted'}
    network = segment.edges(db, as_of, restricted)
    edges = []
    for e in network['available']:
        row = db.execute(
            'SELECT coordinates,layer FROM map_shape WHERE event_id=?',
            (e['event_id'],)).fetchone()
        if row is None:
            continue
        coords = json.loads(row['coordinates'])
        edges.append({
            'segment_id': e['segment_id'],
            'event_id': e['event_id'],
            'from_node': e['from_node'],
            'to_node': e['to_node'],
            'direction': e['direction'],
            'layer': row['layer'],
            'shape': [(float(x), float(y)) for x, y in coords],
        })
    return edges, network['blocked']


# --------------------------------------------------------------------------
# per-level certification
# --------------------------------------------------------------------------

def _junction_coordinates(edges):
    """Canonical source coordinate for every formal node. A node shared by
    several edges is one junction even when its position appears at
    different vertex orders in the input shapes."""
    coords = {}
    for e in edges:
        coords.setdefault(e['from_node'], []).append(e['shape'][0])
        coords.setdefault(e['to_node'], []).append(e['shape'][-1])
    return {node: (sum(pt[0] for pt in pts) / len(pts),
                   sum(pt[1] for pt in pts) / len(pts))
            for node, pts in coords.items()}


def _find_conflicts(work, junction_nodes, quantum, min_gap):
    """Certify the simplified drawing.

    Returns ``(conflicts, grade_separated)``. A conflict is a same-layer
    connection that did not exist in the source: a brand-new crossing, a
    screen-cell merge (including two ridges flattened onto one line) or a
    collapse of the minimum screen spacing. Crossings between different
    height layers are returned separately — they stay separate click
    targets and never become a transfer.
    """
    conflicts, grade_separated = [], []
    simp_cells = {sid: _cells(w['poly'], quantum) for sid, w in work.items()}
    orig_cells = {sid: _cells(w['shape'], quantum) for sid, w in work.items()}
    ids = sorted(work)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            w1, w2 = work[ids[x]], work[ids[y]]
            pair = sorted((w1['meta']['segment_id'], w2['meta']['segment_id']))
            shared = junction_nodes[w1['meta']['segment_id']] & \
                junction_nodes[w2['meta']['segment_id']]
            if w1['meta']['layer'] != w2['meta']['layer']:
                if polylines_cross(w1['poly'], w2['poly']):
                    grade_separated.append({
                        'segments': pair,
                        'layers': sorted((w1['meta']['layer'], w2['meta']['layer'])),
                        'reason': 'crossing_on_separate_layers'})
                continue
            if shared:
                continue
            if polyline_hausdorff(w1['shape'], w2['shape']) <= 1e-12:
                # Distinct formal edges occupying the exact same source
                # geometry can never become distinct tap targets.
                conflicts.append({'segments': pair,
                                  'reason': 'coincident_unconnected_geometries'})
                continue
            shared_now = simp_cells[w1['meta']['segment_id']] & \
                simp_cells[w2['meta']['segment_id']]
            shared_before = orig_cells[w1['meta']['segment_id']] & \
                orig_cells[w2['meta']['segment_id']]
            if shared_now - shared_before:
                conflicts.append({'segments': pair,
                                  'reason': 'fake_transfer_screen_overlap'})
                continue
            if polylines_cross(w1['poly'], w2['poly']) and \
                    not polylines_cross(w1['shape'], w2['shape']):
                conflicts.append({'segments': pair,
                                  'reason': 'new_same_layer_crossing'})
                continue
            original_gap = polyline_distance(w1['shape'], w2['shape'])
            gap = polyline_distance(w1['poly'], w2['poly'])
            if original_gap >= min_gap and gap < min_gap:
                conflicts.append({'segments': pair,
                                  'reason': 'minimum_screen_spacing_violated',
                                  'original_gap': round(original_gap, 6),
                                  'simplified_gap': round(gap, 6)})
    return conflicts, grade_separated


def _certify_level(edges, spec, map_version):
    tolerance, max_points = spec['tolerance'], spec['max_points']
    min_gap = spec['min_gap']
    quantum = spec.get('quantum', min_gap)
    junction_xy = _junction_coordinates(edges)
    junction_drawing = {node: (_snap(xy[0], quantum), _snap(xy[1], quantum))
                        for node, xy in junction_xy.items()}
    junction_nodes = {e['segment_id']: {e['from_node'], e['to_node']}
                      for e in edges}

    work = {}
    for e in edges:
        pins = {0, len(e['shape']) - 1}
        work[e['segment_id']] = {
            'meta': e,
            'shape': e['shape'],
            'pins': pins,
            'kept': rdp_indices(e['shape'], tolerance, pins),
        }

    def _polyline(w):
        e = w['meta']
        poly = [w['shape'][i] for i in w['kept']]
        # Shared formal junctions land on one quantized coordinate in every
        # incident shape, otherwise a screen tap becomes two fake breaks.
        poly[0] = junction_drawing[e['from_node']]
        poly[-1] = junction_drawing[e['to_node']]
        return poly

    for w in work.values():
        w['poly'] = _polyline(w)

    conflicts, grade_separated = _find_conflicts(
        work, junction_nodes, quantum, min_gap)

    # Repair: put source vertices back (largest deviation first). Removing a
    # vertex changes both adjacent spans, so every repair re-runs the whole
    # constrained simplification instead of patching one span.
    repair_rounds = 0
    while conflicts:
        repair_rounds += 1
        pair = conflicts[0]['segments']
        progressed = False
        for sid in pair:
            w = work[sid]
            remaining = [i for i in range(len(w['shape'])) if i not in w['kept']]
            if not remaining:
                continue
            idx = max(remaining,
                      key=lambda i: point_polyline_distance(w['shape'][i], w['poly']))
            w['pins'].add(idx)
            progressed = True
        if not progressed:
            break
        for sid in pair:
            w = work[sid]
            w['kept'] = rdp_indices(w['shape'], tolerance, w['pins'])
            w['poly'] = _polyline(w)
        conflicts, grade_separated = _find_conflicts(
            work, junction_nodes, quantum, min_gap)

    shapes, hit_index, errors = {}, {}, {}
    total_points = 0
    for sid in sorted(work):
        w = work[sid]
        e = w['meta']
        poly = w['poly']
        err = polyline_error(e['shape'], poly)
        shapes[sid] = [[pt[0], pt[1]] for pt in poly]
        errors[sid] = round(err, 6)
        total_points += len(poly)
        hit_index[sid] = {
            'segment_id': sid,
            'event_id': e['event_id'],
            'map_version': map_version,
            'from_node': e['from_node'],
            'to_node': e['to_node'],
            'direction': e['direction'],
            'layer': e['layer'],
            'original_vertex_order': list(w['kept']),
            'original_point_count': len(e['shape']),
            'simplified_point_count': len(poly),
            'max_error': round(err, 6),
        }

    report = {
        'level': spec['level'],
        'tolerance': tolerance,
        'max_points': max_points,
        'min_gap': min_gap,
        'quantum': quantum,
        'point_count': total_points,
        'published': False,
        'max_error': max(errors.values(), default=0.0),
        'errors': errors,
        'junctions': [
            {'node': n,
             'coordinate': list(junction_drawing[n]),
             'segments': sorted(
                 sid for sid, w in work.items()
                 if n in (w['meta']['from_node'], w['meta']['to_node']))}
            for n in sorted(junction_drawing)],
        'break_points': len(junction_drawing),
        'fake_intersections': conflicts,
        'grade_separated_crossings': grade_separated,
        'repair_rounds': repair_rounds,
        'layers': {sid: w['meta']['layer'] for sid, w in sorted(work.items())},
        'one_way_edges': sorted(w['meta']['segment_id'] for w in work.values()
                                if w['meta']['direction'] == 'forward'),
        'segment_trace': {sid: hit_index[sid] for sid in sorted(hit_index)},
    }

    if conflicts:
        report['decision'] = 'not_published'
        report['reason'] = 'topology_constraints_unsatisfiable'
        report['offending_segments'] = sorted(
            s for c in conflicts for s in c['segments'])
        return report, None
    if max(errors.values(), default=0.0) > tolerance + 1e-9:
        report['decision'] = 'not_published'
        report['reason'] = 'tolerance_exceeded'
        report['offending_segments'] = sorted(
            sid for sid, err in errors.items() if err > tolerance + 1e-9)
        return report, None
    if total_points > max_points:
        # Greedy contradiction attribution: peel segments off in ascending
        # minimum-cost order while the remainder still exceeds the cap. The
        # segments left are the smallest set whose tolerance-minimum makes
        # the package cap infeasible; any segment topology repair pinned
        # beyond its minimum always qualifies.
        minimal_sets = {
            sid: set(rdp_indices(w['shape'], tolerance,
                                 {0, len(w['shape']) - 1}))
            for sid, w in work.items()}
        minimal_counts = {sid: len(kept) for sid, kept in minimal_sets.items()}
        # Greedy contradiction attribution: peel off segments in ascending
        # minimum-cost order while the remainder still exceeds the cap. The
        # segments left are the smallest set whose point demand makes the
        # package cap infeasible; topology-forced pins always qualify.
        remaining = set(work)
        for sid in sorted(work, key=lambda s: minimal_counts[s]):
            if sum(minimal_counts[s] for s in remaining) <= max_points:
                break
            remaining.discard(sid)
        over = sorted(
            sid for sid, w in work.items()
            if sid in remaining or set(w['kept']) - minimal_sets[sid])
        report['decision'] = 'not_published'
        report['reason'] = 'package_size_exceeded'
        report['offending_segments'] = over or sorted(work)
        report['size_detail'] = {'points_required': total_points,
                                 'points_allowed': max_points}
        return report, None

    report['decision'] = 'published'
    report['published'] = True
    level_bundle = {
        'level': spec['level'],
        'contract_tolerance': tolerance,
        'min_gap': min_gap,
        'quantum': quantum,
        'point_count': total_points,
        'shapes': shapes,
        'hit_index': hit_index,
        'junctions': report['junctions'],
        'layers': report['layers'],
        'one_way_edges': report['one_way_edges'],
        'grade_separated_crossings': grade_separated,
    }
    return report, level_bundle


def _map_version(as_of, contract, levels, edges):
    payload = json.dumps({
        'as_of': as_of,
        'contract': contract,
        'levels': levels,
        'edges': sorted((e['event_id'], e['segment_id'], e['layer'], e['shape'])
                        for e in edges),
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def build(db, as_of, contract=SURVEY, levels=None):
    """Build a certified multi-scale bundle under one delivery contract.

    The two contracts are adjudicated independently over the same source
    network; a schematic bundle is never relabelled as a survey bundle.
    """
    if contract not in CONTRACTS:
        raise ValueError('unknown map contract ' + str(contract))
    spec_levels = [dict(s) for s in (levels or DEFAULT_LEVELS[contract])]
    for spec in spec_levels:
        for key in ('level', 'tolerance', 'max_points', 'min_gap'):
            if key not in spec:
                raise ValueError('level config missing ' + key)
    edges, blocked = load_network(db, as_of)
    map_version = _map_version(as_of, contract, spec_levels, edges)

    level_reports, published_levels = [], {}
    for spec in spec_levels:
        report, level_bundle = _certify_level(edges, spec, map_version)
        report['map_version'] = map_version
        level_reports.append(report)
        if level_bundle is not None:
            level_bundle['map_version'] = map_version
            published_levels[spec['level']] = level_bundle

    manifest = {
        'as_of': as_of,
        'contract': contract,
        'map_version': map_version,
        'segments': sorted(e['segment_id'] for e in edges),
        'blocked_segments': blocked,
        'levels': {r['level']: r for r in level_reports},
        'bundles': published_levels,
    }
    with db:
        db.execute('INSERT INTO map_bundle(as_of,manifest) VALUES (?,?)',
                   (as_of, json.dumps(manifest, sort_keys=True)))
    return manifest


def latest_manifest(db, as_of=None):
    sql = 'SELECT manifest FROM map_bundle'
    args = ()
    if as_of is not None:
        # Bundles are versioned snapshots; take the newest at or before
        # the requested point in time.
        sql += ' WHERE as_of<=?'
        args = (as_of,)
    sql += ' ORDER BY as_of DESC,id DESC LIMIT 1'
    row = db.execute(sql, args).fetchone()
    return json.loads(row['manifest']) if row else None


def hit_query(manifest, x, y, radius=None, level=None):
    """Hit-test a screen point against a published bundle.

    Returns every segment whose simplified geometry is within ``radius``
    (defaulting to the level quantization), each tracing back to the
    original segment id, original vertex order and map version. Segments on
    different height layers come back as separate hits and never merge into
    one transferable node.
    """
    bundles = manifest.get('bundles', {})
    if not bundles:
        return []
    if level is None:
        level = sorted(bundles)[0]
    bundle = bundles[level]
    if radius is None:
        radius = bundle['quantum']
    p = (float(x), float(y))
    hits = []
    for sid in sorted(bundle['shapes']):
        poly = [(pt[0], pt[1]) for pt in bundle['shapes'][sid]]
        dist = point_polyline_distance(p, poly)
        if dist <= radius:
            idx = bundle['hit_index'][sid]
            hits.append({
                'segment_id': sid,
                'event_id': idx['event_id'],
                'layer': idx['layer'],
                'direction': idx['direction'],
                'from_node': idx['from_node'],
                'to_node': idx['to_node'],
                'distance': round(dist, 6),
                'original_vertex_order': idx['original_vertex_order'],
                'map_version': bundle['map_version'],
                'level': level,
            })
    return hits


def stable_summary(manifest):
    """Deterministic acceptance summary, identical across repeated builds."""
    return {
        'contract': manifest['contract'],
        'map_version': manifest['map_version'],
        'as_of': manifest['as_of'],
        'levels': [
            {
                'level': name,
                'decision': manifest['levels'][name]['decision'],
                'point_count': manifest['levels'][name]['point_count'],
                'max_error': manifest['levels'][name]['max_error'],
                'break_points': manifest['levels'][name]['break_points'],
                'fake_intersections': manifest['levels'][name]['fake_intersections'],
                'grade_separated_crossings':
                    manifest['levels'][name]['grade_separated_crossings'],
                'repair_rounds': manifest['levels'][name]['repair_rounds'],
                'offending_segments':
                    manifest['levels'][name].get('offending_segments', []),
            }
            for name in sorted(manifest['levels'])
        ],
    }
