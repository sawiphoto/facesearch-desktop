# แผนงานการปรับปรุงระบบ (v6.11):
# 1. แสดงชื่อโฟลเดอร์ใน Log [AI SCAN]
# 2. คืนค่าฟอร์แมต photo_id ของรูปใหม่ให้กลับมาเป็น Pxxxxx ต่อเนื่อง
# 3. เพิ่มปุ่มคัดกรองเฉพาะ Error และ Warning ใน Console Debug logs

## 📌 ปัญหาและความต้องการ (Issues & Requirements)
1. **แสดงชื่อโฟลเดอร์ใน Log:** ในระหว่างการสแกนรูปภาพ ต้องการให้ข้อความ Log `[AI SCAN]` ระบุชื่อโฟลเดอร์ด้วย เช่น `[AI SCAN] [{folder_name}] (18/48) ...` เพื่อให้ทราบว่ากำลังทำงานในโฟลเดอร์ใด
2. **กู้คืนรูปแบบ photo_id:** ใน Background Scheduler Task มีการนำ Google Drive File ID (`f_id`) ไปใช้เป็น `photo_id` ส่งผลให้รูปใหม่กลายเป็นรหัสยาว ต้องการให้รูปใหม่ต่อจากนี้สร้างรหัสเป็น `Pxxxxx` (รันต่อจาก `P43681` เป็น `P43682`, ...) ให้เป็นมาตรฐานเดียวกัน โดยคงรูปภาพเก่าไว้ตามเดิม (ไม่กระทบการค้นหา)
3. **ปุ่มกรอง Log ใน Console:** ในแถบหัวข้อ Console Debug logs ต้องการเพิ่มปุ่มตัวกรอง:
   - ปุ่ม **"⚠️ Warning"**: กรองแสดงเฉพาะ Log ที่เป็นคำเตือน
   - ปุ่ม **"❌ Error"**: กรองแสดงเฉพาะ Log ที่มีข้อผิดพลาด
   - ปุ่ม **"🌐 ทั้งหมด (All)"**: แสดง Log ทั้งหมดตามปกติ

---

## 📋 แผนการดำเนินงานอย่างละเอียด (Implementation Steps)

### ข้อที่ 1: เพิ่มฟังก์ชัน `get_next_photo_serial()` ใน `db_manager.py` และปรับ `scheduler_task.py`
1. ใน [`db_manager.py`](db_manager.py):
   - เพิ่มเมธอด `get_next_photo_serial(self)` เพื่อให้ทุกส่วนของระบบ (ทั้ง GUI และ Scheduler) เรียกใช้ส่วนกลางจาก DatabaseManager ได้โดยตรงอย่าง Thread-Safe
2. ใน [`scheduler_task.py`](scheduler_task.py):
   - ปรับปรุงการกำหนด `photo_id` ของรูปใหม่ที่สแกนสำเร็จ โดยดึง `next_serial` จาก `self.db.get_next_photo_serial()` หรือนับเพิ่มใน batch buffer เป็น `f"P{next_serial:05d}"` แทนการใช้ `f_id` ตรงๆ
   - เพิ่มชื่อโฟลเดอร์ `[{folder_name}]` ในข้อความ Log ของ `[AI SCAN]` ทุกจุด (ตรวจจับ RAW, กำลังโหลด, ดาวน์โหลดไม่สำเร็จ, ดีโค้ดไม่สำเร็จ, สแกนสำเร็จ, Error)

### ข้อที่ 2: เพิ่มปุ่มคัดกรอง Error และ Warning บน Console ใน `app_gui.py`
1. **โครงสร้าง UI ของ Console Header ([`app_gui.py`](app_gui.py#L4282)):**
   - เพิ่มปุ่ม Segmented/ปุ่มตัวกรองสถานะ:
     - 🌐 **ทั้งหมด (All)** (สีเริ่มต้นหรือสี Active ไฮไลต์)
     - ⚠️ **Warning** (สีส้ม/เหลือง)
     - ❌ **Error** (สีแดง)
2. **กลไกการกรอง Log (Log Filtering Engine):**
   - บันทึกประวัติ Log เต็มทุกบรรทัดพร้อมแท็กสีไว้ในหน่วยความจำ (`self.all_console_logs = []`)
   - สร้างฟังก์ชัน `apply_console_filter(filter_mode)`:
     - เมื่อเลือก `all`: แสดง Log ทั้งหมด
     - เมื่อเลือก `warning`: กรองแสดงเฉพาะบรรทัดที่เป็น `WARNING` หรือแท็ก `orange_red`
     - เมื่อเลือก `error`: กรองแสดงเฉพาะบรรทัดที่เป็น `ERROR` หรือแท็ก `red`
   - ปรับฟังก์ชัน `check_log_queue()` ให้เพิ่ม Log ลงใน Buffer เสมอ และหากข้อความใหม่ตรงกับ Filter ปัจจุบันก็ให้ insert ลง Textbox ทันที
   - ปรับฟังก์ชัน `clear_console_log()` ให้เคลียร์ทั้ง Buffer และหน้าจอ
3. **ปรับ Window Title และ Sidebar Logo เป็น `v6.11`:**
   - Window Title: `ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v6.11 (Folder Logging, Auto P-Serial & Console Log Filter)`
   - Sidebar Logo: `FACE MATCHING\nSYSTEM v6.11`

### ข้อที่ 3: ตรวจสอบและทดสอบเส้นทางการทำงาน (Execution Path Runtime Verification)
- สร้างสคริปต์ทดสอบจำลอง:
  - การทำงานของ `get_next_photo_serial()`
  - การสร้าง `photo_id` แบบ `Pxxxxx` ต่อเนื่อง
  - การฟอร์แมตข้อความ Log และการทำงานของตัวกรอง Log กรอง Error/Warning
- ตรวจสอบความถูกต้องว่าไม่มี Syntax Error และไม่มีการหลุด Scope

### ข้อที่ 4: อัปเดตบันทึกประวัติการเปลี่ยนแปลงลงบนสุดของ `README.md`
- บันทึก Release Notes ของ **v6.11** แทรกไว้ที่บรรทัดบนสุดของ `README.md` ตามกฎเกณฑ์อย่างเคร่งครัด

### ข้อที่ 5: Git Version Control
- Commit การเปลี่ยนแปลงทั้งหมดและ Push ขึ้น Git
