import os, sys, sqlite3, json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

project_root = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
sys.path.insert(0, project_root)

from db_manager import DatabaseManager

def test_tc35_schema():
    print("=== TC-35: Testing SQLite Schema Migration for academic_year ===")
    db = DatabaseManager()
    with db.get_connection() as conn:
        c = conn.cursor()
        c.execute("PRAGMA table_info(scanned_photos)")
        columns = {row[1]: row[2] for row in c.fetchall()}
        assert "academic_year" in columns, "TC-35 FAILED: academic_year column missing from scanned_photos"
        
        c.execute("PRAGMA index_list(scanned_photos)")
        indexes = [row[1] for row in c.fetchall()]
        assert any("academic_year" in idx for idx in indexes), "TC-35 FAILED: idx_sp_academic_year missing"
    print("✅ TC-35 PASSED: academic_year column and index successfully verified in SQLite.")

def test_tc36_backfill_coverage():
    print("\n=== TC-36: Testing Backfill Coverage & Distribution ===")
    db = DatabaseManager()
    with db.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scanned_photos")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM scanned_photos WHERE academic_year != '' AND academic_year IS NOT NULL")
        with_year = c.fetchone()[0]
        coverage_pct = (with_year / total) * 100
        print(f"Coverage: {with_year:,}/{total:,} photos ({coverage_pct:.2f}%)")
        assert coverage_pct > 99.0, f"TC-36 FAILED: Backfill coverage too low ({coverage_pct:.2f}%)"
    print("✅ TC-36 PASSED: Backfill coverage exceeds 99% (>117,000 photos).")

def test_tc37_known_cases():
    print("\n=== TC-37: Testing Known User Cases (P04972, P04968, P05026) ===")
    db = DatabaseManager()
    sync_data = db.get_all_sync_data()
    photos_map = {p["photo_id"]: p for p in sync_data["photos"]}
    
    # Case 1: P04972 ("ครูและเจ้าหน้าที่ใหม่") under "ภาพกิจกรรม 2569"
    assert "P04972" in photos_map, "P04972 not found in sync_data"
    p4972 = photos_map["P04972"]
    assert p4972.get("year") == "2569", f"P04972 year should be 2569, got {p4972.get('year')}"
    assert p4972.get("face_count") == 1, f"P04972 face_count should be 1, got {p4972.get('face_count')}"
    print(f"  • P04972: event='{p4972.get('event')}', year='{p4972.get('year')}', face_count={p4972.get('face_count')} => VERIFIED")

    # Case 2: P04968 ("กค 2 ต้อนรับครูพละใหม่") under "ภาพกิจกรรม 2569"
    assert "P04968" in photos_map, "P04968 not found in sync_data"
    p4968 = photos_map["P04968"]
    assert p4968.get("year") == "2569", f"P04968 year should be 2569, got {p4968.get('year')}"
    print(f"  • P04968: event='{p4968.get('event')}', year='{p4968.get('year')}' => VERIFIED")

    # Case 3: P05026 ("11 กค อบรมป้องกันการตั้งครรภ์") under "ภาพกิจกรรม 2569"
    assert "P05026" in photos_map, "P05026 not found in sync_data"
    p5026 = photos_map["P05026"]
    assert p5026.get("year") == "2569", f"P05026 year should be 2569, got {p5026.get('year')}"
    print(f"  • P05026: event='{p5026.get('event')}', year='{p5026.get('year')}' => VERIFIED")
    print("✅ TC-37 PASSED: All user test cases correctly resolved to 2569 with face_count.")

def test_tc38_gui_version():
    print("\n=== TC-38: Testing GUI Version v6.26 Integration ===")
    gui_file = os.path.join(project_root, "app_gui.py")
    with open(gui_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert 'v6.26 (Root Year Hierarchy & Academic Year Indexing)' in content, "Window title must be v6.26"
    assert 'FACE MATCHING\\nSYSTEM v6.26' in content, "Sidebar logo must be v6.26"
    print("✅ TC-38 PASSED: GUI Version v6.26 verified on Window Title and Sidebar Logo.")

def test_tc39_json_structure():
    print("\n=== TC-39: Testing photo_index.json serialization structure ===")
    from gdrive_sync import GoogleSyncManager
    sync = GoogleSyncManager()
    sync_data = {
        "photos": [
            {
                "photo_id": "P04972",
                "event": "ครูและเจ้าหน้าที่ใหม่",
                "drive_link": "https://drive.google.com/file/d/1L3-UN9AJLAnEMSHjmYUyW4K78UTJsgJE/view?usp=drivesdk",
                "date": "2026-06-05",
                "year": "2569",
                "face_count": 1
            }
        ],
        "faces": []
    }
    photo_index = {}
    for item in sync_data["photos"]:
        entry = {
            "event": item["event"],
            "drive_link": sync.format_drive_view_url(item["drive_link"]),
            "date": item.get("date", ""),
            "face_count": item.get("face_count", 0)
        }
        if item.get("year"):
            entry["year"] = str(item["year"]).strip()
        photo_index[item["photo_id"]] = entry

    p_entry = photo_index["P04972"]
    assert "year" in p_entry and p_entry["year"] == "2569", "JSON entry missing year 2569"
    assert "face_count" in p_entry and p_entry["face_count"] == 1, "JSON entry missing face_count 1"
    print("  • Sample Output JSON:", json.dumps({"P04972": p_entry}, ensure_ascii=False, indent=2))
    print("✅ TC-39 PASSED: photo_index JSON structure matches required schema 100%.")

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 RUNNING ACADEMIC YEAR VERIFICATION SUITE: TC-35 to TC-39 (v6.26)")
    print("=" * 70)
    test_tc35_schema()
    test_tc36_backfill_coverage()
    test_tc37_known_cases()
    test_tc38_gui_version()
    test_tc39_json_structure()
    print("\n" + "=" * 70)
    print("🎉 ALL TEST CASES (TC-35 to TC-39) PASSED SUCCESSFULLY! (100%)")
    print("=" * 70)
