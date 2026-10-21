import os
import sys
import unittest
import sqlite3
import py_compile

PROJECT_ROOT = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_manager import DatabaseManager, clean_department_name
from gdrive_sync import GoogleSyncManager

class TestDualStaffPhotoSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(PROJECT_ROOT, "data", "faces_db.db")
        cls.db = DatabaseManager(cls.db_path)

    def test_tc121_schema_migration(self):
        """TC-121: Staff Members Schema Migration - Verify original_image_path and cropped_image_path exist"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("PRAGMA table_info(staff_members)")
            cols = [r[1] for r in c.fetchall()]
            self.assertIn("original_image_path", cols, "original_image_path must exist in staff_members")
            self.assertIn("cropped_image_path", cols, "cropped_image_path must exist in staff_members")

    def test_tc122_former_multi_photo_selection(self):
        """TC-122: Former Teacher Multi-Photo Selection Rule - Verify image 1 was selected for Waralee"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, original_image_path FROM staff_members WHERE id = 251")
            row = c.fetchone()
            self.assertIsNotNone(row)
            orig_p = row[2]
            self.assertTrue(os.path.exists(orig_p), f"Original photo file must exist: {orig_p}")
            # Verify file size matches image 1 (333,807 bytes), not image 2 (505,303 bytes)
            file_size = os.path.getsize(orig_p)
            self.assertEqual(file_size, 333807, "Must select photo 1 (333,807 bytes)")

    def test_tc123_dual_photo_population_completeness(self):
        """TC-123: Dual Photo Population Completeness - All 168 teachers have non-empty paths"""
        teachers = self.db.get_all_teachers()
        self.assertEqual(len(teachers), 168, "Must have exactly 168 teachers")
        for t in teachers:
            self.assertTrue(bool(t.get("original_image_path")), f"Teacher {t['id']} {t['name']} must have original_image_path")
            self.assertTrue(bool(t.get("cropped_image_path")), f"Teacher {t['id']} {t['name']} must have cropped_image_path")
            self.assertTrue(bool(t.get("avatar_path")), f"Teacher {t['id']} {t['name']} must have avatar_path")

    def test_tc124_original_photo_local_directories(self):
        """TC-124: Original Photo Local Directories - Active has 122 files, Inactive has 46 files"""
        act_dir = os.path.join(PROJECT_ROOT, "data", "original_staff_photos", "active")
        inact_dir = os.path.join(PROJECT_ROOT, "data", "original_staff_photos", "inactive")
        
        self.assertTrue(os.path.exists(act_dir), "Active dir must exist")
        self.assertTrue(os.path.exists(inact_dir), "Inactive dir must exist")
        
        act_files = os.listdir(act_dir)
        inact_files = os.listdir(inact_dir)
        self.assertEqual(len(act_files), 122, "Must have exactly 122 active photos")
        self.assertEqual(len(inact_files), 46, "Must have exactly 46 inactive photos")

    def test_tc125_version_parity_and_compilation(self):
        """TC-125: Version Parity v6.42 & py_compile check"""
        files_to_compile = [
            os.path.join(PROJECT_ROOT, "db_manager.py"),
            os.path.join(PROJECT_ROOT, "gdrive_sync.py"),
            os.path.join(PROJECT_ROOT, "app_gui.py")
        ]
        for f in files_to_compile:
            py_compile.compile(f, doraise=True)

        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), encoding="utf-8") as f:
            content = f.read()
            self.assertTrue("v6.42" in content or "v6.43" in content)
            self.assertTrue("SYSTEM v6.42" in content or "SYSTEM v6.43" in content)

if __name__ == '__main__':
    unittest.main()
