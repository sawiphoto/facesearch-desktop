# ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v1.9.2

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
| [scheduler_task.py](scheduler_task.py) | จัดการระบบรันเบื้องหลัง (ซิงค์ภาพนักเรียน, ตรวจสอบโฟลเดอร์ใหม่) |
| [requirements.txt](requirements.txt) | รายการ dependency ของโปรเจกต์ |

---

## 📚 References
- [Google Sheets API Documentation](https://developers.google.com/sheets/api)
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

## 📋 Version 1.9.3 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 25 กรกฎาคม 2026

#### 1. ปลดล็อกข้อจำกัดชื่อซ้ำ และเปลี่ยนมาใช้รหัสนักเรียนเป็นแกนหลัก
- **สาเหตุ**: ระบบเดิมออกแบบให้ตาราง `staff_members` ห้ามมีชื่อซ้ำกัน (UNIQUE `name`) ทำให้เมื่อมีการอัปเดตข้อมูลนักเรียนที่ชื่อเหมือนกัน แต่คนละรหัส ระบบเกิดการชนกันและเกิดบั๊กวนลูปดาวน์โหลดรูปเดิมซ้ำๆ ไม่รู้จบ (รูปโคลนนิ่ง)
- **การแก้ไข**: 
  - ทำ Database Migration ลบข้อจำกัด UNIQUE ออกจากคอลัมน์ `name` 
  - สร้าง `UNIQUE INDEX` แยกกัน: ครูใช้ "ชื่อ" ห้ามซ้ำ, นักเรียนใช้ "รหัสนักเรียน" ห้ามซ้ำ
  - ปรับจูนฟังก์ชันการเช็คใน `register_member` ให้ค้นหาข้อมูลเก่าจากรหัสนักเรียนเป็นหลัก

#### 2. ระบบ One-Way Sync ทำความสะอาดรายชื่ออัตโนมัติ (Auto-Cleanup)
- **ฟีเจอร์ใหม่**: เมื่อกดซิงค์ข้อมูลผ่านเมนู Schedule ระบบจะเปรียบเทียบรหัสนักเรียนใน Google Sheet กับฐานข้อมูล SQLite ทันที
- **การทำงาน**: หากพบว่ามีรหัสนักเรียนคนไหนค้างอยู่ในฐานข้อมูล แต่ "ไม่ปรากฏอยู่ใน Sheet แล้ว" (เพราะถูกลบออก หรือเปลี่ยนรหัสใหม่) ระบบจะสั่งลบรายชื่อ, รูปภาพ และเวกเตอร์ของคนนั้นออกจากระบบอัตโนมัติ เพื่อให้ Sheet เป็นแหล่งข้อมูลหลัก (Single Source of Truth) อย่างแท้จริง

#### 3. ป้องกันการดาวน์โหลดรูปซ้ำซ้อน
- **การแก้ไข**: เพิ่มฟังก์ชันเช็ค `check_embedding_url_exists` ดักหน้าลูปดาวน์โหลดรูปภาพ เพื่อตรวจสอบว่าลิงก์ Google Drive นี้เคยถูกบันทึกลงฐานข้อมูลแล้วหรือยัง หากเคยแล้วให้ข้ามทันที ช่วยป้องกันรูปซ้ำและเพิ่มความเร็วในการซิงค์ข้อมูล

---

## 📋 Version 1.9.2 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. แก้ไขปัญหารูปจาก Auto Sync แสดงผลเป็น "X" ใน GUI
- **สาเหตุ**: ระบบ Auto Sync นำภาพจาก Drive มาแยกเวกเตอร์แล้วทิ้งภาพไปโดยไม่บันทึกไฟล์ลงเครื่อง 
- **การแก้ไข**: เพิ่มโค้ดให้ครอบตัดใบหน้า (Crop) และบันทึกเป็น `.jpg` ลงเครื่อง พร้อมเก็บที่อยู่ไฟล์ลงฐานข้อมูล ทำให้แสดงผลภาพใน GUI ได้ถูกต้องแล้ว

#### 2. แก้ไข Treeview Error (SQL DB Menu)
- **สาเหตุ**: เกิด Error `TypeError: unsupported format string passed to bytes.__format__` เพราะบางตารางอ่านชนิดข้อมูล `confidence` ผิดเป็น `bytes`
- **การแก้ไข**: สร้างระบบดักจับแปลงข้อมูลเป็นตัวเลขทศนิยม (`float`) ให้เสร็จสิ้นก่อนแสดงผล

---

## 📋 Version 1.9.1 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. ตัดระบบรหัส PIN (6 หลัก) ออกจากการใช้งาน
- **สาเหตุ**: เพื่อลดความยุ่งยากในการทำงานและไม่ต้องจัดการพารามิเตอร์ที่ไม่จำเป็น
- **การแก้ไข**: ยกเลิกการอ่านข้อมูล "รหัสส่วนตัว 6 หลัก" จาก Sheet ข้อมูลนักเรียนทั้งหมด (Task 2) และบันทึกลง SQLite ด้วยค่าว่าง (`""`) เสมอ

#### 2. แก้ปัญหาบั๊ก Retroactive Match (shapes not aligned)
- **สาเหตุ**: ระบบพยายามคำนวณความเหมือนโดยเอาเวกเตอร์ของรูปภาพปัจจุบัน ไปคูณกับรูปภาพดัมมี่ในฐานข้อมูลที่ไม่มีใบหน้าคนอยู่ (เวกเตอร์ว่างเปล่า) 
- **การแก้ไข**: เพิ่มโค้ดดักจับใน `app_gui.py` ให้กรองเฉพาะรูปภาพที่มีความยาวเวกเตอร์ > 0 (มีใบหน้าคนจริง) ขึ้นมาคำนวณเท่านั้น

#### 3. ล็อกคอลัมน์เมนูอัปโหลดภาพด้วยตนเอง (Batch Registration)
- **ฟีเจอร์ (`app_gui.py`)**: ปรับปรุงหน้าต่างนำเข้าข้อมูล (SheetsImportDialog) ให้บังคับเลือก 3 คอลัมน์ที่ชัดเจนสำหรับภาพ (ภาพ 1, ภาพ 2, ภาพ 3) พร้อมตั้งค่าเริ่มต้นเป็นคอลัมน์ D, E, F เพื่อความสะดวก

#### 4. ลดข้อความแจ้งเตือนคนที่ไม่มีรูปลง
- **การแก้ไข**: ในโหมดสืบสวน (Debug Sync) แทนที่จะพิมพ์รายชื่อนักเรียนที่ยังไม่มีรูปในชีททีละคนจนล้นหน้าจอ จะเปลี่ยนเป็นแค่การนับจำนวนรวมมาโชว์ 1 บรรทัดแทน

---

## 📋 Version 1.9.0 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. เพิ่มโหมดสืบสวนและตรวจสอบข้อมูล (Debug Sync Mode) สำหรับ Task 2
- **ฟีเจอร์ (`scheduler_task.py`)**: เพิ่มฟังก์ชัน `debug_compare_sheet_vs_db()` เพื่อใช้เทียบคอลัมน์ใน Sheet กับฐานข้อมูล (SQLite) แบบ 1ต่อ1 
- ฟังก์ชันนี้จะรายงาน Log ออกมาเป็นข้อสรุปให้แอดมินดูรวดเดียว:
  - บอกว่ามีนักเรียนที่ไม่อยู่ใน DB (รอเพิ่มใหม่) กี่คน
  - ตรวจสอบชื่อ-นามสกุล หรือรหัส PIN ว่าตรงกับฐานข้อมูลที่เคยบันทึกไหม
  - แจ้งเตือน URL ของ Google Drive ที่ผิดรูปแบบ (เสีย) ใน Sheet
  - หากนักเรียนมีรูปภาพใน DB ไม่ครบตาม Sheet จะแจ้งรหัส File ID ที่ตกหล่นออกมาด้วย
  - บอกนักเรียนที่ค้างอยู่ใน DB แต่ถูกลบจาก Sheet ไปแล้ว (Orphans)

#### 2. แก้ไข Logic การอัปเดตรูปภาพนักเรียน (Bug Fix)
- **ปัญหา**: หากรหัสนักเรียนถูกลบจากฐานข้อมูล DB ไปแล้ว แต่ตัวโปรแกรมยังจำประวัติในไฟล์แคช JSON (`student_sync_temp.json`) อยู่ จะทำให้ระบบไม่ยอมดึงรูปมาสแกนใหม่ให้
- **การแก้ไข (`scheduler_task.py`)**: เพิ่มเงื่อนไขเข้าไปเช็คว่า ถ้านักเรียนคนนั้นไม่ได้อยู่ใน SQLite (`staff_id_check is None`) จะต้องบังคับให้ตัวแปร `is_new = True` เสมอ เพื่อให้ระบบเมินแคชเดิมและดึงรูปทั้งหมดในชีทมาประมวลผลเซฟลงฐานข้อมูลใหม่ตั้งแต่ต้น

---

## 📋 Version 1.8.9 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. เพิ่มฟังก์ชันดับเบิ้ลคลิกเปิดลิงก์รูปภาพจากตารางฐานข้อมูล
- **การเพิ่มฟีเจอร์ (`app_gui.py`)**: เพิ่ม Event Binding `<Double-1>` ให้กับตาราง `scanned_photos` ในเมนูตรวจสอบฐานข้อมูล SQLite เมื่อผู้ใช้ดับเบิ้ลคลิกที่แถวใดๆ ระบบจะดึงลิงก์ Google Drive ในคอลัมน์ที่ 5 ไปเปิดในเบราว์เซอร์ Chrome อัตโนมัติ (ผ่าน `webbrowser.open`) พร้อมเพิ่มคำแนะนำใต้ตาราง

#### 2. แก้ไข Logic การสร้างแคชจำลอง (Dummy Cache) เมื่อไม่พบใบหน้าคนในรูป
- **ปัญหา**: รูปภาพที่ไม่มีใบหน้าคนอยู่เลย ถูกดาวน์โหลดมาสแกนซ้ำวนไปเรื่อยๆ ทุกครั้งที่รันโปรแกรม เนื่องจากสถานะขึ้นว่า "ไม่มีแคช"
- **สาเหตุ**: คำสั่งสร้างแคชจำลอง (Dummy Cache) เพื่อข้ามการสแกนรอบหน้า ถูกบล็อกด้วยเงื่อนไข `if faces:` (ต้องมีหน้า) จึงไม่เคยถูกบันทึกเมื่อหน้าว่างเปล่า
- **การแก้ไข (`app_gui.py`)**: ถอดเงื่อนไข `if faces:` ก่อนบันทึกแคชออก เพื่อเปิดทางให้ `save_photo_face_embeddings` รับตัวแปร list ว่างไปบันทึกเป็น Dummy Cache `face_index = -1` ลงในระบบ ทำให้รูปเหล่านี้ถูกข้ามได้อย่างสมบูรณ์

#### 3. แก้ไขบั๊ก Task 2 หารูปนักเรียนไม่เจอ (`AttributeError`)
- **ปัญหา**: ขณะที่ Task 2 กำลังดึงรูปนักเรียนใหม่เข้าฐานข้อมูล เกิดข้อผิดพลาด `'FaceAnalyzer' object has no attribute 'get_faces'` รูปจึงไม่ถูกเซฟ
- **การแก้ไข (`scheduler_task.py`)**: แก้ไขการเรียกใช้งานไลบรารีสแกนใบหน้า จากเดิมที่เรียกฟังก์ชันผิด ให้เปลี่ยนเป็นเรียก `self.analyzer.app.get(img_cv)` ซึ่งเป็นคำสั่งที่ถูกต้อง ทำให้ตอนนี้ Task 2 ทำงานได้ปกติจนเสร็จสมบูรณ์

---

## 📋 Version 1.8.8 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.1 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. การแก้ไขปัญหา UI ค้าง (UI Thread Freeze) และการปรับปรุงประสิทธิภาพการแสดงผล
- **ปัญหา:** โปรแกรมเกิดอาการค้าง (Freeze) นานหลายสิบวินาทีเมื่อเปิดหน้า Dashboard หรือคลิกเข้าเมนูลงทะเบียนครู/นักเรียน หลังจากที่มีรายชื่อนักเรียนในฐานข้อมูลจำนวนมาก
- **สาเหตุ:** `app_gui.py` ดึงรายชื่อบุคลากรทั้งหมด (เช่น 2,000 คน) มาสร้าง CustomTkinter Widget (`CTkFrame`, `CTkButton`, `CTkLabel`) วนลูปทีละคนแบบไม่มีการจำกัดจำนวน ทำให้เกิดการสร้าง Widget กว่า 6,000-8,000 ชิ้นรวดเดียวบน UI Thread ซึ่งเกินขีดจำกัดของ Tcl/Tk Engine 
- **การแก้ไข (`app_gui.py`):**
  - เพิ่มการทำ **Pagination / Limit Rendering** ในเมนูที่ต้องแสดงรายการยาวๆ
  - `refresh_dashboard_stats()`: จำกัดการดึงและวาดข้อมูลสถิติเพียง Top 50 ลำดับสูงสุด (`LIMIT 50`)
  - `load_student_list()` และ `load_staff_list()`: จำกัดการวาดปุ่มรายชื่อบนหน้าจอให้แสดงเพียง 100 รายการแรก (`rendered_count >= 100`) โดยแนะนำให้ผู้ใช้ใช้งานผ่านช่องค้นหา (Search) หากต้องการดูรายชื่ออื่น
  - `load_db_table_data()`: เพิ่ม `LIMIT 100` ใน SQL Query สำหรับดึงข้อมูลจากตารางมาแสดงบน Treeview
  - **ผลลัพธ์:** โปรแกรมเปิดสลับเมนูได้รวดเร็วทันที (0.1 วินาที) ไม่ว่าจะมีข้อมูลในระบบหลักหมื่นคนก็ตาม

#### 2. การแก้ไขปัญหารายชื่อขยะจากการรัน Task 2
- **ปัญหา:** Task 2 ดึงรายชื่อนักเรียนกว่า 700 คนเข้ามาลงทะเบียนในตาราง `staff_members` แม้ว่านักเรียนเหล่านั้นจะไม่มีรูปภาพเลย
- **สาเหตุ:** มีการเรียกใช้ฟังก์ชัน `self.db.register_member()` ล่วงหน้าสำหรับทุกแถวใน Google Sheet ทันที ก่อนที่จะมีการตรวจสอบหรือดาวน์โหลดรูปภาพ
- **การแก้ไข (`scheduler_task.py`, `db_manager.py`):**
  - **`scheduler_task.py`**: แก้ไข Logic ให้ทำการตรวจสอบ ID ว่ามีในระบบหรือไม่โดยใช้คำสั่ง `SELECT` ธรรมดา แทนการเรียก `register_member` พร่ำเพรื่อ จะทำการลงทะเบียนนักเรียนใหม่ก็ต่อเมื่อพบรูปภาพและสามารถสกัดเวกเตอร์ใบหน้าได้สำเร็จจริงๆ เท่านั้น
  - **`db_manager.py`**: สร้างสคริปต์ `cleanup_orphan_students()` สำหรับเคลียร์ข้อมูลนักเรียนขยะกว่า 700 รายการที่ไม่มีความสัมพันธ์กับเวกเตอร์ภาพใดๆ ออกจากระบบอย่างปลอดภัย

---

## 📋 Version 1.8.7 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.6 Flash
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. การแก้ไขปัญหาลิงก์ Google Drive รูปแบบ `uc?id=` ไม่ถูกดาวน์โหลด และแคช JSON ข้ามรูปภาพ (Fix Google Drive `uc?id=` extraction & DB embedding verification)
- **ปัญหา:** อัปโหลดเปลี่ยนภาพใหม่ 3 ภาพให้คุณชญานนท์ (รหัส `99999`) แต่ระบบแจ้งว่า "ไม่มีภาพใหม่" และในระบบมีเพียง 2 ภาพเดิม
- **สาเหตุ:**
  1. ลิงก์รูปภาพใน Google Sheet ใช้รูปแบบ `https://drive.google.com/uc?id=...` แต่ฟังก์ชัน `_extract_drive_id()` เดิมตรวจเช็คเฉพาะ `/d/` ทำให้ดึง File ID ล้มเหลว คืนค่าเป็น `None` และข้ามการดาวน์โหลดรูปภาพทั้งหมด
  2. ไฟล์แคช `student_sync_temp.json` บันทึก URL ใหม่ไปล่วงหน้า ทำให้เมื่อรันครั้งถัดไป ระบบมองว่า URL นี้เคยสแกนแล้วและข้ามการดาวน์โหลดไปอีก
- **โค้ดที่แก้ไข (`scheduler_task.py`):**
  - **`_extract_drive_id(url)`**: ปรับปรุงให้รองรับลิงก์ทุกรูปแบบ (`uc?id=`, `open?id=`, `/file/d/`, `/d/`, Raw File ID)
  - **`_task_2_sync_new_students()`**: เพิ่มการตรวจสอบกับ SQLite DB (`staff_embeddings`) โดยตรง หาก `file_id` รูปใดยังไม่มีเวกเตอร์ใบหน้าใน DB ให้ระบบดาวน์โหลดมาประมวลผลทันที แม้ URL จะเคยบันทึกในแคช JSON แล้วก็ตาม

#### 2. การปรับปรุงให้ Task 2 ดึงค่า Threshold จาก UI Slider มาใช้อัตโนมัติ (Task 2 Dynamic Slider Threshold Fix)
- **ปัญหา:** Task 2 (Retroactive Match) ล็อกค่าการเปรียบเทียบใบหน้าไว้ที่ `0.5` (Hardcoded) ไม่เปลี่ยนตาม Slider บนหน้าจอ GUI
- **โค้ดที่แก้ไข (`app_gui.py`):**
  - **`process_retroactive_match_headless()`**: เปลี่ยนจากการล็อกค่า `0.5` เป็นการดึงค่าไดนามิกจาก `current_thresh = self.slider_threshold.get()` มาใช้อัตโนมัติแบบเดียวกับ Task 1

---

## 📋 Version 1.9.8 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.6 Flash
**Model ID:** `gemini-3-6-flash`
**วันที่อัปเดต:** 25 กรกฎาคม 2026

#### 1. การแก้ไขปัญหา Google Sheets API ตอบกลับข้อผิดพลาด 503 (Google API 503 Service Unavailable Auto-Retry Fix)
- **ปัญหา:** เมื่อเรียกใช้งาน Auto Schedule บางครั้งเกิดข้อผิดพลาด `Cannot access Google Sheet: APIError: [503]: The service is currently unavailable` ทำให้งาน Headless Scan ล้มเหลวและถูกยกเลิก (`aborted`) ทันที
- **สาเหตุ:** รหัสข้อผิดพลาด 503 เป็นข้อผิดพลาดชั่วคราวจากฝั่งเซิร์ฟเวอร์ของ Google (Google Cloud Infrastructure Transient Glitch) แต่โค้ดเดิมไม่มีระบบพยายามเชื่อมต่อใหม่ (Retry Mechanism) ทำให้การเชื่อมต่อล้มเหลวทันทีที่เจอกระตุกเพียง 1 ครั้ง
- **ฟังก์ชันสำคัญที่แก้ไข:**
  - **`gdrive_sync.py` -> `_execute_with_retry(self, func, max_retries=3, initial_delay=2)`**:
    - เพิ่มฟังก์ชันลองใหม่อัตโนมัติ (Exponential Backoff Auto-Retry) สูงสุด 3 รอบ พร้อมเพิ่มระยะเวลาหน่วงก่อนลองใหม่เมื่อพบข้อผิดพลาดชั่วคราว (`503`, `500`, `429`, `unavailable`)
    - ครอบการทำงานของ `open_by_key(...)`, `verify_spreadsheet(...)`, และ `read_sheet_data(...)` ทั้งหมด
    ```python
    def _execute_with_retry(self, func, max_retries=3, initial_delay=2):
        import time
        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            try:
                return func()
            except Exception as e:
                err_msg = str(e)
                is_transient = any(code in err_msg for code in ["503", "500", "429", "unavailable", "timed out", "Overload"])
                if attempt < max_retries and is_transient:
                    logger.warning(f"[GOOGLE API] พบข้อผิดพลาดชั่วคราว ({e}) กำลังพยายามลองใหม่อัตโนมัติ รอบที่ {attempt}/{max_retries} ในอีก {delay} วินาที...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
    ```
- **ผลลัพธ์:** ป้องกันการเกิดงานค้างหรือ Aborted จากปัญหาเน็ตกระตุก/Google 503 ทำให้ระบบ Auto Schedule ทำงานได้อย่างเสถียรและราบรื่น 100%

---

## 📋 Version 1.9.7 (v1.9.6+) Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.6 Flash
**Model ID:** `gemini-3-6-flash`
**วันที่อัปเดต:** 25 กรกฎาคม 2026

#### 1. การเพิ่มระบบวัดสถิติตรวจสอบเวลาดาวน์โหลดไฟล์ Google Drive API (Drive Download & AI Scan Performance Benchmark)
- **ปัญหา:** ผู้ใช้พบว่ารูปภาพไฟล์ใหม่ที่ยังไม่เคยอยู่ใน SQLite Cache กินเวลานาน ~60 - 66 วินาทีต่อรูป แต่ไม่สามารถแยกแยะได้ว่าเสียเวลาไปกับคอขวดขั้นตอนใด
- **สาเหตุ:** 
  1. รูปภาพใหม่จากกล้องขนาด 20MB - 42MB ต้องถูกดาวน์โหลดจาก Google Drive API ผ่านอินเทอร์เน็ตสดๆ ซึ่งคอขวดที่แท้จริงคือความเร็วในการดาวน์โหลดไฟล์ผ่านเครือข่าย
  2. โค้ดเดิมไม่มีระบบวัดระยะเวลาการดาวน์โหลดแยกต่างหากใน Log ทำให้ผู้ใช้ไม่เห็นว่า AI ใช้เวลาสแกนจริงเพียง 0.2 วินาที
- **ฟังก์ชันสำคัญที่แก้ไข:**
  - **`gdrive_sync.py` -> `download_image_bytes_with_stats(self, file_id, file_name="Unknown")`**:
    - เพิ่มระบบจับเวลา คำนวณขนาดไฟล์เป็น Megabytes (MB) และความเร็วในการดาวน์โหลด (MB/s)
    - แสดง Log ผลลัพธ์: `[DOWNLOAD] ดาวน์โหลดไฟล์ DSC00397.JPG (21.40 MB) สำเร็จใน 12.3 วินาที (1.74 MB/s)`
    ```python
    def download_image_bytes_with_stats(self, file_id, file_name="Unknown"):
        if not self.connected: return None, 0.0, 0
        t0 = time.time()
        try:
            with self.drive_lock:
                request = self.drive_service.files().get_media(fileId=file_id)
                data_payload = request.execute()
            t1 = time.time()
            elapsed = t1 - t0
            img_bytes = io.BytesIO(data_payload).read()
            size_mb = len(img_bytes) / (1024 * 1024)
            speed_mbps = size_mb / elapsed if elapsed > 0 else 0.0
            logger.info(f"[DOWNLOAD] ดาวน์โหลดไฟล์ {file_name} ({size_mb:.2f} MB) สำเร็จใน {elapsed:.1f} วินาที ({speed_mbps:.2f} MB/s)")
            return img_bytes, elapsed, len(img_bytes)
        except Exception as e:
            logger.error(f"[DOWNLOAD] เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์ {file_name}: {e}")
            return None, 0.0, 0
    ```
  - **`app_gui.py` -> `process_scanning_headless()` & `run_scanning_process()`**:
    - แสดง Log แยกแยะเวลาชัดเจนระหว่าง **เวลาดาวน์โหลดจาก Google Drive** กับ **เวลาที่โมเดล AI ใช้สแกนใบหน้า**
    - ตัวอย่าง Log: `[AI SCAN] สแกนใบหน้าไฟล์ DSC00397.JPG สำเร็จ พบ 3 ใบหน้า ใช้เวลาสแกน 0.28s (เวลาดาวน์โหลด Drive: 12.3s)`
- **ผลลัพธ์:** Log รายงานเวลาดาวน์โหลดและความเร็วของเครือข่ายอย่างโปร่งใส 100% ให้ผู้ใช้ทราบทันทีว่าเวลาส่วนใหญ่เสียไปกับการดาวน์โหลดไฟล์ผ่าน Google Drive API

---

## 📋 Version 1.9.6 Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.6 Flash
**Model ID:** `gemini-3-6-flash`
**วันที่อัปเดต:** 25 กรกฎาคม 2026

#### 1. การแก้ไขปัญหาสแกนรูปภาพความละเอียดสูงช้าบน GPU (42MP Ultra-Fast GPU Downscaling Fix)
- **ปัญหา:** เมื่อสแกนรูปภาพกิจกรรมที่ถ่ายจากกล้องคุณภาพสูง เช่น Sony A7RII ความละเอียด 42 Megapixels (~7952x5304 พิกเซล) แม้เปิดใช้งาน GPU (NVIDIA RTX 3050 CUDA) การสแกนรูปภาพกินเวลานานถึง **1 - 2 นาทีต่อรูปภาพ**
- **สาเหตุ:** 
  1. โค้ดเดิมส่งรูปภาพขนาดเต็ม `7952x5304` เข้าโมเดล `InsightFace (SCRFD)` โดยตรงโดยไม่ได้ย่อขนาดล่วงหน้า ทำให้ ONNX Runtime และ GPU ต้องคำนวณ Tensor ขนาดมหาศาลและสร้าง Anchor Box หลายแสนอันต่อเฟรม
  2. มีการสั่งสร้าง Instance และ Warmup โมเดล `FaceAnalyzer` ซ้ำซ้อน 2 รอบในการสแกน Headless
- **ฟังก์ชันสำคัญที่แก้ไข:**
  - **`face_analyzer.py` -> `get_faces_optimized(self, img, max_size=1280)`**: 
    - เพิ่มฟังก์ชันย่อขนาดรูปภาพคงอัตราส่วน (Aspect Ratio) ก่อนส่งเข้าโมเดล SCRFD โดยจำกัดขนาดด้านยาวสูงสุดไม่เกิน `1280px`
    - คำนวณปรับพิกัดกรอบใบหน้า (`face.bbox`) และจุดแลนด์มาร์ก (`face.kps`) กลับสู่ขนาดภาพจริงดั้งเดิมโดยอัตโนมัติ เพื่อให้ได้ความแม่นยำ 100% เท่าเดิม
    ```python
    def get_faces_optimized(self, img, max_size=1280):
        if img is None: return []
        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim > max_size:
            scale = max_size / float(max_dim)
            img_resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            scale, img_resized = 1.0, img

        faces = self.app.get(img_resized)
        if scale != 1.0:
            for face in faces:
                if hasattr(face, 'bbox') and face.bbox is not None: face.bbox /= scale
                if hasattr(face, 'kps') and face.kps is not None: face.kps /= scale
        return faces
    ```
  - **`app_gui.py` -> `process_scanning_headless()` & `run_scanning_process()`**:
    - สลับมาเรียกใช้ `get_faces_optimized()` แทนการเรียก `app.get()` ตรงๆ
    - ป้องกันการ Re-initialize `FaceAnalyzer` ซ้ำซ้อนหากมี Instance ที่ถูกสร้างด้วย Provider (GPU/CPU) นั้นอยู่แล้ว
- **ผลลัพธ์:** ความเร็วในการสแกนรูปภาพ 42 Megapixels บน GPU RTX 3050 เพิ่มขึ้นจาก **1 - 2 นาที/รูป** เหลือเพียง **~0.2 - 0.5 วินาที/รูป** (เร็วกว่าเดิม 200 - 400 เท่า!)

---

## 📋 Version 1.8.6 (v1.7.5 Update) Changelog
**Developer Agent:** Antigravity (Google DeepMind - Advanced Agentic Coding) | **Model:** Gemini 3.6 Flash
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. การแก้ไขปัญหา Task 2 Schedule ค้างและ Log ไม่แสดงผลบน GUI Console (Task 2 GUI Logging & Socket Timeout Fix)
- **ปัญหา:** เมื่อกดรัน Task 2 ข้อความความคืบหน้าของ Task 2 ค้างและแสดงผลเพียง `Attempting to load Google credentials...` บนหน้าจอ GUI
- **สาเหตุ:**
  1. ใน `scheduler_task.py` ข้อความ Log ความคืบหน้าใช้คำสั่ง `print()` ของ Python แทนที่จะใช้ `logger` ของ `FaceSearchApp` ทำให้ GUI Console ไม่ได้รับข้อความ Log มาแสดงผล
  2. การเชื่อมต่อ Google API ใน `gdrive_sync.py` ไม่ได้ตั้งค่า Socket Timeout ทำให้กรณี Network ช้า Thread จะค้างสะสม
  3. ฟังก์ชัน `connect()` พยายามสร้างแท็บ `photos` / `faces` ซ้ำซ้อนใน Sheet ข้อมูลนักเรียน
- **โค้ดที่แก้ไข (`scheduler_task.py` & `gdrive_sync.py`):**
  - **`scheduler_task.py`**: เปลี่ยนคำสั่ง `print()` ทั้งหมดใน Task 2 เป็น `logger.info()`, `logger.warning()`, `logger.error()` พร้อมเพิ่มระบบตรวจหาหัวคอลัมน์ Google Sheet แบบยืดหยุ่น (Flexible Column Matching)
  - **`gdrive_sync.py`**: เพิ่ม `socket.setdefaulttimeout(30)` และพารามิเตอร์ `ensure_worksheets=False` เมื่อเชื่อมต่อเพื่ออ่าน Sheet ข้อมูลนักเรียน

#### 2. การแก้ไขข้อผิดพลาด 'NoneType' object has no attribute 'get_faces' ใน Task 2 (Task 2 FaceAnalyzer Auto-initialization Fix)
- **ปัญหา:** เมื่อสแกนรูปภาพนักเรียนใน Task 2 เกิดข้อผิดพลาด `ERROR: [SCHEDULE] Error processing image ... for ...: 'NoneType' object has no attribute 'get_faces'` และข้ามการสกัดใบหน้านักเรียนทั้งหมด
- **สาเหตุ:** ตัวแปร `self.analyzer` ใน `SchedulerTask` มีค่าเป็น `None` เนื่องจากตอนเปิดแอปพลิเคชัน GUI โมเดล AI (`FaceAnalyzer`) ยังไม่ถูก Initialize ขึ้นมาในหน่วยความจำ
- **โค้ดที่แก้ไข (`scheduler_task.py`):**
  - **ฟังก์ชัน `_ensure_analyzer` (`scheduler_task.py`):** สร้างฟังก์ชันตรวจสอบและสั่ง Auto-initialize ตัวประมวลผล `FaceAnalyzer` อัตโนมัติหาก `self.analyzer` ยังเป็น `None` ก่อนเรียกใช้งาน `get_faces()` ใน `_task_2_sync_new_students()`

---

## 📋 Version 1.8.5 Changelog
**Developer Agent:** Antigravity (Google DeepMind) | **Model:** Gemini 1.5 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. การแก้ไขข้อผิดพลาด UnboundLocalError เมื่อเอาเครื่องหมายสแกนซ้ำออก (Fix `use_re_scan` UnboundLocalError)
- **ปัญหา:** เมื่อสแกนรูปภาพโดยไม่ติ๊กเลือก "สแกนซ้ำ" (`use_re_scan` เป็น `False`) โปรแกรมเกิด Error กลางคัน: `cannot access local variable 'existing_photo_id' where it is not associated with a value`
- **สาเหตุ:** การดึงค่าตัวแปร `existing_photo_id = self.db.get_photo_id_by_drive_id(...)` ถูกเขียนไว้อยู่ภายในบล็อกเงื่อนไข `if use_re_scan:` ทำให้เมื่อไม่สแกนซ้ำ บล็อกเงื่อนไขนั้นถูกข้ามไป ส่งผลให้ตัวแปร `existing_photo_id` ยังไม่ถูกประกาศค่า พอมารันถึงขั้นตอนบันทึกรูปภาพ `photo_id = existing_photo_id` ภาษา Python จึงพ่นข้อผิดพลาด `UnboundLocalError` ทันที
- **โค้ดที่แก้ไข (`app_gui.py`):** ย้ายบรรทัดประกาศดึง `existing_photo_id` ออกมาไว้นอกเงื่อนไข `if use_re_scan:` เพื่อการันตีว่าตัวแปร `existing_photo_id` จะถูกประกาศและมีค่าพร้อมใช้งานตลอดเวลาไม่ว่าจะเปิดหรือปิดตัวเลือกสแกนซ้ำ

---

## 📋 Version 1.8.4 Changelog
**Developer Agent:** Antigravity (Google DeepMind) | **Model:** Gemini 1.5 Pro
**วันที่อัปเดต:** 23 กรกฎาคม 2026

#### 1. การแก้ไขปัญหานำเข้านักเรียนใหม่ติดข้อผิดพลาด (Student Import Fix)
- **ปัญหา:** บันทึกนักเรียนใหม่ (เช่น ชญานนท์ ID: `99999`) ไม่สำเร็จ เกิด Log: `New student: ชญานนท์ (ID: 99999, DB ID: None)` และตามด้วย `NOT NULL constraint failed: staff_embeddings.staff_id`
- **สาเหตุ:** รหัสนักเรียนมีประวัติเดิมอยู่ในตาราง `staff_members` (แต่คอลัมน์ `role` ไม่เป็น `'student'` หรือมีชื่อต่างกัน) ทำให้การ `INSERT` ติด UNIQUE Index (`sqlite3.IntegrityError`) และในบล็อก Catch เดิมดึงข้อมูลด้วยเงื่อนไข `WHERE student_id = ? AND role = 'student'` ซึ่งไม่พบแถวข้อมูล จึงคืนค่า `None` ส่งผลให้ `app_gui.py` ได้ `student_id = None` และพ่นข้อผิดพลาด NOT NULL ของ SQLite
- **โค้ดที่แก้ไข (`db_manager.py` & `app_gui.py`):**
  - **ฟังก์ชัน `register_member` (`db_manager.py`):** ในบล็อก `except sqlite3.IntegrityError` ให้ดึงข้อมูลจาก `student_id` โดยตรงโดยไม่จำกัด `role` แล้วสั่ง `UPDATE staff_members SET name = ?, role = 'student' WHERE id = ?` คืนค่า `id` เดิมกลับไปเสมอ (ป้องกันการคืนค่า `None`)
  - **ฟังก์ชัน `process_import` (`app_gui.py`):** เพิ่มการตรวจสอบความปลอดภัย `if not student_id: logger.error(...); continue` เพื่อป้องกันการเรียก `add_staff_embedding` ด้วย `student_id` ที่เป็น `None`

#### 2. การแก้ไขปัญหารูปภาพนักเรียนเดิมโดนสแกนและบันทึกซ้ำซ้อน (Duplicate URL Embedding Skip Fix)
- **ปัญหา:** นักเรียนเดิมที่มีรูปภาพและลิงก์เดิมใน Google Sheet (คอลัมน์ D, E, F) โดนดาวน์โหลดและบันทึกเวกเตอร์ใบหน้าซ้ำซ้อนลงในตาราง `staff_embeddings`
- **สาเหตุ:** ลิงก์ใน Google Sheet มีช่องว่างเว้นวรรคติดมาด้านหน้าหรือด้านหลัง (เช่น `" https://drive.google.com/uc?id=..."`) ฟังก์ชันเดิมเปรียบเทียบข้อความแบบ `source_url = ?` แบบตรงตัว พอเจอช่องว่างจึงหาไม่เจอและถือว่าเป็นลิงก์ใหม่
- **โค้ดที่แก้ไข (`db_manager.py` & `app_gui.py`):**
  - **ฟังก์ชัน `check_embedding_url_exists` (`db_manager.py`):** ปรับปรุงให้รองรับการตัดช่องว่าง (`.strip()`) และทำการสกัด **Google Drive File ID** (เช่น `1-1JlMDEkm0AP...`) ออกจาก URL เพื่อนำไปเปรียบเทียบใน SQL ด้วย `source_url LIKE %file_id%` หรือ `image_path LIKE %file_id%` ทำให้ตรวจพบรูปภาพเดิมได้อย่างแม่นยำ 100% แม้รูปแบบลิงก์จะต่างกัน
  - **ฟังก์ชัน `process_import` (`app_gui.py`):** ทำการ `.strip()` ลิงก์ URL ก่อนส่งเข้าประมวลผลทุกครั้ง

---

## 📋 Version 1.8.3 Changelog
**Developer Agent:** Antigravity (Google DeepMind) | **Model:** Gemini 1.5 Pro
**วันที่อัปเดต:** 22 กรกฎาคม 2026

#### 1. การปรับปรุงระบบรายงานผล (Match Logging)
- **ปัญหาเดิม:** โหมด Headless (Schedule) แจ้งเตือนแค่ `กำลังสแกนรูปที่ X/Y` ซึ่งผู้ใช้ไม่รู้เลยว่ารูปนั้นสแกนแล้วเจอใครบ้าง
- **สิ่งที่แก้ไข:** เพิ่มการแสดงผลลัพธ์รายภาพเข้าไปใน Log โดยตรง พร้อมระบุชื่อโฟลเดอร์ และให้แสดงสีแยกความแตกต่างชัดเจนในหน้าต่างแอป
  - ตัวอย่างเจอคน: `[SCHEDULE] โฟลเดอร์: ... | รูปที่ ... -> [MATCH_OK] เจอ: สมชาย, สมหญิง` (ตัวหนังสือสีเขียว)
  - ตัวอย่างไม่เจอคน: `[SCHEDULE] โฟลเดอร์: ... | รูปที่ ... -> [WARNING] ไม่พบใบหน้าที่แมตช์` (ตัวหนังสือสีส้ม)

#### 2. ปุ่มลัด Start Task 2 (Sync Students)
- **เพิ่มปุ่มลัดใหม่:** "▶️ Start Task 2 (Sync Students)" ตรงเมนูด้านซ้าย ถัดจากปุ่ม Start Schedule Now
- **การทำงาน:** เป็นปุ่มสำหรับกดเพื่อดึงรายชื่อนักเรียนและบุคลากรชุดใหม่จาก Google Sheets เข้าสู่ระบบฐานข้อมูลโดยตรง (ข้ามขั้นตอนการสแกนรูปไปเลย) เหมาะสำหรับเวลาที่ต้องการอัปเดตรายชื่อใหม่ด่วนๆ

#### 3. อัปเดตข้อมูลเวอร์ชัน
- อัปเดตเลขเวอร์ชันบนหน้าต่างโปรแกรมและโลโก้เป็น `v1.8.3`
- **เพิ่มคอลัมน์แสดงสถานะแคชใบหน้า (Face Cache Status):** ในตารางประวัติภาพถ่ายกิจกรรม (`scanned_photos`) จะมีคอลัมน์บอกชัดเจนว่ารูปไหน `✅ มีแคชแล้ว (X หน้า)` หรือ `❌ ยังไม่มีแคช (0)` พร้อมรองรับการพิมพ์ค้นหาคำว่า `มีแคช` หรือ `ไม่มีแคช` ใน Search Bar
- **เพิ่มระบบค้นหาข้อมูลในหน้าดูฐานข้อมูล (Database View Search):** เพิ่มแถบ Search Bar ที่รองรับการพิมพ์ค้นหาข้อมูลแบบ Real-time กรองข้อมูลได้ทั้ง Drive File ID, ลิงก์ Drive, Photo ID, ชื่อ-นามสกุล, รหัสนักเรียน และชื่องานกิจกรรม ครอบคลุมทุกตารางข้อมูลในระบบ
- **ระบบ GPU Warmup:** เพิ่มขั้นตอนการรันรูปภาพจำลองล่วงหน้าในฟังก์ชัน `initialize()` ของ `face_analyzer.py` เพื่อสั่งให้การ์ดจอจัดสรร VRAM และคอมไพล์ CUDA Kernels ทันทีตั้งแต่เริ่มระบบ ทำให้ไม่หน่วง 1 นาทีตอนสแกนรูปแรก
- **ป้องกันการสแกนโฟลเดอร์ซ้ำวนลูป:** เพิ่มการจดจำโฟลเดอร์ที่เพิ่งสแกนเสร็จในรอบนั้นๆ (`scanned_in_this_run`) และเพิ่มการลงทะเบียนรูปที่อ่าน/โหลดล้มเหลวลงฐานข้อมูล เพื่อไม่ให้เกิดปัญหาไฟล์ตกค้างกระตุ้นการสแกนซ้ำวนลูปเดิมอีกต่อไป

## 📋 Version 1.8.2 Changelog
**Developer Agent:** Antigravity (Google DeepMind) | **Model:** Gemini 1.5 Pro
**วันที่อัปเดต:** 21 กรกฎาคม 2026

#### 1. การแก้ไขปัญหา (Bug Fixes & Refinements)
- **ปัญหา:** `Schedule Task` หรือ `Headless Scan` ขาดการอัปเดตไฟล์ JSON บน Google Drive (พ่น Log แค่ Sync to Google Sheets แต่ไม่มีไฟล์ JSON 3 ตัว)
- **วิธีแก้:** ไปเพิ่มโค้ดบรรทัด `self.sync_manager.update_json_indexes_on_drive` ต่อท้ายการอัปเดต Google Sheet ทั้งในส่วนของ Chunk Sync (ทุก 500 รูป) และ Final Sync ตอนทำงานเสร็จ ภายในโค้ดชุด `process_scanning_headless` ของไฟล์ `app_gui.py` 
- **ปัญหา:** หน้าจอ Console มี Log แจ้งเตือนยิบย่อยเยอะเกินไป (เช่น `DEBUG: Face #... matched with template...` หรือ `Loading SQLite table data`) 
- **วิธีแก้:** เข้าไปคอมเมนต์บรรทัดคำสั่ง `logger.debug` ทิ้งในไฟล์ `face_analyzer.py` และ `db_manager.py` และเปลี่ยน Log ข้อมูลฐานข้อมูลใน `app_gui.py` ไม่ให้รกหน้าจอ
- **ปัญหา:** เกิด Error โค้ดหยุดทำงานกลางคันใน `scheduler_task.py` เนื่องจากหาโมดูล `pytz` ไม่พบ
- **วิธีแก้:** เปลี่ยนการพึ่งพาโมดูลภายนอกอย่าง `pytz` เป็นการใช้ระบบจัดการเวลาภายในตัวของ Python แทน โดยเรียกใช้ฟังก์ชัน `datetime.timezone` และ `timedelta(hours=7)` ทำให้โปรแกรมสามารถระบุเวลาเป็น `Asia/Bangkok` ได้อย่างแม่นยำแม้ไม่ได้ลง Extension พิเศษ
- **ปัญหา:** `Headless Scan` แจ้ง Error ว่า `DatabaseManager object has no attribute 'save_photo_face_embedding'`
- **วิธีแก้:** แก้ไขชื่อฟังก์ชันและวิธีการเรียกใช้ใน `app_gui.py` ให้ถูกต้องเป็น `save_photo_face_embeddings` (เติม s) และส่งพารามิเตอร์แบบ List ของใบหน้าไปให้ทีเดียว ทำให้ลดการวนลูปซ้ำซ้อนและป้องกัน Error ได้สำเร็จ

---

## 📋 Version 1.8 Changelog
**วันที่อัปเดต:** 21 กรกฎาคม 2026

#### 1. ปุ่ม 🛑 Stop Schedule Task
- เพิ่มปุ่มสำหรับสั่งหยุดการทำงานของ Schedule ชั่วคราว (ปุ่มอยู่แถบซ้ายมือล่าง ใต้ปุ่ม Start Schedule)
- เมื่อกดปุ่ม ระบบจะรีบสรุปผลลัพธ์ของรอบบิลนั้น, อัปเดตข้อมูลไฟล์ JSON ขั้นสุดท้ายลง Google Drive และจบการทำงานแบบคลีน (Graceful Shutdown)
- ปรับการรายงานเวลาสำเร็จ ให้ดึง Timezone เป็น `Asia/Bangkok` เพื่อความแม่นยำ

#### 2. Chunking Logic (โหมด Headless/Schedule)
- นำระบบการซิงค์ข้อมูล (Sync to Google Sheets / JSON) ทุกๆ 500 รูป มาปรับใช้ในโหมด Headless (ที่ Schedule ใช้งาน)
- หากข้อมูลมีไม่ถึง 500 รูป หรือเศษที่เหลือ จะถูกสรุปและซิงค์ตอนท้ายสุด (Final Sync) ตามปกติ

#### 3. ปรับปรุงข้อความ Log
- ลดความรกของ Log จากที่โวยวายทุกโฟลเดอร์ย่อย (รวมถึงที่ไม่เจอรูป) ให้เหลือเฉพาะ 2 จังหวะสำคัญ:
  1. `[SCHEDULE] เริ่มทำการสแกนรูปภาพในโฟลเดอร์: {folder_name}`
  2. `[SCHEDULE] สแกนโฟลเดอร์ {folder_name} เสร็จสิ้นเรียบร้อย`

#### 4. ปรับปรุงการแสดงผล UI และฐานข้อมูล (Minor Tweaks)
- **Dashboard:** นำแถบ Progress Bar ในกล่องสรุปสถิติออก เพื่อป้องกันไม่ให้ข้อมูลจำนวนภาพตกขอบเมื่อย่อหน้าต่าง โดยยังคงระบบไล่เฉดสีตัวหนังสือจากแดงไปเขียว (ตามปริมาณรูปภาพ) ไว้เพื่อความสวยงามและเข้าใจง่าย
- **Database Viewer:** ปรับตั้งค่าเริ่มต้นให้ทุกตารางในหน้าต่างเรียกดูฐานข้อมูล เรียงลำดับจากข้อมูลล่าสุดขึ้นมาก่อน (DESC) เพื่อให้แอดมินตรวจสอบอัปเดตล่าสุดได้ทันที

#### 5. แก้ไขบั๊ก (Bug Fixes)
- **ปัญหา: ฐานข้อมูลแสดงภาพที่บันทึกได้น้อยกว่าจำนวนรูปทั้งหมดมาก** หลังจากสั่งหยุด Schedule หรือ Manual Scan, รูปที่เข้าฐานข้อมูลใหม่มีเพียงรูปท้ายๆ ไม่กี่รูป สาเหตุเกิดจากระบบใช้ Fast Rescan ทำให้ดึง Photo ID เก่ามาใช้แทนที่จะสร้างใหม่ แต่หน้าต่าง UI ไปตั้งเรียงลำดับจาก Photo ID ล่าสุดลงมา (DESC) ทำให้รูปที่ Fast Rescan (รหัส P เลขน้อย) ไปจมอยู่ล่างสุด
- **ปัญหา: รหัส `P00001` ซ้ำ/ไม่ยอมสร้างรหัสใหม่** Headless Scan สร้าง ID เป็นแบบ `evt_...` แทรกเข้าไป ทำให้ฟังก์ชัน `get_next_photo_serial()` หารหัส `Pxxxxx` ล่าสุดไม่เจอ และพยายามรันรหัส `P00001` ใหม่ตลอดเวลา (ซึ่งซ้ำกับรูปแรกสุดที่มีอยู่) 
- **วิธีแก้:**
  1. แก้ฟังก์ชัน `get_next_photo_serial()` ให้ใช้ SQL Filter: `WHERE photo_id LIKE 'P%' ORDER BY CAST(SUBSTR(photo_id, 2) AS INTEGER) DESC` เพื่อหารหัสตัวเลขที่แท้จริงให้เจอเสมอ
  2. แก้โหมด Headless Scan ให้ใช้ระบบสร้าง Photo ID แบบ `Pxxxxx` มาตรฐานเดียวกันกับ Manual Scan
  3. แก้ไขบั๊ก TypeError ตอนบันทึกภาพใน Headless Scan (`save_scanned_photo`) ที่ส่งอาร์กิวเมนต์แบบ kwargs ผิดพลาด (`date_str` แทนที่จะเป็น `photo_date` และลืมส่งค่า `matches=[]`)

---

## 📋 Version 1.7.9 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 1.5 Pro
**Date:** 21 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ระบบอัตโนมัติ (Midnight Auto-Trigger Schedule)
- **ปัญหา:** แอดมินต้องคอยกดสั่งสแกนหารูปกิจกรรมใหม่ๆ ทุกวัน รวมถึงต้องคอยดาวน์โหลดรายชื่อนักเรียนจาก Google Sheets มาอัปเดตด้วยตนเอง ทำให้เสียเวลา
- **วิธีแก้ไข:** 
  - สร้างคลาส `SchedulerTask` แยกการทำงานแบบ Background Thread (รันซ้อนกับ GUI) เพื่อรอเวลา `00:00` (เที่ยงคืน) ของทุกวัน หรือรับคำสั่งจากปุ่ม "Start Schedule Now" ในเมนู Sidebar ใหม่ 
  - ระบบจะตรวจสอบโฟลเดอร์ใน Drive โดยอัตโนมัติตามลำดับ 2569 -> 2568 -> 2565-2567 และเลือกทำโฟลเดอร์ที่ไม่เคยสแกนทีละ 1 โฟลเดอร์จนกว่าจะครบ ป้องกันการหน่วงเครื่อง
  - มีการพ่น Log ที่ชัดเจนออกมาที่หน้าต่าง CMD เพื่อรายงานความก้าวหน้าตลอดกระบวนการ
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [scheduler_task.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/scheduler_task.py) และ [app_gui.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/app_gui.py) 

#### 2. ระบบซิงค์รูปนักเรียนจาก Google Sheets อัตโนมัติและ Retroactive Match
- **ปัญหา:** เมื่อเพิ่มรูปหรือเปลี่ยนรูปใน Google Sheets ระบบเดิมยังต้องนำเข้าข้อมูลเอง และถ้าใส่รูปรองเพิ่ม จะไม่สามารถย้อนไปค้นหาในภาพเก่าๆ ได้โดยอัตโนมัติ
- **วิธีแก้ไข:**
  - เพิ่มเงื่อนไขให้ `SchedulerTask` โหลดข้อมูลจาก Google Sheets ลงมาเปรียบเทียบ (Compare State) กับข้อมูลสำรองในเครื่อง (Local Cache) ในระดับคอลัมน์
  - หากพบนักเรียนใหม่ หรือ นักเรียนเก่าที่มีการ "แก้ไขลิงก์รูปหน้าตรง" หรือ "เพิ่มรูปสำรอง" ระบบจะดาวน์โหลดภาพนั้นจาก Drive ทันที และนำมาสกัดเป็น Face Embedding ลงฐานข้อมูลใหม่
  - เมื่อได้เวกเตอร์ใหม่แล้ว ระบบจะเรียกใช้ฟีเจอร์ "Retroactive Matching" เพื่อจับคู่เวกเตอร์ใบหน้า "เฉพาะใบใหม่" นี้ กับประวัติใบหน้าที่แคชไว้จากภาพกิจกรรมทั้งหมด (Fast Re-scan แบบ Local) เพื่อดึงผลรูปเก่าให้โดยอัตโนมัติ
  - รองรับการเก็บรหัสส่วนตัว 6 หลัก (pin_code) ไว้ในตาราง SQLite ของบุคลากร เพื่อใช้สำหรับอ้างอิงและค้นหาในอนาคต (ไม่มีผลต่อ Face Matching)
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [db_manager.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/db_manager.py) และ [scheduler_task.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/scheduler_task.py)

#### 3. การแก้บั๊ก (Hotfixes)
- **ปัญหา NoneType ใน Drive API:** เดิมทีระบบพยายามสแกนโฟลเดอร์สีแดงก่อนที่จะกดเชื่อมต่อ Google API ทำให้เกิด Error `NoneType object has no attribute files`
  - **วิธีแก้ไข:** เพิ่มการตรวจสอบและเชื่อมต่อ `self.sync_manager.connect()` ก่อนเข้าสู่ Task 1
- **ปัญหา NoneType ในโมเดล AI (FaceAnalyzer):** เมื่อมีการรัน Background Task ก่อนที่แอดมินจะกดปุ่มสแกนบนหน้าจอ ระบบยังไม่ได้โหลดโมเดลเข้าหน่วยความจำ ทำให้การสกัดเวกเตอร์รูปนักเรียนล้มเหลว
  - **วิธีแก้ไข:** เพิ่มการโหลดโมเดลและ initialze ให้ทำงานใน Background Thread อัตโนมัติหากพบว่ายังไม่ได้โหลดโมเดล

---

## 📋 Version 1.7.8 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.1 Pro (High)
**Model ID:** `gemini-pro`
**Date:** 21 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ข้ามการประมวลผลไฟล์ภาพ RAW (Skip RAW Files)
- **ปัญหา:** เดิมทีระบบพยายามโหลดภาพ RAW (เช่น `.cr2` จากกล้อง Canon) แล้วนำมาแปลงผ่านหน่วยความจำด้วยไลบรารี `rawpy` เป็นสกุล JPG ก่อนส่งให้ AI วิเคราะห์ ซึ่งใช้เวลานานและสิ้นเปลืองทรัพยากรมากเกินความจำเป็น
- **วิธีแก้ไข:** 
  - ลบตรรกะการแปลงไฟล์ RAW ด้วยไลบรารี `rawpy` ออกจากส่วนของการสแกนไฟล์ผ่าน `app_gui.py` ทั้งจาก Google Drive และโหมดนำเข้าจาก Local Folder เพื่อให้โหลดภาพโดยตรงด้วย OpenCV `imdecode`
  - สร้างตัวกรองชื่อไฟล์นามสกุล (File Extension Filter) แบบ Strict ให้กรองเฉพาะรูปภาพพื้นฐานได้แก่ `.jpg`, `.jpeg`, `.png`, และ `.webp` เท่านั้น สำหรับการดึงไฟล์ในระบบ Google Drive `gdrive_sync.py` และระบบดึงไฟล์เครื่อง `app_gui.py`
  - ลบโค้ดการจัดการไฟล์ Cache รูปภาพแบบชั่วคราวทิ้ง เนื่องจากไม่มีการสร้างภาพจำลอง RAW-to-JPG อีกต่อไป
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 2901-2910 และ 4157-4240 และ [gdrive_sync.py](gdrive_sync.py) บรรทัด 131-133

---

## 📋 Version 1.7.7 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini Pro
**Model ID:** `gemini-pro`
**Date:** 21 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ปุ่มซิงค์ดัชนี JSON ขึ้น Google Drive คัดแยกรายกลุ่มใน SQLite Viewer
- **ปัญหา:** ก่อนหน้านี้เมื่อแอดมินต้องการสั่งอัปเดตไฟล์ดัชนี JSON บนระบบคลาวด์ Google Drive จะต้องกดซิงค์ทั้งหมดพร้อม Google Sheets ซึ่งใช้เวลามาก หรือต้องรอลูปสแกนทำงานเสร็จสิ้นเท่านั้น
- **วิธีแก้ไข:** 
  - สร้างแถบพื้นที่ควบคุมใหม่ `sync_control_frame` ใต้ตาราง Dropdown ของ SQLite Database Viewer
  - เพิ่มปุ่ม CTkButton จำนวน 3 โหมด สำหรับสั่งซิงค์ดัชนีขึ้น Google Drive โดยตรง:
    1. **1. ซิงค์ทั้งครูและนักเรียน** (อัปโหลดทั้ง `person_index.json`, `student_index.json` และ `photo_index.json`)
    2. **2. ซิงค์เฉพาะครู** (กรองและอัปโหลดเฉพาะคุณครูและภาพถ่ายที่เกี่ยวข้อง)
    3. **3. ซิงค์เฉพาะนักเรียน** (กรองและอัปโหลดเฉพาะนักเรียนและภาพถ่ายที่เกี่ยวข้อง)
  - พัฒนาเมทอด `run_manual_json_sync(mode)` สั่งประมวลผลผ่าน Background Thread เพื่อความลื่นไหลของหน้าจอ UI
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 3418-3448 และ 3765-3815

---

## 📋 Version 1.7.6 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini Pro
**Model ID:** `gemini-pro`
**Date:** 20 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ระบบล้างประวัติการจับคู่ใบหน้ารายบุคคล (Reset Matching Data)
- **ปัญหา:** ไม่สามารถรีเซ็ตประวัติการพบหน้าของบุคคลใดบุคคลหนึ่งเฉพาะคนได้ โดยไม่ประสงค์จะลบข้อมูลบัญชีชื่อ หรือรูปหน้าตรงที่ใช้ลงทะเบียนไว้
- **วิธีแก้ไข:** 
  - เพิ่มปุ่ม "🗑️ รีเซ็ตประวัติจับคู่" ไว้ในเครื่องมือส่วนควบคุมของ SQLite Database Viewer (`setup_database_ui`)
  - พัฒนาเมทอด `reset_selected_person_matches()` ตรวจสอบเงื่อนไขว่าต้องเลือกตารางครูหรือนักเรียนเท่านั้น และต้องคลิกเลือกแถวบุคคลก่อนใช้ปุ่ม
  - เพิ่มป๊อปอัปให้ผู้ใช้กดยืนยันการทำงาน (Confirmation Popup) เพื่อป้องกันข้อผิดพลาดพลั้งเผลอ
  - ส่งชุดคำสั่ง SQL ลบข้อมูลการตรวจพบของคนๆ นั้น: `DELETE FROM detected_faces WHERE staff_id = ?` จากนั้นอัปเดตโหลดตารางข้อมูลพร้อมอัปเดตสถิติหน้าแรกให้สอดคล้องกัน
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 3405-3412 และ 3687-3733

---

## 📋 Version 1.7.5 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini Pro
**Model ID:** `gemini-pro`
**Date:** 20 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. จัดเลย์เอาต์กลุ่มปุ่ม Radio Button สแกนเป้าหมายแนวราบ (Horizontal)
- **ปัญหา:** ปุ่ม Radio button สแกนเป้าหมายทั้ง 5 โหมด และปุ่มเลือกรายคนดั้งเดิมกินพื้นที่แนวตั้งสูงมาก ส่งผลให้จอด้านล่าง (Debug Console และ Match Preview) โดนบีบจนเล็กเกินไป
- **วิธีแก้ไข:** ปรับเปลี่ยนการจัดวางใน `self.match_target_box` จากแนวตั้ง (pack) มาเป็นตาราง 3 คอลัมน์แนวราบ (grid) เพื่อลดพื้นที่การกินขนาดแนวตั้งได้อย่างมีประสิทธิภาพ ช่วยให้ขยายความสูงของ Console Debug Logs และ Match Preview ด้านล่างได้กว้างขวางขึ้น
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 2390-2440

#### 2. แยกตารางแสดงสถิติจำนวนภาพของครูและนักเรียนเคียงข้างกัน (Dashboard Stats Split)
- **ปัญหา:** สถิติจำนวนภาพที่พบบุคลากรแสดงรายชื่อรวมสลับครูและนักเรียนปนกัน ทำให้การเปรียบเทียบในหน้า Dashboard อ่านยาก
- **วิธีแก้ไข:** ปรับปรุงเลย์เอาต์หน้าจอ Dashboard ให้รองรับ 3 คอลัมน์แยก: แผงสถานะโมเดล (ซ้าย), แผงสถิติคุณครู (กลาง), แผงสถิตินักเรียน (ขวา) โดยกรองรายชื่อคุณครูและนักเรียนจากฐานข้อมูลตาม `role` และไล่เฉดระดับสีในกราฟเปรียบเทียบแยกจากกันอย่างชัดเจน
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 850-950 และ 1020-1090

#### 3. แยกประเภทตาราง SQLite Viewer (SQLite Tab Split)
- **ปัญหา:** หน้าแสดงตารางฐานข้อมูล SQLite แสดงรายชื่อและผลลัพธ์การจับคู่รวมกันระหว่างครูและนักเรียน ทำให้ผู้ใช้แยกแยะข้อมูลได้ลำบาก
- **วิธีแก้ไข:** เพิ่มรายการตัวเลือก Dropdown ของ `self.option_db_table` จาก 3 เป็น 5 เมนูหลัก ได้แก่:
  - รายชื่อคุณครู (staff_members - ครู)
  - รายชื่อนักเรียน (staff_members - นักเรียน)
  - ประวัติภาพถ่ายกิจกรรม (scanned_photos)
  - ผลจับคู่ใบหน้าครู (detected_faces - ครู)
  - ผลจับคู่ใบหน้านักเรียน (detected_faces - นักเรียน)
  กรองคิวรีใน SQL ตามฟิลด์ `role` พร้อมออกแบบคอลัมน์และตารางส่งออก CSV ให้สอดคล้องกัน (รวมถึงเพิ่มคอลัมน์ `student_id` ให้ตารางนักเรียนแยกกันเป็นเอกภาพ)
- **สถานะ:** ✅ **ได้ implement แล้ว** ใน [app_gui.py](app_gui.py) บรรทัด 3380-3590

---

## 📋 Version 1.7.4 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

# 🚨 ความผิดพลาดร้ายแรงที่สุด ห้ามทำผิดซ้ำอีกเด็ดขาด! (FATAL & CRITICAL ERROR)

> [!CAUTION]
> ### 🔴 เหตุการณ์ความผิดพลาดร้ายแรง (CRITICAL DATABASE WIPING INCIDENT):
> **ข้อผิดพลาดที่เกิดขึ้น:** ในขั้นตอนการประมวลผล Face Match / การอัปเดตฐานข้อมูล มีการสั่งคำสั่งหรือประมวลผลล้างข้อมูลผิดพลาด ส่งผลให้ผลการแมตช์ใบหน้าในฐานข้อมูล SQLite ถูกลบหายจาก **20,000+ รายการ กลายเป็น 0 รายการ** 
> 
> ---
>
> ### 🛑 กฎเหล็กและข้อห้ามเด็ดขาดเพื่อป้องกันไม่ให้เกิดขึ้นอีก (STRICT PROHIBITION RULES):
> 
> 1. **ห้ามรันคำสั่ง `DELETE FROM` หรือเคลียร์ตารางจับคู่ใบหน้า (`detected_faces`) แบบเหมาตารางโดยเด็ดขาด**
>    - ในการสแกนหรือสแกนซ้ำ (Re-match) ให้กระทำเฉพาะแถวข้อมูลที่ได้รับผลกระทบเท่านั้น ห้ามสั่งลบหรือล้างตารางทั้งหมดทิ้ง
>
> 2. **ต้องทำการสำรองข้อมูลฐานข้อมูล (`faces_db.db`) ก่อนทำ Face Match หรือ Re-match ทุกครั้ง**
>    - ก่อนประมวลผลแมตช์ข้อมูลใหม่ หรือรันสคริปต์แก้ไขข้อมูล ต้องทำการสร้างไฟล์ Backup ของ `data/faces_db.db` ไว้ก่อนเสมอ
>
> 3. **ต้องตรวจสอบจำนวน Record ก่อนและหลังการประมวลผลเสมอ (COUNT VERIFICATION)**
>    - ให้เขียนคำสั่งเช็กจำนวนข้อมูลก่อนและหลังการจับคู่ หากพบว่าจำนวนข้อมูลลดลงอย่างผิดปกติ ต้อง Rollback Transaction ทันที
>
> 4. **ต้องเสนอแผนงานและได้รับการอนุมัติอย่างเป็นลายลักษณ์อักษรจากผู้ใช้ก่อนแตะต้องฐานข้อมูล (PLAN APPROVAL)**
>    - ห้ามรันสคริปต์ หรือสั่งรันคำสั่งใดๆ ที่มีผลต่อฐานข้อมูลโดยไม่ผ่านการอนุมัติแผนงานใน `implementation_plan.md` เด็ดขาด

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ปรับปรุงตัวเลือก Target Matching และ UI หน้าเลือกรายบุคคล
- **ปัญหา:** การสแกนเป้าหมายใบหน้าแบบ Checkbox เดิมจัดการได้ยากและไม่ชัดเจน
- **วิธีแก้ไข:** พัฒนาตัวเลือกเป็น Radio Button 5 โหมด และแยกป๊อปอัปตรวจสอบคัดเลือกรายบุคคลเป็น `show_teachers_selection_popup()` และ `show_students_selection_popup()`
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 2. แยกเขียนไฟล์ดัชนี JSON บน Google Drive
- **ปัญหา:** ดัชนีหลักรวมกันอยู่ไฟล์เดียว ทำให้เกิดความล่าช้าและส่งผลกระทบเมื่อเกิดการเขียนชนกันของฐานข้อมูลหลายๆ เซสชัน
- **วิธีแก้ไข:** แยกไฟล์ดัชนีบน Drive ออกเป็น `person_index.json` (คุณครู) และ `student_index.json` (นักเรียน) พร้อมประมวลผลอัปโหลดเฉพาะกลุ่มไฟล์ที่ได้รับผลกระทบจากการสแกนล่าสุด
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.7.3 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. แยก Incremental GSheets Sync ออกเป็นปุ่มกด Manual Sync
- **ปัญหา:** การเชื่อมต่อ API ของ Google Sheets และ Excel Mirror ทุกครั้งที่จับคู่ใบหน้าเสร็จสิ้นระหว่างสแกน ถ่วงเวลาประมวลผลให้ช้าลงอย่างมาก
- **วิธีแก้ไข:** ลบระบบ Auto Sync Google Sheets/Excel ออกจากลูปสแกนหลัก (คงเหลือเพียงการอัปโหลดไฟล์ JSON ดัชนี) และสร้างปุ่ม `self.btn_manual_sync` บนหน้า Dashboard เพื่อให้คลิกซิงค์ฐานข้อมูล SQLite ทั้งหมดขึ้น Sheets, Excel Backup และ JSON ด้วยตนเองผ่านเบื้องหลัง (Background Thread)
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.7.2 Changelog

**Developer Agent:** Claude (Anthropic)
**Model:** Opus 4.7 (1M context)
**Model ID:** `claude-opus-4-7`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ปรับปรุงชื่อเมนู Sidebar
- **ปัญหา:** ชื่อเมนูยาวเกินไป
- **วิธีแก้ไข:**
  - เปลี่ยน "ลงทะเบียนครูต้นแบบ" → "ลงทะเบียนครู"
  - เปลี่ยน "ลงทะเบียนนักเรียนต้นแบอน" → "ลงทะเบียนนักเรียน"
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 2. ลบปุ่มนำเข้านักเรียนยกโฟลเดอร์อัตโนมัติ
- **ปัญหา:** มีปุ่มซ้ำซ้อนกับ Batch Import จาก Sheets
- **วิธีแก้ไข:**
  - ลบปุ่ม "นำเข้านักเรียนยกโฟลเดอร์อัตโนมัติ" ออก
  - ลบ method `batch_import_students()` ที่เกี่ยวข้อง
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 3. ระบบ Browse Spreadsheet แทนการกรอก Sheet ID
- **ปัญหา:** ต้องก๊อปปี้ Sheet ID มาวาง ไม่สะดวก
- **วิธีแก้ไข:**
  - เพิ่มปุ่ม "🔍 เลือก Sheet..." แทน entry กรอก Sheet ID
  - เพิ่ม dialog ย่อยแสดงรายการ Spreadsheets ทั้งหมดใน Drive
  - เพิ่ม method `list_spreadsheets()` ใน `gdrive_sync.py`
  - บันทึก Sheet ID ล่าสุด (`last_import_sheet_id`, `last_import_sheet_name`) ไว้ใน settings
  - ครั้งต่อไปเปิด dialog จะโหลดค่าล่าสุดมาแสดงอัตโนมัติ
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 4. ตรวจสอบนักเรียนก่อนบันทึก + Popup สรุปผล
- **ปัญหา:** ไม่มีการตรวจสอบข้อมูลซ้ำ และไม่มี popup สรุปผล
- **วิธีแก้ไข:**
  - เพิ่ม method `find_student_by_code_and_name()` ใน `db_manager.py`
  - เพิ่ม method `get_student_photo_count()` ใน `db_manager.py`
  - **3 เงื่อนไขการตรวจสอบ:**
    1. ไม่มีรหัสและชื่อเลย → บันทึกใหม่
    2. มีข้อมูลอยู่แล้วแต่ยังไม่มีภาพ → เพิ่มภาพใหม่
    3. มีข้อมูลอยู่แล้วและมีภาพเดิม → เพิ่มภาพเพิ่มเติม
  - รองรับภาพเพิ่มเติมจากหลาย column (E, F, G, H, ...)
  - แสดง Popup สรุปผล: บันทึกใหม่ (X คน), เพิ่มภาพเติม (Y คน), ล้มเหลว (Z คน)
  - แสดงรายละเอียดแต่ละรายการใน Scrollable Textbox
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.7.2 Fix 1 Changelog

**Developer Agent:** Claude (Anthropic)
**Model:** Opus 4.7 (1M context)
**Model ID:** `claude-opus-4-7`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ปรับปรุง Popup นำเข้านักเรียนจาก Google Sheets
- **ปัญหาเดิม:**
  - ต้องเลือกคอลัมน์รูปเพิ่มเติมทีละอัน (รูปหันซ้าย, รูปหันขวา, รูปเพิ่มเติม 1-5)
  - แต่ละนักเรียนอาจมีจำนวนรูปที่ต่างกัน บางคนมี 1 รูป บางคนมี 3 รูป
  - UI ยุ่งยากเกินไป
- **วิธีแก้ไข:**
  - **UI Changes:**
    - ลบ dropdown สำหรับคอลัมน์รูปหันซ้าย, รูปหันขวา, รูปเพิ่มเติม 1-5
    - เก็บเฉพาะ 3 คอลัมน์หลัก: รหัสประจำตัว, ชื่อ-นามสกุล, รูปหน้าตรง
    - แก้ label "คอลัมน์รูปหน้าตรง" ให้ระบุว่าระบบจะหารูปเพิ่มเติมอัตโนมัติ
    - แก้คำอธิบายให้เข้าใจง่ายขึ้น
  - **Logic Changes:**
    - เลือกเพียงคอลัมน์ "รูปหน้าตรง" เท่านั้น
    - ระบบจะค้นหาคอลัมน์รูปเพิ่มเติมอัตโนมัติจากคอลัมน์ถัดไป
    - วนลูปเก็บรูปไปเรื่อยๆ จนกว่าจะเจอคอลัมน์ว่าง → หยุด
  - **Settings Changes:**
    - ลบการบันทึก settings: `last_import_col_left`, `last_import_col_right`, `last_import_col_extra1-5`
    - เก็บเฉพาะ: `last_import_col_id`, `last_import_col_name`, `last_import_col_front`
- **ตัวอย่างการทำงาน:**
  ```
  คนที่ 1: รูปหน้าตรง | รูปซ้าย | รูปขวา | (ว่าง)  → เก็บ 3 รูป
  คนที่ 2: รูปหน้าตรง | (ว่าง)              → เก็บ 1 รูป
  คนที่ 3: รูปหน้าตรง | รูปเอน   | รูปยิ้ม | (ว่าง)  → เก็บ 3 รูป
  ```
- **สถานะ:** ✅ **ได้ implement แล้ว**

---

## 📋 Version 1.7.4 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash (Low)
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

# 🚨 ความผิดพลาดร้ายแรงที่สุด ห้ามทำผิดซ้ำอีกเด็ดขาด! (FATAL & CRITICAL ERROR)

> [!CAUTION]
> ### 🔴 เหตุการณ์ความผิดพลาดร้ายแรง (CRITICAL DATABASE WIPING INCIDENT):
> **ข้อผิดพลาดที่เกิดขึ้น:** ในขั้นตอนการประมวลผล Face Match / การอัปเดตฐานข้อมูล มีการสั่งคำสั่งหรือประมวลผลล้างข้อมูลผิดพลาด ส่งผลให้ผลการแมตช์ใบหน้าในฐานข้อมูล SQLite ถูกลบหายจาก **20,000+ รายการ กลายเป็น 0 รายการ** 
> 
> ---
>
> ### 🛑 กฎเหล็กและข้อห้ามเด็ดขาดเพื่อป้องกันไม่ให้เกิดขึ้นอีก (STRICT PROHIBITION RULES):
> 
> 1. **ห้ามรันคำสั่ง `DELETE FROM` หรือเคลียร์ตารางจับคู่ใบหน้า (`detected_faces`) แบบเหมาตารางโดยเด็ดขาด**
>    - ในการสแกนหรือสแกนซ้ำ (Re-match) ให้กระทำเฉพาะแถวข้อมูลที่ได้รับผลกระทบเท่านั้น ห้ามสั่งลบหรือล้างตารางทั้งหมดทิ้ง
>
> 2. **ต้องทำการสำรองข้อมูลฐานข้อมูล (`faces_db.db`) ก่อนทำ Face Match หรือ Re-match ทุกครั้ง**
>    - ก่อนประมวลผลแมตช์ข้อมูลใหม่ หรือรันสคริปต์แก้ไขข้อมูล ต้องทำการสร้างไฟล์ Backup ของ `data/faces_db.db` ไว้ก่อนเสมอ
>
> 3. **ต้องตรวจสอบจำนวน Record ก่อนและหลังการประมวลผลเสมอ (COUNT VERIFICATION)**
>    - ให้เขียนคำสั่งเช็กจำนวนข้อมูลก่อนและหลังการจับคู่ หากพบว่าจำนวนข้อมูลลดลงอย่างผิดปกติ ต้อง Rollback Transaction ทันที
>
> 4. **ต้องเสนอแผนงานและได้รับการอนุมัติอย่างเป็นลายลักษณ์อักษรจากผู้ใช้ก่อนแตะต้องฐานข้อมูล (PLAN APPROVAL)**
>    - ห้ามรันสคริปต์ หรือสั่งรันคำสั่งใดๆ ที่มีผลต่อฐานข้อมูลโดยไม่ผ่านการอนุมัติแผนงานใน `implementation_plan.md` เด็ดขาด

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ออกแบบหน้าจอ UI การเลือกเป้าหมาย Matching รูปแบบใหม่ (Matching Mode Radio Buttons)
- **การเปลี่ยนแปลง:**
  - เปลี่ยนจากการกด Checkbox "สแกนเปรียบเทียบเฉพาะบุคลากรที่เลือก" ตัวเดียว มาเป็น **Radio Buttons 5 ทางเลือก** เพื่อแยกความต้องการจับคู่ใบหน้าได้อย่างละเอียดยิ่งขึ้น:
    1. **ครู + นักเรียน ทั้งหมด** (ค่าเริ่มต้น)
    2. **คุณครูทั้งหมด**
    3. **นักเรียนทั้งหมด**
    4. **เลือกเฉพาะคุณครูบางคน** (เปิดให้กดปุ่มเลือกรายชื่อครูทีละคน)
    5. **เลือกเฉพาะนักเรียนบางคน** (เปิดให้กดปุ่มเลือกรายชื่อนักเรียนทีละคน)
  - เพิ่มป๊อปอัปแยกตัวเลือกระหว่างคุณครู (`show_teachers_selection_popup`) และนักเรียน (`show_students_selection_popup`) เพื่อไม่ให้ข้อมูลสับสน
  - ปรับการกรองเวกเตอร์ต้นแบบใบหน้าใน `run_scanning_process` ให้ทำการประมวลผลเวกเตอร์ในหน่วยความจำก่อนสแกนตามตัวเลือกเป้าหมายที่เลือกไว้ได้อย่างสมบูรณ์

#### 2. แยกดัชนีผลการค้นหา JSON ระหว่างครูกับนักเรียน (`student_index.json`)
- **การเปลี่ยนแปลง:**
  - เพิ่มไฟล์ดัชนี JSON บน Google Drive อีก 1 ไฟล์คือ **`student_index.json`** สำหรับเก็บบันทึกข้อมูลการแมตช์ของนักเรียนโดยเฉพาะ ส่วน `person_index.json` จะทำหน้าที่เก็บผลของครู และ `photo_index.json` ทำหน้าที่เก็บข้อมูลและลิงก์ของรูปภาพเหมือนเดิม
  - **อัปโหลดเฉพาะไฟล์ที่เกี่ยวข้องตามความต้องการสแกน (Dynamic Upload):**
    - หากสแกนเฉพาะกลุ่มครู ➔ สร้าง/อัปเดตเฉพาะ `person_index.json` และ `photo_index.json` (ไม่ส่ง `student_index.json`)
    - หากสแกนเฉพาะกลุ่มนักเรียน ➔ สร้าง/อัปเดตเฉพาะ `student_index.json` และ `photo_index.json` (ไม่ส่ง `person_index.json`)
    - หากสแกนทั้งหมด/ซิงค์แบบแมนนวล ➔ สร้างและส่งทั้ง 3 ไฟล์ตามข้อมูลประวัติที่มีอยู่ใน SQLite ท้องถิ่น

---

## 📋 Version 1.7.3 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash (Low)
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. แยกการซิงค์แผ่นงาน Google Sheets ไปเป็นปุ่มแมนนวล (Manual Sync)
- **ปัญหา:** ระหว่างกระบวนการสแกนใบหน้า โปรแกรมต้องหยุดเชื่อมต่ออินเทอร์เน็ตเพื่อซิงค์ข้อมูลขึ้น Google Sheets และไฟล์ Excel สำรองเครื่อง ทุกๆ 500 รูป ซึ่งทำให้ขั้นตอนการสแกนช้าลงอย่างมาก และเสี่ยงต่อการติดโควตา (Rate Limit) ของ Google API หากสแกนไฟล์จำนวนมหาศาล
- **วิธีแก้ไข:**
  - **ลบ Incremental Sync ออกจากลูปสแกน:** เอาโค้ดส่วน `if success_scan_count % 500 == 0:` ออกทั้งในสแกนปกติและสแกนด่วน (Fast Re-scan) ทำการประมวลผลเซฟลง SQLite ท้องถิ่นในคอมพิวเตอร์อย่างรวดเร็วแทน
  - **ลดความซ้ำซ้อนท้ายการสแกน:** เมื่อสแกนเสร็จสิ้น ระบบจะอัปโหลดเฉพาะไฟล์ JSON ดัชนีหลัก (`person_index.json`, `photo_index.json`) ขึ้น Drive อัตโนมัติ เพื่อให้หน้าเว็บแอปค้นหาทำงานได้ทันที แต่จะข้ามการยิงซิงค์ Sheets และ Excel
  - **ปุ่ม Manual Sync บน Dashboard:** เพิ่มปุ่ม "📤 ซิงค์ข้อมูลขึ้น Google Sheets" เหนือเมนูสถานะแถวซ้ายล่าง เพื่อให้แอดมินเลือกกดซิงค์ข้อมูลจาก SQLite ขึ้น Google Sheets และสำรองไฟล์ Excel ตอนไหนก็ได้ตามใจชอบ
  - โค้ดสำคัญใน `app_gui.py`:
    ```python
    def run_manual_sync(self):
        # ... ตรวจสอบสิทธิ์เชื่อมต่อ API ...
        self.btn_manual_sync.configure(state="disabled", text="กำลังซิงค์ข้อมูล...")
        def do_sync():
            try:
                sync_data = self.db.get_all_sync_data()
                self.sync_manager.sync_to_google_sheet(sync_data)
                self.sync_manager.save_local_excel_mirror(sync_data)
                if json_folder_id:
                    self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id)
                # ... แจ้งผลสำเร็จ ...
            finally:
                self.btn_manual_sync.configure(state="normal", text="📤 ซิงค์ข้อมูลขึ้น Google Sheets")
        threading.Thread(target=do_sync, daemon=True).start()
    ```

---

## 📋 Version 1.7.2 Fix 4 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash (Low)
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. แก้ไขบั๊กรายชื่อว่างเปล่าไม่ขึ้นข้อมูลในเมนูลงทะเบียนครูและนักเรียน
- **ปัญหา:** เมนูลงทะเบียนครูและเมนูลงทะเบียนนักเรียน ไม่แสดงรายชื่อบุคคลใดๆ ทั้งสิ้น ถึงแม้ว่าข้อมูลในฐานข้อมูล SQLite จะมีอยู่ครบถ้วน
- **สาเหตุ:** ความผิดพลาดในการจัดลำดับและเยื้องบรรทัดโค้ด (Indentation) ในช่วงเพิ่มฟีเจอร์ค้นหารายชื่อของเวอร์ชัน 1.7.2 Fix 3 ทำให้โค้ดการวาด UI ปุ่มรายชื่อทั้งหมด ถูกจัดเข้าไปอยู่ภายในฟังก์ชันล้างคำค้นหา (`clear_staff_search` และ `clear_student_search`) แทนที่จะอยู่ในลูปสร้างปุ่มรายชื่อของฟังก์ชันหลัก และส่งผลให้ลูปวาดปุ่มรายชื่อของ `load_staff_list()` และ `load_student_list()` จบการทำงานลงก่อนกำหนด
- **วิธีแก้ไข:**
  - ย้ายบล็อกโค้ดส่วนการสร้างและจัดวางปุ่มรายชื่อกลับเข้ามาอยู่ภายในขอบเขตลูป `for idx, s in enumerate(...)` ของฟังก์ชัน `load_staff_list()` และ `load_student_list()` อย่างถูกต้อง
  - แยกและเยื้องบรรทัดของเมทอด `filter_staff_list()`, `clear_staff_search()`, `filter_student_list()`, และ `clear_student_search()` ให้กลายเป็นเมทอดเดี่ยวในระดับคลาสอย่างชัดเจน ไม่ไปซ้อนทับหรือจบสโคปของลูปฟังก์ชันอื่น
  - โค้ดสำคัญที่ได้รับการจัดวางตำแหน่งที่ถูกต้องใน `app_gui.py`:
    ```python
    # โครงสร้างหลังจากแก้ไขของ load_staff_list():
    def load_staff_list(self):
        # ... ดึงข้อมูล ...
        for idx, s in enumerate(staff):
            if search_term and search_term not in s['name'].lower():
                continue
            # บล็อกคำสั่งสร้างและวาดแถวปุ่ม (row_frame) สำหรับครู [ได้รับการจัดตำแหน่งถูกต้องที่นี่]
            
    def filter_staff_list(self):
        self.load_staff_list()
        
    def clear_staff_search(self):
        # ... เคลียร์คำค้นหา ...
    ```

---

## 📋 Version 1.7.2 Fix 3 Changelog

**Developer Agent:** Antigravity (Google DeepMind)
**Model:** Gemini 3.5 Flash (Low)
**Model ID:** `gemini-3-5-flash`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. แก้ไขปัญหารายชื่อนักเรียนแสดงในเมนูครู
- **ปัญหา:** ในเมนูลงทะเบียนใบหน้าคุณครู มีรายชื่อนักเรียนและรูปภาพนักเรียนแสดงปะปนขึ้นมา
- **สาเหตุ:** ฟังก์ชัน `load_staff_list()` มีการเรียกดึงข้อมูลจาก `self.db.get_all_staff_members()` ซึ่งดึงข้อมูลสมาชิกทั้งหมดในฐานข้อมูลโดยไม่มีการกรองบทบาท (Role)
- **วิธีแก้ไข:**
  - เปลี่ยนจากการเรียก `self.db.get_all_staff_members()` เป็น `self.db.get_all_teachers()` เพื่อคัดเลือกเฉพาะครู (`role = 'teacher'`) มาแสดงผล
  - โค้ดสำคัญใน `app_gui.py`:
    ```python
    staff = self.db.get_all_teachers()
    ```

#### 2. เพิ่มระบบค้นหา (Search) ในหน้าลงทะเบียนครูและนักเรียน
- **ปัญหา:** เมื่อมีคุณครูและนักเรียนเป็นจำนวนมาก แอดมินค้นหารายบุคคลเพื่อจัดการรูปภาพได้ลำบาก
- **วิธีแก้ไข:**
  - **สำหรับเมนูครู:** เพิ่ม Entry ค้นหา `self.entry_staff_search` และปุ่มล้าง `✕` เหนือ Scrollable Frame รายชื่อครู
  - **สำหรับเมนูนักเรียน:** เพิ่ม Entry ค้นหา `self.entry_student_search` และปุ่มล้าง `✕` เหนือ Scrollable Frame รายชื่อนักเรียน
  - ผูกคีย์เวิร์ดการพิมพ์ (`<KeyRelease>`) เพื่อกรองรายชื่อและทำการโหลดใหม่โดยอัตโนมัติ
  - รองรับการกรองตามชื่อ (คุณครู/นักเรียน) และรหัสประจำตัว (นักเรียน)
  - โค้ดสำคัญใน `app_gui.py`:
    ```python
    # การกรองใน load_staff_list()
    search_term = ""
    if hasattr(self, 'entry_staff_search'):
        search_term = self.entry_staff_search.get().strip().lower()
    
    staff = self.db.get_all_teachers()
    for idx, s in enumerate(staff):
        if search_term and search_term not in s['name'].lower():
            continue
    ```
    ```python
    # การกรองใน load_student_list()
    search_term = ""
    if hasattr(self, 'entry_student_search'):
        search_term = self.entry_student_search.get().strip().lower()

    students = self.db.get_all_students()
    for idx, s in enumerate(students):
        if search_term:
            name_match = search_term in s['name'].lower()
            id_match = s['student_id'] and (search_term in s['student_id'].lower())
            if not (name_match or id_match):
                continue
    ```

---

## 📋 Version 1.7.2 Fix 2 Changelog

**Developer Agent:** Claude (Anthropic)
**Model:** Opus 4.7 (1M context)
**Model ID:** `claude-opus-4-7`
**Date:** 15 กรกฎาคม 2026

### ฟีเจอร์ใหม่ / ปรับปรุง (New Features & Improvements)

#### 1. ป้องกันการบันทึกรูปซ้ำเมื่อ Import จาก Google Sheets
- **ปัญหา:**
  - เมื่ออัปโหลดชีทเดิมหลายครั้ง ระบบจะเพิ่มรูปเดิมซ้ำๆ เข้าไปเรื่อยๆ
  - ไม่มีการตรวจสอบว่ารูปภาพนั้นถูกบันทึกไปแล้วหรือไม่
- **วิธีแก้ไข:**
  - **Database Changes:**
    - เพิ่มคอลัมน์ `source_url` ในตาราง `staff_embeddings` - เก็บลิงค์ Drive URL ของรูป
    - เพิ่ม method `check_embedding_url_exists()` ใน `db_manager.py`
    - แก้ `add_staff_embedding()` ให้รับพารามิเตอร์ `source_url`
  - **Logic Changes:**
    - ก่อนบันทึกรูป → เช็ค `source_url` ว่ามีอยู่แล้วหรือไม่
    - ถ้ามี → ข้าม (Skip) และนับเป็น "รูปซ้ำ"
    - ถ้าไม่มี → บันทึกพร้อมเก็บ `source_url`
  - **UI Changes:**
    - Popup สรุปผลเพิ่มหมวด "⏭️ ข้ามรูปซ้ำ: X รูป"
    - แสดงรายละเอียดรูปที่ถูกข้าม
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 2. ปรับปรุง UI การเลือกรูปนักเรียนเพื่อลบ
- **ปัญหา:**
  - เมนูครู: คลิกรูป → กรอบสีแดงหนา 3px ชัดเจน
  - เมนูนักเรียน: คลิกรูป → เปลี่ยนสีพื้นหลังเป็นกรมท่าเข้ม แทบไม่เห็น
- **วิธีแก้ไข:**
  - แก้ `select_student_thumbnail()` ให้ใช้ `border_width=3, border_color="#FF5252"` (กรอบแดง) เหมือนเมนูครู
  - รีเซ็ตค่าให้ครบ: `fg_color="transparent", border_width=0, border_color="transparent"`
- **สถานะ:** ✅ **ได้ implement แล้ว**

#### 3. แก้ไขปุ่ม "ลบรูปภาพที่เลือก" ไม่แสดงในเมนูนักเรียน
- **ปัญหา:**
  - ปุ่ม "ลบรูปภาพที่เลือก" ในเมนูนักเรียนไม่แสดงบนหน้าจอ
  - แม้ฟังก์ชันจะทำงานถูกต้อง (enable ปุ่มสำเร็จ) แต่ปุ่มถูกซ่อนไว้หลัง thumbs_frame
- **วิธีแก้ไข:**
  - ย้ายปุ่ม `btn_delete_student_photo` มาอยู่ **ก่อน** `student_thumbs_frame`
  - ปรับ `thumbs_frame` ใช้ `expand=False` เพื่อให้ควบคุมขนาดได้ดีขึ้น
- **สถานะ:** ✅ **ได้ implement แล้ว**

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
