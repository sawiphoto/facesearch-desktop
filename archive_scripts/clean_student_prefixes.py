import sqlite3
import os
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

project_root = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(project_root, "data", "faces_db.db")

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT id, name, student_id FROM staff_members WHERE role = 'student'")
rows = c.fetchall()

prefixes = ["เด็กชาย", "เด็กหญิง", "ด.ช.", "ด.ญ.", "ด.ช", "ด.ญ", "นาย", "นางสาว", "น.ส."]
updated_count = 0

for sid, name, std_id in rows:
    if not name:
        continue
    new_name = name
    for p in prefixes:
        if new_name.startswith(p):
            new_name = new_name[len(p):].strip()
            break
            
    if new_name != name:
        c.execute("UPDATE staff_members SET name = ? WHERE id = ?", (new_name, sid))
        print(f"[UPDATED] ID {sid} (รหัส: {std_id}): '{name}' -> '{new_name}'")
        updated_count += 1

conn.commit()

# ตรวจสอบซ้ำ
c.execute("SELECT id, name, student_id FROM staff_members WHERE role = 'student'")
all_after = c.fetchall()
prefix_remaining = [s for s in all_after if any(s[1].startswith(p) for p in prefixes)]

conn.close()

print("\n" + "="*50)
print(f"ผลการปรับปรุงรายชื่อนักเรียน:")
print(f" - อัปเดตสำเร็จ: {updated_count} คน")
print(f" - รายชื่อที่มีคำนำหน้าหลงเหลือ: {len(prefix_remaining)} คน")
print("="*50)
