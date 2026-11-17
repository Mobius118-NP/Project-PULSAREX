# GUI launcher - 0.4.0

No PowerShell commands are needed for normal Windows operation.

1. Extract the complete Windows ZIP into a folder.
2. Double-click **PULSAREX.exe**. The native launcher opens without a terminal.
3. Choose **LAN (same Wi-Fi)** to allow authorized browsers on your local network,
   or **Local only** for this computer.
4. Keep the generated access token or enter one with 16-512 characters. **Generate**
   replaces it; **Copy token** lets you paste it into the dashboard login. It is
   masked initially, kept in process memory and never saved in preferences or URLs.
5. Choose **Synthetic demonstration** or **Live microphone**, then **Start server**.
6. Once the status says running, use **Open dashboard** here. For another device,
   click **Copy LAN link**, open that link on the same Wi-Fi/LAN, and enter the token.
7. **Stop server** closes capture and releases the server port. Closing the launcher
   also stops its server. Leave the window open while using the dashboard.

The LAN link is detected on each start. The selector lists available IPv4 addresses
and prefers the current outbound adapter; virtual adapters may also appear. Choose
the adapter shared with the other device. LAN URLs are shown only for LAN mode;
links are enabled only after successful server startup. A link is not a guarantee
that a second device can reach through a firewall or Wi-Fi client isolation.

Use a trusted private network. HTTP is unencrypted. No router, firewall, UPnP or
public internet settings are changed. No cloud account is required. The launcher
does not save or record raw audio. Microphone and two-mic geometry configuration
remain in the dashboard; an optional TOML file can supply advanced startup settings.

## Preferences and credentials

Mode, port, selected audio source, optional TOML path and browser preference persist
in `launcher-settings.json` in the application data directory. This file has an
explicit allow-list and cannot contain the token. A new random token is generated
when the launcher opens. Changes to token/connection settings are locked while its
server runs; stop before changing them. Copying the token is an explicit operator
action. Avoid leaving a sensitive token on a shared clipboard.

Packaged data default to `%LOCALAPPDATA%\PULSAREX`; source launches use the project's
`data` directory. Relative data paths in a selected TOML resolve beside that file.
Runtime dashboard controls and saved profiles keep their existing behavior.

## Lifecycle and failures

Tk stays on the main GUI thread. A spawned non-daemon process owns FastAPI/Uvicorn;
it can spawn the existing native microphone process. A private event requests
graceful shutdown so capture and SQLite writes finish. The GUI polls bounded status
messages and stays responsive. Startup can be cancelled. A watchdog detects the
launcher's disappearance; a hung owned process tree is terminated after a shutdown
deadline. The launcher never stops another application using the chosen port.

Occupied ports and invalid settings produce visible errors before startup. Pick a
different port or stop the existing application. Cold packaged startup can take
tens of seconds on this host; the launcher shows Starting and allows cancellation.
Live microphone errors are reported in the dashboard without stopping HTTP service.

## Source and console operation

For a source checkout, install with a full Windows Python distribution containing
Tcl/Tk, then double-click `Start-PULSAR.cmd`. It runs the GUI using `pythonw.exe`.
This development workspace also has an isolated `.venv-gui` environment because its
original bundled Python lacks compatible Tcl/Tk assets. The script prefers that
environment when present; ordinary installations use `.venv`.

The package retains **PULSAREX-Console.exe** for advanced command-line use. The
existing Python command `python -m pulsar.main` is unchanged. `PULSAREX.exe` with
explicit server arguments remains available for automated headless checks, while
double-clicking it without arguments opens the GUI.

Build using `Build-PULSAREX.cmd`. PyInstaller bundles Tk, Tcl, PortAudio, dashboard
assets and dependencies; end users do not need Python installed. The GUI and console
executables share their `_internal` directory, which must stay with them.

References: [Tk's event/thread model](https://docs.python.org/3/library/tkinter.html#threading-model),
[PyInstaller multiprocessing and windowed streams](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
