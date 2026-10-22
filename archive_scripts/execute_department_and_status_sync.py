import os
import sys
import json
import re

# Force UTF-8 output if possible
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

def clean_name(raw_name):
    # remove file extension
    name = os.path.splitext(raw_name)[0]
    # remove "สำเนาของ " or "สำเนาของ"
    name = re.sub(r"^สำเนาของ\s*", "", name)
    # remove trailing numbers/brackets
    name = re.sub(r"\s*\(\d+\)$", "", name)
    name = re.sub(r"\s+\d+$", "", name)
    return name.strip()

def normalize_thai_name(name):
    cleaned = clean_name(name)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

def run_sync():
    print("[INFO] === เริ่มต้นกระบวนการอัปเดตสังกัดและสถานะบุคลากร (v6.39) ===")
    
    # 1. Load data
    with open(r"C:\Users\hp\.gemini\antigravity\brain\4fa49501-0cca-487f-8274-2b82548023cf\scratch\drive_folder_analysis.json", "r", encoding="utf-8") as f:
        drive_data = json.load(f)

    with open(r"C:\Users\hp\.gemini\antigravity\brain\4fa49501-0cca-487f-8274-2b82548023cf\scratch\former_staff_details.json", "r", encoding="utf-8") as f:
        former_data = json.load(f)

    db = DatabaseManager()
    
    # Query DB teachers
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, department, status, role FROM staff_members WHERE role = 'teacher' OR role IS NULL OR role = ''")
        db_teachers = cursor.fetchall()
        
    db_teacher_map = {}
    for r in db_teachers:
        norm = normalize_thai_name(r[1])
        db_teacher_map[norm] = {
            "id": r[0],
            "name": r[1],
            "old_dept": r[2] or "",
            "old_status": r[3] or "active",
            "role": r[4] or "teacher"
        }

    # 1. Process Active Staff from Drive
    active_drive_teachers = []
    for sf in drive_data["subfolders"]:
        if sf["name"] == "อดีตบุคลากร":
            continue
        dept_name = sf["name"]
        for fn in sf["file_names"]:
            cleaned = clean_name(fn)
            active_drive_teachers.append({
                "raw_filename": fn,
                "cleaned_name": cleaned,
                "dept": dept_name,
                "status": "active"
            })

    # 2. Process Former Staff from Drive
    former_drive_teachers = []
    for f_dept in former_data:
        dept_name = f_dept["dept_under_former"]
        for fn in f_dept["files"]:
            cleaned = clean_name(fn)
            former_drive_teachers.append({
                "raw_filename": fn,
                "cleaned_name": cleaned,
                "dept": dept_name,
                "status": "inactive"
            })

    all_drive_people = {}

    # Add active first
    for t in active_drive_teachers:
        norm = normalize_thai_name(t["cleaned_name"])
        all_drive_people[norm] = {
            "raw_name": t["cleaned_name"],
            "dept": t["dept"],
            "status": "active"
        }

    # Override with former (Former takes absolute precedence)
    for t in former_drive_teachers:
        norm = normalize_thai_name(t["cleaned_name"])
        existing = all_drive_people.get(norm, {})
        chosen_dept = t["dept"] if t["dept"] != "อื่นๆ" else existing.get("dept", t["dept"])
        all_drive_people[norm] = {
            "raw_name": t["cleaned_name"],
            "dept": chosen_dept,
            "status": "inactive",
            "is_former": True
        }

    print(f"[INFO] รวมบุคลากรที่ไม่ซ้ำจาก Google Drive ทั้งสิ้น: {len(all_drive_people)} ท่าน")

    updates_list = []
    audit_log = []
    not_found = []

    for norm, p in all_drive_people.items():
        db_rec = db_teacher_map.get(norm)
        if not db_rec:
            # Try prefix-stripped matching
            core = re.sub(r"^(นาย|นางสาว|นาง|ว่าที่ ร\.ต\.|ว่าที่ร้อยตรี|ดร\.|ครู)\s*", "", norm).strip()
            for db_n, rec in db_teacher_map.items():
                db_core = re.sub(r"^(นาย|นางสาว|นาง|ว่าที่ ร\.ต\.|ว่าที่ร้อยตรี|ดร\.|ครู)\s*", "", db_n).strip()
                if core == db_core:
                    db_rec = rec
                    break

        if db_rec:
            updates_list.append((p["dept"], p["status"], db_rec["id"]))
            audit_log.append({
                "id": db_rec["id"],
                "name": db_rec["name"],
                "matched_drive_name": p["raw_name"],
                "old_dept": db_rec["old_dept"],
                "new_dept": p["dept"],
                "old_status": db_rec["old_status"],
                "new_status": p["status"],
                "is_former": p.get("is_former", False)
            })
        else:
            not_found.append(p)
            print(f"[WARN] ไม่พบในฐานข้อมูล: {p['raw_name']} ({norm})")

    print(f"[INFO] แมตช์สำเร็จ: {len(updates_list)} รายการ (ไม่พบ: {len(not_found)} รายการ)")
    
    # 2. Execute DB batch update
    affected = db.batch_update_staff_departments_and_statuses(updates_list)
    print(f"[OK] บันทึกข้อมูลลงฐานข้อมูล SQLite เรียบร้อย: {affected} รายการ")

    # 3. Synchronize JSON indexes to Google Drive
    print("[INFO] กำลังประมวลผลซิงก์ดัชนี JSON ขึ้น Google Drive...")
    sync_manager = GoogleSyncManager()
    if sync_manager.connect():
        settings_path = os.path.join(PROJECT_ROOT, "data", "app_settings.json")
        json_folder_id = "1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L" # default รวมไฟล์ JSON INDEX
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    json_folder_id = settings.get("json_folder_id", json_folder_id)
            except Exception:
                pass
        
        sync_data = db.get_sync_data_sharded()
        print(f"[INFO] สถิติ Shard ดัชนี: บุคลากรปัจจุบัน {len(sync_data['active_staff'])} คน, อดีตบุคลากร {len(sync_data['former_staff'])} คน")
        
        ok = sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id=json_folder_id, scan_mode="teachers")
        if ok:
            print("[OK] ซิงก์ดัชนี JSON (staff_index.json, former_staff_index.json, person_index.json) ขึ้น Google Drive สำเร็จ 100%")
        else:
            print("[WARN] การซิงก์ดัชนีขึ้น Google Drive พบข้อความเตือน กรุณาตรวจสอบ Log")
    else:
        print("[ERROR] ไม่สามารถเชื่อมต่อ Google Drive ได้")

    out_audit = os.path.join(PROJECT_ROOT, "data", "staff_update_audit_v639.json")
    with open(out_audit, "w", encoding="utf-8") as f:
        json.dump(audit_log, f, ensure_ascii=False, indent=2)
    print(f"[INFO] บันทึกรายงานผลการอัปเดตไว้ที่ {out_audit}")

if __name__ == "__main__":
    run_sync()
