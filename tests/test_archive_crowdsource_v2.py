import unittest
import os
import sys
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db_manager import DatabaseManager

class TestArchiveCrowdsourceV2UltraMinimal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.data = cls.db.get_archive_crowdsource_data(academic_year="25xx")

    def test_tc160_root_schema_keys(self):
        """TC-160: ตรวจสอบว่า Root Level มีเฉพาะ schema_version และ photos เท่านั้น"""
        self.assertIn("schema_version", self.data)
        self.assertIn("photos", self.data)
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(set(self.data.keys()), {"schema_version", "photos"},
                         "Root Level ต้องมีเฉพาะ schema_version และ photos")

    def test_tc161_photo_structure(self):
        """TC-161: ตรวจสอบโครงสร้างภาพว่ามีเฉพาะ drive_file_id, dimensions และ faces"""
        photos = self.data["photos"]
        self.assertGreater(len(photos), 0, "ต้องพบรูปภาพใน 25xx")
        
        # ตรวจสอบภาพ P59508
        self.assertIn("P59508", photos)
        p = photos["P59508"]
        self.assertEqual(set(p.keys()), {"drive_file_id", "dimensions", "faces"})
        self.assertTrue(isinstance(p["drive_file_id"], str))
        self.assertIn("width", p["dimensions"])
        self.assertIn("height", p["dimensions"])
        self.assertGreater(p["dimensions"]["width"], 0)
        self.assertGreater(p["dimensions"]["height"], 0)

    def test_tc162_face_structure_and_id_format(self):
        """TC-162: ตรวจสอบโครงสร้างใบหน้า face_id ในรูปแบบ P59508_F001 และ box_pct"""
        p = self.data["photos"]["P59508"]
        faces = p["faces"]
        self.assertGreater(len(faces), 0)
        f0 = faces[0]
        self.assertEqual(set(f0.keys()), {"face_id", "box_pct"})
        self.assertEqual(f0["face_id"], "P59508_F001")
        
        box = f0["box_pct"]
        self.assertEqual(set(box.keys()), {"left", "top", "width", "height"})
        self.assertAlmostEqual(box["left"], 51.1, delta=0.5)
        self.assertAlmostEqual(box["top"], 40.88, delta=0.5)

    def test_tc163_all_coordinates_clamped(self):
        """TC-163: ตรวจสอบว่าพิกัดทุกใบหน้าอยู่ในช่วง 0.0 - 100.0% ไม่มีค่าติดลบ"""
        for pid, p in self.data["photos"].items():
            for f in p["faces"]:
                b = f["box_pct"]
                self.assertGreaterEqual(b["left"], 0.0)
                self.assertLessEqual(b["left"], 100.0)
                self.assertGreaterEqual(b["top"], 0.0)
                self.assertLessEqual(b["top"], 100.0)
                self.assertGreater(b["width"], 0.0)
                self.assertLessEqual(b["width"], 100.0)
                self.assertGreater(b["height"], 0.0)
                self.assertLessEqual(b["height"], 100.0)

    def test_tc164_compact_json_size(self):
        """TC-164: ตรวจสอบขนาด JSON แบบ Compact ต้องต่ำกว่า 300 KB (เป้าหมาย <4 MB)"""
        raw_json = json.dumps(self.data, separators=(',', ':'), ensure_ascii=False)
        size_kb = len(raw_json.encode('utf-8')) / 1024.0
        self.assertLess(size_kb, 300.0, f"ขนาดไฟล์ {size_kb:.2f} KB เกินเกณฑ์ 300 KB")

if __name__ == "__main__":
    unittest.main()
