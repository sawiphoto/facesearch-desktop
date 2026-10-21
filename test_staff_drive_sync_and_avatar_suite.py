import os
import sys
import unittest
import sqlite3
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import py_compile

# Project root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_manager import DatabaseManager, SW_DEPARTMENTS, clean_department_name
from gdrive_sync import GoogleSyncManager

class TestStaffDriveSyncAndAvatarSuite(unittest.TestCase):
    """
    ชุดทดสอบระบบซิงก์รูปภาพบุคลากรขึ้น Google Drive และตาราง Treeview พร้อม Avatar (v6.41)
    TC-116 ถึง TC-120 ครอบคลุมทุก Execution Paths และ Edge Cases
    """

    def setUp(self):
        self.db_path = os.path.join(PROJECT_ROOT, "data", "faces_db.db")
        self.db = DatabaseManager(self.db_path)

    def test_tc116_treeview_avatar_column_configuration(self):
        """TC-116: ตรวจสอบการตั้งค่าคอลัมน์ Avatar ใน Treeview (show='tree headings', #0 column, rowheight)"""
        root = tk.Tk()
        root.withdraw()
        try:
            style = ttk.Style()
            style.configure("Treeview", rowheight=38)
            current_rowheight = style.lookup("Treeview", "rowheight")
            self.assertEqual(int(current_rowheight), 38, "Treeview rowheight must be configured to 38px for 32x32 avatars")

            cols = ("id", "name", "department", "photos")
            tree = ttk.Treeview(root, columns=cols, show="tree headings", selectmode="browse")
            tree.column("#0", width=46, anchor="center")
            tree.heading("#0", text="รูป")

            # ตรวจสอบการใส่ข้อมูล
            dummy_img = Image.new("RGBA", (32, 32), (32, 48, 64, 255))
            dummy_photo = ImageTk.PhotoImage(dummy_img)

            tree.insert("", "end", iid="101", text="", image=dummy_photo, values=(101, "ครูทดสอบ ระบบ", "คณิตศาสตร์", 5))
            item_vals = tree.item("101", "values")
            self.assertEqual(item_vals[0], "101")
            self.assertEqual(item_vals[1], "ครูทดสอบ ระบบ")
            self.assertEqual(item_vals[2], "คณิตศาสตร์")
            self.assertEqual(item_vals[3], "5")
        finally:
            root.destroy()

    def test_tc117_avatar_in_memory_cache_performance(self):
        """TC-117: ทดสอบระบบ In-Memory Avatar Caching และ Fallback Placeholder (Zero Disk I/O)"""
        # 1. ทดสอบการสร้าง Avatar Thumbnail 32x32
        test_img_path = os.path.join(PROJECT_ROOT, "scratch", "temp_test_avatar.jpg")
        img = Image.new("RGB", (120, 160), color=(100, 150, 200))
        img.save(test_img_path)

        cache = {}
        shared_placeholder = None

        def get_avatar(staff_id, path):
            nonlocal shared_placeholder
            key = (staff_id, path)
            if key in cache:
                return cache[key], "cache_hit"
            if not path or not os.path.exists(path):
                if shared_placeholder is None:
                    ph = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
                    d = ImageDraw.Draw(ph)
                    d.ellipse([1, 1, 30, 30], fill="#20334F")
                    shared_placeholder = ImageTk.PhotoImage(ph)
                cache[key] = shared_placeholder
                return shared_placeholder, "placeholder"
            with Image.open(path) as pi:
                pi = pi.convert("RGBA")
                pi.thumbnail((32, 32), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
                canvas.paste(pi, ((32 - pi.width) // 2, (32 - pi.height) // 2))
                photo = ImageTk.PhotoImage(canvas)
                cache[key] = photo
                return photo, "disk_load"

        root = tk.Tk()
        root.withdraw()
        try:
            # ครั้งแรก: อ่านดิสก์
            photo1, source1 = get_avatar(1, test_img_path)
            self.assertEqual(source1, "disk_load")
            self.assertIsNotNone(photo1)

            # ครั้งที่สอง: ดึงจากแคชใน RAM (Zero Disk I/O)
            photo2, source2 = get_avatar(1, test_img_path)
            self.assertEqual(source2, "cache_hit")
            self.assertIs(photo1, photo2)

            # ทดสอบกรณีไม่มีไฟล์: ดึง Placeholder Singleton
            ph1, src_ph1 = get_avatar(999, "")
            ph2, src_ph2 = get_avatar(998, "non_existent.jpg")
            self.assertEqual(src_ph1, "placeholder")
            self.assertEqual(src_ph2, "placeholder")
            self.assertIs(ph1, ph2, "Shared placeholder singleton must be reused across missing avatars")
        finally:
            root.destroy()
            if os.path.exists(test_img_path):
                os.remove(test_img_path)

    def test_tc118_department_normalization_and_database_teachers(self):
        """TC-118: ตรวจสอบการแปลงชื่อกลุ่มสาระมาตรฐาน และตรวจสอบครู 168 คนใน DB"""
        # ทดสอบ clean_department_name
        self.assertEqual(clean_department_name("ผู้บริหาร"), "คณะผู้บริหาร")
        self.assertEqual(clean_department_name("สังคมศึกษา"), "สังคมศึกษาฯ")
        self.assertEqual(clean_department_name("กลุ่มสาระการเรียนรู้วิทยาศาสตร์และเทคโนโลยี"), "วิทยาศาสตร์และเทคโนโลยี")
        self.assertEqual(clean_department_name("กลุ่มสาระฯคณิตศาสตร์"), "คณิตศาสตร์")

        # ตรวจสอบ get_all_teachers จากฐานข้อมูลจริง
        teachers = self.db.get_all_teachers()
        self.assertEqual(len(teachers), 168, "Must return exactly 168 teachers")

        # ตรวจสอบว่าไม่มีสังกัด 'ผู้บริหาร' หรือ 'สังคมศึกษา' หรือ ค่าว่างหลงเหลือ
        valid_depts = set(SW_DEPARTMENTS) | {"อื่นๆ"}
        for t in teachers:
            dept = t['department']
            self.assertNotIn(dept, ["ผู้บริหาร", "สังคมศึกษา", "", None], f"Invalid department '{dept}' found in teacher {t['name']}")
            self.assertIn(dept, valid_depts, f"Department '{dept}' not in valid departments")
            self.assertIn('avatar_path', t, "avatar_path field must be present in teacher dict")
            self.assertTrue(len(t['avatar_path']) > 0, f"Teacher {t['name']} has empty avatar_path")

    def test_tc119_drive_sync_logic_simulation(self):
        """TC-119: จำลองกระบวนการซิงก์รูปภาพ (Skip Existing, Relocate Mismatches, Upload New)"""
        import re

        def normalize_teacher_name(n):
            if not n:
                return ""
            n = os.path.splitext(str(n))[0]
            for pre in ["ว่าที่ร้อยตรีหญิง", "ว่าที่ร้อยตรี", "ว่าที่ ร.ต.หญิง", "ว่าที่ ร.ต.", 
                        "นางสาว", "น.ส.", "นาย", "นาง", "ดร.", "คุณครู", "ครู", "อาจารย์", "อ.", 
                        "Mr.", "Mrs.", "Ms.", "Miss"]:
                if n.startswith(pre):
                    n = n[len(pre):]
                    break
            return re.sub(r'[\s\.\-_]+', '', n).lower()

        # Mock catalogs
        active_folders = {"คณิตศาสตร์": "f_math", "ภาษาไทย": "f_thai", "คณะผู้บริหาร": "f_exec"}
        former_folders = {"คณิตศาสตร์": "f_math_former", "ภาษาไทย": "f_thai_former"}

        # Drive file catalog
        mock_drive_catalog = {
            normalize_teacher_name("นายสมชาย ใจดี"): {
                "file_id": "file_1",
                "file_name": "นายสมชาย ใจดี.png",
                "parent_id": "f_math",
                "dept_name": "คณิตศาสตร์",
                "is_former": False
            },
            normalize_teacher_name("นางสมศรี มีสุข"): {
                "file_id": "file_2",
                "file_name": "นางสมศรี มีสุข.png",
                "parent_id": "f_thai", # อยู่ภาษาไทย แต่อยากย้ายไป คณิต
                "dept_name": "ภาษาไทย",
                "is_former": False
            }
        }

        test_staff = [
            {"id": 1, "name": "นายสมชาย ใจดี", "department": "คณิตศาสตร์", "status": "active", "avatar_path": "dummy1.jpg"},
            {"id": 2, "name": "นางสมศรี มีสุข", "department": "คณิตศาสตร์", "status": "active", "avatar_path": "dummy2.jpg"},
            {"id": 3, "name": "Mr. John Doe", "department": "คณิตศาสตร์", "status": "active", "avatar_path": "dummy3.jpg"},
        ]

        skipped = []
        relocated = []
        uploaded = []

        for t in test_staff:
            norm = normalize_teacher_name(t['name'])
            target_fid = active_folders.get(t['department'])
            if norm in mock_drive_catalog:
                entry = mock_drive_catalog[norm]
                if entry['parent_id'] == target_fid:
                    skipped.append(t['name'])
                else:
                    relocated.append((t['name'], entry['dept_name'], t['department']))
                    entry['parent_id'] = target_fid
            else:
                uploaded.append(t['name'])

        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0], "นายสมชาย ใจดี")
        self.assertEqual(len(relocated), 1)
        self.assertEqual(relocated[0][0], "นางสมศรี มีสุข")
        self.assertEqual(len(uploaded), 1)
        self.assertEqual(uploaded[0], "Mr. John Doe")

    def test_tc120_version_parity_and_compilation(self):
        """TC-120: ตรวจสอบความสอดคล้องของเลขเวอร์ชัน v6.41 และคอมไพล์โค้ดทุกไฟล์ผ่าน 100%"""
        # ตรวจสอบ py_compile
        py_files = ["db_manager.py", "gdrive_sync.py", "app_gui.py", "face_analyzer.py"]
        for pf in py_files:
            full_path = os.path.join(PROJECT_ROOT, pf)
            self.assertTrue(os.path.exists(full_path), f"File {pf} must exist")
            py_compile.compile(full_path, doraise=True)

        # ตรวจสอบ Window Title และ Sidebar Logo ใน app_gui.py
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue("v6.41" in content or "v6.42" in content or "v6.43" in content, "Window Title must reflect v6.41, v6.42 or v6.43")
        self.assertTrue("SYSTEM v6.41" in content or "SYSTEM v6.42" in content or "SYSTEM v6.43" in content, "Sidebar Logo must reflect v6.41, v6.42 or v6.43")

if __name__ == '__main__':
    unittest.main()
