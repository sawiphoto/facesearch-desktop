import os
import sys
import json
import sqlite3

sys.stdout.reconfigure(encoding='utf-8')

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

def run_test_suite():
    print("======================================================================")
    print("🧪 COMPREHENSIVE RUNTIME VERIFICATION SUITE: v6.30 (TC-60 to TC-65)")
    print("======================================================================")
    
    db = DatabaseManager()
    sharded = db.get_sync_data_sharded()
    
    # -------------------------------------------------------------
    # TC-60: Student Index Sharding Generation
    # -------------------------------------------------------------
    print("\n--- TC-60: Student Index Sharding Generation ---")
    active_students = sharded["active_students"]
    alumni_students = sharded["alumni_students"]
    print(f"Active students count: {len(active_students)}")
    print(f"Alumni students count: {len(alumni_students)}")
    
    assert len(active_students) > 0, "Active students should not be empty"
    # Ensure no student exists in both active and alumni
    overlap = set(active_students.keys()).intersection(set(alumni_students.keys()))
    assert len(overlap) == 0, f"Overlap between active and alumni: {overlap}"
    
    # Verify structure: each student must have 'photos' and 'years'
    sample_name = list(active_students.keys())[0]
    sample_entry = active_students[sample_name]
    assert "photos" in sample_entry and isinstance(sample_entry["photos"], list)
    assert "years" in sample_entry and isinstance(sample_entry["years"], list)
    print(f"Sample Student: '{sample_name}' | Photos: {len(sample_entry['photos'])} | Years: {sample_entry['years']}")
    print("✅ TC-60 PASSED: Student index sharding generated correctly without overlap.")

    # -------------------------------------------------------------
    # TC-61: Photo Index Yearly Sharding & Manifest
    # -------------------------------------------------------------
    print("\n--- TC-61: Photo Index Yearly Sharding & Manifest ---")
    manifest = sharded["manifest"]
    photos_by_shard = sharded["photos_by_shard"]
    
    print(f"Manifest Version: {manifest['version']}")
    print(f"Available Shards: {manifest['available_years']}")
    print("Year counts in manifest:", manifest["year_counts"])
    
    assert manifest["version"] in ["v6.30", "v6.31"]
    for yr in ["2569", "2568", "2567", "2566", "archive"]:
        assert yr in manifest["available_years"], f"Missing year {yr} in manifest"
        assert yr in photos_by_shard, f"Missing shard {yr} in photos_by_shard"
        assert len(photos_by_shard[yr]) > 0, f"Shard {yr} is empty"
    print("✅ TC-61 PASSED: Photo index yearly shards and manifest verified.")

    # -------------------------------------------------------------
    # TC-62: Dual-Write Backward Compatibility on Google Drive
    # -------------------------------------------------------------
    print("\n--- TC-62: Dual-Write Backward Compatibility on Drive ---")
    with open("data/app_settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
    json_folder_id = settings.get("json_folder_id")
    
    sync = GoogleSyncManager()
    sync.connect(ensure_worksheets=False)
    query = f"'{json_folder_id}' in parents and trashed = false"
    drive_files = sync.drive_service.files().list(q=query, fields='files(id, name, size)').execute().get('files', [])
    drive_file_names = {f['name']: f for f in drive_files}
    
    required_files = [
        "person_index.json",
        "photo_index.json",
        "student_index.json",
        "photo_manifest.json",
        "student_index_active.json",
        "student_index_alumni.json",
        "photo_index_2569.json",
        "photo_index_2568.json",
        "photo_index_2567.json",
        "photo_index_2566.json",
        "photo_index_archive.json"
    ]
    for rf in required_files:
        assert rf in drive_file_names, f"File {rf} missing from Google Drive folder!"
        f_size = int(drive_file_names[rf].get('size', 0))
        print(f"  ✓ Found on Drive: {rf:<26} (Size: {f_size:>10,} B)")
    print("✅ TC-62 PASSED: Both Sharded files and Legacy Dual-Write files exist on Google Drive.")

    # -------------------------------------------------------------
    # TC-63: Compact JSON Minification Rate
    # -------------------------------------------------------------
    print("\n--- TC-63: Compact JSON Minification Rate ---")
    legacy_photo_file = drive_file_names["photo_index.json"]
    legacy_size = int(legacy_photo_file.get("size", 0))
    # Original uncompressed indent=2 size was 33,288,326 bytes
    original_size = 33288326
    reduction_pct = (1.0 - (legacy_size / original_size)) * 100.0
    print(f"Original size (indent=2): {original_size:,} bytes")
    print(f"Compact size:             {legacy_size:,} bytes")
    print(f"Reduction rate:           {reduction_pct:.2f}%")
    assert reduction_pct >= 13.0, f"Reduction rate {reduction_pct:.2f}% lower than expected!"
    print("✅ TC-63 PASSED: Compact JSON minification rate verified.")

    # -------------------------------------------------------------
    # TC-64: Apps Script Intelligent Lazy Load Simulation
    # -------------------------------------------------------------
    print("\n--- TC-64: Apps Script Intelligent Lazy Load Simulation ---")
    # Simulate a student who only has photos in year 2568
    # Search student in active_students
    student_with_single_year = None
    for s_name, s_info in active_students.items():
        if len(s_info["years"]) == 1:
            student_with_single_year = (s_name, s_info)
            break
            
    if not student_with_single_year:
        sample_name = list(active_students.keys())[0]
        student_with_single_year = (sample_name, active_students[sample_name])
        
    s_name, s_info = student_with_single_year
    target_years = s_info["years"]
    year_map = manifest["year_file_map"]
    
    # Calculate bytes to load with Lazy Loading vs Full Monolithic
    lazy_load_bytes = sum(int(drive_file_names[year_map[yr]].get('size', 0)) for yr in target_years if yr in year_map)
    monolithic_bytes = legacy_size
    bandwidth_saved_pct = (1.0 - (lazy_load_bytes / monolithic_bytes)) * 100.0
    
    print(f"Simulating student: '{s_name}'")
    print(f"Student active years: {target_years}")
    print(f"Shards loaded: {[year_map[yr] for yr in target_years]}")
    print(f"Lazy loaded payload:  {lazy_load_bytes:,} bytes ({lazy_load_bytes/(1024*1024):.2f} MB)")
    print(f"Monolithic payload:   {monolithic_bytes:,} bytes ({monolithic_bytes/(1024*1024):.2f} MB)")
    print(f"Bandwidth saved:      {bandwidth_saved_pct:.2f}%")
    assert lazy_load_bytes < monolithic_bytes, "Lazy loading must use less bandwidth than monolithic index"
    print("✅ TC-64 PASSED: Intelligent Lazy Load simulation reduces client payload significantly.")

    # -------------------------------------------------------------
    # TC-65: Zero Data Loss Integrity Check
    # -------------------------------------------------------------
    print("\n--- TC-65: Zero Data Loss Integrity Check ---")
    total_db_photos = len(sharded["photos"])
    total_shard_photos = sum(len(shard) for shard in photos_by_shard.values())
    
    print(f"Total photos in DB:     {total_db_photos:,}")
    print(f"Total photos in Shards: {total_shard_photos:,}")
    assert total_db_photos == total_shard_photos, f"Photo count mismatch: {total_db_photos} vs {total_shard_photos}"
    
    # Verify all photo IDs in DB are present across shards
    all_shard_pids = set()
    for shard in photos_by_shard.values():
        all_shard_pids.update(shard.keys())
    db_pids = {p["photo_id"] for p in sharded["photos"]}
    
    missing_pids = db_pids - all_shard_pids
    assert len(missing_pids) == 0, f"Missing photo IDs in shards: {len(missing_pids)}"
    print(f"100% of {len(db_pids):,} photo IDs verified across shards without any loss.")
    print("✅ TC-65 PASSED: Zero data loss confirmed 100%.")

    print("\n======================================================================")
    print("🎉 ALL TEST CASES (TC-60 TO TC-65) PASSED 100%!")
    print("======================================================================")

if __name__ == "__main__":
    run_test_suite()
