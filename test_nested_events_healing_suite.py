import sqlite3
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager, is_generic_folder_name, GENERIC_SUBFOLDER_KEYWORDS

def run_test_suite():
    print("=" * 80)
    print("🧪 RUNNING COMPREHENSIVE TEST SUITE: TC-71 TO TC-75 (v6.32)")
    print("   Nested Event Healing & Anti-Generic Guard Verification")
    print("=" * 80)

    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "faces_db.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    test_results = []

    # -------------------------------------------------------------
    # TC-71: Verify 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม' Photos Count
    # -------------------------------------------------------------
    print("\n[TC-71] Verifying 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม' Event Photos...")
    c.execute("SELECT count(*) FROM scanned_photos WHERE event_name = 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม'")
    cnt_tc71 = c.fetchone()[0]
    # Expected: 369 (นักเรียน) + 266 (ครู) = 635 photos
    if cnt_tc71 == 635:
        print(f"  ✅ PASS: Found exactly {cnt_tc71} photos for 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม'")
        test_results.append(("TC-71", "สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม Count (635)", "PASS"))
    else:
        print(f"  ❌ FAIL: Expected 635 photos, got {cnt_tc71}")
        test_results.append(("TC-71", "สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม Count (635)", f"FAIL ({cnt_tc71})"))

    # -------------------------------------------------------------
    # TC-72: Confirm Zero Generic Event Names in DB
    # -------------------------------------------------------------
    print("\n[TC-72] Verifying Zero Generic Isolated Event Names in Database...")
    generic_list = [
        'นักเรียน', 'ครู', 'ภาพอำเภอ', 'TargetFolder', 'คำสั่ง', 'doc', 
        'ภาพ', 'ผลงานครู', 'รวม', 'อาสุ', 'ไวนิล', 'ครูธนา', 'Thana', 
        "Jim's", 'ครูอ้อย', 'น้านัน', 'VDO'
    ]
    pl = ','.join('?' for _ in generic_list)
    c.execute(f"SELECT count(*) FROM scanned_photos WHERE event_name IN ({pl})", generic_list)
    cnt_generic = c.fetchone()[0]
    if cnt_generic == 0:
        print(f"  ✅ PASS: Found 0 generic event names remaining in DB.")
        test_results.append(("TC-72", "Zero Generic Event Names in DB", "PASS"))
    else:
        print(f"  ❌ FAIL: Found {cnt_generic} generic event names remaining!")
        test_results.append(("TC-72", "Zero Generic Event Names in DB", f"FAIL ({cnt_generic})"))

    # -------------------------------------------------------------
    # TC-73: Total Photo Count and Zero Data Loss
    # -------------------------------------------------------------
    print("\n[TC-73] Verifying Total Photo Count & Zero Data Loss...")
    c.execute("SELECT count(*) FROM scanned_photos")
    total_db = c.fetchone()[0]
    if total_db == 124813:
        print(f"  ✅ PASS: Total photo count is exactly {total_db} (Zero Data Loss Guaranteed)")
        test_results.append(("TC-73", "Total Photo Count Parity (124,813)", "PASS"))
    else:
        print(f"  ❌ FAIL: Expected 124,813 photos, got {total_db}")
        test_results.append(("TC-73", "Total Photo Count Parity (124,813)", f"FAIL ({total_db})"))

    # -------------------------------------------------------------
    # TC-74: Anti-Generic Guard Unit Verification
    # -------------------------------------------------------------
    print("\n[TC-74] Verifying Anti-Generic Guard Functionality...")
    generic_samples = ['นักเรียน', 'ครู', 'TargetFolder', 'doc', 'VDO', 'Thana', "Jim's", '  ครูธนา  ']
    non_generic_samples = ['สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม', 'กีฬาสี 65', 'ภาพกิจกรรม 2569']
    
    all_guards_ok = True
    for g in generic_samples:
        if not is_generic_folder_name(g):
            print(f"  ❌ Failed to flag generic: {g}")
            all_guards_ok = False
    for ng in non_generic_samples:
        if is_generic_folder_name(ng):
            print(f"  ❌ Incorrectly flagged valid event: {ng}")
            all_guards_ok = False

    if all_guards_ok:
        print("  ✅ PASS: Anti-Generic Guard flags all generic names and preserves valid events.")
        test_results.append(("TC-74", "Anti-Generic Guard Unit Verification", "PASS"))
    else:
        test_results.append(("TC-74", "Anti-Generic Guard Unit Verification", "FAIL"))

    # -------------------------------------------------------------
    # TC-75: Manifest Sharding Verification
    # -------------------------------------------------------------
    print("\n[TC-75] Verifying Manifest Shards and Archive Count...")
    db_mgr = DatabaseManager()
    sync_data = db_mgr.get_sync_data_sharded()
    manifest = sync_data['manifest']
    counts = manifest.get('year_counts', {})
    print(f"  Manifest Year Counts: {counts}")
    
    if counts.get('archive') == 0 and counts.get('2569') == 23819 and counts.get('2565') == 17273 and manifest.get('version') == 'v6.32':
        print(f"  ✅ PASS: Version is {manifest.get('version')}, archive count is 0, 2569 has 23,819, 2565 has 17,273 photos.")
        test_results.append(("TC-75", "Manifest Shards Distribution & v6.32 & Archive=0", "PASS"))
    else:
        print(f"  ❌ FAIL: Unexpected manifest or counts: version={manifest.get('version')}, counts={counts}")
        test_results.append(("TC-75", "Manifest Shards Distribution & v6.32 & Archive=0", "FAIL"))

    conn.close()

    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY REPORT")
    print("=" * 80)
    passed_cnt = sum(1 for _, _, st in test_results if st == "PASS")
    for tid, desc, st in test_results:
        icon = "✅" if st == "PASS" else "❌"
        print(f" {icon} {tid:<8} | {desc:<50} | {st}")
    print("-" * 80)
    print(f" Total Tests: {len(test_results)} | Passed: {passed_cnt} | Failed: {len(test_results) - passed_cnt}")
    print("=" * 80)

    assert passed_cnt == len(test_results), "Some test cases failed!"

if __name__ == "__main__":
    run_test_suite()
