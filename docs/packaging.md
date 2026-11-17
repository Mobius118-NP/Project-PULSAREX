# Windows executable

Build on Windows x64 with a full Python 3.11+ installation including Tcl/Tk (validated here on 3.12):

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[packaging,discovery]"
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm PULSAREX.spec
& .\.venv\Scripts\python.exe examples/smoke_executable.py dist/PULSAREX/PULSAREX.exe .test-tmp/frozen-smoke
```

`Build-PULSAREX.cmd` performs the install/build. Distribute the **entire**
`dist/PULSAREX` folder, including `_internal`, as a ZIP. `PULSAREX.exe` hosts HTTP;
it is not an HTML launcher requiring a separately installed Python. A one-folder
distribution was selected for inspectable DLL dependencies and to avoid repeated
one-file extraction of NumPy/SciPy and PortAudio. Double-click `PULSAREX.exe` to open the native GUI. `PULSAREX-Console.exe` displays console startup/errors and supports Ctrl+C. Both share the bundled dependencies. See [GUI launch steps](gui-launcher.md).

```powershell
.\PULSAREX.exe --open-browser
.\PULSAREX.exe --config C:\PULSAREX\config.toml
.\PULSAREX.exe --source simulation --port 8765 --data-dir C:\PULSAREX\data
```

Without external configuration, packaged data default to `%LOCALAPPDATA%\PULSAREX`.
`--data-dir` overrides that location. Relative data paths in external TOML resolve
against the configuration file, not a bundle extraction directory. Dashboard assets
are read-only package data. LAN tokens stay in GUI memory; console mode uses the PULSAR_TOKEN environment variable. The GUI never writes the token to preferences.

The entry calls `multiprocessing.freeze_support()` before loading the application,
so spawned microphone-driver workers dispatch correctly rather than starting another
server. PyInstaller's sounddevice hook bundles PortAudio. The smoke test sanitizes
PATH/PYTHONPATH/PYTHONHOME/VIRTUAL_ENV, changes the working directory, verifies HTTP,
automatic baseline calibration, static assets, freeze/pause controls, invalid-device
native worker handling and simulation recovery. It never opens a valid microphone.

Observed distribution size/startup results are in [validation](validation.md).
Nuitka was considered as an alternative compiled distribution, but has not been
built or benchmarked here; no comparative speed claim is made. Compilation does not
improve NumPy/SciPy algorithms automatically. Revisit Nuitka if startup/size becomes
an operational constraint, using the same smoke test and clean-machine measurements.

This is an unsigned application build. A separate clean Windows machine, Windows
microphone permission/driver combinations and real array hardware still need testing.
Signing and installer creation are outside this local build. GitHub Actions includes
an independent Windows build/smoke job, but that hosted workflow has not run here.

References: [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[multiprocessing support](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing).

A packaged GUI-backend check is available as `PULSAREX.exe --check-launcher <output.json>`. It verifies bundled Tcl, frozen server-process spawning, authenticated LAN access and graceful shutdown/port release, without physical audio capture. The result file contains no token.
