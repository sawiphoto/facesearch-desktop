import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import os
import sys
import json
import types
import tempfile
import py_compile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Mock optional GUI/Cloud dependencies if running in base python environment
for mod_name in [
    "insightface", "insightface.app", "onnxruntime", "customtkinter",
    "gspread", "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "google", "google.oauth2", "google.oauth2.service_account"
]:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            m = types.ModuleType(mod_name)
            if mod_name == "insightface.app":
                m.FaceAnalysis = object
            elif mod_name == "customtkinter":
                m.CTk = object
                m.CTkToplevel = object
                m.CTkFrame = object
            elif mod_name == "googleapiclient.discovery":
                m.build = lambda *a, **kw: None
            elif mod_name == "googleapiclient.http":
                m.MediaFileUpload = object
                m.MediaIoBaseDownload = object
            elif mod_name == "google.oauth2.service_account":
                m.Credentials = object
            sys.modules[mod_name] = m

from db_manager import DatabaseManager
from scheduler_task import SchedulerTask
from app_gui import FaceSearchApp


def run_test_suite():
    print("=" * 72)
    print("🚀 Running Root Year Folders Management Verification Suite (v6.27)")
    print("=" * 72)

    passed = 0
    total = 4

    # -------------------------------------------------------------------------
    # TC-40: Production SQLite Table Creation, Auto-Seeding & Photo Counts
    # -------------------------------------------------------------------------
    print("\n[TC-40] Testing Production SQLite root_year_folders & Live Photo Counts...")
    prod_db = DatabaseManager()
    prod_db._sync_root_folders_to_json()
    prod_folders = prod_db.get_root_year_folders(active_only=False, include_photo_counts=True)
    assert len(prod_folders) == 6, f"Expected 6 root folders, got {len(prod_folders)}"
    years_found = [f["academic_year"] for f in prod_folders]
    assert years_found == ["2569", "2568", "2567", "2566", "2565", "2563"], f"Unexpected order/years: {years_found}"
    for f in prod_folders:
        print(f"  - Year {f['academic_year']}: {f['name']} (ID={f['id']}, Active={f['is_active']}, Photos={f['photo_count']:,})")
    assert prod_folders[0]["photo_count"] > 20000, "Expected >20,000 photos for year 2569"
    print("  ✅ TC-40 PASSED")
    passed += 1

    # -------------------------------------------------------------------------
    # TC-41: Isolated CRUD & JSON Auto-Sync Verification
    # -------------------------------------------------------------------------
    print("\n[TC-41] Testing Isolated CRUD (Add / Update / Toggle Active / Delete) & JSON Sync...")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_db_path = os.path.join(tmpdir, "test_faces.db")
        tmp_json_path = os.path.join(tmpdir, "year_folders.json")
        test_db = DatabaseManager(db_path=tmp_db_path, year_folders_json_path=tmp_json_path)

        # 1. Check initial auto-seed from default config/year_folders.json
        initial = test_db.get_root_year_folders(active_only=False)
        assert len(initial) == 6, f"Expected 6 initial seeded folders, got {len(initial)}"

        # 2. Add new folder for 2570 (auto-extract year from name)
        test_db.upsert_root_year_folder(
            folder_id="1Folder2570TestID_ABCDEFGHIJ",
            folder_name="ภาพกิจกรรม 2570",
            academic_year=""
        )
        after_add = test_db.get_root_year_folders(active_only=False)
        assert len(after_add) == 7
        assert after_add[0]["academic_year"] == "2570"
        assert after_add[0]["id"] == "1Folder2570TestID_ABCDEFGHIJ"

        # 3. Add folder with custom name (no year in name, explicit year 2571)
        test_db.upsert_root_year_folder(
            folder_id="1CustomAlbumNoYearInName_XYZ",
            folder_name="อัลบั้มรวมภาพพิเศษโรงเรียน",
            academic_year="2571"
        )
        after_custom = test_db.get_root_year_folders(active_only=False)
        assert len(after_custom) == 8
        assert after_custom[0]["academic_year"] == "2571"

        # 4. Toggle active off for 2563
        test_db.toggle_root_year_folder_active("1uE8wHS5MNxscTIif9TmRLoxd5ptK16_t", 0)
        active_list = test_db.get_root_year_folders(active_only=True)
        all_list = test_db.get_root_year_folders(active_only=False)
        assert len(active_list) == 7
        assert len(all_list) == 8

        # 5. Verify JSON file auto-sync
        assert os.path.exists(tmp_json_path), "Expected synced year_folders.json to exist"
        with open(tmp_json_path, "r", encoding="utf-8") as f:
            synced_json = json.load(f)
        assert len(synced_json) == 8
        assert synced_json[0]["name"] == "อัลบั้มรวมภาพพิเศษโรงเรียน"
        assert synced_json[0]["academic_year"] == "2571"

        # 6. Delete the 2571 and 2570 test folders
        assert test_db.delete_root_year_folder("1CustomAlbumNoYearInName_XYZ") is True
        assert test_db.delete_root_year_folder("1Folder2570TestID_ABCDEFGHIJ") is True
        final_list = test_db.get_root_year_folders(active_only=False)
        assert len(final_list) == 6
    print("  ✅ TC-41 PASSED")
    passed += 1

    # -------------------------------------------------------------------------
    # TC-42: URL Extraction & Scheduler Integration
    # -------------------------------------------------------------------------
    print("\n[TC-42] Testing Drive Folder URL Extraction & SchedulerTask Integration...")
    url_cases = [
        ("https://drive.google.com/drive/folders/1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ?usp=sharing", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
        ("https://drive.google.com/drive/u/0/folders/1YYkDLsalb0jVM0K876lcejLoiggoJ18N", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
        ("https://drive.google.com/open?id=1ocR4srmu1tA1nYgJOhoM9I0KDVMmbRGF", "1ocR4srmu1tA1nYgJOhoM9I0KDVMmbRGF"),
        ("1ZMhLENv8u-onIhVzwBTxCzjJVQVCriVd", "1ZMhLENv8u-onIhVzwBTxCzjJVQVCriVd"),
    ]
    for raw_url, expected_id in url_cases:
        extracted = FaceSearchApp.extract_drive_folder_id(raw_url)
        assert extracted == expected_id, f"URL extract failed for {raw_url}: got {extracted}"

    sched = SchedulerTask(prod_db, None, None, None)
    loaded_active = sched._load_year_folders(active_only=True)
    year_lookup = sched._get_root_folder_year_lookup()
    assert len(loaded_active) == 6
    assert year_lookup.get("1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ") == "2569"
    assert year_lookup.get("1uE8wHS5MNxscTIif9TmRLoxd5ptK16_t") == "2563"
    print(f"  - Scheduler loaded {len(loaded_active)} active folders; year_lookup mapped {len(year_lookup)} IDs.")
    print("  ✅ TC-42 PASSED")
    passed += 1

    # -------------------------------------------------------------------------
    # TC-43: GUI Version & Module Compilation Check
    # -------------------------------------------------------------------------
    print("\n[TC-43] Verifying GUI Version v6.27 & Compiling All Modified Modules...")
    for mod in ["db_manager.py", "scheduler_task.py", "gdrive_sync.py", "app_gui.py"]:
        py_compile.compile(mod, doraise=True)
    with open("app_gui.py", "r", encoding="utf-8") as f:
        gui_src = f.read()
    assert "v6.27" in gui_src, "v6.27 not found in app_gui.py"
    assert "SYSTEM v6.27" in gui_src, "SYSTEM v6.27 not found in sidebar logo"
    assert "v6.26" not in gui_src, "Found leftover v6.26 in app_gui.py"
    print("  ✅ TC-43 PASSED")
    passed += 1

    print("\n" + "=" * 72)
    print(f"🎉 SUMMARY: {passed}/{total} Test Cases Passed (100%)")
    print("=" * 72)


if __name__ == "__main__":
    run_test_suite()
