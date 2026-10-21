# -*- coding: utf-8 -*-
"""
test_batch_inactive_teachers_suite.py
Automated Runtime Test Suite for Teacher Inactive Scanning & Batch Deactivation Suite (v6.37)
Test Cases TC-97 through TC-100
"""

import sys
import os
import unittest
import py_compile

# เพิ่ม Root Path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from db_manager import DatabaseManager


class TestBatchInactiveTeachersSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()

    def test_tc97_batch_inactive_status_verification(self):
        """TC-97: ตรวจสอบคุณครูทั้ง 33 ท่าน (ID 241-273) ต้องมีสถานะเป็น inactive 100%"""
        target_ids = list(range(241, 274))
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT id, name, status, role
                FROM staff_members
                WHERE id BETWEEN 241 AND 273
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()

        self.assertEqual(len(rows), 33, "ต้องพบคุณครูในกลุ่มนี้ครบทั้ง 33 ท่าน")
        for r in rows:
            sid, name, status, role = r
            self.assertEqual(status, "inactive", f"ครู ID {sid} ({name}) ต้องมีสถานะเป็น inactive")
            self.assertEqual(role, "teacher", f"ครู ID {sid} ต้องมี role เป็น teacher")
        print(f"[TC-97 PASSED] All 33 teachers (IDs 241-273) verified as 'inactive'.")

    def test_tc98_non_target_staff_integrity(self):
        """TC-98: ตรวจสอบข้อมูลบุคลากรก่อนหน้า (ID < 241) ต้องไม่ได้รับผลกระทบ"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM staff_members
                WHERE id < 241 AND (role = 'teacher' OR role IS NULL OR role = '') AND status = 'active'
            """)
            active_prior_teachers = cursor.fetchone()[0]
        self.assertGreater(active_prior_teachers, 100, "ครูรุ่นก่อนหน้ายังคงมีสถานะ active ปกติ")
        print(f"[TC-98 PASSED] Non-target staff intact ({active_prior_teachers} prior active teachers).")

    def test_tc99_inactive_teachers_scan_retention(self):
        """TC-99: ตรวจสอบว่า get_all_embeddings(active_only=True) ยังคงดึงข้อมูลครูที่เป็น inactive มาสแกนใบหน้า"""
        embs_data = self.db.get_all_embeddings(active_only=True)
        self.assertIn("staff_ids", embs_data)
        self.assertIn("embeddings", embs_data)

        staff_ids_set = set(embs_data["staff_ids"])
        target_ids = list(range(241, 274))

        # ตรวจสอบว่าครูที่เป็น inactive ทั้ง 33 ท่าน ยังคงถูกโหลดเข้าสู่หน่วยความจำเพื่อสแกนใบหน้า
        for tid in target_ids:
            self.assertIn(tid, staff_ids_set, f"ครู ID {tid} ที่เป็น inactive ต้องยังคงอยู่ในชุด embeddings สำหรับสแกน")

        print(f"[TC-99 PASSED] Inactive teachers retention in face scanning verified (33/33 included).")

    def test_tc100_version_v637_parity_and_py_compile(self):
        """TC-100: ตรวจสอบความถูกต้องของเลขเวอร์ชัน v6.37 และการคอมไพล์ py_compile"""
        # 1. py_compile
        py_compile.compile("app_gui.py", doraise=True)
        py_compile.compile("db_manager.py", doraise=True)

        # 2. db_manager manifest
        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertIn('"version": "v6.37"', db_code, "db_manager.py manifest must be v6.37")
        self.assertIn("def batch_update_staff_status", db_code, "db_manager.py must have batch_update_staff_status")

        # 3. app_gui.py
        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()
        self.assertIn("v6.37", gui_code, "app_gui.py must have v6.37")
        self.assertIn("SYSTEM v6.37", gui_code, "app_gui.py sidebar must have v6.37")
        print(f"[TC-100 PASSED] Version v6.37 parity and compilation verified.")


if __name__ == "__main__":
    unittest.main()
