# Windows x64, single executable for local non-commercial research.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

if sys.version_info[:3] == (3, 12, 0):
    raise SystemExit('Python 3.12.0 cannot freeze SciPy reliably. Use Python 3.12.1 or newer, or 3.11.')

project = Path(SPECPATH).resolve()
argos = Path(os.environ.get('PULSAREX_ARGOS_SOURCE', Path.home() / 'ARGOS')).resolve()
assets = collect_data_files('pulsar', includes=['dashboard/*', 'dashboard/fonts/*'])
assets += collect_data_files('_sounddevice_data')

# Keep this list explicit. The local catalogue and recordings are private data.
for relative in (
    'config/default.yaml',
    'models/face_detection_yunet_2023mar.onnx',
    'models/w600k_r50.onnx',
):
    source = argos / relative
    if not source.is_file():
        raise SystemExit(f'Required ARGOS build asset is missing: {source}')
    assets.append((str(source), 'pulsar/argos_assets/' + Path(relative).parent.as_posix()))

assets.extend([
    (str(project / 'LICENSE'), 'licenses/pulsarex'),
    (str(project / 'packaging/YuNet-LICENSE.txt'), 'licenses/yunet'),
    (str(project / 'docs/argos-models.md'), 'licenses/insightface'),
])
analysis = Analysis(
    [str(project / 'packaging/launcher.py')],
    pathex=[str(project / 'src'), str(argos / 'src')],
    datas=assets,
    hiddenimports=collect_submodules('uvicorn') + ['_cffi_backend'],
    excludes=['pytest', 'httpx', 'ruff'],
    noarchive=False,
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='PULSAREX', debug=False, strip=False, upx=False, console=False,
)
