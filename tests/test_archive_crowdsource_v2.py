import unittest
import os
import sys
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db_manager import DatabaseManager

class TestArchiveCrowdsourceV2GeneralInfo(unittest.TestCase):
    """
    ชุดทดสอบโครงสร้างข้อมูลทั่วไปของภาพกิจกรรมในอดีต (v6.70):
    - ตัดข้อมูลตำแหน่งใบหน้า (box_pct / bbox) ออกทั้งหมด 100%
    - ตัดการนับจำนวนใบหน้า (face_count) ออกทั้งหมด 100%
    - ตรวจสอบขนาด JSON กะทัดรัดยิ่งขึ้น (<500 KB สำหรับ 845 ภาพ)
    """

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.data = cls.db.get_archive_crowdsource_data(academic_year="25xx")

    def test_tc160_root_schema_keys(self):
        """TC-160: ตรวจสอบว่า Root Level มีเฉพาะ schema_version และ photos เท่านั้น"""
        self.assertIn("schema_version", self.data)
        self.assertIn("photos", self.data)
        self.assertEqual(self.data["schema_version"], 2)
        self.assertEqual(set(self.data.keys()), {"schema_version", "photos"},
                         "Root Level ต้องมีเฉพาะ schema_version และ photos")

    def test_tc161_photo_general_structure(self):
        """TC-161: ตรวจสอบโครงสร้างภาพว่ามีเฉพาะข้อมูลทั่วไป (ไม่มี dimensions, faces, face_count)"""
        photos = self.data["photos"]
        self.assertGreater(len(photos), 0, "ต้องพบรูปภาพใน 25xx")
        
        # ตรวจสอบภาพ P59508
        self.assertIn("P59508", photos)
        p = photos["P59508"]
        expected_keys = {"photo_id", "drive_file_id", "drive_link", "event", "file_name", "date", "year"}
        self.assertEqual(set(p.keys()), expected_keys, f"โครงสร้างคีย์ไม่ตรง: {set(p.keys())}")
        self.assertTrue(isinstance(p["drive_file_id"], str))
        self.assertTrue(p["drive_link"].startswith("https://drive.google.com/"))
        
        # ยืนยันว่าไม่มีคีย์เกี่ยวกับใบหน้า
        self.assertNotIn("dimensions", p)
        self.assertNotIn("faces", p)
        self.assertNotIn("face_count", p)
        self.assertNotIn("box_pct", p)

    def test_tc164_compact_json_size_extremely_small(self):
        """TC-164: ตรวจสอบขนาด JSON แบบ Compact ต้องต่ำกว่า 500 KB สำหรับ 845 ภาพ (ลดลงจากเดิมที่เคยเกือบ 2 MB)"""
        raw_json = json.dumps(self.data, separators=(',', ':'), ensure_ascii=False)
        size_kb = len(raw_json.encode('utf-8')) / 1024.0
        self.assertLess(size_kb, 500.0, f"ขนาดไฟล์ {size_kb:.2f} KB เกินเกณฑ์ 500 KB")

if __name__ == "__main__":
    unittest.main()
