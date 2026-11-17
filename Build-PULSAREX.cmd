@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -e ".[packaging,discovery]"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm PULSAREX.spec
if errorlevel 1 exit /b 1
echo Distribute the entire dist\PULSAREX folder. Launch PULSAREX.exe.
copy /Y config.example.toml dist\PULSAREX\config.example.toml >nul
copy /Y LICENSE dist\PULSAREX\LICENSE >nul
copy /Y README.md dist\PULSAREX\README.md >nul
