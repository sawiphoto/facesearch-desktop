import os
import sys
import time
import tempfile
import sqlite3
import py_compile
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db_manager import DatabaseManager


def run_test_suite():
    print("=" * 85)
    print("🚀 RUNNING STUDENT ACADEMIC YEAR LIFECYCLE TEST SUITE v6.29 (TC-52 to TC-59)")
    print("=" * 85)

    # Pre-check: compilation
    py_compile.compile("db_manager.py", doraise=True)
    py_compile.compile("app_gui.py", doraise=True)
    print("[PRE-CHECK] py_compile passed cleanly for db_manager.py and app_gui.py\n")

    results = []
    prod_db_path = os.path.join("data", "faces_db.db")
    prod_db = DatabaseManager(prod_db_path)

    # -------------------------------------------------------------------------
    # TC-52: Student Schema Migration & Data Backfill
    # -------------------------------------------------------------------------
    print("--- [TC-52] Student Schema Migration & Data Backfill ---")
    conn = prod_db.get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(staff_members);")
    cols = {row[1]: row[2] for row in cur.fetchall()}
    has_status = "status" in cols
    has_entry = "entry_year" in cols
    has_grad = "graduation_year" in cols
    has_class = "class_room" in cols

    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='staff_members';")
    indices = [r[0] for r in cur.fetchall()]
    has_idx_status = "idx_sm_status_role" in indices
    has_idx_class = "idx_sm_classroom" in indices

    cur.execute("SELECT COUNT(*) FROM staff_members WHERE role='student';")
    total_students = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staff_members WHERE role='student' AND status='active';")
    active_students = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staff_members WHERE role='student' AND (status IS NULL OR status = '');")
    empty_status = cur.fetchone()[0]
    conn.close()

    tc52_pass = (
        has_status and has_entry and has_grad and has_class and
        has_idx_status and has_idx_class and
        total_students > 0 and active_students == total_students and empty_status == 0
    )
    print(f"Schema columns present: status={has_status}, class_room={has_class}, entry={has_entry}, grad={has_grad}")
    print(f"Indexes: idx_sm_status_role={has_idx_status}, idx_sm_classroom={has_idx_class}")
    print(f"Production Students: total={total_students}, active={active_students}, empty_status={empty_status}")
    print(f"Result: {'PASS' if tc52_pass else 'FAIL'}\n")
    results.append(("TC-52", "Student Schema Migration & Data Backfill", tc52_pass,
                    f"Columns & Indexes OK, {active_students}/{total_students} students backfilled to active"))

    # -------------------------------------------------------------------------
    # TC-53: Cascade Delete Hazard Prevention
    # -------------------------------------------------------------------------
    print("--- [TC-53] Cascade Delete Hazard Prevention ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_lifecycle.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        # Insert a student
        st_id = db_tmp.register_member("นักเรียน ทดสอบรักษาประวัติ", role="student", student_id="99901", class_room="ม.3/1")
        
        # Insert a scanned photo
        photo_id = "test_photo_001"
        conn = db_tmp.get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO scanned_photos (photo_id, file_name, total_faces_detected, drive_file_id, event_name, drive_link, academic_year)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (photo_id, "test.jpg", 1, "test_file_id", "งานกีฬาสี 2568", "https://drive.google.com/test", "2568"))
        for i in range(10):
            c.execute("INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                      (photo_id, st_id, 0.85 + (i * 0.01)))
        conn.commit()
        
        # Count before
        c.execute("SELECT COUNT(*) FROM detected_faces WHERE staff_id = ?", (st_id,))
        count_before = c.fetchone()[0]
        
        # Instead of deleting, mark as graduated
        db_tmp.batch_update_student_status([st_id], "graduated", graduation_year="2568")
        
        # Count after
        c.execute("SELECT COUNT(*) FROM detected_faces WHERE staff_id = ?", (st_id,))
        count_after = c.fetchone()[0]
        
        # Check student status
        c.execute("SELECT status, graduation_year FROM staff_members WHERE id = ?", (st_id,))
        st_status, st_grad_year = c.fetchone()
        conn.close()
        
        tc53_pass = (count_before == 10 and count_after == 10 and st_status == "graduated" and st_grad_year == "2568")
        print(f"Matches before graduation: {count_before}, after: {count_after}")
        print(f"Student status: {st_status}, graduation_year: {st_grad_year}")
        print(f"Result: {'PASS' if tc53_pass else 'FAIL'}\n")
        results.append(("TC-53", "Cascade Delete Hazard Prevention", tc53_pass,
                        f"All {count_after}/10 detected_faces preserved intact after graduation (0% data loss)"))

    # -------------------------------------------------------------------------
    # TC-54: Active-Only Embeddings Filter (Scanning Mode)
    # -------------------------------------------------------------------------
    print("--- [TC-54] Active-Only Embeddings Filter (Scanning Mode) ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_tc54.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        # Register 1 teacher, 1 active student, 1 graduated student
        t_id = db_tmp.register_member("ครูใจดี", role="teacher")
        s1_id = db_tmp.register_member("นักเรียน ปัจจุบัน", role="student", student_id="99911", class_room="ม.1/1")
        s2_id = db_tmp.register_member("นักเรียน ศิษย์เก่า", role="student", student_id="99912", class_room="ม.3/1")
        
        # Add embeddings
        dummy_vec = np.random.rand(512).astype(np.float32)
        dummy_vec /= np.linalg.norm(dummy_vec)
        db_tmp.add_staff_embedding(t_id, "t.jpg", dummy_vec)
        db_tmp.add_staff_embedding(s1_id, "s1.jpg", dummy_vec)
        db_tmp.add_staff_embedding(s2_id, "s2.jpg", dummy_vec)
        
        # Mark s2 as graduated
        db_tmp.batch_update_student_status([s2_id], "graduated", graduation_year="2568")
        
        # Query active-only embeddings (Default scanning mode)
        active_embs = db_tmp.get_all_embeddings(active_only=True)
        active_staff_ids = set(active_embs["staff_ids"])
        
        tc54_pass = (t_id in active_staff_ids and s1_id in active_staff_ids and s2_id not in active_staff_ids)
        print(f"Active staff IDs returned: {active_staff_ids} (Teacher={t_id}, Active={s1_id}, Graduated={s2_id})")
        print(f"Result: {'PASS' if tc54_pass else 'FAIL'}\n")
        results.append(("TC-54", "Active-Only Embeddings Filter (Scanning Mode)", tc54_pass,
                        f"Active student & teacher included, graduated student excluded (0% false positives)"))

    # -------------------------------------------------------------------------
    # TC-55: Retroactive Scan Mode (All Embeddings)
    # -------------------------------------------------------------------------
    print("--- [TC-55] Retroactive Scan Mode (All Embeddings) ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_tc55.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        t_id = db_tmp.register_member("ครูใจดี", role="teacher")
        s1_id = db_tmp.register_member("นักเรียน ปัจจุบัน", role="student", student_id="99921", class_room="ม.1/1")
        s2_id = db_tmp.register_member("นักเรียน ศิษย์เก่า", role="student", student_id="99922", class_room="ม.3/1")
        
        dummy_vec = np.random.rand(512).astype(np.float32)
        dummy_vec /= np.linalg.norm(dummy_vec)
        db_tmp.add_staff_embedding(t_id, "t.jpg", dummy_vec)
        db_tmp.add_staff_embedding(s1_id, "s1.jpg", dummy_vec)
        db_tmp.add_staff_embedding(s2_id, "s2.jpg", dummy_vec)
        
        db_tmp.batch_update_student_status([s2_id], "graduated", graduation_year="2567")
        
        all_embs = db_tmp.get_all_embeddings(active_only=False)
        all_staff_ids = set(all_embs["staff_ids"])
        
        tc55_pass = (t_id in all_staff_ids and s1_id in all_staff_ids and s2_id in all_staff_ids)
        print(f"All staff IDs returned: {all_staff_ids} (All 3 included)")
        print(f"Result: {'PASS' if tc55_pass else 'FAIL'}\n")
        results.append(("TC-55", "Retroactive Scan Mode (All Embeddings)", tc55_pass,
                        f"All {len(all_staff_ids)} members (teachers, active, graduated) loaded for retroactive search"))

    # -------------------------------------------------------------------------
    # TC-56: Batch Graduation Execution & Stats
    # -------------------------------------------------------------------------
    print("--- [TC-56] Batch Graduation Execution & Stats ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_tc56.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        ids = []
        for i in range(5):
            sid = db_tmp.register_member(f"ม.3 คนที่ {i+1}", role="student", student_id=f"3000{i+1}", class_room="ม.3/2")
            ids.append(sid)
            
        for i in range(3):
            db_tmp.register_member(f"ม.1 คนที่ {i+1}", role="student", student_id=f"1000{i+1}", class_room="ม.1/1")
            
        # Batch graduate the 5 M.3 students
        updated_count = db_tmp.batch_update_student_status(ids, "graduated", graduation_year="2568")
        stats = db_tmp.get_student_lifecycle_stats()
        
        tc56_pass = (
            updated_count == 5 and
            stats.get("total_students") == 8 and
            stats.get("active_count") == 3 and
            stats.get("graduated_count") == 5
        )
        print(f"Updated count: {updated_count}, Stats: {stats}")
        print(f"Result: {'PASS' if tc56_pass else 'FAIL'}\n")
        results.append(("TC-56", "Batch Graduation Execution & Stats", tc56_pass,
                        f"Batch graduated 5 students in 1 transaction; Active=3, Graduated=5"))

    # -------------------------------------------------------------------------
    # TC-57: Batch Promotion Execution & Classroom Listing
    # -------------------------------------------------------------------------
    print("--- [TC-57] Batch Promotion Execution & Classroom Listing ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_tc57.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        # 4 students in M.1/1 and 3 in M.2/1
        for i in range(4):
            db_tmp.register_member(f"นักเรียน A{i}", role="student", student_id=f"110{i}", class_room="ม.1/1")
        for i in range(3):
            db_tmp.register_member(f"นักเรียน B{i}", role="student", student_id=f"210{i}", class_room="ม.2/1")
            
        rooms_before = db_tmp.get_student_classrooms()
        
        # Promote M.2/1 -> M.3/1 first, then M.1/1 -> M.2/1
        p2 = db_tmp.batch_promote_students("ม.2/1", "ม.3/1")
        p1 = db_tmp.batch_promote_students("ม.1/1", "ม.2/1")
        promoted_total = p1 + p2
        rooms_after = db_tmp.get_student_classrooms()
        
        # Check counts
        conn = db_tmp.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM staff_members WHERE class_room = 'ม.2/1';")
        count_m2 = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staff_members WHERE class_room = 'ม.3/1';")
        count_m3 = cur.fetchone()[0]
        conn.close()
        
        tc57_pass = (
            promoted_total == 7 and
            count_m2 == 4 and
            count_m3 == 3 and
            "ม.1/1" not in rooms_after and
            "ม.2/1" in rooms_after and
            "ม.3/1" in rooms_after
        )
        print(f"Promoted total: {promoted_total}, Rooms before: {rooms_before}, Rooms after: {rooms_after}")
        print(f"Classroom counts: M.2/1={count_m2}, M.3/1={count_m3}")
        print(f"Result: {'PASS' if tc57_pass else 'FAIL'}\n")
        results.append(("TC-57", "Batch Promotion Execution & Classroom Listing", tc57_pass,
                        f"Promoted 7 students: M.1/1->M.2/1 (4), M.2/1->M.3/1 (3)"))

    # -------------------------------------------------------------------------
    # TC-58: Student Find, Update & Classroom Integration (Google Sheets Workflow)
    # -------------------------------------------------------------------------
    print("--- [TC-58] Student Find, Update & Classroom Integration ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_tc58.db")
        db_tmp = DatabaseManager(tmp_db_path)
        
        # Initial import: student in M.1/1
        s_id = db_tmp.register_member("ด.ช. สมชาย รักเรียน", role="student", student_id="55001", class_room="ม.1/1", entry_year="2567")
        db_tmp.add_staff_embedding(s_id, "photo1.jpg", np.zeros(512, dtype=np.float32))
        
        # Second year import from Google Sheets: Same student_id "55001", but now in M.2/1
        existing_info = db_tmp.find_student_by_code_and_name("55001", "สมชาย")
        
        # Verify find
        assert existing_info is not None
        existing_id = existing_info["id"]
        assert existing_id == s_id
        
        # Update student classroom & status
        db_tmp.update_student_info(existing_id, "ด.ช. สมชาย รักเรียน", "55001", class_room="ม.2/1", status="active")
        db_tmp.add_staff_embedding(existing_id, "photo2.jpg", np.ones(512, dtype=np.float32))
        
        # Check student info
        students = db_tmp.get_all_students()
        target = [s for s in students if s["id"] == existing_id][0]
        
        tc58_pass = (
            len(students) == 1 and
            target["class_room"] == "ม.2/1" and
            target["status"] == "active" and
            target["photo_count"] == 2
        )
        print(f"Existing student found: id={existing_id}, Updated classroom={target['class_room']}, photo_count={target['photo_count']}")
        print(f"Result: {'PASS' if tc58_pass else 'FAIL'}\n")
        results.append(("TC-58", "Student Find, Update & Classroom Integration", tc58_pass,
                        f"Updated existing student to M.2/1 with 2 photos; 0 duplicate member created"))

    # -------------------------------------------------------------------------
    # TC-59: GUI Version v6.29 & py_compile Parity
    # -------------------------------------------------------------------------
    print("--- [TC-59] GUI Version v6.29 & py_compile Parity ---")
    with open("app_gui.py", "r", encoding="utf-8") as f:
        gui_content = f.read()
        
    has_window_title_v629 = 'self.title("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v6.29 (Student Lifecycle & Graduation Suite)")' in gui_content
    has_sidebar_logo_v629 = 'text="FACE MATCHING\\nSYSTEM v6.29"' in gui_content
    has_lifecycle_dialog = "class StudentLifecycleDialog" in gui_content
    has_segmented_status = "student_status_segmented" in gui_content
    
    tc59_pass = has_window_title_v629 and has_sidebar_logo_v629 and has_lifecycle_dialog and has_segmented_status
    print(f"Window title v6.29: {has_window_title_v629}")
    print(f"Sidebar logo v6.29: {has_sidebar_logo_v629}")
    print(f"StudentLifecycleDialog class: {has_lifecycle_dialog}")
    print(f"Status Segmented filter: {has_segmented_status}")
    print(f"Result: {'PASS' if tc59_pass else 'FAIL'}\n")
    results.append(("TC-59", "GUI Version v6.29 & py_compile Parity", tc59_pass,
                    f"Title, Sidebar, Dialog, and Filter Bar verified v6.29"))

    # -------------------------------------------------------------------------
    # Summary Report
    # -------------------------------------------------------------------------
    print("=" * 85)
    print("📋 SUMMARY REPORT: v6.29 TEST EXECUTION")
    print("=" * 85)
    passed_count = sum(1 for r in results if r[2])
    total_count = len(results)
    for tid, name, passed, details in results:
        status_str = "✅ PASS" if passed else "❌ FAIL"
        print(f"[{status_str}] {tid}: {name} -> {details}")
    print("-" * 85)
    print(f"TOTAL: {passed_count}/{total_count} PASSED ({passed_count/total_count*100:.1f}%)")
    print("=" * 85)

    return passed_count == total_count


if __name__ == "__main__":
    success = run_test_suite()
    sys.exit(0 if success else 1)
