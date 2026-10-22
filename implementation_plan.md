# แผนงานการเพิ่มระบบสร้างและ Sync ดัชนีภาพกิจกรรมในอดีต (2562-25xx) ใน Task 1 พร้อมปุ่มกดแยกในหน้าตั้งค่าโฟลเดอร์ (v6.49)

## 📌 1. วัตถุประสงค์และความต้องการ (Objectives & Requirements)
1. **ผูกการทำงานไว้ใน Task 1 โดยตรง (Direct Integration into Task 1 Scan):**
   - ในการทำงานของ **Task 1: สแกนรูปภาพกิจกรรมใหม่ (`_task_1_scan_new_photos_fast`)**:
     - เมื่อระบบวนลูปสแกนโฟลเดอร์ตามปีการศึกษา และเข้าสู่โฟลเดอร์ **"ภาพกิจกรรม 2562- 25xx ในอดีต"** (Folder ID: `1seCE5Uh5pvvKXiYeP8479wNynF2ZEYe1` / Academic Year: `25xx`)
     - ระบบจะตรวจจับใบหน้าทั้งหมดในรูปภาพ และบันทึกพิกัดใบหน้า (`bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2`) ลงในตาราง `scanned_photo_faces`
   - **ตอนซิงค์ดัชนีของ Task 1:** หากตรวจพบว่ามีภาพในโฟลเดอร์เก่านี้ (ไม่ว่าจะสแกนใหม่หรือมีอยู่ในระบบแล้ว) ให้เรียกฟังก์ชันสร้างและอัปโหลดไฟล์ **`archive_crowdsource_index.json`** ขึ้น Google Drive (`json_folder_id`) ควบคู่ไปกับไฟล์ดัชนีปกติทันที
   - หากไม่มีภาพในโฟลเดอร์นี้ ให้ข้ามไปอย่างปลอดภัยโดยไม่ส่งผลกระทบต่อ Task อื่นๆ
2. **เพิ่มปุ่มกดซิงค์ JSON เฉพาะโฟลเดอร์นี้แยกต่างหากในหน้าตั้งค่าโฟลเดอร์ (Dedicated Sync Button in GUI):**
   - ในหน้า **ตั้งค่าโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders)**:
   - เพิ่มปุ่มกด **`⚡ ซิงค์ JSON ภาพอดีต`** (สีส้ม/แอมเบอร์เด่นชัด) ที่แถวของโฟลเดอร์ภาพกิจกรรมในอดีต (`25xx`) และในแถบเครื่องมือ
   - เมื่อผู้ใช้กดปุ่มนี้ ระบบจะทำงานใน **Background Daemon Thread** (หน้าจอ GUI ลื่นไหล ไม่ค้าง ไม่ Lag) เพื่อดึงข้อมูลพิกัดใบหน้าทั้งหมดของภาพในอดีต แปลงเป็นเปอร์เซ็นต์ และอัปโหลดไฟล์ `archive_crowdsource_index.json` ขึ้น Google Drive พร้อมแสดงข้อความแจ้งเตือนผลลัพธ์
3. **รักษาการ Sync ดัชนีเดิมตามปกติ (Zero Impact to Existing Sync):**
   - ไฟล์ดัชนีหลักทั้งหมด (`staff_index.json`, `former_staff_index.json`, `student_index_active.json`, `student_index_alumni.json`, `photo_index_YYYY.json`, `photo_manifest.json`, `person_index.json`, `photo_index.json`, `student_index.json`) ยังคงทำงานและถูกอัปโหลดขึ้น Google Drive ครบถ้วน 100%
4. **โครงสร้างข้อมูลใน `archive_crowdsource_index.json`:**
   - **ไม่มีข้อมูลชื่อหรือตำแหน่งของบุคคล** (เพราะเป็นภาพเก่าในอดีต 40 ปีก่อน และต้องการให้ผู้ใช้งานบนเว็บเป็นผู้ระบุชื่อ/Crowdsourcing Tagging)
   - ประกอบด้วยรายการรูปภาพทั้งหมดในโฟลเดอร์นี้
   - ในแต่ละรูปภาพ มีข้อมูลพิกัดใบหน้าทั้งหมดที่ระบบเคยสแกนตรวจพบ (`scanned_photo_faces`):
     - `face_index`: ลำดับใบหน้า (0, 1, 2, ...) สำหรับเชื่อมโยง
     - `center_pct`: พิกัดจุดกึ่งกลางและรัศมีวงกลมในหน่วยเปอร์เซ็นต์ (`x`, `y`, `r`) สำหรับให้เว็บทำ Hover วงกลมชี้ตำแหน่งในภาพทันที
     - `box_pct`: พิกัดกรอบสี่เหลี่ยมในหน่วยเปอร์เซ็นต์ (`left`, `top`, `width`, `height`) สำหรับให้เว็บใช้ CSS/Canvas ตัดรูปทำเป็น Avatar เรียงกันใต้ภาพ
     - `box_px`: พิกัดพิกเซลเดิม `[x1, y1, x2, y2]`
     - `tagged_name`: ชื่อที่มีคนระบุ (ค่าเริ่มต้นเป็น `null` พร้อมให้เว็บส่งบันทึกชื่อ)
5. **ลงทะเบียนในสารบัญหลัก (`photo_manifest.json`):**
   - เพิ่มคีย์ `"archive_crowdsource_file": "archive_crowdsource_index.json"` ใน `photo_manifest.json` เพื่อให้หน้าเว็บทราบและดึงไปใช้งานได้ทันที

---

## 🏗️ 2. ขั้นตอนการดำเนินงานทีละข้ออย่างละเอียด (Step-by-Step Implementation Plan)

### ขั้นตอนที่ 1: พัฒนาฟังก์ชันสกัดข้อมูลใน [db_manager.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/db_manager.py)
- เพิ่มเมธอด `get_archive_crowdsource_data(academic_year="25xx")` ในคลาส `DatabaseManager`:
  1. ดึงข้อมูลรูปภาพจากตาราง `scanned_photos` ที่มี `academic_year = '25xx'`
  2. ดึงข้อมูลพิกัดใบหน้าทั้งหมดของรูปภาพเหล่านี้จากตาราง `scanned_photo_faces` (โดยกรองเฉพาะ `face_index >= 0`)
  3. คำนวณหาขนาดภาพ (Width, Height) และแปลงพิกัดพิกเซล `[bbox_x1, bbox_y1, bbox_x2, bbox_y2]` ให้เป็นเปอร์เซ็นต์:
     - `box_pct`: `{ "left": round(x1/w*100, 2), "top": round(y1/h*100, 2), "width": round((x2-x1)/w*100, 2), "height": round((y2-y1)/h*100, 2) }`
     - `center_pct`: `{ "x": round((x1+x2)/2/w*100, 2), "y": round((y1+y2)/2/h*100, 2), "r": round(max(w_pct, h_pct)*0.65, 2) }`
  4. ประกอบเป็นโครงสร้าง JSON ที่สะอาด สมบูรณ์ และมีขนาดกะทัดรัด

### ขั้นตอนที่ 2: ปรับปรุงระบบ Sync ใน [gdrive_sync.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/gdrive_sync.py) และ [scheduler_task.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/scheduler_task.py)
- ในฟังก์ชัน `update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")`:
  1. ตรวจสอบว่ามีข้อมูลรูปภาพในอดีต `25xx` หรือไม่ หากมีให้ดึงข้อมูลผ่าน `db.get_archive_crowdsource_data("25xx")`
  2. อัปโหลดไฟล์ `archive_crowdsource_index.json` ไปยัง `json_folder_id` บน Google Drive ผ่านฟังก์ชัน `upload_overwrite_json`
  3. ปรับปรุง `manifest` ใน `photo_manifest.json` ให้ระบุ `"archive_crowdsource_file": "archive_crowdsource_index.json"` และระบุจำนวนรูปภาพในอดีต
- ใน **Task 1** ของ [scheduler_task.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/scheduler_task.py):
  - ตรวจสอบให้มั่นใจว่าเมื่อสแกนภาพในโฟลเดอร์ภาพกิจกรรม 2562-25xx ในอดีต และในจังหวะ Sync ดัชนีหลังจบ Task 1 (`_sync_all_json_to_drive`) จะมีการกระตุ้นการสร้างและซิงค์ `archive_crowdsource_index.json` ขึ้น Google Drive เสมอ

### ขั้นตอนที่ 3: เพิ่มปุ่มกดซิงค์แยกและเมธอดควบคุมใน [app_gui.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/app_gui.py)
- เพิ่มฟังก์ชัน `sync_archive_crowdsource_json_manual()`:
  - ทำงานใน Background Daemon Thread
  - ดึงข้อมูลจากฐานข้อมูล และส่งให้อัปโหลดขึ้น Google Drive
  - อัปเดต Log และแสดง `messagebox.showinfo` แจ้งความสำเร็จ
- เพิ่มปุ่ม `⚡ ซิงค์ JSON ภาพอดีต` ในการ์ดแสดงผลของโฟลเดอร์ `25xx` ในตารางโฟลเดอร์หลักประจำปีการศึกษา

### ขั้นตอนที่ 4: พัฒนาชุดทดสอบความถูกต้อง (Execution Path Runtime Verification)
- สร้างไฟล์ทดสอบ [test_archive_crowdsource_sync.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/tests/test_archive_crowdsource_sync.py):
  - **TC-151:** ทดสอบการดึงข้อมูล `get_archive_crowdsource_data("25xx")` ว่าได้ข้อมูลครบถ้วนทั้ง 202 รูป และค่าเปอร์เซ็นต์ (`box_pct`, `center_pct`) อยู่ในช่วง `0.0 - 100.0%` เสมอ
  - **TC-152:** ตรวจสอบโครงสร้างไฟล์ JSON ว่าไม่มีข้อมูลชื่อหรือตำแหน่งของบุคคลหลุดไป (Privacy & Tagging Readiness)
  - **TC-153:** ทดสอบการเชื่อมโยงใน `photo_manifest.json` ว่ามีฟิลด์ `archive_crowdsource_file` ครบถ้วน
  - **TC-154:** ทดสอบ Task 1 Sync Path จำลองว่าเมื่อมีภาพ `25xx` ระบบจะกระตุ้นการซิงค์ไฟล์นี้อย่างถูกต้อง
  - **TC-155:** ทดสอบปุ่ม Manual Sync ใน GUI ว่าทำงานแบบ Daemon Thread โดยไม่บล็อก Main Thread

### ขั้นตอนที่ 5: อัปเดตบันทึกประวัติและเวอร์ชันระบบ
- อัปเดตเลขเวอร์ชันระบบเป็น `v6.49 (Task 1 Archive Historical Crowdsource Face Sync Suite)`:
  - อัปเดตใน [app_gui.py](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/app_gui.py) (Title bar และ Sidebar Logo)
  - บันทึกรายละเอียดการเปลี่ยนแปลงทั้งหมดลงบนสุดของไฟล์ [README.md](file:///d:/Projects/07%20ระบบค้นหาใบหน้าบุคลากรโรงเรียน/README.md) ตามกฎ Prepend Logging

---

## 🔒 3. เงื่อนไขความปลอดภัยและการยืนยัน (Safety & Compliance Check)
- **ไม่กระทบฐานข้อมูลหลัก:** ไม่มีการลบหรือแก้ไขข้อมูลใบหน้าที่มีอยู่แล้วใน `faces_db.db`
- **ไม่กระทบระบบค้นหาปัจจุบัน:** ดัชนีรายปี 2563-2569 ของครูและนักเรียนยังคงทำงานเหมือนเดิม 100%
- **รออนุมัติก่อนลงมือทำ:** AI จะหยุดการทำงานทันที และรอข้อความยืนยันสั่งการจากผู้ใช้ก่อนเริ่มดำเนินการแก้ไขไฟล์โค้ด
