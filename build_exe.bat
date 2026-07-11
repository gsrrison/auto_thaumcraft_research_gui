@echo off
setlocal
cd /d "%~dp0"

py -3.14 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name AutoThaumcraftResearch ^
  --specpath build ^
  --workpath build\work ^
  --distpath dist ^
  --add-data "%CD%\class.txt;." ^
  --add-data "%CD%\ys.txt;." ^
  --add-data "%CD%\auto_thaumcraft_research.zip;." ^
  main.py

if errorlevel 1 exit /b %errorlevel%
echo Built: dist\AutoThaumcraftResearch.exe
