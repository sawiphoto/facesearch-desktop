import unittest
import os
import sys
import json
import sqlite3

# รองรับ Dynamic sys.path Resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

class TestArchiveCrowdsourceSync(unittest.TestCase):
    """
    ชุดทดสอบระบบดัชนีภาพกิจกรรมในอดีต (2562-25xx) สำหรับ Crowdsourcing Tagging (v6.49)
    ครอบคลุม TC-151 ถึง TC-155
    """

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.sync = GoogleSyncManager()

    def test_tc151_archive_crowdsource_data_extraction_and_pct_bounds(self):
        """TC-151: ตรวจสอบการดึงข้อมูลและขอบเขตพิกัดเปอร์เซ็นต์ (Ultra-Minimal v6.53)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("schema_version"), 1)
        
        photos = data.get("photos", {})
        self.assertGreaterEqual(len(photos), 200)

        # สุ่มตรวจสอบ 15 รูปแรกเพื่อความรวดเร็วและแม่นยำ
        sample_keys = list(photos.keys())[:15]
        for pid in sample_keys:
            p = photos[pid]
            self.assertIn("drive_file_id", p)
            self.assertIn("dimensions", p)
            self.assertGreater(p["dimensions"]["width"], 0)
            self.assertGreater(p["dimensions"]["height"], 0)

            for face in p.get("faces", []):
                self.assertIn("face_id", face)
                self.assertIn("box_pct", face)

                bp = face["box_pct"]
                # ตรวจสอบว่าพิกัดเปอร์เซ็นต์ต้องอยู่ในช่วง 0.0 - 100.0%
                self.assertTrue(0.0 <= bp["left"] <= 100.0, f"box left {bp['left']} out of range")
                self.assertTrue(0.0 <= bp["top"] <= 100.0, f"box top {bp['top']} out of range")
                self.assertTrue(0.0 < bp["width"] <= 100.0, f"box width {bp['width']} out of range")
                self.assertTrue(0.0 < bp["height"] <= 100.0, f"box height {bp['height']} out of range")

    def test_tc152_privacy_and_crowdsource_tagging_readiness(self):
        """TC-152: ตรวจสอบว่าไม่มีข้อมูลชื่อหรือตำแหน่งของบุคคลหลุดไป (Zero-Person Privacy)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        photos = data.get("photos", {})
        
        for pid, p in list(photos.items())[:20]:
            # ต้องไม่มีคีย์ staff_id, role, student_id, หรือ name ในระดับ photo หรือ face
            self.assertNotIn("staff_id", p)
            self.assertNotIn("role", p)
            self.assertNotIn("name", p)
            for face in p.get("faces", []):
                self.assertNotIn("staff_id", face)
                self.assertNotIn("name", face)
                self.assertNotIn("role", face)

    def test_tc153_photo_manifest_integration(self):
        """TC-153: ตรวจสอบการลงทะเบียนไฟล์ภาพในอดีตลงใน photo_manifest.json"""
        sharded_data = self.db.get_sync_data_sharded()
        manifest = sharded_data.get("manifest", {})
        self.assertIn("available_years", manifest)
        self.assertIn("year_file_map", manifest)
        self.assertEqual(manifest.get("version"), "v6.64")

    def test_tc154_task1_and_sync_archive_method_exists(self):
        """TC-154: ตรวจสอบว่า GoogleSyncManager มีเมธอด sync_archive_crowdsource_only พร้อมใช้งาน"""
        self.assertTrue(hasattr(self.sync, "sync_archive_crowdsource_only"))
        self.assertTrue(callable(getattr(self.sync, "sync_archive_crowdsource_only")))

    def test_tc155_gui_integration_and_version(self):
        """TC-155: ตรวจสอบเลขเวอร์ชันและการมีอยู่ของเมธอด GUI สำหรับปุ่ม Manual Sync"""
        import app_gui
        self.assertTrue(hasattr(app_gui.FaceSearchApp, "sync_archive_crowdsource_json_manual"))

    def test_tc172_complete_archive_coverage_845_photos(self):
        """TC-172: ตรวจสอบความครอบคลุมคลังภาพในอดีตครบถ้วน 845 ภาพ (802 ภาพมีใบหน้า, 43 ภาพ faces: []) (v6.57)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        self.assertEqual(data.get("schema_version"), 1)
        photos = data.get("photos", {})
        self.assertEqual(len(photos), 845, f"ต้องมีรูปภาพครบถ้วน 845 ภาพ แต่พบ {len(photos)}")
        
        with_faces = sum(1 for p in photos.values() if len(p.get("faces", [])) > 0)
        empty_faces = sum(1 for p in photos.values() if len(p.get("faces", [])) == 0)
        total_faces = sum(len(p.get("faces", [])) for p in photos.values())
        
        self.assertEqual(with_faces, 802, "ภาพที่มีใบหน้าต้องมี 802 ภาพ")
        self.assertEqual(empty_faces, 43, "ภาพที่ไม่มีใบหน้า (faces: []) ต้องมี 43 ภาพ")
        self.assertEqual(total_faces, 8307, "จุดใบหน้าทั้งหมดต้องมี 8,307 จุด")


if __name__ == "__main__":
    unittest.main()
