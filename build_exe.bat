@echo off
setlocal
cd /d "%~dp0"
set "APP_VERSION=1.1.1"

py -3.14 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name AutoThaumcraftResearch-v%APP_VERSION% ^
  --version-file "%CD%\version_info.txt" ^
  --specpath build ^
  --workpath build\work ^
  --distpath dist ^
  --add-data "%CD%\class.txt;." ^
  --add-data "%CD%\ys.txt;." ^
  --add-data "%CD%\auto_thaumcraft_research.zip;." ^
  main.py

if errorlevel 1 exit /b %errorlevel%
echo Built: dist\AutoThaumcraftResearch-v%APP_VERSION%.exe
