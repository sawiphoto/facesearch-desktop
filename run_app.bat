@echo off
rem ===================================================
rem  ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (Face Search Admin)
rem  Windowless Launcher v6.56 (ไร้หน้าต่างดำ Command Prompt & Self-Healing)
rem ===================================================
cd /d "%~dp0"
start "" "venv\Scripts\pythonw.exe" main.py
exit
