@echo off
echo ===================================================
echo  Face Search Admin - Debug Console Mode (v6.44)
echo ===================================================
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Starting Application in Debug Console Mode...
python main.py
echo.
echo Application closed.
pause
