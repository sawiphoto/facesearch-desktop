# ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v1.7.2 Fix 4

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
