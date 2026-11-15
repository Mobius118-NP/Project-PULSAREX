@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3.11 or newer is required. Install Python, then run this again.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 (
  echo Installation failed. Check the messages above and your internet connection.
) else (
  echo Ready. Double-click Start-PULSAR.cmd.
)
pause
