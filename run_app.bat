@echo off
echo ==========================================
echo    Face Search Admin Console (v1.7.9)
echo ==========================================
echo Starting Virtual Environment...
call venv\Scripts\activate.bat

echo Starting Application...
python main.py

echo.
echo Application closed.
pause
