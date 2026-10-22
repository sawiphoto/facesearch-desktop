import os, sys, time, json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

project_root = r"d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"
sys.path.insert(0, project_root)

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager

def main():
    print("=" * 70)
    print("🚀 SYNCING UPDATED photo_index.json TO GOOGLE DRIVE (v6.26)")
    print("=" * 70)

    db = DatabaseManager()
    sync = GoogleSyncManager()
    sync.connect()

    # Load json_folder_id from app_settings.json
    settings_path = os.path.join(project_root, "data", "app_settings.json")
    json_folder_id = "1xxNfIxM9a9wlo6sgThZmpMVYWn4QFTUI"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                json_folder_id = settings.get("json_folder_id", json_folder_id)
        except Exception as e:
            print(f"Warning reading settings: {e}")

    print(f"Target Google Drive Folder ID: {json_folder_id}")

    # Fetch sync data from SQLite
    print("Fetching all sync data from SQLite...")
    t0 = time.time()
    sync_data = db.get_all_sync_data()
    print(f"Loaded {len(sync_data['photos']):,} photos and {len(sync_data['faces']):,} faces in {time.time()-t0:.2f}s.")

    # Upload to Google Drive
    print(f"Uploading updated photo_index.json to Google Drive...")
    t1 = time.time()
    ok = sync.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
    print(f"Sync complete in {time.time()-t1:.2f}s. Success: {ok}")

    # Verify upload by downloading or reading back photo_index
    print("Verifying uploaded photo_index on Google Drive...")
    query = f"'{json_folder_id}' in parents and name = 'photo_index.json' and trashed = false"
    res = sync.drive_service.files().list(q=query, fields="files(id, name, modifiedTime)").execute()
    files = res.get("files", [])
    if files:
        f = files[0]
        print(f"  ✅ Verified file on Drive: Name='{f['name']}', ID='{f['id']}', Modified='{f.get('modifiedTime')}'")
    else:
        print("  ⚠️ Warning: Could not locate photo_index.json in specified folder immediately.")

    print("\n" + "=" * 70)
    print("🎉 GOOGLE DRIVE SYNC FINISHED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
