import os, sys, time, json
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
project_root = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
sys.path.insert(0, project_root)

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager
from scheduler_task import SchedulerTask

def main():
    print("=" * 70)
    print("🚀 STARTING ACADEMIC YEAR ONE-TIME BACKFILL (v6.26)")
    print("=" * 70)

    # 1. Initialize DB and apply schema migration
    db = DatabaseManager()
    print("✅ Step 1: Database schema verified and migration applied.")

    # 2. Connect to Google Drive and fetch folder-to-year mapping
    print("\n⏳ Step 2: Fetching Google Drive folder-to-year mapping...")
    sync = GoogleSyncManager()
    sync.connect()
    
    sched = SchedulerTask(db, sync, None, None)
    t0 = time.time()
    event_to_years = sched.fetch_drive_folder_year_mapping()
    t_fetch = time.time() - t0
    print(f"✅ Step 2 Complete: Mapped {len(event_to_years)} distinct folder names to academic years in {t_fetch:.2f}s.")

    # 3. Execute 3-Tier Backfill in SQLite
    print("\n⏳ Step 3: Executing 3-tier cascade backfill on scanned_photos in SQLite...")
    t1 = time.time()
    result = db.backfill_academic_year(event_to_years)
    t_backfill = time.time() - t1
    print(f"✅ Step 3 Complete: Processed {result['total_photos']:,} photos in {t_backfill:.2f}s.")

    # 4. Display Distribution Summary
    print("\n" + "=" * 70)
    print("📊 ACADEMIC YEAR DISTRIBUTION SUMMARY")
    print("=" * 70)
    total = result['total_photos']
    print("\n[RESOLUTION SOURCES]")
    for src, cnt in result['source_counts'].items():
        pct = (cnt / total) * 100 if total > 0 else 0
        print(f"  • {src}: {cnt:,} photos ({pct:.2f}%)")

    print("\n[BREAKDOWN BY ACADEMIC YEAR (พ.ศ.)]")
    for yr in sorted(result['year_counts'].keys(), reverse=True):
        cnt = result['year_counts'][yr]
        pct = (cnt / total) * 100 if total > 0 else 0
        print(f"  • ปีการศึกษา {yr}: {cnt:,} รูป ({pct:.2f}%)")

    # 5. Verify Known Problem Cases
    print("\n" + "=" * 70)
    print("🔍 VERIFYING KNOWN TEST CASES")
    print("=" * 70)
    with db.get_connection() as conn:
        c = conn.cursor()
        test_ids = ['P04968', 'P04969', 'P04972', 'P04973', 'P05026']
        placeholders = ','.join('?' for _ in test_ids)
        c.execute(f"SELECT photo_id, event_name, photo_date, academic_year FROM scanned_photos WHERE photo_id IN ({placeholders})", test_ids)
        rows = c.fetchall()
        for r in rows:
            print(f"  📸 Photo {r[0]}: Event='{r[1]}', Date='{r[2]}' => Academic Year='{r[3]}'")

    # 6. Verify get_all_sync_data integration
    print("\n⏳ Step 4: Testing get_all_sync_data() output for photo_index.json...")
    sync_data = db.get_all_sync_data()
    sample_photos = {p['photo_id']: p for p in sync_data['photos'] if p['photo_id'] in test_ids}
    for pid, p in sample_photos.items():
        print(f"  ✨ sync_data['photos'] -> Photo {pid}: year='{p.get('year')}', event='{p.get('event')}', face_count={p.get('face_count')}")

    print("\n" + "=" * 70)
    print("🎉 BACKFILL COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == '__main__':
    main()
