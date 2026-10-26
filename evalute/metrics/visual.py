from collections import Counter
from math import hypot

ROLE_FLOORS = {'title': 24, 'body': 14, 'table': 12, 'chart_label': 12,
               'diagram': 12, 'caption': 10, 'label': 10, 'stat': 24}


def _intersection(a, b):
    x = max(0, min(a['left'] + a['width'], b['left'] + b['width']) - max(a['left'], b['left']))
    y = max(0, min(a['top'] + a['height'], b['top'] + b['height']) - max(a['top'], b['top']))
    return x * y


def _contains(a, b):
    eps = 1e-5
    return (a['left'] <= b['left'] + eps and a['top'] <= b['top'] + eps
            and a['left'] + a['width'] + eps >= b['left'] + b['width']
            and a['top'] + a['height'] + eps >= b['top'] + b['height'])


def _allowed_overlap(a, b):
    # A group alone is not a containment declaration. Siblings can collide.
    for container, child in ((a, b), (b, a)):
        declared = child.get('container_id') == container['shape_id'] and container.get('role') == 'container'
        background = (container.get('role') == 'background' and not container.get('text')
                      and container.get('z_order', -1) < child.get('z_order', 0))
        if (declared or background) and _contains(container, child):
            return True
    return False


def _line_crosses(line, box):
    """Clip the actual segment against the interior, rather than its bounding box."""
    if box['shape_id'] in line.get('connector_endpoints', []) or box.get('role') in {'background', 'container'}:
        return False
    segment = line.get('line_segment')
    if not segment:
        return False
    x, y, end_x, end_y = segment
    dx, dy = end_x-x, end_y-y
    eps = .01
    low, high = 0.0, 1.0
    for p, q in ((-dx, x-box['left']-eps), (dx, box['left']+box['width']-x-eps),
                 (-dy, y-box['top']-eps), (dy, box['top']+box['height']-y-eps)):
        if abs(p) < 1e-10:
            if q < 0:
                return False
        elif p < 0:
            low = max(low, q/p)
        else:
            high = min(high, q/p)
    return low <= high


def evaluate(slides, width, height, config):
    c, results, all_fonts = config['visual'], [], []
    floors = {**ROLE_FLOORS, 'body': c['body_small_font_pt'], **c.get('role_font_floors', {})}
    for slide in slides:
        objects = slide['shapes']
        shapes = [s for s in objects if s['width'] and s['height'] and not s['is_line']]
        oob = sum(s['left'] < -1e-5 or s['top'] < -1e-5 or s['left'] + s['width'] > width + 1e-5
                  or s['top'] + s['height'] > height + 1e-5 for s in objects)
        margin = sum(bool(s['text']) and min(s['left'], s['top'], width-s['left']-s['width'], height-s['top']-s['height']) < c['safe_margin_inches'] for s in shapes)
        pairs, font_findings, unknown = [], [], []
        for i, a in enumerate(shapes):
            for b in shapes[i + 1:]:
                area = min(a['width'] * a['height'], b['width'] * b['height'])
                if area and _intersection(a, b) / area > c['overlap_ratio'] and not _allowed_overlap(a, b):
                    pairs.append([a['shape_id'], b['shape_id']])
        for line in (s for s in objects if s['is_line']):
            for box in shapes:
                if _line_crosses(line, box):
                    pairs.append([line['shape_id'], box['shape_id']])
        for shape in shapes:
            runs = shape.get('text_runs', [{'font_size': size, 'role': shape.get('role', 'body')} for size in shape['font_sizes']])
            for run in runs:
                role = run.get('role', 'body')
                floor = floors.get(role, floors['body'])
                size = run['font_size']
                if size is None:
                    unknown.append(shape['shape_id'])
                elif size < floor:
                    font_findings.append({'shape_id': shape['shape_id'], 'role': role, 'font_size': size,
                                          'floor_pt': floor, 'required': shape.get('required', True)})
        fonts = [x for s in shapes for x in s['font_sizes']]
        all_fonts += [x for s in shapes for x in s['font_names']]
        total_area = sum(s['width'] * s['height'] for s in shapes)
        mass = total_area or 1
        cx = sum(s['width'] * s['height'] * (s['left'] + s['width'] / 2) for s in shapes) / mass / width
        cy = sum(s['width'] * s['height'] * (s['top'] + s['height'] / 2) for s in shapes) / mass / height
        balance = hypot(cx - .5, cy - .5)
        warnings = []
        unknown_geometry = [s['shape_id'] for s in objects if s.get('geometry_uncertainties')]
        if oob: warnings.append(f'{oob} out-of-bounds objects')
        if pairs: warnings.append(f'{len(pairs)} suspicious overlaps: {pairs}')
        if font_findings: warnings.append(f'{len(font_findings)} runs below role readability floors')
        if unknown: warnings.append('Inherited font sizes unresolved; rendered readability still requires assessment')
        if unknown_geometry: warnings.append('Rotated/flipped group geometry requires rendered inspection')
        if slide['word_count'] > c['dense_words']: warnings.append('Dense slide text')
        penalty = min(1, .15 * (oob + len(pairs) + len(font_findings)) + (.15 if slide['word_count'] > c['dense_words'] else 0) + balance * .2)
        results.append({'slide_no': slide['slide_no'], 'out_of_bounds_count': oob, 'margin_violation_count': margin,
                        'suspicious_overlap_count': len(pairs), 'overlap_pairs': pairs, 'small_font_count': len(font_findings),
                        'font_findings': font_findings, 'unknown_font_shape_ids': sorted(set(unknown)),
                        'unknown_geometry_shape_ids': unknown_geometry,
                        'geometry_check': 'APPROXIMATE_NATIVE_BOUNDS', 'rendered_clipping_status': 'NOT_EVALUATED',
                        'min_body_font_pt': min(fonts) if fonts else None, 'occupancy_ratio': min(1, total_area/(width*height)),
                        'balance_offset': balance, 'score': 1-penalty, 'warnings': warnings})
    return results, {'score': sum(x['score'] for x in results) / max(1, len(results)),
                     'dominant_font': Counter(all_fonts).most_common(1)[0][0] if all_fonts else None,
                     'status': ('EVALUATED_FAIL' if any(r['out_of_bounds_count'] or r['suspicious_overlap_count'] or any(f['required'] for f in r['font_findings']) for r in results)
                                else 'NOT_EVALUATED' if any(r['unknown_geometry_shape_ids'] for r in results) else 'EVALUATED_PASS'),
                     'geometry_check': 'APPROXIMATE_NATIVE_BOUNDS', 'rendered_clipping_status': 'NOT_EVALUATED'}
