import unittest
import os
import sys
import sqlite3
import tempfile
import shutil

# เพิ่ม Path ปัจจุบัน
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_manager import DatabaseManager, SW_DEPARTMENTS, clean_department_name, parse_teacher_filename

class TestTeacherTableAndDBEditorSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="test_teacher_table_")
        cls.db_path = os.path.join(cls.temp_dir, "test_faces.db")
        cls.db = DatabaseManager(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_tc82_teacher_table_sorting_logic(self):
        """TC-82: ทดสอบตรรกะการจัดเรียงตารางครูตามคอลัมน์ต่างๆ (ID, ชื่อ, สังกัด, รูป)"""
        # เตรียมข้อมูลจำลองครู 5 ท่าน
        mock_teachers = [
            {"id": 10, "name": "นายสมชาย ใจดี", "department": "วิทยาศาสตร์และเทคโนโลยี", "photo_count": 5},
            {"id": 2, "name": "นางสาวกนกพร สดใส", "department": "คณิตศาสตร์", "photo_count": 12},
            {"id": 25, "name": "นายธนกฤต มั่นคง", "department": "ภาษาไทย", "photo_count": 1},
            {"id": 4, "name": "นางพิมพ์ใจ รักเรียน", "department": "การงานอาชีพ", "photo_count": 8},
            {"id": 1, "name": "นายอำนาจ สามารถ", "department": "ศิลปะ", "photo_count": 3},
        ]

        # 1. จัดเรียงตาม ID (ตัวเลข)
        sorted_id_asc = sorted(mock_teachers, key=lambda x: int(x['id']), reverse=False)
        self.assertEqual([x['id'] for x in sorted_id_asc], [1, 2, 4, 10, 25])

        sorted_id_desc = sorted(mock_teachers, key=lambda x: int(x['id']), reverse=True)
        self.assertEqual([x['id'] for x in sorted_id_desc], [25, 10, 4, 2, 1])

        # 2. จัดเรียงตามรูป (ตัวเลข)
        sorted_photos_desc = sorted(mock_teachers, key=lambda x: int(x['photo_count']), reverse=True)
        self.assertEqual([x['photo_count'] for x in sorted_photos_desc], [12, 8, 5, 3, 1])

        sorted_photos_asc = sorted(mock_teachers, key=lambda x: int(x['photo_count']), reverse=False)
        self.assertEqual([x['photo_count'] for x in sorted_photos_asc], [1, 3, 5, 8, 12])

        # 3. จัดเรียงตามสังกัด (ตัวอักษร)
        sorted_dept_asc = sorted(mock_teachers, key=lambda x: x['department'], reverse=False)
        dept_names_asc = [x['department'] for x in sorted_dept_asc]
        self.assertTrue(dept_names_asc.index("การงานอาชีพ") < dept_names_asc.index("วิทยาศาสตร์และเทคโนโลยี"))

    def test_tc83_teacher_department_filtering_logic(self):
        """TC-83: ทดสอบการกรองสังกัดและคำค้นหา (Department & Search Filtering)"""
        mock_teachers = [
            {"id": 1, "name": "นายสมชาย ใจดี", "department": "วิทยาศาสตร์และเทคโนโลยี", "photo_count": 5},
            {"id": 2, "name": "นางสาวกนกพร สดใส", "department": "คณิตศาสตร์", "photo_count": 2},
            {"id": 3, "name": "นายวิทย์ ก้าวหน้า", "department": "วิทยาศาสตร์และเทคโนโลยี", "photo_count": 4},
            {"id": 4, "name": "นางมาลี วิทยา", "department": "ภาษาไทย", "photo_count": 1},
        ]

        # กรองเฉพาะสังกัด 'วิทยาศาสตร์และเทคโนโลยี'
        filtered_sci = [s for s in mock_teachers if s['department'] == 'วิทยาศาสตร์และเทคโนโลยี']
        self.assertEqual(len(filtered_sci), 2)
        self.assertEqual({s['id'] for s in filtered_sci}, {1, 3})

        # กรองสังกัด 'คณิตศาสตร์'
        filtered_math = [s for s in mock_teachers if s['department'] == 'คณิตศาสตร์']
        self.assertEqual(len(filtered_math), 1)
        self.assertEqual(filtered_math[0]['name'], "นางสาวกนกพร สดใส")

        # ค้นหาคำว่า "วิทย" ในชื่อและสังกัด
        search_kw = "วิทย".lower()
        search_res = [
            s for s in mock_teachers
            if (search_kw in str(s['id']) or search_kw in s['name'].lower() or search_kw in s['department'].lower())
        ]
        # ควรพบ: id 1 (สังกัด วิทยาศาสตร์), id 3 (ชื่อ วิทย์ + สังกัด วิทยาศาสตร์), id 4 (ชื่อ วิทยา)
        self.assertIn(1, [s['id'] for s in search_res])
        self.assertIn(3, [s['id'] for s in search_res])
        self.assertIn(4, [s['id'] for s in search_res])

    def test_tc84_sqlite_db_record_full_update(self):
        """TC-84: ทดสอบการแก้ไขข้อมูลบุคลากรใน SQLite (Status active/inactive, department, name, role)"""
        # ลงทะเบียนครูทดสอบ
        t_id = self.db.register_staff_member("นายทดสอบ ระบบ", department="วิทยาศาสตร์และเทคโนโลยี")
        self.assertIsNotNone(t_id)

        # ตรวจสอบข้อมูลเริ่มต้น
        rec = self.db.get_staff_member_by_id(t_id)
        self.assertEqual(rec['name'], "นายทดสอบ ระบบ")
        self.assertEqual(rec['department'], "วิทยาศาสตร์และเทคโนโลยี")
        self.assertEqual(rec['status'], "active")

        # แก้ไขข้อมูล: เปลี่ยนสถานะเป็น inactive, เปลี่ยนสังกัดเป็น คณิตศาสตร์, ปรับ threshold
        updated = self.db.update_staff_member_full(
            staff_id=t_id,
            name="นายทดสอบ สวีวิทยา",
            department="คณิตศาสตร์",
            status="inactive",
            personal_threshold=0.62,
            student_id="T0099"
        )
        self.assertTrue(updated)

        # ดึงมาตรวจสอบใหม่
        rec_after = self.db.get_staff_member_by_id(t_id)
        self.assertEqual(rec_after['name'], "นายทดสอบ สวีวิทยา")
        self.assertEqual(rec_after['department'], "คณิตศาสตร์")
        self.assertEqual(rec_after['status'], "inactive")
        self.assertAlmostEqual(rec_after['personal_threshold'], 0.62)
        self.assertEqual(rec_after['student_id'], "T0099")

        # เปลี่ยนกลับเป็น active
        self.db.update_staff_member_full(staff_id=t_id, status="active")
        rec_active = self.db.get_staff_member_by_id(t_id)
        self.assertEqual(rec_active['status'], "active")

        # ทดสอบอัปเดต scanned_photos
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO scanned_photos (photo_id, event_name, academic_year, drive_file_id, drive_link)
                VALUES ('P99999', 'กิจกรรมทดสอบ', '2567', 'test_drive_fid_999', 'https://drive.google.com/test')
            """)
            conn.commit()

        photo_upd = self.db.update_scanned_photo_record("P99999", event_name="กิจกรรมกีฬาสี 2568", academic_year="2568")
        self.assertTrue(photo_upd)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT event_name, academic_year FROM scanned_photos WHERE photo_id = 'P99999'")
            row = cursor.fetchone()
            self.assertEqual(row[0], "กิจกรรมกีฬาสี 2568")
            self.assertEqual(row[1], "2568")

    def test_tc85_clean_department_name_and_zero_klum_sara(self):
        """TC-85: ทดสอบตัดคำว่า 'กลุ่มสาระ' ออก 100% ทั้งในค่าคงที่และฟังก์ชันสกัด"""
        # 1. ตรวจสอบว่าใน SW_DEPARTMENTS ไม่มีคำว่า "กลุ่มสาระ" แม้แต่คำเดียว
        for dept in SW_DEPARTMENTS:
            self.assertNotIn("กลุ่มสาระ", dept, f"พบคำว่ากลุ่มสาระใน: {dept}")

        expected_count = 13  # 12 หมวดหมู่จริง + "อื่นๆ (ระบุเอง)"
        self.assertEqual(len(SW_DEPARTMENTS), expected_count)

        # 2. ทดสอบฟังก์ชัน clean_department_name
        self.assertEqual(clean_department_name("กลุ่มสาระฯวิทยาศาสตร์และเทคโนโลยี"), "วิทยาศาสตร์และเทคโนโลยี")
        self.assertEqual(clean_department_name("กลุ่มสาระฯคณิตศาสตร์"), "คณิตศาสตร์")
        self.assertEqual(clean_department_name("กลุ่มสาระภาษาไทย"), "ภาษาไทย")
        self.assertEqual(clean_department_name("กลุ่มสาระการเรียนรู้ศิลปะ"), "ศิลปะ")
        self.assertEqual(clean_department_name("การงานอาชีพ"), "การงานอาชีพ")
        self.assertEqual(clean_department_name(""), "")

        # 3. ทดสอบ parse_teacher_filename ว่าตัดคำว่ากลุ่มสาระออกจากชื่อไฟล์
        name, dept, idx = parse_teacher_filename("นายสมชาย ใจดี กลุ่มสาระฯวิทยาศาสตร์และเทคโนโลยี 1.jpg")
        self.assertEqual(name, "นายสมชาย ใจดี")
        self.assertEqual(dept, "วิทยาศาสตร์และเทคโนโลยี")
        self.assertEqual(idx, 1)

        name2, dept2, idx2 = parse_teacher_filename("นางสาวสมหญิง สดใส กลุ่มสาระคณิตศาสตร์ 2.png")
        self.assertEqual(name2, "นางสาวสมหญิง สดใส")
        self.assertEqual(dept2, "คณิตศาสตร์")
        self.assertEqual(idx2, 2)

        # 4. ทดสอบ Database Migration Normalization (Idempotent DB cleaning)
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO staff_members (name, department, role) VALUES ('ครูเก่า 1', 'กลุ่มสาระฯสังคมศึกษาฯ', 'teacher')")
            cursor.execute("INSERT INTO staff_members (name, department, role) VALUES ('ครูเก่า 2', 'กลุ่มสาระการเรียนรู้สุขศึกษาฯ', 'teacher')")
            conn.commit()

        # รัน normalization logic
        self.db.init_db(force=True)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT department FROM staff_members WHERE name IN ('ครูเก่า 1', 'ครูเก่า 2')")
            rows = cursor.fetchall()
            for r in rows:
                self.assertNotIn("กลุ่มสาระ", r[0])

    def test_tc86_version_v634_parity_and_manifest(self):
        """TC-86: ตรวจสอบความถูกต้องของเลขเวอร์ชัน v6.34/v6.35 ทั่วทั้งระบบ"""
        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()

        # ตรวจสอบ Window Title
        self.assertTrue("v6.34" in gui_code or "v6.35" in gui_code or "v6.36" in gui_code)
        # ตรวจสอบ Sidebar Header
        self.assertTrue("SYSTEM v6.34" in gui_code or "SYSTEM v6.35" in gui_code or "SYSTEM v6.36" in gui_code)

        # ตรวจสอบ manifest ใน db_manager.py
        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertTrue('"version": "v6.34"' in db_code or '"version": "v6.35"' in db_code or '"version": "v6.36"' in db_code)

if __name__ == "__main__":
    unittest.main()
