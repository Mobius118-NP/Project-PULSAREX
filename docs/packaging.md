# Single-file Windows executable

Copy `dist/onefile/PULSAREX.exe` to a Windows x64 host and double-click it. The
native launcher starts the local server and opens the dashboard in the host's
browser. Select **LAN (same Wi-Fi)** to use a six-digit PIN with other devices.
[Launcher instructions](gui-launcher.md).

The executable bundles Python, Tcl/Tk, PortAudio, NumPy/SciPy, the dashboard and
fonts, the ARGOS runtime, YuNet and ArcFace. Windows extracts the bundled runtime
to a temporary folder on startup, so allow time for launch and leave space on the
temporary drive. The isolated test reached HTTP readiness in about 37 seconds on
the development computer. The build is unsigned.

The included InsightFace weights are for non-commercial research. Consult the
publisher's terms for redistribution or other use. [InsightFace model licensing](https://github.com/deepinsight/insightface#license).

The host's settings, baselines and event archive use `%LOCALAPPDATA%\PULSAREX`.
An external TOML or `--data-dir` can select another location. Enrollment writes
to `%USERPROFILE%\ARGOS\data\face_templates.json`, reusing the catalogue on a host
that already has one. The build reads an explicit list of configuration and model
files and does not copy enrolled identities, event data, photos, or PINs.

## Build and verify

On the build machine, use Windows x64 and full Python 3.11 or 3.12.1+ with Tcl/Tk.
Python 3.12.0 has a known freezing bug. [PyInstaller issue](https://github.com/pyinstaller/pyinstaller/issues/8186).

Place the ARGOS source checkout with both installed models at `%USERPROFILE%\ARGOS`, or set
`PULSAREX_ARGOS_SOURCE` to that checkout. [Model provenance](argos-models.md).
Run `Install-PULSAR.cmd` first if the PULSAREX development environment is absent.
Set `PULSAREX_BUILD_PYTHON` to the executable in a different build environment as needed.

```powershell
.\Build-PULSAREX.cmd
```

The script installs build dependencies and runs `PULSAREX-OneFile.spec` in the
project environment. `PULSAREX.spec` remains the earlier folder build used by CI.
The same entry point calls `multiprocessing.freeze_support()` for camera, audio
and launcher child processes.

For a standalone smoke test, copy only the EXE to a separate folder. Run the
test from the build environment with the copied executable as its target.

```powershell
& .\.venv-gui\Scripts\python.exe examples/smoke_executable.py dist/onefile/PULSAREX.exe .test-tmp/onefile-smoke --onefile
```

The smoke test sets a clean Windows PATH and an empty user profile for the child
process. It checks assets, calibration, synthetic two-mic bearings, archive clearing
and recovery from an invalid microphone. `--camera 0` also tests the local webcam
and starts both bundled models with an empty catalogue. `PULSAREX.exe
--check-launcher <output.json>` verifies Tcl, PIN authentication, frozen server
spawning and orderly shutdown. [Validation results](validation.md).
