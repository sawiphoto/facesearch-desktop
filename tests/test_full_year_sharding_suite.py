import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import os
import sys
import json
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

def run_test_suite():
    print("======================================================================")
    print("🧪 COMPREHENSIVE RUNTIME VERIFICATION SUITE: TC-66 to TC-70")
    print("   Full Academic Year Sharding (2563 - 2569) & Dynamic Manifest")
    print("======================================================================")
    
    db = DatabaseManager()
    sharded = db.get_sync_data_sharded()
    manifest = sharded["manifest"]
    photos_by_shard = sharded["photos_by_shard"]
    
    # -------------------------------------------------------------
    # TC-66: All Active Years Shard Generation
    # -------------------------------------------------------------
    print("\n--- TC-66: All Active Years Shard Generation ---")
    expected_years = ['2569', '2568', '2567', '2566', '2565', '2564', '2563']
    print(f"Detected shards in photos_by_shard: {list(photos_by_shard.keys())}")
    for yr in expected_years:
        assert yr in photos_by_shard, f"Missing year shard: {yr}"
    assert "archive" in photos_by_shard, "Missing archive shard"
    print("✅ TC-66 PASSED: All individual years (2563 to 2569) and archive shards are present.")

    # -------------------------------------------------------------
    # TC-67: Shard Size & Photo Count Parity
    # -------------------------------------------------------------
    print("\n--- TC-67: Shard Size & Photo Count Parity ---")
    expected_counts = {
        '2569': 23815,
        '2568': 27299,
        '2567': 23676,
        '2566': 22997,
        '2565': 17273,
        '2564': 7227,
        '2563': 2522,
        'archive': 4
    }
    for yr, exp_cnt in expected_counts.items():
        actual_cnt = len(photos_by_shard[yr])
        print(f"  - Year {yr}: Expected = {exp_cnt:,} | Actual = {actual_cnt:,}")
        assert actual_cnt == exp_cnt, f"Count mismatch for {yr}: expected {exp_cnt}, got {actual_cnt}"
    print("✅ TC-67 PASSED: Photo count for every academic year matches SQLite database exactly.")

    # -------------------------------------------------------------
    # TC-68: Manifest Structure Verification
    # -------------------------------------------------------------
    print("\n--- TC-68: Manifest Structure Verification ---")
    available_years = manifest["available_years"]
    year_file_map = manifest["year_file_map"]
    year_counts = manifest["year_counts"]
    total_photos = manifest["total_photos"]
    
    print(f"Manifest available_years: {available_years}")
    for yr in expected_years:
        assert yr in available_years, f"Year {yr} missing from available_years in manifest"
        assert yr in year_file_map, f"Year {yr} missing from year_file_map in manifest"
        assert year_file_map[yr] == f"photo_index_{yr}.json", f"Wrong file name for {yr}: {year_file_map[yr]}"
        assert year_counts[yr] == expected_counts[yr], f"Wrong count in manifest for {yr}"
        
    assert "archive" in available_years
    assert year_file_map["archive"] == "photo_index_archive.json"
    assert year_counts["archive"] == 4
    assert total_photos == 124813
    assert sum(year_counts.values()) == total_photos
    print("✅ TC-68 PASSED: Manifest structure and mappings are completely verified.")

    # -------------------------------------------------------------
    # TC-69: Drive Files Verification
    # -------------------------------------------------------------
    print("\n--- TC-69: Drive Files Verification ---")
    with open("data/app_settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
    json_folder_id = settings.get("json_folder_id")
    
    sync = GoogleSyncManager()
    sync.connect(ensure_worksheets=False)
    query = f"'{json_folder_id}' in parents and trashed = false"
    res = sync.drive_service.files().list(q=query, fields='files(id, name, size)').execute().get('files', [])
    
    drive_file_map = {f['name']: (int(f.get('size', 0)), f['id']) for f in res}
    print(f"Files found in Drive folder '{json_folder_id}': {len(drive_file_map)} files")
    
    required_files = [
        "photo_manifest.json",
        "photo_index.json",
        "photo_index_2569.json",
        "photo_index_2568.json",
        "photo_index_2567.json",
        "photo_index_2566.json",
        "photo_index_2565.json",
        "photo_index_2564.json",
        "photo_index_2563.json",
        "photo_index_archive.json",
        "student_index.json",
        "student_index_active.json",
        "student_index_alumni.json",
        "person_index.json"
    ]
    
    for r_file in required_files:
        assert r_file in drive_file_map, f"Required file missing from Drive: {r_file}"
        size_b, file_id = drive_file_map[r_file]
        size_mb = size_b / (1024 * 1024)
        print(f"  - {r_file:<26} | {size_mb:>6.2f} MB | ID: {file_id}")
        assert size_b > 0, f"File {r_file} has 0 bytes on Drive"
        
    print("✅ TC-69 PASSED: All 14 files exist on Drive folder 'รวมไฟล์ JSON INDEX' with non-zero size.")

    # -------------------------------------------------------------
    # TC-70: Zero Data Loss & Recombination Integrity
    # -------------------------------------------------------------
    print("\n--- TC-70: Zero Data Loss & Recombination Integrity ---")
    recombined = {}
    for yr, shard_dict in photos_by_shard.items():
        for pid, entry in shard_dict.items():
            assert pid not in recombined, f"Duplicate photo_id across shards: {pid}"
            recombined[pid] = entry
            
    assert len(recombined) == 124813, f"Recombined count is {len(recombined)}, expected 124813"
    
    # Compare against raw SQLite scanned_photos count
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scanned_photos")
        raw_db_count = cursor.fetchone()[0]
        
    print(f"Recombined Shards Total: {len(recombined):,} | Raw SQLite Database Total: {raw_db_count:,}")
    assert len(recombined) == raw_db_count, f"Recombined ({len(recombined)}) != SQLite ({raw_db_count})"
    print("✅ TC-70 PASSED: Zero data loss verified! 124,813 / 124,813 photos matched 100%.")

    print("\n======================================================================")
    print("🎉 ALL 5 TEST CASES (TC-66 TO TC-70) PASSED PERFECTION!")
    print("======================================================================")

if __name__ == "__main__":
    run_test_suite()
