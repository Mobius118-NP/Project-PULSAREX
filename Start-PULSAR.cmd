@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Install-PULSAR.cmd first.
  pause
  exit /b 1
)
echo PULSAR dashboard: http://127.0.0.1:8765
echo Keep this window open. Press Ctrl+C to stop the server.
if exist "config.toml" (
  ".venv\Scripts\python.exe" -m pulsar.main --config config.toml --open-browser
) else (
  ".venv\Scripts\python.exe" -m pulsar.main --open-browser
)
pause
