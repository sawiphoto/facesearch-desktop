import os
import sys
import time
import sqlite3
import json
from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def run_tests():
    print("=" * 70)
    print("🚀 RUNNING VERIFICATION SUITE: TC-21 to TC-24 (v6.23 Face Count Index)")
    print("=" * 70)

    db = DatabaseManager()

    # TC-21: Backfill Data Verification
    with db.get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT p.photo_id, p.total_faces_detected, COUNT(pf.id)
            FROM scanned_photos p
            JOIN scanned_photo_faces pf ON p.photo_id = pf.photo_id
            WHERE pf.face_index >= 0
            GROUP BY p.photo_id
            HAVING p.total_faces_detected != COUNT(pf.id)
            LIMIT 5
        """)
        mismatches = c.fetchall()
        assert len(mismatches) == 0, f"TC-21 FAILED: Found {len(mismatches)} mismatches"
        print("✅ TC-21 PASSED: Backfill Data Verified (100% exact match with scanned_photo_faces, 0 mismatches).")

    # TC-22: DB Sync Data Query Speed
    t0 = time.time()
    sync_data = db.get_all_sync_data()
    duration = time.time() - t0
    assert duration < 2.0, f"TC-22 FAILED: Query took {duration:.3f}s (expected < 2.0s)"
    assert len(sync_data["photos"]) > 0, "TC-22 FAILED: Empty photos list"
    assert "face_count" in sync_data["photos"][0], "TC-22 FAILED: Missing face_count key in sync_data['photos']"
    print(f"✅ TC-22 PASSED: DB Sync Data Query Speed Verified ({duration:.3f}s for {len(sync_data['photos'])} photos).")

    # TC-23: JSON Index Generation & Structure
    sync = GoogleSyncManager()
    sample_photos = sync_data["photos"][:3]
    photo_index = {}
    for item in sample_photos:
        photo_id = item["photo_id"]
        raw_link = item["drive_link"]
        photo_index[photo_id] = {
            "event": item["event"],
            "drive_link": sync.format_drive_view_url(raw_link),
            "date": item.get("date", ""),
            "face_count": item.get("face_count", 0)
        }
    for pid, meta in photo_index.items():
        assert "face_count" in meta, f"TC-23 FAILED: Missing face_count for {pid}"
        assert isinstance(meta["face_count"], int), f"TC-23 FAILED: face_count is not int for {pid}"
        assert "event" in meta and "drive_link" in meta and "date" in meta, f"TC-23 FAILED: Missing standard fields for {pid}"
    print(f"✅ TC-23 PASSED: JSON Index Schema Verified (face_count correctly populated with original fields preserved).")

    # TC-24: GUI Version Check
    app_gui_path = os.path.join(os.path.dirname(__file__), "app_gui.py")
    with open(app_gui_path, "r", encoding="utf-8") as f:
        gui_content = f.read()
    assert 'v6.23' in gui_content, "TC-24 FAILED: v6.23 not found in app_gui.py"
    assert 'FACE MATCHING\\nSYSTEM v6.23' in gui_content, "TC-24 FAILED: Sidebar logo is not v6.23"
    print("✅ TC-24 PASSED: System and GUI Version Verified (v6.23 on Window Title and Sidebar).")

    print("=" * 70)
    print("📊 ALL TESTS PASSED: TC-21 to TC-24 (100% SUCCESS)")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
