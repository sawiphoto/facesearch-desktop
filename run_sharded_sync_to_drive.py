import os
import sys
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

from gdrive_sync import GoogleSyncManager

def run_sync():
    print("==================================================")
    print("🚀 STARTING SHARDED JSON INDEXES SYNC TO GOOGLE DRIVE (v6.30)")
    print("==================================================")
    
    with open("data/app_settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
        
    json_folder_id = settings.get("json_folder_id")
    print(f"Target Google Drive Folder ID: {json_folder_id}")
    
    sync = GoogleSyncManager()
    if not sync.connect(ensure_worksheets=False):
        print("❌ Failed to connect to Google Drive Service Account.")
        sys.exit(1)
        
    print("Connected to Google Drive successfully. Uploading all sharded and dual-write index files...")
    t0 = time.time()
    success = sync.update_json_indexes_on_drive(None, json_folder_id, scan_mode="all")
    elapsed = time.time() - t0
    
    if success:
        print(f"\n🎉 Sync completed successfully in {elapsed:.2f} seconds!")
        
        # Verify files in folder
        print("\n📂 Inspecting files in Google Drive folder 'รวมไฟล์ JSON INDEX':")
        query = f"'{json_folder_id}' in parents and trashed = false"
        res = sync.drive_service.files().list(
            q=query,
            fields='files(id, name, size, modifiedTime)'
        ).execute().get('files', [])
        
        total_size = 0
        for f in sorted(res, key=lambda x: x['name']):
            size = int(f.get('size', 0))
            total_size += size
            size_mb = size / (1024 * 1024)
            print(f"  - {f['name']:<28} | Size: {size_mb:>6.2f} MB ({size:>10,} B) | ID: {f['id']}")
            
        print(f"\nTotal Files: {len(res)} | Total Size on Drive: {total_size / (1024*1024):.2f} MB")
    else:
        print("\n❌ Sync failed!")
        sys.exit(1)

if __name__ == "__main__":
    run_sync()
