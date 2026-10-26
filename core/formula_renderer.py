"""Bounded Mathtext worker. No TeX shell, filesystem commands or executable input."""
from pathlib import Path
import json
import subprocess
import sys
from core.artifacts import sha256_value, file_hash, atomic_json
from core.job_context import check


def formula_identity():
    import matplotlib
    from matplotlib import font_manager
    font = font_manager.findfont('DejaVu Sans')
    return {'matplotlib': matplotlib.__version__, 'font_sha256': file_hash(font), 'font': 'DejaVu Sans',
            'renderer': 'mathtext-v1'}


def render_formula(expression, style, cache_root, *, context=None):
    check(context)
    if not expression or len(expression) > 4000 or any(token in expression for token in
        ('\\input', '\\include', '\\write', '\\read', '\\open', '\\usepackage', '\\begin', '\\def', '\\href')):
        return {'status': 'FORMULA_UNSUPPORTED', 'representations': []}
    identity = formula_identity()
    key = sha256_value({'expression': expression, 'style': style, 'identity': identity})
    directory = Path(cache_root) / key
    record = directory / 'render.json'
    if record.is_file():
        try:
            result = json.loads(record.read_text(encoding='utf-8'))
            if result.get('status')=='RENDERED' and result.get('cache_key')==key and result.get('identity')==identity and \
               {r.get('role') for r in result.get('representations',[])}=={'display_png','formula_svg'} and all(
                Path(r['path']).resolve().is_relative_to(directory.resolve()) and Path(r['path']).is_file() and
                file_hash(r['path']) == r['sha256'] for r in result['representations']):
                return result
        except (ValueError, OSError, KeyError):
            pass
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / 'request.json', {'expression': expression, 'style': style})
    try:
        subprocess.run([sys.executable, '-B', '-m', 'core.formula_renderer', str(directory.resolve())],
                       cwd=Path(__file__).resolve().parents[1], check=True, timeout=style.get('timeout', 20), capture_output=True)
    except subprocess.TimeoutExpired:
        return {'status': 'FORMULA_RENDER_TIMEOUT', 'representations': []}
    except (subprocess.CalledProcessError, OSError):
        return {'status': 'FORMULA_UNSUPPORTED', 'representations': []}
    check(context)
    result = {'status': 'RENDERED', 'identity': identity, 'cache_key': key, 'representations': []}
    from PIL import Image
    with Image.open(directory / 'formula.png') as image:
        dimensions = image.size
    for name, role, media in [('formula.png', 'display_png', 'image/png'), ('formula.svg', 'formula_svg', 'image/svg+xml')]:
        path = directory / name
        result['representations'].append({'representation_id': role, 'role': role, 'path': str(path.resolve()),
            'sha256': file_hash(path), 'media_type': media, 'editability': 'raster' if role == 'display_png' else 'vector_source',
            'width': dimensions[0], 'height': dimensions[1]})
    atomic_json(record, result)
    return result


if __name__ == '__main__':
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.mathtext import math_to_image
    from matplotlib.font_manager import FontProperties
    directory = Path(sys.argv[1])
    request = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
    text = request['expression'].strip('$')
    style = request['style']
    with matplotlib.rc_context({'text.usetex': False, 'mathtext.fontset': 'dejavusans', 'svg.hashsalt': 'f04'}):
        for extension in ('png', 'svg'):
            math_to_image('$' + text + '$', directory / ('formula.' + extension),
                prop=FontProperties(family='DejaVu Sans', size=style.get('font_size', 20)),
                dpi=style.get('dpi', 200), format=extension)
