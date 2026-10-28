import os
import sys
import unittest
import tempfile
import sqlite3

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db_manager import DatabaseManager

class TestReconcileWithDrive(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_faces.db")
        self.json_path = os.path.join(self.tmpdir.name, "year_folders.json")
        self.db = DatabaseManager(db_path=self.db_path, year_folders_json_path=self.json_path)
        
        # Populate test data
        with self.db.get_connection() as conn:
            c = conn.cursor()
            # 10 live photos
            for i in range(1, 11):
                c.execute(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, academic_year, drive_link) VALUES (?, ?, ?, ?, ?)",
                    (f"P{i:04d}", f"LIVE_FID_{i:04d}", "2530 เมย 15-21 การฝึกอบรม", "25xx", f"http://drive/{i}")
                )
            # 15 moved-out 2550 photos
            for i in range(11, 26):
                c.execute(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, academic_year, drive_link) VALUES (?, ?, ?, ?, ?)",
                    (f"P{i:04d}", f"MOVED_2550_FID_{i:04d}", "2550 ประกวดขยะรีไซเคิล", "25xx", f"http://drive/{i}")
                )
            # 5 moved-out 2549 photos
            for i in range(26, 31):
                c.execute(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, academic_year, drive_link) VALUES (?, ?, ?, ?, ?)",
                    (f"P{i:04d}", f"MOVED_2549_FID_{i:04d}", "2549 รวมกิจกรรม", "25xx", f"http://drive/{i}")
                )
            # 3 moved-out photos without year
            for i in range(31, 34):
                c.execute(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, academic_year, drive_link) VALUES (?, ?, ?, ?, ?)",
                    (f"P{i:04d}", f"MOVED_NOYEAR_FID_{i:04d}", "ภาพกิจกรรมชุมชน", "25xx", f"http://drive/{i}")
                )
            conn.commit()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_reconcile_logic(self):
        # Live drive file IDs only contain the 10 live photos + 2 new unscanned photos
        live_fids = {f"LIVE_FID_{i:04d}" for i in range(1, 11)} | {"NEW_FID_0001", "NEW_FID_0002"}
        
        res = self.db.reconcile_root_year_folder_with_drive(
            folder_id="FOLDER_25XX",
            academic_year="25xx",
            live_drive_file_ids=live_fids
        )
        
        self.assertEqual(res["total_db_before"], 33)
        self.assertEqual(res["matched_count"], 10)
        self.assertEqual(res["moved_out_count"], 23)
        self.assertEqual(res["total_db_after"], 10)
        self.assertEqual(res["new_unscanned_count"], 2)
        
        self.assertEqual(res["moved_out_breakdown"]["2550"], 15)
        self.assertEqual(res["moved_out_breakdown"]["2549"], 5)
        self.assertEqual(res["moved_out_breakdown"]["unassigned"], 3)
        
        # Verify database rows
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM scanned_photos WHERE academic_year = '25xx'")
            self.assertEqual(c.fetchone()[0], 10)
            
            c.execute("SELECT COUNT(*) FROM scanned_photos WHERE academic_year = '2550'")
            self.assertEqual(c.fetchone()[0], 15)
            
            c.execute("SELECT COUNT(*) FROM scanned_photos WHERE academic_year = '2549'")
            self.assertEqual(c.fetchone()[0], 5)
            
            c.execute("SELECT COUNT(*) FROM scanned_photos WHERE academic_year = 'unassigned'")
            self.assertEqual(c.fetchone()[0], 3)
        print("✅ test_reconcile_logic PASSED 100%!")

    def test_extract_year_expansion(self):
        self.assertEqual(DatabaseManager.extract_year_from_text("2550 ประกวดขยะ"), "2550")
        self.assertEqual(DatabaseManager.extract_year_from_text("2549 รวม"), "2549")
        self.assertEqual(DatabaseManager.extract_year_from_text("2530 ธค 5"), "2530")
        self.assertEqual(DatabaseManager.extract_year_from_text("2528 กีฬาจังหวัด"), "2528")
        self.assertEqual(DatabaseManager.extract_year_from_text("ไม่มีปีในนี้"), "")
        print("✅ test_extract_year_expansion PASSED 100%!")

if __name__ == "__main__":
    unittest.main()
