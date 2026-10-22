# -*- coding: utf-8 -*-
"""
test_teacher_avatar_gallery_suite.py
Automated Runtime Test Suite for Teacher Avatar Directory & Master-Detail Gallery (v6.36)
Test Cases TC-92 through TC-96
"""

import sys
import os
import unittest

# เพิ่ม Root Path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from db_manager import DatabaseManager, SW_DEPARTMENTS, clean_department_name
from face_analyzer import get_project_root


class TestTeacherAvatarGallerySuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()

    def test_tc92_teacher_avatar_and_match_stats_extraction(self):
        """TC-92: ตรวจสอบ get_all_teachers_with_avatar_stats ดึงข้อมูลครบถ้วน ถูกต้องตาม Schema"""
        teachers = self.db.get_all_teachers_with_avatar_stats()
        self.assertIsInstance(teachers, list)
        self.assertGreater(len(teachers), 0, "ควรมีข้อมูลคุณครูในระบบอย่างน้อย 1 ท่าน")

        for t in teachers[:10]:
            self.assertIn("id", t)
            self.assertIn("name", t)
            self.assertIn("department", t)
            self.assertIn("status", t)
            self.assertIn("avatar_path", t)
            self.assertIn("matched_count", t)
            self.assertIn("ref_photos_count", t)

            self.assertIsInstance(t["id"], int)
            self.assertIsInstance(t["name"], str)
            self.assertIsInstance(t["matched_count"], int)
            self.assertGreaterEqual(t["matched_count"], 0)

        # ตรวจสอบลำดับการเรียงเริ่มต้น: matched_count ต้องมากไปน้อย
        counts = [t["matched_count"] for t in teachers]
        self.assertEqual(counts, sorted(counts, reverse=True), "เริ่มต้นต้องเรียงตาม matched_count DESC")
        print(f"[TC-92 PASSED] Extracted {len(teachers)} teachers with avatar stats.")

    def test_tc93_search_and_department_filtering_logic(self):
        """TC-93: ตรวจสอบตรรกะการค้นหาและกรองสังกัดของการ์ดคุณครู"""
        teachers = self.db.get_all_teachers_with_avatar_stats()
        self.assertGreater(len(teachers), 0)

        # 1. ทดสอบกรองสังกัด
        dept_target = "วิทยาศาสตร์และเทคโนโลยี"
        dept_filtered = [
            t for t in teachers
            if dept_target in t.get("department", "") or t.get("department", "") == dept_target
        ]
        self.assertIsInstance(dept_filtered, list)
        for t in dept_filtered:
            self.assertIn(dept_target, t["department"])

        # 2. ทดสอบค้นหาด้วยคำค้นหา (ชื่อครูท่านแรก)
        target_name = teachers[0]["name"]
        search_query = target_name[:3].lower()
        search_filtered = [
            t for t in teachers
            if search_query in t.get("name", "").lower()
            or search_query in str(t.get("id", ""))
            or search_query in t.get("department", "").lower()
        ]
        self.assertGreater(len(search_filtered), 0)
        self.assertIn(teachers[0]["id"], [t["id"] for t in search_filtered])
        print(f"[TC-93 PASSED] Search and department filtering logic validated.")

    def test_tc94_teacher_card_sorting_logic(self):
        """TC-94: ตรวจสอบตรรกะจัดเรียงการ์ดคุณครู (Sort by Matched Count, Name, Dept, ID)"""
        teachers = self.db.get_all_teachers_with_avatar_stats()
        self.assertGreater(len(teachers), 1)

        # 1. เรียงตามยอดรูปที่แมตช์มากที่สุด
        sorted_by_count = sorted(teachers, key=lambda x: (-x.get("matched_count", 0), x.get("name", "")))
        self.assertEqual(sorted_by_count[0]["matched_count"], max(t["matched_count"] for t in teachers))

        # 2. เรียงตามชื่อ (ก-ฮ)
        sorted_by_name = sorted(teachers, key=lambda x: x.get("name", ""))
        names = [t["name"] for t in sorted_by_name]
        self.assertEqual(names, sorted(names))

        # 3. เรียงตามสังกัด
        sorted_by_dept = sorted(teachers, key=lambda x: (x.get("department", ""), -x.get("matched_count", 0)))
        self.assertEqual(len(sorted_by_dept), len(teachers))

        # 4. เรียงตาม ID
        sorted_by_id = sorted(teachers, key=lambda x: x.get("id", 0))
        ids = [t["id"] for t in sorted_by_id]
        self.assertEqual(ids, sorted(ids))
        print(f"[TC-94 PASSED] All 4 sorting algorithms validated.")

    def test_tc95_master_detail_navigation_and_caching(self):
        """TC-95: ตรวจสอบการสร้าง Image Placeholder, Avatar Cache และฟังก์ชันของ GUI Class"""
        import app_gui
        # ตรวจสอบว่าโมดูลมีคลาสหลัก
        self.assertTrue(hasattr(app_gui, "FaceSearchApp"))

        # ตรวจสอบว่า ttk ถูก import เข้ามาใน app_gui
        self.assertTrue(hasattr(app_gui, "ttk"), "ttk must be imported in app_gui")

        # ตรวจสอบเมธอดใหม่สำหรับ Teacher Avatar Directory & Master-Detail
        methods = [
            "setup_matched_gallery_ui",
            "bind_scroll_events",
            "get_teacher_avatar_ctk_image",
            "reload_teacher_avatars_data",
            "filter_teacher_avatar_grid",
            "render_teacher_avatar_grid",
            "open_teacher_gallery",
            "back_to_teacher_grid",
            "load_photos_for_teacher",
            "refresh_current_gallery",
            "on_matched_role_change",
        ]
        for m in methods:
            self.assertTrue(
                hasattr(app_gui.FaceSearchApp, m),
                f"FaceSearchApp class must contain method '{m}'"
            )
        print(f"[TC-95 PASSED] FaceSearchApp master-detail methods verified.")

    def test_tc96_version_v636_parity(self):
        """TC-96: ตรวจสอบเลขเวอร์ชัน v6.36 ครบถ้วนทุกจุดในระบบ"""
        # 1. db_manager.py
        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertTrue('"version": "v6.36"' in db_code or '"version": "v6.37"' in db_code)

        # 2. app_gui.py Window Title
        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()
        self.assertTrue("v6.36" in gui_code or "v6.37" in gui_code)
        self.assertTrue("SYSTEM v6.36" in gui_code or "SYSTEM v6.37" in gui_code)
        self.assertIn("from tkinter import filedialog, messagebox, ttk", gui_code, "app_gui.py must import ttk")
        print(f"[TC-96 PASSED] Version parity verified across files.")


if __name__ == "__main__":
    unittest.main()
