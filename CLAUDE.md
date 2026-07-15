# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow (สำคัญ - อ่านทุกครั้ง)

เมื่อได้รับคำสั่งจากผู้ใช้ ให้ทำตามลำดับนี้ **ทุกครั้ง**:

1. **ตอบคำถาม** ให้ชัดเจน ถ้ามีส่วนที่ไม่เข้าใจให้ถามก่อน
2. **เขียนแผนงาน** แยกเป็นขั้นตอน ระบุไฟล์ที่ต้องแก้ และสิ่งที่จะเปลี่ยน
3. **ห้ามลงมือทำ** จนกว่าผู้ใช้จะอนุมัติแผน (รอคำว่า "ทำได้" / "เริ่มได้" / "OK")

## Project Overview

This is a **School Personnel Face Search System** - a desktop GUI application for school administrators to:
1. Register staff members with face template images
2. Scan event photos from Google Drive folders
3. Match faces against registered staff using InsightFace (antelopev2) model
4. Store results in local SQLite database
5. Sync search indexes to Google Sheets and JSON files on Google Drive

## Running the Application

```bash
# Create and activate virtual environment (first time only)
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

**⚠️ CRITICAL: ต้องใช้ venv เสมอ**
- **การลง lib:** ต้อง activate venv ก่อน ทุกครั้ง
- **การรันโปรแกรม:** ต้องรันผ่าน venv เสมอ
- เหตุผล: เคยเจอปัญหา Agent กับ User อยู่คนละ environment → ทดสอบแล้วไม่เหมือนกัน → โค้ดรันไม่ได้/ผิดพลาด

**First run**: The system automatically downloads the `antelopev2.zip` model (~360MB) from GitHub and extracts it to `models/antelopev2/`.

## Architecture

### Entry Point
- `main.py` - Sets up required directories and launches the GUI application

### Core Modules

**`app_gui.py`** (GUI - CustomTkinter)
- Main desktop interface with 5 primary sections:
  1. Dashboard - Statistics and system status
  2. Staff Registry - Register/delete staff and upload face templates
  3. Scan Console - Configure and run face scans on Google Drive folders
  4. Delete Requests - Process deletion requests from JSON file
  5. Matching Console - Re-match photos against selected staff members
- Contains `GoogleDrivePicker` class for folder/file selection from Drive
- Settings are persisted to `data/app_settings.json`

**`db_manager.py`** (Database - SQLite)
- Local database at `data/faces_db.db`
- Tables:
  - `staff_members` - Staff names
  - `staff_embeddings` - 512-dim face vectors (BLOB)
  - `scanned_photos` - Photo scan history with event names and Drive links
  - `detected_faces` - Match results linking photos to staff
  - `scanned_photo_faces` - Cached face embeddings from event photos

**`face_analyzer.py`** (Face Recognition - InsightFace)
- Uses `antelopev2` model (scrfd_10g_bnkps.onnx + glintr100.onnx)
- Returns 512-dimensional embeddings for each detected face
- Supports GPU acceleration via CUDA (onnxruntime-gpu)
- Handles Thai file paths with `cv2.imdecode(np.fromfile(...))`
- Matrix-based batch matching using cosine similarity

**`gdrive_sync.py`** (Google Integration)
- Service account authentication via `config/service_account.json`
- Thread-safe Google API access with `drive_lock`
- Recursive folder scanning from Google Drive
- Updates Google Sheets with `photos` and `faces` worksheets
- Uploads JSON index files (`person_index.json`, `photo_index.json`)

## Key Configuration Files

- `config/service_account.json` - Google Service Account credentials (not in repo)
- `data/app_settings.json` - User preferences (Drive folder IDs, threshold, GPU mode)
- `data/matched_folders.json` - Tracks which folders have been scanned
- `requirements.txt` - Python dependencies

## GPU/CUDA Support

The system supports NVIDIA GPU acceleration via `onnxruntime-gpu`. The CUDA DLLs are pre-loaded in `face_analyzer.py` to handle Windows paths with Thai characters. If GPU initialization fails, it falls back to CPU automatically.

## Face Matching Logic

- **Similarity metric**: Cosine similarity of 512-dim embeddings
- **Default threshold**: 0.5 (configurable in GUI)
- **Batch processing**: Matrix multiplication for efficient multi-face comparison
- **Caching**: Event photo face embeddings are cached to `scanned_photo_faces` table for re-scanning

## Google Sheets Structure

Two worksheets are auto-created:
- `photos`: photo_id, event, drive_link, date
- `faces`: face_id, person, photo_id

## JSON Index Files

Two search index files are uploaded to Drive:
- `person_index.json`: Maps person names to photo IDs
- `photo_index.json`: Maps photo IDs to event metadata and Drive links

## Development Notes

- The project uses Thai language extensively - UI strings, comments, and file names may contain Thai characters
- CustomTkinter (ctk) is used for modern dark-themed UI
- Threading is used for long-running operations (Drive scans, face matching) to keep UI responsive
- Logging is configured to output to both console and GUI log display

## Post-Release Workflow (สำคัญ)

หลังจากทำเวอร์ชั่นใหม่เสร็จ **ต้อง commit git ทุกครั้ง**:

1. **อัปเดตเวอร์ชั่นโปรแกรม:**
   - `app_gui.py`: title bar + logo label (vX.X.X)
   - `README.md`: เพิ่ม changelog เวอร์ชั่นใหม่

2. **Commit files:**
   ```bash
   git add app_gui.py db_manager.py gdrive_sync.py README.md
   git commit -m "Release vX.X.X - [ชื่อฟีเจอร์หลัก]"
   ```

3. **Agent Information (ระบุใน commit):**
   - Developer: Claude (Anthropic)
   - Model: Opus 4.7 (1M context)
   - Model ID: `claude-opus-4-7`
   - Date: [วันที่ปัจจุบัน]

4. **ไฟล์ที่ไม่ต้อง commit:**
   - `data/matched_folders.json` - ข้อมูลรันไทม์
   - `sheet_mirror_backup.xlsx` - backup file
   - `.claude/settings.local.json` - settings ของ Claude Code
   - `app_execution.log` - log file

