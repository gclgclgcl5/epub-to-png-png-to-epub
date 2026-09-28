@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m PyInstaller -F -w -n EpubToPng --clean main.py
echo.
echo Build finished. Output: dist\EpubToPng.exe
pause
