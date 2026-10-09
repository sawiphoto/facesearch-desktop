import os
import sys
import sqlite3
import re

# บังคับ UTF-8 สำหรับการแสดงผลบน Windows Terminal
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def export_student_photos():
    project_root = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(project_root, "data", "faces_db.db")
    export_dir = os.path.join(project_root, "export_student")
    
    os.makedirs(export_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT sm.id, sm.name, sm.student_id, se.image_path
        FROM staff_members sm
        JOIN staff_embeddings se ON sm.id = se.staff_id
        WHERE sm.role = 'student'
        ORDER BY sm.student_id ASC, sm.name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    print(f"พบรายการรูปภาพนักเรียนทั้งหมด {len(rows)} รายการในฐานข้อมูล")
    
    student_img_count = {}
    success_count = 0
    missing_count = 0
    
    for staff_id, name, student_id, src_path in rows:
        name_clean = sanitize_filename(name or "Unknown")
        std_id_clean = sanitize_filename(str(student_id) if student_id else f"ID_{staff_id}")
        
        key = (std_id_clean, name_clean)
        student_img_count[key] = student_img_count.get(key, 0) + 1
        seq = student_img_count[key]
        
        if not src_path or not os.path.exists(src_path):
            if src_path:
                alt_path = os.path.join(project_root, src_path)
                if os.path.exists(alt_path):
                    src_path = alt_path
                else:
                    alt_path_tpl = os.path.join(project_root, "data", "student_templates", os.path.basename(src_path))
                    if os.path.exists(alt_path_tpl):
                        src_path = alt_path_tpl
                        
        if not src_path or not os.path.exists(src_path):
            print(f"[MISSING] ไม่พบไฟล์ภาพต้นทางสำหรับ: {std_id_clean}_{name_clean} (Path: {src_path})")
            missing_count += 1
            continue
            
        ext = os.path.splitext(src_path)[1]
        if not ext:
            ext = ".jpg"
            
        if seq == 1:
            dst_filename = f"{std_id_clean}_{name_clean}{ext}"
        else:
            dst_filename = f"{std_id_clean}_{name_clean}_{seq}{ext}"
            
        dst_path = os.path.join(export_dir, dst_filename)
        
        try:
            with open(src_path, "rb") as f_src:
                data = f_src.read()
            with open(dst_path, "wb") as f_dst:
                f_dst.write(data)
                
            success_count += 1
            print(f"[SUCCESS] ส่งออก: {dst_filename}")
        except Exception as e:
            print(f"[ERROR] เกิดข้อผิดพลาดในการส่งออก {dst_filename}: {e}")
            
    print("\n" + "="*50)
    print(f"สรุปการส่งออกรูปภาพนักเรียน:")
    print(f" - ส่งออกสำเร็จ: {success_count} รูป")
    print(f" - ไฟล์สูญหาย/ไม่พบต้นฉบับ: {missing_count} รูป")
    print(f" - โฟลเดอร์ปลายทาง: {export_dir}")
    print("="*50)

if __name__ == "__main__":
    export_student_photos()
