@echo off
cd /d "%~dp0"
set "PULSAREX_BUILD_PYTHON=.venv\Scripts\python.exe"
if exist ".venv-gui\Scripts\python.exe" set "PULSAREX_BUILD_PYTHON=.venv-gui\Scripts\python.exe"
"%PULSAREX_BUILD_PYTHON%" -c "import tkinter; tkinter.Tcl()"
if errorlevel 1 (
  echo A full Windows Python installation with Tcl/Tk is required to build the GUI.
  exit /b 1
)
"%PULSAREX_BUILD_PYTHON%" -m pip install -e ".[packaging,discovery]"
if errorlevel 1 exit /b 1
"%PULSAREX_BUILD_PYTHON%" -m PyInstaller --noconfirm PULSAREX.spec
if errorlevel 1 exit /b 1
echo Distribute the entire dist\PULSAREX folder. Launch PULSAREX.exe.
copy /Y config.example.toml dist\PULSAREX\config.example.toml >nul
copy /Y LICENSE dist\PULSAREX\LICENSE >nul
copy /Y README.md dist\PULSAREX\README.md >nul
xcopy /E /I /Y docs dist\PULSAREX\docs >nul
copy /Y docs\launcher-quick-start.txt dist\PULSAREX\START-HERE.txt >nul
xcopy /E /I /Y docs dist\PULSAREX\docs >nul
