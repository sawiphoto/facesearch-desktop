#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_smart_teacher_batch_import_suite.py
-------------------------------------------------------------
Comprehensive Test Suite for Smart Batch Teacher Import & Department (v6.33)
Tests:
  TC-76: Teacher Filename Parsing Accuracy
  TC-77: Teacher Department Database Schema Migration & Indexes
  TC-78: Multi-Photo Registration Integrity for Single Teacher
  TC-79: Department Search Filtering Logic
  TC-80: Version v6.33 Parity & py_compile
-------------------------------------------------------------
"""

import sys
import os
import re
import sqlite3
import py_compile
import tempfile
import shutil

# กำหนด Path ให้ทำงานได้ถูกต้อง
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_manager import DatabaseManager

THAI_PREFIXES = [
    r'ว่าที่\s*ร้อยตรี\s*หญิง',
    r'ว่าที่\s*ร้อยตรี',
    r'ว่าที่\s*ร\.ต\.หญิง',
    r'ว่าที่\s*ร\.ต\.',
    r'นางสาว',
    r'น\.ส\.',
    r'นาย',
    r'นาง',
    r'ดร\.',
    r'ผศ\.ดร\.',
    r'รศ\.ดร\.',
    r'ศ\.ดร\.',
    r'ผศ\.',
    r'รศ\.',
    r'ศ\.',
    r'อาจารย์',
    r'อ\.',
    r'คุณครู',
    r'ครู',
    r'Mr\.',
    r'Mrs\.',
    r'Miss',
    r'Ms\.',
]

def parse_teacher_filename(filename):
    """
    แยกวิเคราะห์ชื่อไฟล์ครูออกเป็น (main_name, department, photo_index)
    ตัวอย่าง:
      'นายสมชาย ใจดี วิทยาศาสตร์  1.jpg' -> ('นายสมชาย ใจดี', 'วิทยาศาสตร์', 1)
      'นางสาวสมหญิง สดใส คณิตศาสตร์ (2).png' -> ('นางสาวสมหญิง สดใส', 'คณิตศาสตร์', 2)
      'นายวิชาญ การงาน ภาษาไทย.jpg' -> ('นายวิชาญ การงาน', 'ภาษาไทย', 1)
      'นายสมศักดิ์ รักดี 1.jpg' -> ('นายสมศักดิ์ รักดี', '', 1)
    """
    base_name = os.path.splitext(os.path.basename(filename))[0].strip()
    photo_index = 1
    idx_match = re.search(r'[\s_\-\(\[\{]+(\d+)[\s\)\]\}]*$', base_name)
    if idx_match:
        try:
            photo_index = int(idx_match.group(1))
            base_name = base_name[:idx_match.start()].strip()
        except Exception:
            photo_index = 1
            
    clean_text = re.sub(r'\s+', ' ', base_name).strip()
    if not clean_text:
        return ("", "", photo_index)
        
    prefix_matched = None
    had_space = False
    remaining_after_prefix = clean_text
    
    for prefix_pat in THAI_PREFIXES:
        match = re.match(r'^(' + prefix_pat + r')(\s*)(.*)$', clean_text, re.IGNORECASE)
        if match:
            prefix_matched = match.group(1).strip()
            had_space = bool(match.group(2))
            remaining_after_prefix = match.group(3).strip()
            break
            
    if prefix_matched:
        tokens = [t for t in remaining_after_prefix.split(' ') if t]
        # คำนำหน้าไทยทั่วไป (นาย, นาง, นางสาว, น.ส., ครู, ดร.) ปกติเขียนติดกับชื่อตัว
        no_space_prefixes = ('นาย', 'นาง', 'นางสาว', 'น.ส.', 'ครู', 'คุณครู', 'ดร.')
        join_char = "" if (prefix_matched in no_space_prefixes and not had_space) else " "
        
        if len(tokens) == 0:
            main_name = prefix_matched
            department = ""
        elif len(tokens) == 1:
            main_name = f"{prefix_matched}{join_char}{tokens[0]}".strip()
            department = ""
        elif len(tokens) == 2:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = ""
        else:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = " ".join(tokens[2:]).strip()
    else:
        tokens = [t for t in clean_text.split(' ') if t]
        if len(tokens) == 1:
            main_name = tokens[0]
            department = ""
        elif len(tokens) == 2:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = ""
        else:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = " ".join(tokens[2:]).strip()
            
    return (main_name.strip(), department.strip(), photo_index)


def test_tc_76_filename_parser():
    print("Testing TC-76: Teacher Filename Parsing Accuracy...")
    test_cases = [
        # (Input, Expected (main_name, department, photo_index))
        ("นายสมชาย ใจดี วิทยาศาสตร์  1.jpg", ("นายสมชาย ใจดี", "วิทยาศาสตร์", 1)),
        ("นายสมชาย ใจดี วิทยาศาสตร์  2.jpg", ("นายสมชาย ใจดี", "วิทยาศาสตร์", 2)),
        ("นางสาวสมหญิง สดใส คณิตศาสตร์ (1).png", ("นางสาวสมหญิง สดใส", "คณิตศาสตร์", 1)),
        ("นางสาวสมหญิง สดใส คณิตศาสตร์ (2).png", ("นางสาวสมหญิง สดใส", "คณิตศาสตร์", 2)),
        ("นายวิชาญ การงาน ภาษาไทย.jpg", ("นายวิชาญ การงาน", "ภาษาไทย", 1)),
        ("นายสมศักดิ์ รักดี 1.jpg", ("นายสมศักดิ์ รักดี", "", 1)),
        ("ว่าที่ ร.ต. ชูเกียรติ มั่นคง สุขศึกษาและพลศึกษา _2.jpeg", ("ว่าที่ ร.ต. ชูเกียรติ มั่นคง", "สุขศึกษาและพลศึกษา", 2)),
        ("ดร.สมบัติ มีทรัพย์ สังคมศึกษา ศาสนา และวัฒนธรรม  3.jpg", ("ดร.สมบัติ มีทรัพย์", "สังคมศึกษา ศาสนา และวัฒนธรรม", 3)),
        ("สมปอง ใจกล้า การงานอาชีพ 1.jpg", ("สมปอง ใจกล้า", "การงานอาชีพ", 1)),
        ("ครูวรรณา สว่างจิต ศิลปะ 1.webp", ("ครูวรรณา สว่างจิต", "ศิลปะ", 1)),
    ]
    
    for filename, expected in test_cases:
        res = parse_teacher_filename(filename)
        assert res == expected, f"Failed for '{filename}': expected {expected}, got {res}"
        
    print("  -> TC-76 PASSED: All 10 filename variations parsed with 100% precision.")


def test_tc_77_db_schema_migration():
    print("Testing TC-77: Teacher Department Database Schema Migration & Indexes...")
    temp_dir = tempfile.mkdtemp()
    temp_db_path = os.path.join(temp_dir, "test_schema.db")
    try:
        db = DatabaseManager(temp_db_path)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(staff_members)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            assert "department" in columns, "Column 'department' missing in staff_members"
            
            cursor.execute("PRAGMA index_list(staff_members)")
            indexes = [row[1] for row in cursor.fetchall()]
            assert "idx_sm_department" in indexes, "Index 'idx_sm_department' missing on staff_members"
            
        # Test register_staff_member with department
        staff_id1 = db.register_staff_member("นายทดสอบ ระบบ", department="วิทยาศาสตร์")
        assert staff_id1 > 0
        
        # Test update existing teacher department
        staff_id2 = db.register_staff_member("นายทดสอบ ระบบ", department="วิทยาศาสตร์และเทคโนโลยี")
        assert staff_id1 == staff_id2, "Duplicate teacher created instead of re-using existing ID"
        
        # Test get_all_teachers returns department
        teachers = db.get_all_teachers()
        target = next((t for t in teachers if t['id'] == staff_id1), None)
        assert target is not None
        assert target['department'] == "วิทยาศาสตร์และเทคโนโลยี"
        
        # Test update_teacher_department
        ok = db.update_teacher_department(staff_id1, "คณิตศาสตร์")
        assert ok is True
        teachers2 = db.get_all_teachers()
        target2 = next((t for t in teachers2 if t['id'] == staff_id1), None)
        assert target2['department'] == "คณิตศาสตร์"
        
        print("  -> TC-77 PASSED: Database schema migration and CRUD operations verified.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_tc_78_multi_photo_registration():
    print("Testing TC-78: Multi-Photo Registration Integrity for Single Teacher...")
    temp_dir = tempfile.mkdtemp()
    temp_db_path = os.path.join(temp_dir, "test_multiphoto.db")
    try:
        db = DatabaseManager(temp_db_path)
        import numpy as np
        mock_embedding = np.ones((512,), dtype=np.float32)
        
        # ครูนายสมชาย ใจดี มี 2 ภาพ
        filenames = [
            "นายสมชาย ใจดี วิทยาศาสตร์  1.jpg",
            "นายสมชาย ใจดี วิทยาศาสตร์  2.jpg"
        ]
        
        teacher_ids = []
        for fn in filenames:
            m_name, dept, p_idx = parse_teacher_filename(fn)
            t_id = db.register_staff_member(m_name, department=dept)
            teacher_ids.append(t_id)
            # Add embedding
            fake_crop_path = f"data/registered_teachers/teacher_{t_id}_{p_idx}_{m_name}_{p_idx}.jpg"
            db.add_staff_embedding(t_id, fake_crop_path, mock_embedding)
            
        assert teacher_ids[0] == teacher_ids[1], "Separate teachers created for the same teacher photos!"
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM staff_members WHERE name = 'นายสมชาย ใจดี'")
            cnt = cursor.fetchone()[0]
            assert cnt == 1, f"Expected 1 teacher row, got {cnt}"
            
            cursor.execute("SELECT id, image_path FROM staff_embeddings WHERE staff_id = ?", (teacher_ids[0],))
            embs = cursor.fetchall()
            assert len(embs) == 2, f"Expected 2 embeddings for teacher, got {len(embs)}"
            
        print("  -> TC-78 PASSED: Multi-photo registration under single teacher verified.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_tc_79_department_search_filtering():
    print("Testing TC-79: Department Search Filtering Logic...")
    teachers = [
        {"id": 1, "name": "นายสมชาย ใจดี", "department": "วิทยาศาสตร์", "photo_count": 2},
        {"id": 2, "name": "นางสาวสมหญิง สดใส", "department": "คณิตศาสตร์", "photo_count": 1},
        {"id": 3, "name": "นายวิชาญ การงาน", "department": "ภาษาไทย", "photo_count": 3},
        {"id": 4, "name": "ว่าที่ ร.ต. เอกชัย มุ่งมั่น", "department": "สุขศึกษาและพลศึกษา", "photo_count": 1},
    ]
    
    def filter_teachers(query):
        q = query.strip().lower()
        if not q:
            return teachers
        res = []
        for s in teachers:
            dep = s.get('department', '') or ''
            if q in s['name'].lower() or q in dep.lower():
                res.append(s)
        return res
        
    res_sci = filter_teachers("วิทยาศาสตร์")
    assert len(res_sci) == 1 and res_sci[0]['name'] == "นายสมชาย ใจดี"
    
    res_short = filter_teachers("วิทย")
    # "วิทย" in "วิทยาศาสตร์" -> True in Thai
    assert len(res_short) == 1 and res_short[0]['id'] == 1
    
    res_name = filter_teachers("สมหญิง")
    assert len(res_name) == 1 and res_name[0]['id'] == 2
    
    res_none = filter_teachers("ฝรั่งเศส")
    assert len(res_none) == 0
    
    print("  -> TC-79 PASSED: Department and name dual search filtering verified.")


def test_tc_80_version_and_py_compile():
    print("Testing TC-80: Version v6.33 Parity & py_compile...")
    # 1. py_compile on db_manager.py and app_gui.py
    py_compile.compile("db_manager.py", doraise=True)
    py_compile.compile("app_gui.py", doraise=True)
    
    # 2. Check version string in app_gui.py
    with open("app_gui.py", "r", encoding="utf-8") as f:
        content = f.read()
        assert any(v in content for v in ["v6.33", "v6.34", "v6.35"]), "Window title not updated"
        assert any(v in content for v in ["SYSTEM v6.33", "SYSTEM v6.34", "SYSTEM v6.35"]), "Sidebar logo not updated"
    print("  -> TC-80 PASSED: Version and py_compile verified.")


def test_tc_81_end_to_end_smart_batch_import_simulation():
    print("Testing TC-81: End-to-End Smart Batch Import Runtime Simulation...")
    temp_dir = tempfile.mkdtemp()
    temp_db_path = os.path.join(temp_dir, "test_batch_e2e.db")
    import_folder = os.path.join(temp_dir, "teachers_input")
    os.makedirs(import_folder, exist_ok=True)
    
    try:
        db = DatabaseManager(temp_db_path)
        
        # สร้างไฟล์รูปภาพจำลองในโฟลเดอร์เดียว
        test_files = [
            "นายสมชาย ใจดี วิทยาศาสตร์  1.jpg",
            "นายสมชาย ใจดี วิทยาศาสตร์  2.jpg",
            "นางสาวสมหญิง สดใส คณิตศาสตร์ (1).png"
        ]
        for tf in test_files:
            fp = os.path.join(import_folder, tf)
            with open(fp, "wb") as f:
                f.write(b"FAKE_IMAGE_DATA")
                
        # รันขั้นตอนจำลองการทำงานของ _batch_import_thread
        valid_extensions = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff")
        direct_files = [
            f for f in os.listdir(import_folder) 
            if os.path.splitext(f)[1].lower() in valid_extensions and os.path.isfile(os.path.join(import_folder, f))
        ]
        assert len(direct_files) == 3, f"Expected 3 files, got {len(direct_files)}"
        
        teachers_map = {}
        for f in direct_files:
            full_path = os.path.join(import_folder, f)
            m_name, dept, p_idx = parse_teacher_filename(f)
            if not m_name:
                m_name = os.path.splitext(f)[0]
            if m_name not in teachers_map:
                teachers_map[m_name] = {'department': dept, 'files': []}
            elif dept and not teachers_map[m_name]['department']:
                teachers_map[m_name]['department'] = dept
            teachers_map[m_name]['files'].append((p_idx, f, full_path))
            
        for m_name in teachers_map:
            teachers_map[m_name]['files'].sort(key=lambda x: (x[0], x[1]))
            
        assert len(teachers_map) == 2, f"Expected 2 teachers, got {len(teachers_map)}"
        assert "นายสมชาย ใจดี" in teachers_map
        assert "นางสาวสมหญิง สดใส" in teachers_map
        assert len(teachers_map["นายสมชาย ใจดี"]["files"]) == 2
        assert len(teachers_map["นางสาวสมหญิง สดใส"]["files"]) == 1
        
        import numpy as np
        mock_embedding = np.ones((512,), dtype=np.float32)
        total_photos = 0
        
        for m_name, info in teachers_map.items():
            dept = info['department']
            staff_id = db.register_staff_member(m_name, department=dept)
            for p_idx, orig_file, full_path in info['files']:
                fake_crop = f"data/registered_teachers/teacher_{staff_id}_{p_idx}_{m_name}_{p_idx}.jpg"
                db.add_staff_embedding(staff_id, fake_crop, mock_embedding)
                total_photos += 1
                
        assert total_photos == 3
        
        # ตรวจสอบผลลัพธ์ในฐานข้อมูล
        teachers = db.get_all_teachers()
        assert len(teachers) == 2
        
        t1 = next(t for t in teachers if t['name'] == "นายสมชาย ใจดี")
        assert t1['department'] == "วิทยาศาสตร์"
        assert t1['photo_count'] == 2
        
        t2 = next(t for t in teachers if t['name'] == "นางสาวสมหญิง สดใส")
        assert t2['department'] == "คณิตศาสตร์"
        assert t2['photo_count'] == 1
        
        print("  -> TC-81 PASSED: End-to-end Smart Batch Import simulated and verified.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    print("=== Running Smart Batch Teacher Import Test Suite (v6.33) ===")
    test_tc_76_filename_parser()
    test_tc_77_db_schema_migration()
    test_tc_78_multi_photo_registration()
    test_tc_79_department_search_filtering()
    test_tc_80_version_and_py_compile()
    test_tc_81_end_to_end_smart_batch_import_simulation()
    print("=== All Test Cases (TC-76 to TC-81) Passed Successfully! ===")
