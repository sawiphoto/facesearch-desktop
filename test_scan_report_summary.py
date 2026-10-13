import os
import sys
import json
import tempfile
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Set path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scheduler_task import ScanSessionTracker, SchedulerTask
from face_analyzer import get_project_root


def test_tc25_tracker_accounting():
    print("=== TC-25: Testing ScanSessionTracker Accounting & Top 10 ===")
    tracker = ScanSessionTracker()
    assert tracker.has_scanned_items() is False, "Initial tracker should have no items"

    # Record Folder 1
    tracker.record_folder_start("กค 2 ต้อนรับครูใหม่", "2567", 5)
    tracker.record_raw_photo("กค 2 ต้อนรับครูใหม่", "DSC001.ARW", "drive_id_raw_1")
    tracker.record_ai_photo("กค 2 ต้อนรับครูใหม่", "IMG002.JPG", "drive_id_ai_2", 2, ["นายสมชาย เข็มทิศ", "นางสาวสมหญิง จริงใจ"])
    tracker.record_ai_photo("กค 2 ต้อนรับครูใหม่", "IMG003.JPG", "drive_id_ai_3", 1, ["นายสมชาย เข็มทิศ"])
    tracker.record_skipped("กค 2 ต้อนรับครูใหม่", "CORRUPT.JPG", "drive_id_skip_4", "ไม่สามารถ Decode ไฟล์ภาพได้", "https://drive.google.com/test4")
    tracker.record_folder_finish("กค 2 ต้อนรับครูใหม่", is_completed=False)

    # Record Folder 2
    tracker.record_folder_start("วันภาษาไทย 2567", "2567", 3)
    tracker.record_ai_photo("วันภาษาไทย 2567", "THAI01.JPG", "drive_id_ai_5", 3, ["นายสมชาย เข็มทิศ", "ครูกานดา มณีโชติ"])
    tracker.record_raw_photo("วันภาษาไทย 2567", "THAI02.CR3", "drive_id_raw_6")
    tracker.record_folder_finish("วันภาษาไทย 2567", is_completed=True)

    assert tracker.has_scanned_items() is True, "Tracker should now have items"

    summary = tracker.finalize(stopped_by_user=True, json_synced=True)

    assert summary["total_folders"] == 2, f"Expected 2 folders, got {summary['total_folders']}"
    assert summary["total_all_images"] == 6, f"Expected 6 images, got {summary['total_all_images']}"
    assert summary["total_ai_photos"] == 3, f"Expected 3 AI photos, got {summary['total_ai_photos']}"
    assert summary["total_raw_photos"] == 2, f"Expected 2 RAW photos, got {summary['total_raw_photos']}"
    assert summary["total_skipped_photos"] == 1, f"Expected 1 skipped photo, got {summary['total_skipped_photos']}"
    assert summary["total_faces_detected"] == 6, f"Expected 6 faces, got {summary['total_faces_detected']}"
    assert summary["stopped_by_user"] is True, "stopped_by_user should be True"
    assert summary["json_sync_completed"] is True, "json_sync_completed should be True"

    # Verify Top 10
    top_10 = summary["top_10_people"]
    assert len(top_10) == 3, f"Expected 3 distinct people, got {len(top_10)}"
    assert top_10[0]["name"] == "นายสมชาย เข็มทิศ"
    assert top_10[0]["count"] == 3, f"Expected Somchai count 3, got {top_10[0]['count']}"

    # Verify Skipped files
    assert len(summary["skipped_files"]) == 1
    assert summary["skipped_files"][0]["file_name"] == "CORRUPT.JPG"

    print("✅ TC-25 PASSED: Tracker Accounting, Metrics & Top 10 verified.")


def test_tc26_save_report_to_disk():
    print("=== TC-26: Testing Report Exporter (Markdown & JSON) ===")
    tracker = ScanSessionTracker()
    tracker.record_folder_start("อบรมคอมพิวเตอร์", "2567", 2)
    tracker.record_ai_photo("อบรมคอมพิวเตอร์", "PC01.JPG", "id_1", 1, ["อาจารย์ประเสริฐ"])
    tracker.record_folder_finish("อบรมคอมพิวเตอร์", is_completed=True)

    project_root = get_project_root()
    saved_path = tracker.save_report_to_disk(project_root)

    assert os.path.exists(saved_path), f"Saved markdown report not found: {saved_path}"
    json_path = saved_path.replace(".md", ".json")
    assert os.path.exists(json_path), f"Saved json report not found: {json_path}"

    with open(saved_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    assert "# 📊 รายงานสรุปผลการสแกนภาพถ่ายกิจกรรม" in md_content
    assert "อบรมคอมพิวเตอร์" in md_content
    assert "อาจารย์ประเสริฐ" in md_content

    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert json_data["total_ai_photos"] == 1
    assert json_data["top_10_people"][0]["name"] == "อาจารย์ประเสริฐ"

    print(f"✅ TC-26 PASSED: Report generated and saved to {saved_path}.")


def test_tc27_stop_flow_and_idempotent_sync():
    print("=== TC-27: Testing Stop Flow & Idempotent JSON Sync ===")
    
    # Mock minimal SchedulerTask components
    class MockDB:
        def get_all_sync_data(self): return {}
    class MockSync:
        call_count = 0
        def update_json_indexes_on_drive(self, data, fid, scan_mode):
            self.call_count += 1

    sync = MockSync()
    task = SchedulerTask.__new__(SchedulerTask)
    task.db = MockDB()
    task.sync_manager = sync
    task._stopped_json_synced = False
    task.stop_requested = False

    # Simulate _safe_sync_json_on_stop calls multiple times
    task._safe_sync_json_on_stop()
    assert sync.call_count == 1, f"Expected 1 call, got {sync.call_count}"
    assert task._stopped_json_synced is True

    # Call again, should not increment call_count
    task._safe_sync_json_on_stop()
    assert sync.call_count == 1, "Expected call_count to remain 1 (idempotent)"

    print("✅ TC-27 PASSED: Safe JSON Sync on Stop is idempotent.")


def test_tc28_gui_v624_and_popup_method():
    print("=== TC-28: Testing GUI v6.24 & show_scan_report_popup method ===")
    app_gui_path = os.path.join(get_project_root(), "app_gui.py")
    with open(app_gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert ('v6.24' in content or 'v6.25' in content), "Window title must be v6.24 or v6.25"
    assert ('FACE MATCHING\\nSYSTEM v6.24' in content or 'FACE MATCHING\\nSYSTEM v6.25' in content), "Sidebar logo must be v6.24 or v6.25"
    assert 'def show_scan_report_popup(self, report_data, saved_path):' in content, "show_scan_report_popup method missing"

    print("✅ TC-28 PASSED: GUI Version v6.24/v6.25 and Popup handler verified.")


if __name__ == "__main__":
    test_tc25_tracker_accounting()
    test_tc26_save_report_to_disk()
    test_tc27_stop_flow_and_idempotent_sync()
    test_tc28_gui_v624_and_popup_method()
    print("\n🎉 ALL SCAN REPORT SUMMARY TEST CASES (TC-25 to TC-28) PASSED SUCCESSFULLY!")
