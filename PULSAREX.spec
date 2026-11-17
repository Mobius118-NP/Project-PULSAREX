# Build on Windows: python -m PyInstaller --noconfirm PULSAREX.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

assets = collect_data_files('pulsar', includes=['dashboard/*'])
assets += collect_data_files('_sounddevice_data')
analysis = Analysis(['packaging/launcher.py'], pathex=['src'], datas=assets,
                    hiddenimports=collect_submodules('uvicorn') + ['_cffi_backend'],
                    excludes=['pytest', 'httpx', 'ruff'], noarchive=False)
archive = PYZ(analysis.pure)
exe = EXE(archive, analysis.scripts, [], exclude_binaries=True,
          name='PULSAREX', debug=False, strip=False, upx=False, console=True)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='PULSAREX')
