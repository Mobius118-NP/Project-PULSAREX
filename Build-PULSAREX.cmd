@echo off
setlocal
cd /d "%~dp0"
if not defined PULSAREX_BUILD_PYTHON (
  set "PULSAREX_BUILD_PYTHON=.venv\Scripts\python.exe"
  if exist ".venv-gui\Scripts\python.exe" set "PULSAREX_BUILD_PYTHON=.venv-gui\Scripts\python.exe"
  if exist ".venv-onefile\Scripts\python.exe" set "PULSAREX_BUILD_PYTHON=.venv-onefile\Scripts\python.exe"
)
"%PULSAREX_BUILD_PYTHON%" -c "import sys, tkinter; assert sys.version_info[:3] != (3, 12, 0), 'Python 3.12.0 has a freezing bug'; tkinter.Tcl()"
if errorlevel 1 (
  echo The build requires full Windows Python 3.11 or 3.12.1+ with Tcl/Tk.
  exit /b 1
)
"%PULSAREX_BUILD_PYTHON%" -m pip install -e ".[packaging,discovery,vision]"
if errorlevel 1 exit /b 1
"%PULSAREX_BUILD_PYTHON%" -m PyInstaller --noconfirm --distpath dist\onefile --workpath build\onefile PULSAREX-OneFile.spec
if errorlevel 1 exit /b 1
echo Built dist\onefile\PULSAREX.exe for local non-commercial research.
