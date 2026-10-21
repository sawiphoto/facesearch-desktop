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

class TestTeacherDepartmentOtherSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(PROJECT_ROOT, "data", "faces_db.db")
        cls.db = DatabaseManager()

    def test_tc111_zero_unassigned_teachers(self):
        """TC-111: ตรวจสอบว่าไม่มีบุคลากรครูที่ไร้สังกัด (department เป็นค่าว่าง หรือ NULL) หลงเหลือในระบบ"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(id) 
                FROM staff_members 
                WHERE (role = 'teacher' OR role IS NULL OR role = '') 
                  AND (department IS NULL OR TRIM(department) = '' OR department = 'ไม่ระบุ')
            """)
            unassigned_count = cursor.fetchone()[0]
            
        self.assertEqual(unassigned_count, 0, f"ต้องไม่มีครูที่ไม่มีสังกัดหลงเหลือในระบบ (พบ {unassigned_count} ท่าน)")

    def test_tc112_targeted_teachers_department_verification(self):
        """TC-112: ตรวจสอบความถูกต้องของสังกัดและสถานะของครูทั้ง 8 ท่านเป้าหมาย"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, department, status FROM staff_members WHERE id IN (4, 5, 242, 246, 256, 261, 266, 267)")
            rows = cursor.fetchall()

        member_map = {r[0]: {"name": r[1], "dept": r[2], "status": r[3]} for r in rows}
        
        # ครูต่างชาติ 2 ท่าน (ผู้ใช้จัดการเป็น ภาษาต่างประเทศ, active)
        self.assertEqual(member_map[4]["dept"], "ภาษาต่างประเทศ")
        self.assertEqual(member_map[4]["status"], "active")
        self.assertEqual(member_map[5]["dept"], "ภาษาต่างประเทศ")
        self.assertEqual(member_map[5]["status"], "active")

        # อีก 6 ท่านที่ไม่มีสังกัด ต้องได้รับสังกัด 'อื่นๆ' (status: inactive)
        inactive_other_ids = [242, 246, 256, 261, 266, 267]
        for sid in inactive_other_ids:
            self.assertIn(sid, member_map, f"ต้องพบ ID {sid} ในฐานข้อมูล")
            self.assertEqual(member_map[sid]["dept"], "อื่นๆ", f"ID {sid} ({member_map[sid]['name']}) ต้องมีสังกัด 'อื่นๆ'")
            self.assertEqual(member_map[sid]["status"], "inactive", f"ID {sid} ต้องมีสถานะ 'inactive'")

    def test_tc113_department_other_total_count(self):
        """TC-113: ตรวจสอบยอดรวมบุคลากรในสังกัด 'อื่นๆ'"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM staff_members WHERE (role = 'teacher' OR role IS NULL OR role = '') AND department = 'อื่นๆ'")
            other_count = cursor.fetchone()[0]
            
        # 2 ท่านเดิมจาก Drive (นายบำรุง อุชุภาพ, นายสมชาย สังข์ดี) + 6 ท่านที่ไม่ทราบสังกัด = 8 ท่าน
        self.assertEqual(other_count, 8, f"บุคลากรในสังกัด 'อื่นๆ' ต้องมีจำนวน 8 ท่านพอดี (พบ {other_count} ท่าน)")

    def test_tc114_full_member_inclusion_in_json_index(self):
        """TC-114: ตรวจสอบว่าดัชนี JSON บรรจุรายชื่อบุคลากรครบ 100% ทุกคน (ท่านที่ไม่มีรูปต้องมีค่า [])"""
        sync_data = self.db.get_sync_data_sharded()
        
        active_staff = sync_data["active_staff"]
        former_staff = sync_data["former_staff"]
        teachers = sync_data["teachers"]

        # ตรวจสอบจำนวนรายชื่อ
        self.assertEqual(len(active_staff), 122, "staff_index.json ต้องมีบุคลากรปัจจุบันครบ 122 ท่าน 100%")
        self.assertEqual(len(former_staff), 46, "former_staff_index.json ต้องมีอดีตบุคลากรครบ 46 ท่าน 100%")
        self.assertEqual(len(teachers), 122, "person_index.json ต้องมีครูปัจจุบันครบ 122 ท่าน 100%")

        # ยอดรวมไม่ซ้ำต้องเท่ากับ 168 คนพอดี
        total_unique = set(active_staff.keys()).union(set(former_staff.keys()))
        self.assertEqual(len(total_unique), 168, "ยอดรวมบุคลากรในดัชนีทั้งสองส่วนต้องครบ 168 คนพอดี")

        # ตรวจสอบบุคลากรที่ไม่มีรูปกิจกรรม ต้องมีค่าเป็น [] (Empty list) ไม่หลุดหาย
        empty_active = [k for k, v in active_staff.items() if len(v) == 0]
        empty_former = [k for k, v in former_staff.items() if len(v) == 0]
        
        self.assertTrue(len(empty_active) >= 1, "ต้องมีครูปัจจุบันที่ไม่มีรูปกิจกรรมบรรจุเป็น [] อย่างน้อย 1 คน")
        self.assertTrue(len(empty_former) >= 20, "ต้องมีอดีตครูที่ไม่มีรูปกิจกรรมบรรจุเป็น [] มากกว่า 20 คน")

        # ตรวจสอบตัวอย่างครูที่ไม่มีรูป ต้องมีค่าเป็น []
        self.assertIn("นายวิชิต ศิริพันธ์", former_staff, "ต้องพบ 'นายวิชิต ศิริพันธ์' ใน former_staff")
        self.assertEqual(former_staff["นายวิชิต ศิริพันธ์"], [], "'นายวิชิต ศิริพันธ์' ต้องมีรูปเป็น [] (อาร์เรย์ว่าง)")

        # ตรวจสอบ manifest
        manifest = sync_data["manifest"]
        self.assertEqual(manifest["version"], "v6.40", "Manifest version ต้องเป็น v6.40")
        self.assertEqual(manifest["staff_counts"]["active"], 122)
        self.assertEqual(manifest["staff_counts"]["former"], 46)

    def test_tc115_version_parity_and_compilation(self):
        """TC-115: ตรวจสอบความสอดคล้องของเลขเวอร์ชัน v6.40 และการ Compile ทั่วทั้งระบบ"""
        app_gui_path = os.path.join(PROJECT_ROOT, "app_gui.py")
        with open(app_gui_path, "r", encoding="utf-8") as f:
            gui_content = f.read()

        self.assertIn('v6.40 (Full Member Inclusion & Department Fallback Suite)', gui_content)
        self.assertIn('FACE MATCHING\\nSYSTEM v6.40', gui_content)

        db_manager_path = os.path.join(PROJECT_ROOT, "db_manager.py")
        with open(db_manager_path, "r", encoding="utf-8") as f:
            db_content = f.read()
        self.assertIn('"version": "v6.40"', db_content)

        # Compilation test
        for f in [app_gui_path, db_manager_path, os.path.join(PROJECT_ROOT, "gdrive_sync.py")]:
            py_compile.compile(f, doraise=True)

if __name__ == "__main__":
    unittest.main()
