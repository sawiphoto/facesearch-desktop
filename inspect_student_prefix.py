import sqlite3
import json
import os
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

project_root = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(project_root, "data", "faces_db.db")

# 1. Check SQLite
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id, name, student_id FROM staff_members WHERE role = 'student' ORDER BY id")
all_students_db = c.fetchall()
conn.close()

prefixes = ("เด็กชาย", "เด็กหญิง", "ด.ช.", "ด.ญ.", "ด.ช", "ด.ญ", "นาย", "นางสาว", "น.ส.")
prefix_db = [s for s in all_students_db if s[1] and s[1].startswith(prefixes)]
no_prefix_db = [s for s in all_students_db if s not in prefix_db]

print(f"=== 1. SQLite Database (data/faces_db.db) ===")
print(f"จำนวนนักเรียนทั้งหมดใน DB: {len(all_students_db)} คน")
print(f"นักเรียนที่บันทึก 'มีคำนำหน้าชื่อ': {len(prefix_db)} คน")
for s in prefix_db:
    print(f"  - DB ID: {s[0]}, รหัสนักเรียน: {s[2]}, ชื่อ: {s[1]}")

print(f"\nนักเรียนที่บันทึก 'ไม่มีคำนำหน้าชื่อ' (บันทึกแค่ชื่อ-นามสกุล): {len(no_prefix_db)} คน")
print("ตัวอย่างรายชื่อที่ไม่มีคำนำหน้า (10 คนแรก):")
for s in no_prefix_db[:10]:
    print(f"  - DB ID: {s[0]}, รหัสนักเรียน: {s[2]}, ชื่อ: {s[1]}")

# 2. Check student_index.json
json_paths = [
    os.path.join(project_root, "student_index.json"),
    os.path.join(project_root, "data", "student_index.json")
]

for jp in json_paths:
    if os.path.exists(jp):
        print(f"\n=== 2. Local JSON File ({jp}) ===")
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"ประเภทข้อมูล: {type(data)}")
        if isinstance(data, list):
            print(f"จำนวนใน JSON: {len(data)} รายการ")
            prefix_json = [item for item in data if any(str(item.get("name" if isinstance(item, dict) else item)).startswith(p) for p in prefixes)]
            print(f"รายการที่มีคำนำหน้า: {len(prefix_json)}")
            for item in prefix_json:
                print(f"  - {item}")
        elif isinstance(data, dict):
            print(f"จำนวน key ใน JSON: {len(data)} รายการ")
            prefix_json = [k for k in data.keys() if any(k.startswith(p) for p in prefixes)]
            print(f"Key ที่มีคำนำหน้า: {len(prefix_json)}")
            for k in prefix_json:
                print(f"  - {k}")
