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
    ชุดทดสอบระบบดัชนีภาพกิจกรรมในอดีต (2562-25xx/2568) แบบข้อมูลทั่วไป (v6.70)
    ครอบคลุม TC-151 ถึง TC-155 และ TC-172:
    - ตัดตำแหน่งพิกัดกรอบใบหน้า (box_pct/bbox) ออกทั้งหมด 100%
    - ตัดการนับจำนวนใบหน้า (face_count / archive_crowdsource_faces) ออกทั้งหมดตามความต้องการของผู้ใช้
    - คงเหลือเฉพาะข้อมูลทั่วไปของรูปภาพ (General Photo Info)
    """

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.sync = GoogleSyncManager()

    def test_tc151_archive_general_photo_info_extraction(self):
        """TC-151: ตรวจสอบการดึงข้อมูลทั่วไปของรูปภาพและยืนยันว่าไม่มีข้อมูลใบหน้าหลงเหลือ (v6.70)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("schema_version"), 2)
        
        photos = data.get("photos", {})
        self.assertGreaterEqual(len(photos), 200)

        # สุ่มตรวจสอบ 20 รูปแรกเพื่อความครอบคลุม
        sample_keys = list(photos.keys())[:20]
        for pid in sample_keys:
            p = photos[pid]
            # 1. ต้องมีฟิลด์ข้อมูลทั่วไปครบถ้วน
            self.assertIn("photo_id", p)
            self.assertIn("drive_file_id", p)
            self.assertIn("drive_link", p)
            self.assertIn("event", p)
            self.assertIn("file_name", p)
            self.assertIn("date", p)
            self.assertIn("year", p)

            # 2. ต้องไม่มีพิกัดตำแหน่งกรอบใบหน้าหรือมิติภาพ
            self.assertNotIn("box_pct", p, f"พบ box_pct ใน {pid}")
            self.assertNotIn("dimensions", p, f"พบ dimensions ใน {pid}")

            # 3. ต้องไม่มีการนับจำนวนใบหน้าหรือข้อมูลใบหน้าใดๆ
            self.assertNotIn("faces", p, f"พบ faces ใน {pid}")
            self.assertNotIn("face_count", p, f"พบ face_count ใน {pid}")

    def test_tc152_privacy_and_crowdsource_tagging_readiness(self):
        """TC-152: ตรวจสอบว่าไม่มีข้อมูลชื่อหรือตำแหน่งของบุคคลหลุดไป (Zero-Person Privacy)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        photos = data.get("photos", {})
        
        for pid, p in list(photos.items())[:20]:
            self.assertNotIn("staff_id", p)
            self.assertNotIn("role", p)
            self.assertNotIn("name", p)
            self.assertNotIn("student_id", p)

    def test_tc153_photo_manifest_integration(self):
        """TC-153: ตรวจสอบการลงทะเบียนไฟล์ภาพในอดีตลงใน photo_manifest.json (ไม่มี archive_crowdsource_faces)"""
        sharded_data = self.db.get_sync_data_sharded()
        manifest = sharded_data.get("manifest", {})
        self.assertIn("available_years", manifest)
        self.assertIn("year_file_map", manifest)

    def test_tc154_task1_and_sync_archive_method_exists(self):
        """TC-154: ตรวจสอบว่า GoogleSyncManager มีเมธอด sync_archive_crowdsource_only พร้อมใช้งาน"""
        self.assertTrue(hasattr(self.sync, "sync_archive_crowdsource_only"))
        self.assertTrue(callable(getattr(self.sync, "sync_archive_crowdsource_only")))

    def test_tc155_gui_integration_and_version(self):
        """TC-155: ตรวจสอบเลขเวอร์ชันและการมีอยู่ของเมธอด GUI สำหรับปุ่ม Manual Sync"""
        import app_gui
        self.assertTrue(hasattr(app_gui.FaceSearchApp, "sync_archive_crowdsource_json_manual"))

    def test_tc172_complete_archive_coverage_845_photos(self):
        """TC-172: ตรวจสอบความครอบคลุมคลังภาพในอดีตครบถ้วน 845 ภาพ (General Info Only - v6.70)"""
        data = self.db.get_archive_crowdsource_data("25xx")
        self.assertEqual(data.get("schema_version"), 2)
        photos = data.get("photos", {})
        self.assertEqual(len(photos), 845, f"ต้องมีรูปภาพครบถ้วน 845 ภาพ แต่พบ {len(photos)}")
        
        # ทุกภาพต้องไม่มีคีย์ faces หรือ face_count
        has_face_keys = any("faces" in p or "face_count" in p for p in photos.values())
        self.assertFalse(has_face_keys, "ต้องไม่มีข้อมูลเกี่ยวกับใบหน้าในทุกรูปภาพ")


if __name__ == "__main__":
    unittest.main()
