import unittest
import sqlite3
import py_compile
import os
import sys

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

class TestDateReconciliationSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "data/faces_db.db"
        cls.db = DatabaseManager(cls.db_path)

    def test_tc134_database_backfill_zero_contamination(self):
        """TC-134: ตรวจสอบความถูกต้องของฐานข้อมูล ไม่เหลือภาพปีย้อนหลัง 2563-2565 ที่มี photo_date ปี 2026"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM scanned_photos
            WHERE photo_date LIKE '2026%' AND academic_year IN ('2563', '2564', '2565')
        """)
        mismatch_cnt = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(mismatch_cnt, 0, f"Expected 0 mismatched 2026 photos in past years, got {mismatch_cnt}")

    def test_tc135_specific_event_date_parity(self):
        """TC-135: ตรวจสอบรูปภาพเป้าหมาย P53723, P53676, P53650 ต้องมีวันที่ 2022-03-22 และปีการศึกษา 2564"""
        target_ids = ('P53723', 'P53676', 'P53650')
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT photo_id, photo_date, academic_year, event_name
            FROM scanned_photos
            WHERE photo_id IN (?, ?, ?)
        """, target_ids)
        rows = cursor.fetchall()
        conn.close()

        self.assertEqual(len(rows), 3)
        for pid, pdate, a_year, ev in rows:
            self.assertEqual(pdate, "2022-03-22", f"Photo {pid} date mismatch: {pdate}")
            self.assertEqual(a_year, "2564", f"Photo {pid} academic year mismatch: {a_year}")
            self.assertIn("วันม่วงเหลือง64", ev)

    def test_tc136_smart_date_parser_scenarios(self):
        """TC-136: ทดสอบ parse_smart_photo_date กับกรณีทดสอบหลากหลายรูปแบบ"""
        # 1. Thai Numerals in LINE album
        d1 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="วันม่วงเหลือง64",
            file_name="LINE_ALBUM_วันม่วงเหลือง64_๒๒๐๓๒๒_163.jpg",
            academic_year="2564"
        )
        self.assertEqual(d1, "2022-03-22")

        # 2. Arabic Numerals in LINE album
        d2 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="วันเพ็ญ64",
            file_name="LINE_ALBUM_วันเพ็ญ64_211119_267.jpg",
            academic_year="2564"
        )
        self.assertEqual(d2, "2021-11-19")

        # 3. Explicit date in folder name (DD-MM-YY)
        d3 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="เยี่ยม รร 14-07-63 ปี 2563",
            file_name="IMG_1234.JPG"
        )
        self.assertEqual(d3, "2020-07-14")

        # 4. Thai month text with academic_year
        d4 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="ประชุม ผปค 23 พย",
            file_name="IMG_6018.JPG",
            academic_year="2564"
        )
        self.assertEqual(d4, "2021-11-23")

        # 5. School event keyword heuristic
        d5 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="สอบธรรมศึกษาปี63",
            file_name="IMG_8097.JPG"
        )
        self.assertEqual(d5, "2020-11-20")

        # 6. Upload date pollution guard: createdTime in 2026 must NOT override historical academic_year
        d6 = GoogleSyncManager.parse_smart_photo_date(
            folder_name="กิจกรรมทั่วไป 2564",
            file_name="IMG_9999.JPG",
            file_meta={"createdTime": "2026-10-16T08:00:00Z"},
            academic_year="2564"
        )
        self.assertTrue(d6.startswith("2021-"), f"Pollution guard failed: {d6}")

    def test_tc137_gallery_grouping_and_sorting(self):
        """TC-137: ทดสอบ get_matched_photos_for_staff ส่ง academic_year และจัดเรียงถูกต้อง"""
        matches = self.db.get_matched_photos_for_staff(60) # ครูพิมพ์ชนก
        self.assertGreater(len(matches), 0)
        
        # ตรวจสอบว่ามี academic_year ในข้อมูล
        first_item = matches[0]
        self.assertIn("academic_year", first_item)
        self.assertIn("photo_date", first_item)

        # ตรวจสอบว่ารูปเป้าหมาย P53723 มีวันที่ 2022-03-22 และ academic_year 2564
        target_item = next((m for m in matches if m["photo_id"] == "P53723"), None)
        self.assertIsNotNone(target_item)
        self.assertEqual(target_item["photo_date"], "2022-03-22")
        self.assertEqual(target_item["academic_year"], "2564")

        # ตรวจสอบการแปลง Header
        from app_gui import FaceSearchApp
        header_text = FaceSearchApp.format_month_year_header(None, "2022-03-22", academic_year="2564")
        self.assertIn("มีนาคม พ.ศ. 2565", header_text)
        self.assertIn("ปีการศึกษา 2564", header_text)

    def test_tc138_version_parity_and_compilation(self):
        """TC-138: ตรวจสอบความสอดคล้องของเวอร์ชัน v6.45 และไวยากรณ์โค้ด"""
        for mod in ["gdrive_sync.py", "db_manager.py", "app_gui.py"]:
            py_compile.compile(mod, doraise=True)

        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()

        self.assertIn("v6.45 (Smart Event Date & Academic Year Reconciliation Suite)", gui_code)
        self.assertIn("SYSTEM v6.45", gui_code)

if __name__ == "__main__":
    unittest.main()
