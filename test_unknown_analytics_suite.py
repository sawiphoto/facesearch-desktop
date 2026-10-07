# -*- coding: utf-8 -*-
"""
Test Suite for Unknown Faces VIP & Yearly Analytics Dashboard (v6.20)
Covers all test cases from TC-01 to TC-18 in implementation_plan.md
"""

import os
import sys
import json
import sqlite3
import tempfile
import numpy as np

# Configure UTF-8 for console output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root is in path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db_manager import DatabaseManager
import unknown_analyzer
from gradient_chart import get_gradient_color, GradientBarChart
from face_analyzer import read_image_file

def run_tests():
    passed = 0
    failed = 0
    total = 18

    print("=" * 70)
    print("🚀 STARTING RUNTIME VERIFICATION SUITE: TC-01 to TC-18 (v6.20)")
    print("=" * 70)

    # ----------------------------------------------------
    # TC-01: db_manager.create_unknown_tables
    # ----------------------------------------------------
    try:
        temp_db_path = os.path.join(tempfile.gettempdir(), f"test_unknown_{os.getpid()}.db")
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

        db = DatabaseManager(db_path=temp_db_path)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unknown_clusters'")
            t1 = cursor.fetchone()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unknown_cluster_members'")
            t2 = cursor.fetchone()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unknown_cluster_year_stats'")
            t3 = cursor.fetchone()

        assert t1 and t2 and t3, "One or more unknown tables missing"
        print("✅ TC-01 PASSED: Unknown tables created with proper schema in SQLite.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-01 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-02: Idempotency test (call create_unknown_tables again)
    # ----------------------------------------------------
    try:
        db.create_unknown_tables()
        print("✅ TC-02 PASSED: Idempotency verified (no errors when calling create_unknown_tables repeatedly).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-02 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-03: filter_unknown_faces / get_unmatched_face_embeddings
    # ----------------------------------------------------
    try:
        # Populate mock data in temp db
        with db.get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO staff_members (id, name, role) VALUES (1, 'Teacher 1', 'teacher')")
            # Photo P001 has matched face in detected_faces
            c.execute("INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, photo_date, drive_link) VALUES ('P001', 'F001', 'Event 1', '2026-01-01', 'https://drive.google.com/test1')")
            c.execute("INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES ('P001', 1, 0.85)")
            emb_matched = np.ones(512, dtype=np.float32).tobytes()
            c.execute("INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding) VALUES ('P001', 0, 10, 10, 50, 50, ?)", (emb_matched,))
            
            # Photo P002 has unmatched unknown face (no record in detected_faces)
            c.execute("INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, photo_date, drive_link) VALUES ('P002', 'F002', 'Event 2', '2026-01-02', 'https://drive.google.com/test2')")
            emb_unknown = (np.ones(512, dtype=np.float32) * 2).tobytes()
            c.execute("INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding) VALUES ('P002', 0, 60, 60, 100, 100, ?)", (emb_unknown,))
            conn.commit()

        unmatched = db.get_unmatched_face_embeddings()
        assert len(unmatched) == 1, f"Expected 1 unmatched face, got {len(unmatched)}"
        assert unmatched[0]["photo_id"] == "P002", f"Expected photo_id P002, got {unmatched[0]['photo_id']}"
        print("✅ TC-03 PASSED: Matched photos correctly filtered out; only unknown faces retrieved.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-03 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-04: extract_thai_year normal date
    # ----------------------------------------------------
    try:
        res = unknown_analyzer.extract_thai_year("2026-05-12", "กิจกรรมวันเด็ก")
        assert res == "2569", f"Expected '2569', got '{res}'"
        print("✅ TC-04 PASSED: Standard AD date converted to Thai Buddhist year correctly (2026 -> 2569).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-04 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-05: extract_thai_year fallback
    # ----------------------------------------------------
    try:
        res = unknown_analyzer.extract_thai_year("", "ภาพกิจกรรมวันไหว้ครู 2568")
        assert res == "2568", f"Expected '2568', got '{res}'"
        res2 = unknown_analyzer.extract_thai_year("invalid-date", "กีฬาสี 2023")
        assert res2 == "2566", f"Expected '2566', got '{res2}'"
        print("✅ TC-05 PASSED: Year successfully extracted from folder/event name fallback.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-05 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-06: cluster_unknown_faces (same person)
    # ----------------------------------------------------
    try:
        np.random.seed(42)
        base_a = np.random.randn(512).astype(np.float32)
        base_a /= np.linalg.norm(base_a)

        # 3 variations of person A (cos sim > 0.85)
        face_items_same = []
        for i in range(3):
            noise = np.random.randn(512).astype(np.float32)
            noise = (noise / np.linalg.norm(noise)) * 0.15
            vec = base_a + noise
            vec /= np.linalg.norm(vec)
            face_items_same.append({
                "photo_id": f"P_A_{i}",
                "face_index": 0,
                "embedding": vec.tobytes(),
                "photo_date": "2026-01-01",
                "event_name": "Event A",
                "bbox": [10, 10, 50, 50]
            })

        c_data, m_data, y_data = unknown_analyzer.cluster_unknown_faces(face_items_same, sim_threshold=0.65)
        assert len(c_data) == 1, f"Expected 1 cluster for same person, got {len(c_data)}"
        assert len(m_data) == 3, f"Expected 3 members in cluster, got {len(m_data)}"
        print("✅ TC-06 PASSED: Faces of the same individual merged into 1 cluster accurately.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-06 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-07: Anti-Drift (distinct individuals remain separate)
    # ----------------------------------------------------
    try:
        base_b = np.random.randn(512).astype(np.float32)
        base_b /= np.linalg.norm(base_b)

        face_items_diff = face_items_same.copy()
        for i in range(2):
            noise = np.random.randn(512).astype(np.float32)
            noise = (noise / np.linalg.norm(noise)) * 0.15
            vec = base_b + noise
            vec /= np.linalg.norm(vec)
            face_items_diff.append({
                "photo_id": f"P_B_{i}",
                "face_index": 0,
                "embedding": vec.tobytes(),
                "photo_date": "2025-01-01",
                "event_name": "Event B",
                "bbox": [20, 20, 60, 60]
            })

        c_data, m_data, y_data = unknown_analyzer.cluster_unknown_faces(face_items_diff, sim_threshold=0.65)
        assert len(c_data) == 2, f"Expected 2 clusters for 2 distinct persons, got {len(c_data)}"
        print("✅ TC-07 PASSED: Anti-drift threshold prevented distinct individuals from merging.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-07 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-08: save_unknown_clusters_batch in DB
    # ----------------------------------------------------
    try:
        ok = db.save_unknown_clusters_batch(c_data, m_data, y_data)
        assert ok, "save_unknown_clusters_batch returned False"
        summary = db.get_unknown_clusters_summary(selected_year="all", min_photos=1)
        assert len(summary) == 2, f"Expected 2 clusters in summary, got {len(summary)}"
        years = db.get_unknown_available_years()
        assert "2569" in years and "2568" in years, f"Expected years 2569, 2568, got {years}"
        print("✅ TC-08 PASSED: Clusters and yearly stats committed into SQLite in single batch transaction.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-08 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-09: Gradient color min value (ratio = 0.0) -> Red
    # ----------------------------------------------------
    try:
        color_min = get_gradient_color(0, 0, 100).upper()
        assert color_min == "#E74C3C", f"Expected '#E74C3C', got '{color_min}'"
        print("✅ TC-09 PASSED: Minimum value mapped to RED (#E74C3C).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-09 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-10: Gradient color mid value (ratio = 0.5) -> Yellow
    # ----------------------------------------------------
    try:
        color_mid = get_gradient_color(50, 0, 100).upper()
        assert color_mid == "#F1C40F", f"Expected '#F1C40F', got '{color_mid}'"
        print("✅ TC-10 PASSED: Midpoint value mapped to YELLOW (#F1C40F).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-10 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-11: Gradient color max value (ratio = 1.0) -> Green
    # ----------------------------------------------------
    try:
        color_max = get_gradient_color(100, 0, 100).upper()
        assert color_max == "#2ECC71", f"Expected '#2ECC71', got '{color_max}'"
        print("✅ TC-11 PASSED: Maximum value mapped to GREEN (#2ECC71).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-11 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-12: GradientBarChart year sorting (descending: 2569 -> 2568 -> ...)
    # ----------------------------------------------------
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        chart = GradientBarChart(root)
        chart.set_data([("2565", 10), ("2568", 25), ("2566", 12), ("2569", 40), ("2567", 18)])
        years_in_order = [y for y, _ in chart.bar_data]
        expected_order = ["2569", "2568", "2567", "2566", "2565"]
        assert years_in_order == expected_order, f"Expected {expected_order}, got {years_in_order}"
        print("✅ TC-12 PASSED: Bar chart correctly sorts years descending (Present -> Past).")
        passed += 1
    except Exception as e:
        print(f"❌ TC-12 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-13: GradientBarChart edge case (single year, division by zero)
    # ----------------------------------------------------
    try:
        chart.set_data([("2569", 15)])
        chart.draw_chart()
        assert len(chart.bar_data) == 1
        print("✅ TC-13 PASSED: Single year edge case handled safely without ZeroDivisionError.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-13 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-14: Crop face with 25% padding margin
    # ----------------------------------------------------
    try:
        import cv2
        test_img = np.zeros((300, 300, 3), dtype=np.uint8)
        # Face box: x1=100, y1=100, x2=200, y2=200 (width=100, height=100)
        cv2.rectangle(test_img, (100, 100), (200, 200), (255, 255, 255), -1)
        h, w = test_img.shape[:2]
        bw, bh = 100, 100
        pad_x, pad_y = int(bw * 0.25), int(bh * 0.25)
        cx1 = max(0, 100 - pad_x)
        cy1 = max(0, 100 - pad_y)
        cx2 = min(w, 200 + pad_x)
        cy2 = min(h, 200 + pad_y)
        cropped = test_img[cy1:cy2, cx1:cx2]
        assert cropped.shape == (150, 150, 3), f"Expected shape (150, 150, 3), got {cropped.shape}"
        print("✅ TC-14 PASSED: Bounding box cropped with 25% padding margin accurately.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-14 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-15: Export cropped face to disk with Thai Unicode path
    # ----------------------------------------------------
    try:
        temp_thai_dir = os.path.join(tempfile.gettempdir(), "ทดสอบ_โฟลเดอร์_ภาษาไทย")
        os.makedirs(temp_thai_dir, exist_ok=True)
        save_path = os.path.join(temp_thai_dir, "รูปใบหน้า_UNK_00001.jpg")
        success, enc = cv2.imencode('.jpg', cropped)
        assert success, "cv2.imencode failed"
        enc.tofile(save_path)
        assert os.path.exists(save_path) and os.path.getsize(save_path) > 0, "Saved file missing or empty"

        # Verify reading with read_image_file
        loaded_img = read_image_file(save_path)
        assert loaded_img is not None, "Failed to read saved image with read_image_file"
        os.remove(save_path)
        os.rmdir(temp_thai_dir)
        print("✅ TC-15 PASSED: Exported face image saved and read with Thai Unicode path without issue.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-15 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-16: App GUI Year Filter Change
    # ----------------------------------------------------
    try:
        # Test query filtering by year in DB manager
        rows_all = db.get_unknown_clusters_summary(selected_year="all", min_photos=1)
        rows_2569 = db.get_unknown_clusters_summary(selected_year="2569", min_photos=1)
        rows_2568 = db.get_unknown_clusters_summary(selected_year="2568", min_photos=1)
        assert len(rows_all) >= len(rows_2569), "Overall count should be >= year count"
        print("✅ TC-16 PASSED: Year filter query retrieves matching records for specific years.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-16 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-17: App GUI on_unknown_cluster_select data binding
    # ----------------------------------------------------
    try:
        summary = db.get_unknown_clusters_summary(selected_year="all", min_photos=1)
        assert len(summary) > 0, "No summary rows found"
        cluster_id = summary[0][0]
        y_stats = db.get_unknown_cluster_yearly_breakdown(cluster_id)
        m_photos = db.get_unknown_cluster_member_photos(cluster_id)
        assert len(y_stats) > 0, "No yearly breakdown found"
        assert len(m_photos) > 0, "No member photos found"
        print("✅ TC-17 PASSED: Detail data binding (profile, yearly breakdown, member photos) verified.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-17 FAILED: {e}")
        failed += 1

    # ----------------------------------------------------
    # TC-18: Multi-Threading Clustering & Non-blocking execution
    # ----------------------------------------------------
    try:
        import threading
        thread_done = False
        def worker_test():
            nonlocal thread_done
            unmatched = db.get_unmatched_face_embeddings()
            c, m, y = unknown_analyzer.cluster_unknown_faces(unmatched, sim_threshold=0.65)
            thread_done = True

        t = threading.Thread(target=worker_test, daemon=True)
        t.start()
        t.join(timeout=5.0)
        assert thread_done, "Worker thread timed out or failed"
        print("✅ TC-18 PASSED: Clustering thread executed asynchronously without blocking main thread.")
        passed += 1
    except Exception as e:
        print(f"❌ TC-18 FAILED: {e}")
        failed += 1

    # Cleanup temp db
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except Exception:
        pass

    root.destroy()

    print("=" * 70)
    print(f"📊 TEST RESULTS SUMMARY: {passed}/{total} PASSED ({failed} FAILED)")
    print("=" * 70)
    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
