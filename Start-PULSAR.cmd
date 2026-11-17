@echo off
cd /d "%~dp0"
set "PULSAREX_RUNTIME=.venv\Scripts\pythonw.exe"
if exist ".venv-gui\Scripts\pythonw.exe" set "PULSAREX_RUNTIME=.venv-gui\Scripts\pythonw.exe"
if not exist "%PULSAREX_RUNTIME%" (
  echo Run Install-PULSAR.cmd first.
  pause
  exit /b 1
)
start "" "%PULSAREX_RUNTIME%" -m pulsar.launcher
