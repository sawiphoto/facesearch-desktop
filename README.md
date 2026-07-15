# ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v1.7.1

## 📖 Project Overview
ระบบนี้เป็นเครื่องมือสำหรับ **ค้นหาและวิเคราะห์ใบหน้าบุคลากรโรงเรียน** โดยใช้ SQLite เป็นฐานข้อมูลจัดเก็บเวกเตอร์ใบหน้าและข้อมูลเมตาที่เกี่ยวข้อง พร้อม UI ที่ทำงานบน CustomTkinter ให้ผู้ดูแลระบบสามารถอัปโหลดรูป, ทำการสแกน, และจัดการผลลัพธ์ได้ง่าย ๆ

---

## 🛠️ Installation & Quick Start
```bash
# Clone the repository
git clone <repository-url>
cd "07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน"

# Create virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt

# ตั้งค่า Google API credentials (service_account.json) ตาม README เดิม

# Run the application
python main.py
```

---

## 🗂️ Project Structure
| File / Folder | Description |
|---|---|
| [main.py](main.py) | Entry point – สร้างไดเรกทอรีที่จำเป็นและเรียก GUI |
| [app_gui.py](app_gui.py) | GUI หลัก (CustomTkinter) – แสดงผล UI, ควบคุมการสแกน, 7 เมนูหลัก |
| [db_manager.py](db_manager.py) | จัดการ SQLite DB – สร้างตาราง, บันทึก/ดึงเวกเตอร์ใบหน้า, จัดการ cache |
| [face_analyzer.py](face_analyzer.py) | สร้างเวกเตอร์ใบหน้า 512-dim ด้วย InsightFace (antelopev2) |
| [gdrive_sync.py](gdrive_sync.py) | ซิงค์ข้อมูล Google Drive + Google Sheets + JSON index |
| [requirements.txt](requirements.txt) | รายการ dependency ของโปรเจกต์ |
| [config/](config/) | เก็บ service_account.json (Google credentials) |
| [data/](data/) | SQLite DB, settings, cache, temp files |
| [models/](models/) | โมเดล InsightFace antelopev2 (ดาวน์โหลดอัตโนมัติ) |

---

## 📚 References
- [Google Sheets API Documentation](https://developers.google.com/sheets/api)
- [Google Drive API Documentation](https://developers.google.com/drive/api)
- [InsightFace (antelopev2)](https://github.com/deepinsight/insightface)
- [CustomTkinter Documentation](https://customtkinter.tomschimanych.dev/)

---

*This README is automatically generated and kept up‑to‑date with each version change.*

## ✅ Walkthrough Summary
All SQLite DB verification tests passed successfully:
- **Database Tables** – 5 ตารางหลัก: `staff_members`, `staff_embeddings`, `scanned_photos`, `detected_faces`, `scanned_photo_faces`
- **Face Embedding Cache** – เก็บเวกเตอร์ 512-dim ใน SQLite BLOB
- **Selective Match Deletion** – สามารถลบแมตช์ตาม `face_index` ได้โดยไม่มีผลกระทบต่อข้อมูลอื่น
- **Sync Frequency** – ซิงค์ข้อมูลทุกๆ 500 รูป

> **Result:** The system now handles images without detectable faces efficiently and syncs data to Google services at a reduced frequency, improving overall performance.

---

## 📋 Version 1.7.1 Changelog

**Developer Agent:** Claude (Anthropic)
**Model:** Opus 4.7 (1M context)
**Model ID:** `claude-opus-4-7`
**Date:** 14 กรกฎาคม 2026

### ฟีเจอร์ใหม่ (New Features)

#### 1. ระบบรหัสประจำตัวนักเรียน
- **ปัญหา:** นักเรียนมีชื่อซ้ำกันได้ ระบบเดิมไม่รองรับ
- **วิธีแก้ไข:**
  - เพิ่มคอลัมน์ `student_id` ในตาราง `staff_members` พร้อม UNIQUE index
  - ฟอร์มลงทะเบียนนักเรียน: บังคับกรอก **รหัสประจำตัว** + ชื่อ-นามสกุล
  - ตรวจสอบรหัสซ้ำอัตโนมัติก่อนลงทะเบียน
  - Naming convention: `student_{รหัส}_{timestamp}...`
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 2. Batch Import จาก Google Sheets
- **ปัญหา:** การลงทะเบียนนักเรียนทีละคนใช้เวลามาก
- **วิธีแก้ไข:**
  - เพิ่มฟีเจอร์ "นำเข้านักเรียนจาก Google Sheets"
  - รองรับโครงสร้าง Sheets: รหัส | ชื่อ | รูปหน้าตรง | รูปซ้าย (optional) | รูปขวา (optional)
  - ดาวน์โหลดรูปจาก Drive URL อัตโนมัติ
  - สแกนใบหน้า → ลงทะเบียน → แจ้งเตือนเมื่อไม่พบใบหน้า
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.7 Changelog (ก่อนหน้า)

**Date:** 14 กรกฎาคม 2026

### ฟีเจอร์ใหม่

#### 1. ระบบลงทะเบียนนักเรียน (v1.7 New Feature)
- **ปัญหา:** ระบบเดิมรองรับเฉพาะครูเท่านั้น ไม่สามารถลงทะเบียนนักเรียนแยกกันได้
- **วิธีแก้ไข:**
  - เพิ่มคอลัมน์ `role` ในตาราง `staff_members` เพื่อแยกประเภทระหว่าง 'teacher' และ 'student'
  - เพิ่มเมทอดใหม่: `get_all_teachers()`, `get_all_students()`, `register_member(name, role)`
  - เปลี่ยนชื่อโฟลเดอร์: `registered_faces/` → `registered_teachers/` และเพิ่ม `registered_students/`
  - เปลี่ยน naming convention: `face_` → `teacher_` และเพิ่ม `student_`
  - เพิ่มหน้า "ลงทะเบียนนักเรียนต้นแบอน" ใน GUI
  - Dashboard: แยกสถิติครูและนักเรียน (4 การ์ด)
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.6.9+ Changelog (เดิม)

**Date:** 14 กรกฎาคม 2026

### ปัญหาที่พบและวิธีแก้ไข

#### 1. Fast Re-scan กับภาพที่ไม่พบใบหน้า (0 faces)
- **ปัญหา:** เดิมเมื่อวิเคราะห์รูปที่ไม่พบใบหน้า (เช่น ถ่ายขนม สิ่งของ) ตาราง `scanned_photo_faces` จะไม่มีแถวข้อมูลของรูปดังกล่าว ทำให้ครั้งถัดไปเมื่อสั่งสแกนซ้ำ ฟังก์ชัน `has_cached_faces()` จะวิเคราะห์ว่ารูปนี้ยังไม่เคยทำแคช
- **วิธีแก้ไข:** ปรับปรุงเมทอด `save_photo_face_embeddings()` หากไม่พบใบหน้า (0 faces) ให้ทำการบันทึกแถวจำลอง (Dummy Record) ที่มีค่า `face_index = -1` ลงไปในตาราง `scanned_photo_faces`
- **สถานะ:** ✅ **ได้ implement ไว้แล้ว** ใน `db_manager.py` บรรทัด 296-304

#### 2. ปรับระยะการบันทึกข้อมูล Google Drive/Sheets
- **ปัญหา:** Incremental Sync ทุกๆ 100 รูป ทำให้การสแกนช้าลง
- **วิธีแก้ไข:** ปรับรอบความถี่การทำ Incremental Sync จากเดิมทุกๆ 100 รูป เป็นทุกๆ **500 รูป**
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 3. Selective Match Deletion (ระบบลบการจับคู่แบบเฉพาะคน)
- **ปัญหา:** หากใช้การ Re-scan แบบเจาะจงบางบุคคล ระบบเดิมจะลบผลการแมตช์ของอีก 100 คนเดิมในฐานข้อมูลรูปภาพนั้นออกทั้งหมด
- **วิธีแก้ไข:** พัฒนาเมทอด `delete_photo_matches_selective()` ใน `db_manager.py`
- **สถานะ:** ✅ **ได้ implement ไว้แล้ว** ใน `db_manager.py` บรรทัด 368-386

---

## 🧪 Testing

**วันที่ทดสอบ:** 14 กรกฎาคม 2026

**ผลการทดสอบ:**
- ✅ Import `app_gui` ผ่าน
- ✅ Database migration (role, student_id) ผ่าน
- ✅ ลงทะเบียนนักเรียนพร้อมรหัสประจำตัว ผ่าน
- ✅ ตรวจสอบรหัสซ้ำ ผ่าน
- ✅ Batch Import from Sheets ผ่าน

---

## 📝 Database Schema (v1.7.1)

### staff_members
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | PK Autoincrement |
| name | TEXT | ชื่อบุคลากร |
| role | TEXT | 'teacher' or 'student' (default: 'teacher') |
| student_id | TEXT | รหัสประจำตัวนักเรียน (unique, nullable) |

### Indexes
- `unique_student_id` - UNIQUE index on `student_id` WHERE role = 'student'

---

## 🔧 AI Agent & Development Information

### Developer (AI Agent)
| Property | Value |
|----------|-------|
| **AI Service** | Claude Code (Anthropic) |
| **Agent Name** | Claude Opus 4.7 |
| **Model Family** | Claude 4.X |
| **Model ID** | `claude-opus-4-7` |
| **Context Window** | 1,000,000 tokens |
| **Knowledge Cutoff** | January 2026 |
| **Session Type** | Interactive CLI Development |
| **Platform** | Windows 11 |
| **Shell** | Bash (Git Bash) |

### Model Capabilities Used
- **Code Generation** - Python, SQLite, CustomTkinter GUI
- **System Architecture** - Database schema design, API integration
- **Debugging** - Problem identification, root cause analysis
- **Documentation** - README, CLAUDE.md, inline comments
- **Multi-tool Orchestration** - Read, Edit, Bash, Grep, Glob, Agent spawning

### Development Workflow
1. **Requirement Analysis** - User provides Thai language requirements
2. **Planning** - Create step-by-step implementation plan
3. **User Approval** - Wait for "ทำได้" / "เริ่มได้" / "OK"
4. **Implementation** - Code writing with proper error handling
5. **Testing** - Verify functionality (type checking, runtime tests)
6. **Documentation** - Update README.md, CLAUDE.md

---

## 🐛 Known Issues & Solutions

### Issue #1: Virtual Environment Mismatch
**Problem:** โค้ดรันไม่ได้เมื่ออยู่นอก venv
**Solution:** ต้องใช้ venv เสมอ
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Issue #2: Thai File Paths
**Problem:** cv2.imread() อ่านไฟล์ภาษาไทยไม่ได้
**Solution:** ใช้ cv2.imdecode(np.fromfile(...))
```python
img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
```

### Issue #3: Images with No Faces
**Problem:** รูปที่ไม่มีใบหน้า (0 faces) ไม่ถูก cache → rescan ซ้ำ
**Solution:** บันทึก dummy record (face_index = -1)
**Status:** ✅ Fixed in v1.6.9+

### Issue #4: Sync Performance
**Problem:** Sync ทุกๆ 100 รูป → ช้า
**Solution:** เปลี่ยนเป็นทุกๆ 500 รูป
**Status:** ✅ Fixed in v1.6.9+

### Issue #5: Student Name Duplication
**Problem:** นักเรียนมีชื่อซ้ำกันได้
**Solution:** เพิ่ม `student_id` column (UNIQUE)
**Status:** ✅ Fixed in v1.7.1

### Issue #6: Slow Registration
**Problem:** ลงทะเบียนทีละคน ช้ามาก
**Solution:** Batch Import from Google Sheets
**Status:** ✅ Fixed in v1.7.1

---

## 💻 Technical Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.x |
| **GUI Framework** | CustomTkinter (ctk) |
| **Database** | SQLite |
| **Face Recognition** | InsightFace (antelopev2) |
| **Model Runtime** | ONNX Runtime (CPU/GPU) |
| **Google APIs** | Drive API, Sheets API |
| **Authentication** | Service Account (JSON) |
| **Vector Dimension** | 512 |
| **Similarity Metric** | Cosine Similarity |
| **Default Threshold** | 0.5 |

---

## 📂 File Naming Convention (v1.7.1)

## 📂 File Naming Convention (v1.7.1)

```
ครู:     teacher_{db_id}_{timestamp}_{index}_{name}.jpg
นักเรียน: student_{รหัสประจำตัว}_{timestamp}_{index}_{name}.jpg

ตัวอย่าง:
- teacher_101_20250714_001_ครูสมชาย.jpg
- student_66001_20250714_001_ด.ช.สมชาย.jpg
```

---
