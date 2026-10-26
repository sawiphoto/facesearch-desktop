import os
import sys
import time
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_manager import DatabaseManager


class TestOneToNFaceSearchSuite(unittest.TestCase):
    """ชุดทดสอบฟีเจอร์ค้นหาใบหน้า 1-ต่อ-N ความเร็วสูง และบันทึกขึ้นทะเบียนด่วน (v6.61)"""

    def test_01_live_db_vector_search_and_cancellation(self):
        """ทดสอบค้นหาเวกเตอร์ใบหน้าจริงกับฐานข้อมูล SQLite (1,091,602+ ใบหน้า) และการยกเลิกกลางคัน"""
        db = DatabaseManager()
        years = db.get_available_academic_years()
        self.assertIsInstance(years, list)
        self.assertTrue(len(years) > 0)

        # ดึงเวกเตอร์จริง 1 รายการจาก scanned_photo_faces มาทดสอบค้นหา
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pf.embedding, p.academic_year
                FROM scanned_photo_faces pf
                JOIN scanned_photos p ON pf.photo_id = p.photo_id
                WHERE pf.face_index >= 0 AND pf.embedding IS NOT NULL AND LENGTH(pf.embedding) = 2048
                LIMIT 1
            """)
            row = cursor.fetchone()

        self.assertIsNotNone(row, "Expected at least 1 valid face embedding in scanned_photo_faces")
        sample_emb = np.frombuffer(row[0], dtype=np.float32)
        sample_year = row[1]

        progress_calls = []
        def _progress_cb(done, total, found):
            progress_calls.append((done, total, found))

        t0 = time.time()
        matches = db.search_faces_by_embedding(
            query_emb=sample_emb,
            threshold=0.55,
            academic_year=sample_year if sample_year else "ทั้งหมด",
            progress_callback=_progress_cb
        )
        elapsed = time.time() - t0

        self.assertTrue(len(matches) >= 1, "Querying an existing embedding must match at least its own photo")
        self.assertTrue(len(progress_calls) >= 2, "Progress callback should be invoked")
        # ตรวจสอบการเรียงลำดับจากความมั่นใจสูงสุดลงมา และไม่มี photo_id ซ้ำ
        seen_pids = set()
        prev_conf = 2.0
        for m in matches:
            self.assertNotIn(m["photo_id"], seen_pids, "Results must be deduplicated per photo_id")
            seen_pids.add(m["photo_id"])
            self.assertLessEqual(m["confidence"], prev_conf + 1e-6)
            prev_conf = m["confidence"]
            self.assertIn("drive_file_id", m)
            self.assertIn("event_name", m)
            self.assertIn("bbox", m)

        # ทดสอบการสั่งยกเลิกกลางคัน (Cancel Event)
        cancel_ev = threading.Event()
        cancel_ev.set()
        cancelled_matches = db.search_faces_by_embedding(
            query_emb=sample_emb,
            threshold=0.45,
            cancel_event=cancel_ev
        )
        self.assertEqual(cancelled_matches, [])
        print(f"[TEST 01] Live vector search (year={sample_year}) matched {len(matches)} photos in {elapsed:.3f}s")

    def test_02_bulk_append_12000_matches_and_non_destructive_safety(self):
        """ทดสอบบันทึกผูกภาพระดับ 12,000+ รูปใน Transaction เดียว โดยไม่กระทบข้อมูลของบุคคลอื่นในรูปเดียวกัน"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db_path = os.path.join(tmpdir, "test_faces_12k.db")
            temp_year_json = os.path.join(tmpdir, "year_folders.json")
            db = DatabaseManager(db_path=temp_db_path, year_folders_json_path=temp_year_json)

            staff_other = db.register_staff_member("ครูท่านอื่น ที่มีผลแมตช์อยู่แล้ว", department="คณิตศาสตร์")
            staff_new = db.register_staff_member("ครูคนใหม่ ทดสอบหมื่นภาพ", department="วิทยาศาสตร์")

            # สร้างข้อมูลจำลอง 12,000 รูป และผูกครูท่านอื่นไว้ใน 100 รูปแรก
            with db.get_connection() as conn:
                cur = conn.cursor()
                photo_rows = [
                    (f"P{i}", f"FID_{i}", f"กิจกรรมที่ {i % 50}", f"https://drive.google.com/file/d/FID_{i}/view", "2026-01-15", "2568")
                    for i in range(1, 12001)
                ]
                cur.executemany(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date, academic_year) VALUES (?, ?, ?, ?, ?, ?)",
                    photo_rows
                )
                other_rows = [(f"P{i}", staff_other, 0.88) for i in range(1, 101)]
                cur.executemany(
                    "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                    other_rows
                )
                conn.commit()

            # เตรียมผลลัพธ์ 12,000 รูปสำหรับครูคนใหม่
            matches_12k = [
                {
                    "photo_id": f"P{i}",
                    "confidence": 0.50 + ((i % 45) * 0.01),
                    "bbox": [10.0, 20.0, 110.0, 120.0]
                }
                for i in range(1, 12001)
            ]

            t0 = time.time()
            inserted = db.bulk_append_detected_faces(staff_new, matches_12k, used_threshold=0.45)
            elapsed = time.time() - t0

            self.assertEqual(inserted, 12000)
            self.assertLess(elapsed, 2.0, f"Bulk insert of 12,000 matches should be fast, took {elapsed:.2f}s")

            # ตรวจสอบว่าข้อมูลของครูท่านอื่น 100 รูปยังคงอยู่ครบ 100%
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM detected_faces WHERE staff_id = ?", (staff_other,))
                other_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM detected_faces WHERE staff_id = ?", (staff_new,))
                new_cnt = cur.fetchone()[0]

            self.assertEqual(other_cnt, 100, "Other staff members' matches must NOT be deleted!")
            self.assertEqual(new_cnt, 12000)

            # ทดสอบรันซ้ำอีกครั้ง ต้องไม่เกิดแถวซ้ำซ้อน
            inserted_again = db.bulk_append_detected_faces(staff_new, matches_12k[:500], used_threshold=0.45)
            self.assertEqual(inserted_again, 500)
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM detected_faces WHERE staff_id = ?", (staff_new,))
                new_cnt_after = cur.fetchone()[0]
            self.assertEqual(new_cnt_after, 12000, "Re-running bulk_append_detected_faces must not create duplicate rows")
            print(f"[TEST 02] Bulk inserted 12,000 matches in {elapsed:.3f}s with 0 duplicates and 100% non-destructive safety")

    def test_03_gui_face_search_10500_items_pagination_and_subfilters(self):
        """ทดสอบหน้าจอ GUI เมนูค้นหาบุคคลจากภาพ การกรองย่อยระดับ 10,500 รูป และการแบ่งหน้าละ 24 การ์ด"""
        from app_gui import FaceSearchApp

        mock_analyzer = MagicMock()
        mock_analyzer.initialized = True

        app = FaceSearchApp(analyzer=mock_analyzer)
        try:
            # 1. สลับไปยังเมนูใหม่ face_search
            app.select_menu("face_search")
            self.assertEqual(app.btn_face_search.cget("text_color"), "white")

            # 2. จำลองผลลัพธ์การค้นหา 10,500 รูปภาพ
            synthetic_matches = []
            for i in range(1, 10501):
                year_str = "2569" if i <= 3500 else ("2568" if i <= 7000 else "2567")
                conf_val = 0.85 if (i % 5 == 0) else (0.65 if (i % 2 == 0) else 0.48)
                ev_str = "งานวันไหว้ครู" if (i % 10 == 0) else f"กิจกรรมหน้าเสาธง {i}"
                synthetic_matches.append({
                    "photo_id": f"P{i}",
                    "drive_file_id": "",
                    "event_name": ev_str,
                    "drive_link": f"https://drive.google.com/file/d/FID_{i}/view",
                    "photo_date": f"2026-01-{(i % 28) + 1:02d}",
                    "academic_year": year_str,
                    "file_name": f"IMG_{i:05d}.JPG",
                    "confidence": conf_val,
                    "face_index": 0,
                    "bbox": [0, 0, 100, 100]
                })

            app.face_search_all_matches = synthetic_matches
            app.face_search_selected_pids = {m["photo_id"] for m in synthetic_matches}

            t0 = time.time()
            app.apply_face_search_subfilters(reset_page=True)
            filter_elapsed = time.time() - t0

            self.assertEqual(len(app.face_search_filtered_matches), 10500)
            self.assertEqual(app._get_fs_total_pages(), 438)  # ceil(10500 / 24) = 438 หน้า
            # ตรวจสอบว่าใน ScrollableFrame สร้างการ์ดเพียง 24 ใบเท่านั้น ไม่สร้างหมื่นใบจนค้าง
            rendered_cards = app.scr_face_search_results.winfo_children()
            self.assertEqual(len(rendered_cards), 24)
            self.assertLess(filter_elapsed, 1.5, f"Filtering and rendering page 1 of 10,500 items took {filter_elapsed:.2f}s")

            # 3. ทดสอบกระโดดไปหน้าสุดท้าย (หน้าที่ 438 มี 12 รูป: 10500 - 437*24 = 12)
            app.go_to_face_search_page(438)
            self.assertEqual(app.face_search_current_page, 438)
            self.assertEqual(len(app.scr_face_search_results.winfo_children()), 12)

            # 4. ทดสอบตัวกรองย่อย: ปี 2569 + ความเหมือน >= 80% + คำค้น "ไหว้ครู"
            app.combo_fs_sub_year.set("2569")
            app.combo_fs_sub_conf.set(">= 80%")
            app.entry_fs_sub_keyword.delete(0, "end")
            app.entry_fs_sub_keyword.insert(0, "ไหว้ครู")
            app.apply_face_search_subfilters(reset_page=True)

            # ใน 3,500 รูปแรก (ปี 2569) รูปที่หาร 10 ลงตัวมีทั้ง i%5==0 (conf 0.85) และชื่อ "งานวันไหว้ครู" = 350 รูป
            self.assertEqual(len(app.face_search_filtered_matches), 350)

            # 5. ทดสอบปุ่มเลือก/ยกเลิกการเลือกแบบกลุ่ม
            app.fs_deselect_all()
            self.assertEqual(len(app.face_search_selected_pids), 0)
            app.fs_select_current_page()
            self.assertEqual(len(app.face_search_selected_pids), 24)
            app.fs_select_all_filtered()
            self.assertEqual(len(app.face_search_selected_pids), 350)

            # 6. ทดสอบปุ่มปฏิเสธ / ล้างผลลัพธ์ (Discard)
            app.discard_face_search_results()
            self.assertEqual(len(app.face_search_all_matches), 0)
            self.assertEqual(len(app.face_search_selected_pids), 0)
            print(f"[TEST 03] GUI 10,500 items pagination & sub-filtering verified in {filter_elapsed:.3f}s")
        finally:
            app.face_search_worker_gen += 1
            app.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
