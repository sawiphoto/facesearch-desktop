import unittest
import os
import sys
import json
import sqlite3
import py_compile

PROJECT_ROOT = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_manager import DatabaseManager

class TestDepartmentAndStatusSyncSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(PROJECT_ROOT, "data", "faces_db.db")
        cls.db = DatabaseManager()

    def test_tc106_database_department_and_inactive_status(self):
        """TC-106: ตรวจสอบความถูกต้องของสังกัดกลุ่มสาระ และสถานะ active/inactive ในฐานข้อมูล SQLite"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, department, status FROM staff_members WHERE role = 'teacher' OR role IS NULL OR role = ''")
            rows = cursor.fetchall()

        self.assertEqual(len(rows), 168, "ต้องมีบุคลากรครูรวม 168 ท่านในฐานข้อมูล")
        
        teacher_map = {r[1]: {"id": r[0], "dept": r[2], "status": r[3]} for r in rows}

        # 4 รายชื่อที่เคยอยู่ทั้งโฟลเดอร์ปกติและอดีตบุคลากร (สำเนา) ต้องถูกบังคับเป็น inactive
        duplicate_four = [
            ("นายธนา เทพวารินทร์", "ภาษาต่างประเทศ"),
            ("นางศิโรรัตน์ เปรมไธสง", "วิทยาศาสตร์และเทคโนโลยี"),
            ("นายพงศกร ยังสวัสดิ์", "คณิตศาสตร์"),
            ("นางสาวสุดารัตน์ เสนสิงห์", "ภาษาไทย")
        ]
        for name, expected_dept in duplicate_four:
            self.assertIn(name, teacher_map, f"ต้องพบบุคลากร {name} ในฐานข้อมูล")
            info = teacher_map[name]
            self.assertEqual(info["status"], "inactive", f"{name} ต้องมีสถานะเป็น inactive (อดีตบุคลากร)")
            self.assertEqual(info["dept"], expected_dept, f"{name} ต้องมีสังกัด {expected_dept}")

        # ตรวจสอบ 13 อดีตบุคลากรที่มาจากโฟลเดอร์อดีตบุคลากร
        former_13 = [
            "นางศิโรรัตน์ เปรมไธสง", "นางสาวสุดารัตน์ เสนสิงห์", "นายธนา เทพวารินทร์", "นายพงศกร ยังสวัสดิ์",
            "นายบำรุง อุชุภาพ", "นายสมชาย สังข์ดี", "นางพันธ์ทิพย์ จิตร์ไพศาลศักดิ์", "นายเกรียงศักดิ์ อัจกลับ",
            "นางสาวอุษณีย์ โยธินะเวคิน", "นางสาวจุไรรัตน์ อ่อนมุข", "นายกำพล ชุ่มจันทร์", "นายไกรวัลย์ สังฆะสา", "นายชาญชัย ผลอุบัติ"
        ]
        for name in former_13:
            self.assertIn(name, teacher_map, f"ต้องพบอดีตบุคลากร {name} ในฐานข้อมูล")
            self.assertEqual(teacher_map[name]["status"], "inactive", f"{name} ต้องมีสถานะ inactive")
            self.assertTrue(len(teacher_map[name]["dept"]) > 0, f"{name} ต้องมีกลุ่มสาระ/สังกัด")

        # ตรวจสอบสถิติรวม active และ inactive
        active_count = sum(1 for r in rows if r[3] == "active")
        inactive_count = sum(1 for r in rows if r[3] == "inactive")
        self.assertEqual(active_count, 122, "ต้องมีบุคลากรปัจจุบัน (active) จำนวน 122 ท่าน (120 จาก Drive + 2 ครูต่างชาติ)")
        self.assertEqual(inactive_count, 46, "ต้องมีอดีตบุคลากร (inactive) จำนวน 46 ท่าน (13 จาก Drive + 33 เดิม)")

    def test_tc107_sharded_json_index_generation(self):
        """TC-107: ตรวจสอบโครงสร้างข้อมูล Sharded JSON Index จาก db_manager"""
        sync_data = self.db.get_sync_data_sharded()
        
        self.assertIn("active_staff", sync_data)
        self.assertIn("former_staff", sync_data)
        self.assertIn("teachers", sync_data)
        self.assertIn("manifest", sync_data)
        
        self.assertEqual(len(sync_data["active_staff"]), 121)
        self.assertEqual(len(sync_data["former_staff"]), 19)
        self.assertEqual(sync_data["manifest"]["staff_counts"]["active"], 121)
        self.assertEqual(sync_data["manifest"]["staff_counts"]["former"], 19)

    def test_tc108_audit_log_file_integrity(self):
        """TC-108: ตรวจสอบความถูกต้องและครบถ้วนของ Audit Log"""
        audit_file = os.path.join(PROJECT_ROOT, "data", "staff_update_audit_v639.json")
        self.assertTrue(os.path.exists(audit_file), "ไฟล์ staff_update_audit_v639.json ต้องมีอยู่จริง")
        
        with open(audit_file, "r", encoding="utf-8") as f:
            audit_log = json.load(f)
            
        self.assertEqual(len(audit_log), 133, "Audit log ต้องบันทึกผลการแมตช์ครบทั้ง 133 รายชื่อจาก Drive")

    def test_tc109_version_parity(self):
        """TC-109: ตรวจสอบความสอดคล้องของเลขเวอร์ชัน v6.39 ข้ามระบบ"""
        app_gui_path = os.path.join(PROJECT_ROOT, "app_gui.py")
        with open(app_gui_path, "r", encoding="utf-8") as f:
            gui_content = f.read()

        self.assertIn('v6.39 (Staff Department & Inactive Matching Suite)', gui_content, "Title ต้องเป็น v6.39")
        self.assertIn('FACE MATCHING\\nSYSTEM v6.39', gui_content, "Sidebar logo ต้องเป็น v6.39")

        db_manager_path = os.path.join(PROJECT_ROOT, "db_manager.py")
        with open(db_manager_path, "r", encoding="utf-8") as f:
            db_content = f.read()
        self.assertIn('"version": "v6.39"', db_content, "DatabaseManager manifest version ต้องเป็น v6.39")

    def test_tc110_compilation_and_syntax(self):
        """TC-110: ตรวจสอบ Syntax และ Compilation ของไฟล์สำคัญ"""
        files_to_check = [
            os.path.join(PROJECT_ROOT, "execute_department_and_status_sync.py"),
            os.path.join(PROJECT_ROOT, "db_manager.py"),
            os.path.join(PROJECT_ROOT, "gdrive_sync.py"),
            os.path.join(PROJECT_ROOT, "app_gui.py")
        ]
        for f in files_to_check:
            py_compile.compile(f, doraise=True)

if __name__ == "__main__":
    unittest.main()
