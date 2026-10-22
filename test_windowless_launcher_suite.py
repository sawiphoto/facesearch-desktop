# -*- coding: utf-8 -*-
"""
test_windowless_launcher_suite.py
Unit Test Suite for v6.44: No-Console Windowless Launcher Suite
Covers Test Cases: TC-131 through TC-133
"""

import os
import sys
import unittest
import py_compile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


class TestWindowlessLauncherSuite(unittest.TestCase):
    def test_tc131_run_app_bat_structure(self):
        """TC-131: ตรวจสอบโครงสร้างไฟล์ run_app.bat ว่าต้องเป็น Windowless Launcher ไร้หน้าต่างดำ"""
        bat_path = os.path.join(PROJECT_ROOT, "run_app.bat")
        self.assertTrue(os.path.exists(bat_path), "run_app.bat must exist")

        with open(bat_path, "r", encoding="utf-8") as f:
            content = f.read()

        # ต้องใช้ pythonw.exe สำหรับรันแบบไร้คอนโซล
        self.assertIn("pythonw.exe", content, "run_app.bat must use pythonw.exe")
        # ต้องใช้คำสั่ง start ""
        self.assertIn('start ""', content, 'run_app.bat must use start "" to launch asynchronously')
        # ต้องมี cd /d "%~dp0"
        self.assertIn('cd /d "%~dp0"', content, 'run_app.bat must switch to script directory')
        # ต้องมี exit เพื่อปิดหน้าต่าง cmd ทันที
        self.assertIn("exit", content, "run_app.bat must exit immediately")
        # ต้องไม่มีคำสั่ง pause ที่ทำให้หน้าต่างดำค้าง
        self.assertNotIn("pause", content.lower(), "run_app.bat must not contain pause")

    def test_tc132_main_py_pythonw_compatibility(self):
        """TC-132: ตรวจสอบ main.py ว่ารองรับสภาวะ sys.stdout/sys.stderr เป็น None (pythonw.exe)"""
        main_path = os.path.join(PROJECT_ROOT, "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()

        # ตรวจสอบว่ามีการตรวจเช็ค sys.stdout is not None ก่อนเพิ่ม StreamHandler
        self.assertIn("if sys.stdout is not None:", content, "main.py must check if sys.stdout is not None")
        # ตรวจสอบว่ามี FileHandler บันทึกลง app_execution.log
        self.assertIn("FileHandler", content, "main.py must have a FileHandler")
        # ตรวจสอบว่าไม่บล็อกค้างที่ input() ในสภาวะไม่มีคอนโซล (non-isatty)
        self.assertIn("isatty()", content, "main.py must check isatty() before calling input()")

    def test_tc133_version_parity_and_compilation(self):
        """TC-133: ตรวจสอบเลขเวอร์ชัน v6.44 และคอมไพล์โค้ดทุกไฟล์ผ่าน 100%"""
        files = ["main.py", "app_gui.py", "db_manager.py", "gdrive_sync.py"]
        for f in files:
            full_path = os.path.join(PROJECT_ROOT, f)
            py_compile.compile(full_path, doraise=True)

        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            gui_content = f.read()

        self.assertIn("v6.44 (No-Console Windowless Launcher Suite)", gui_content)
        self.assertIn("FACE MATCHING\\nSYSTEM v6.44", gui_content)

        with open(os.path.join(PROJECT_ROOT, "db_manager.py"), "r", encoding="utf-8") as f:
            db_content = f.read()

        self.assertIn('"version": "v6.44"', db_content)


if __name__ == '__main__':
    unittest.main()
