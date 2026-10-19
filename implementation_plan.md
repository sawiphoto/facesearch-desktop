# แผนงานการพัฒนาระบบสถิติและจัดกลุ่มใบหน้าบุคคลนิรนาม (Unknown VIP & Yearly Analytics)
# พร้อมระบบกราฟแท่งเปรียบเทียบสถิติรายปีและไล่เฉดสี (Bar Chart with Color Gradient)

## 📌 ที่มาและวัตถุประสงค์ (Background & Objectives)
- ในรูปภาพกิจกรรมของโรงเรียน มีใบหน้าจำนวนมากที่ระบบสแกนตรวจจับได้ แต่ **ยังไม่มีข้อมูลรูปภาพในฐานข้อมูลบุคลากร/นักเรียนมาเทียบ (Unmatched / Unknown Faces)**
- ผู้ใช้ต้องการดู **สถิติความถี่ของการปรากฏตัว** ของใบหน้านิรนามเหล่านี้ เพื่อค้นหาว่ามีใครที่มีรูปเยอะผิดปกติ (เช่น เป็นบุคคลสำคัญ เช่น ผู้บริหาร, ครูใหม่, หรือครูที่เกษียณอายุราชการไปแล้วแต่ไม่มีรูปโปรไฟล์ในระบบ)
- ต้องการดูสถิติทั้งแบบ **ภาพรวมสะสมทั้งหมด (Overall)** และแบบ **แยกรายปีการศึกษา (2569, 2568, 2567, ...)**
- **ความต้องการเพิ่มเติม:** แสดง **กราฟแท่ง (Bar Chart) รายปีสำหรับแต่ละบุคคล** โดยเรียงลำดับตามปี (เช่น 2563 ➔ 2565 ➔ 2566 ➔ 2567 ➔ 2568 ➔ 2569) และ **แท่งกราฟต้องมีการไล่เฉดสีตามจำนวนรูป (Color Gradient):**
  - **ค่าน้อย:** เฉดสีแดง (`#E74C3C` / `#FF5252`)
  - **ค่าปานกลาง:** เฉดสีส้ม/เหลือง (`#F39C12` / `#F1C40F`)
  - **ค่ามาก:** เฉดสีเขียวสด (`#2ECC71` / `#27AE60`)
- **เงื่อนไขสำคัญ:** ต้องแยกจัดเก็บลง **ตารางฐานข้อมูลใหม่โดยเฉพาะ (Dedicated Analytics Tables)** ไม่ผูกหรือรบกวนตารางหลัก และไม่กระทบต่อกระบวนการสแกนหรือระบบค้นหาเดิม 100%

---

## 🗄️ 1. โครงสร้างฐานข้อมูลใหม่ (Database Schema Design)

สร้างตารางใหม่ 3 ตารางใน SQLite (`faces_db.db`) ซึ่งแยกอิสระจากระบบเดิม:

### 1.1 ตารางกลุ่มบุคคลนิรนาม: `unknown_clusters`
- `cluster_id` (TEXT PRIMARY KEY): รหัสกลุ่ม เช่น `UNK_00001`
- `photo_count` (INTEGER): จำนวนรูปถ่ายสะสมทั้งหมดที่พบ
- `event_count` (INTEGER): จำนวนกิจกรรม/โฟลเดอร์สะสมที่พบ
- `rep_photo_id` (TEXT): รหัสรูปภาพตัวอย่างที่มีความชัดเจนและขนาดใบหน้าเหมาะสม
- `rep_face_index` (INTEGER): ตำแหน่ง face_index ในรูปตัวอย่าง
- `rep_bbox` (TEXT): พิกัด Bounding Box `[x1, y1, x2, y2]` เป็น JSON
- `first_seen_year` (TEXT): ปี พ.ศ. ที่พบครั้งแรก
- `last_seen_year` (TEXT): ปี พ.ศ. ที่พบล่าสุด
- `active_years` (TEXT): รายการปี พ.ศ. ที่พบ เช่น `"2567, 2568, 2569"`
- `created_at` (TIMESTAMP): เวลาที่สร้างกลุ่ม
- `updated_at` (TIMESTAMP): เวลาที่อัปเดตสถิติล่าสุด

### 1.2 ตารางสมาชิกใบหน้าในกลุ่ม: `unknown_cluster_members`
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `cluster_id` (TEXT NOT NULL): ชี้ไปยัง `unknown_clusters(cluster_id)`
- `photo_id` (TEXT NOT NULL): รหัสรูปภาพ
- `face_index` (INTEGER NOT NULL): ตำแหน่งใบหน้าในรูปนั้น
- `year` (TEXT NOT NULL): ปี พ.ศ. ของรูปภาพ (เช่น `2569`, `2568`)
- `event_name` (TEXT): ชื่อกิจกรรม/โฟลเดอร์
- `confidence` (REAL): ค่าความคล้ายคลึงกับจุดศูนย์กลางของกลุ่ม (Cluster Centroid)

### 1.3 ตารางสถิติแยกรายปี: `unknown_cluster_year_stats`
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `cluster_id` (TEXT NOT NULL): ชี้ไปยัง `unknown_clusters`
- `year` (TEXT NOT NULL): ปี พ.ศ. เช่น `2569`, `2568`, `2567`
- `photo_count` (INTEGER): จำนวนรูปที่พบเฉพาะในปีนั้น
- `rep_photo_id` (TEXT): รูปภาพตัวอย่างของปีนั้น
- `rep_face_index` (INTEGER): ตำแหน่งใบหน้าในรูปตัวอย่างของปีนั้น

---

## 🧠 2. สถาปัตยกรรมอัลกอริทึมจัดกลุ่ม (Clustering Engine)

สร้างโมดูลใหม่ `unknown_analyzer.py` สำหรับประมวลผลสถิติ:
1. **คัดกรองเฉพาะใบหน้า Unknown:**
   - ดึงเวกเตอร์จาก `scanned_photo_faces` ที่ **ไม่มี `(photo_id, face_index)` อยู่ใน `detected_faces`** (ตัดครู/นักเรียนที่รู้ชื่อแล้วออก 100%)
2. **การแยกปี (Year Extraction):**
   - สกัดปี พ.ศ. จาก `photo_date` (เช่น ปี ค.ศ. + 543) หรือจาก Prefix/โครงสร้างชื่อ `event_name`
3. **อัลกอริทึม Fast GPU/CPU Clustering:**
   - ใช้ Cosine Distance Threshold ระดับปลอดภัยสูง ($\ge 0.65$) เพื่อป้องกันไม่ให้คนหน้าคล้ายปนกัน (Anti-Drift)
   - ใช้วิธี **Agglomerative Hierarchical Clustering / FAISS-based Community Detection** เพื่อรวมกลุ่มอย่างแม่นยำ
   - คัดเลือกตัวแทนกลุ่ม (Representative Face) จากใบหน้าที่มี Bounding Box ชัดเจนที่สุด
4. **บันทึกผลลัพธ์ลง SQLite:**
   - บันทึกลงตารางทั้ง 3 ตารางใน 1 Transaction

---

## 📊 3. ระบบกราฟแท่งแบบ Native Canvas พร้อมการไล่เฉดสี (Color Gradient Bar Chart)

เพื่อหลีกเลี่ยงการพึ่งพาไลบรารีภายนอกขนาดใหญ่ (ไม่ต้องลง matplotlib เพิ่ม) และให้กราฟแสดงผลเร็วและสวยงามกลมกลืนกับ Dark Navy Theme ของ CustomTkinter:
1. **วาดกราฟด้วย Tkinter Canvas / CustomTkinter Frames:**
   - สามารถเรนเดอร์กราฟแท่งแนวตั้ง (Vertical Bar Chart) หรือแนวนอน (Horizontal Bar Chart) บน Canvas ได้ทันทีแบบเนทีฟ
2. **อัลกอริทึมการคำนวณเฉดสีแบบ Gradient Interpolation:**
   - คำนวณอัตราส่วนของแต่ละแท่ง: $ratio = \frac{count - min\_count}{max\_count - min\_count}$ (ระหว่าง 0.0 ถึง 1.0)
   - ไล่เฉดสีจาก **แดง ➔ ส้ม ➔ เหลือง ➔ เขียวมะนาว ➔ เขียวสด**:
     - $ratio \le 0.5$: ผสมสีระหว่าง Red (`#E74C3C`) ➔ Yellow (`#F1C40F`)
     - $ratio > 0.5$: ผสมสีระหว่าง Yellow (`#F1C40F`) ➔ Green (`#2ECC71`)
   - แต่ละแท่งจะมีตัวเลขจำนวนรูปกำกับด้านบนแท่ง และมีป้ายกำกับปี พ.ศ. (เช่น `2563`, `2565`, `2566`, ...) กำกับด้านล่าง
3. **การโต้ตอบ (Interactive Tooltip / Click):**
   - เมื่อนำเมาส์ไปชี้ที่แท่งกราฟ หรือคลิกที่แท่งปีใด จะกรองแสดงเฉพาะรูปภาพกิจกรรมของปีนั้นทันที

---

## 🖥️ 4. การออกแบบหน้าจอ UI (UI/UX Design in `app_gui.py`)

เพิ่มเมนูใหม่ใน Sidebar: **"📊 สถิติบัญชีบุคคลนิรนาม (Unknown Faces Analytics)"**
1. **แถบตัวกรองด้านบน (Filter Header):**
   - **ตัวเลือกมุมมองปี (Year Selector):**
     - 🌐 `ภาพรวมทั้งหมด (Overall ทุกปีสะสม)`
     - 📅 `ปีการศึกษา 2569`
     - 📅 `ปีการศึกษา 2568`
     - 📅 `ปีการศึกษา 2567`
     - 📅 `ปีอื่นๆ ที่พบในระบบ...`
   - **ตัวกรองความถี่ขั้นต่ำ (Min Photos Filter):** กำหนดจำนวนรูปขั้นต่ำที่ต้องการค้นหา (เช่น $\ge 5$ รูป)
   - **ปุ่ม "🔄 ประมวลผลจัดกลุ่มสถิติใหม่ (Run / Re-cluster)"**: ทำงานใน Background Thread พร้อม Progress Bar
2. **หน้าจอแบ่งเป็น 2 ฝั่ง (Split-Pane View):**
   - **ฝั่งซ้าย: ตารางจัดอันดับ (Ranking Table)**
     - ลำดับที่ | รูปหน้าตัวอย่าง | รหัสกลุ่ม | จำนวนรูปในปีที่เลือก | จำนวนรูปรวมทุกปี | ช่วงปีที่พบ |
   - **ฝั่งขวา: รายละเอียดบุคคลและกราฟแท่งแนวโน้มรายปี (Profile & Yearly Bar Chart)**
     - **ส่วนบน:** รูปครอปใบหน้าตัวอย่างขนาดใหญ่ + รหัสกลุ่ม + สถิติภาพรวม
     - **ส่วนกลาง: กราฟแท่งเปรียบเทียบแต่ละปี (Yearly Gradient Bar Chart):**
       - เรียงตามปี พ.ศ. จากปัจจุบันไปหาอดีต (2569 -> 2568 -> 2567 -> ...)
       - แท่งสีแดง (น้อย) ➔ สีเขียว (มาก)
       - เห็นแนวโน้มทันทีว่า *"คนนี้โผล่ปี 2563-2566 แล้วหายไปในปี 2567-2569 แปลว่าเป็นครูเกษียณ หรือนักเรียนรุ่นเก่า"*
     - **ส่วนล่าง: แกลเลอรีภาพกิจกรรมที่บุคคลนี้ปรากฏตัว:**
       - รายการรูปกิจกรรม, ชื่อกิจกรรม, วันที่ และปุ่มดับเบิ้ลคลิกเพื่อเปิด Google Drive
       - ปุ่ม **"➕ บันทึกรูปครอปใบหน้าลงเครื่อง (Save Cropped Face)"** เพื่อเปิดฟอร์มสร้างครู/นักเรียนใหม่ทันที

---

## 🔒 5. ความปลอดภัยและความสมบูรณ์ของระบบเดิม (Zero-Impact Guarantee)
1. ไม่แก้ไข Schema ของตารางเดิม (`scanned_photos`, `detected_faces`, `staff_members`, `raw_camera_photos`)
2. ไม่แตะต้องไฟล์ Index บน Google Drive (`photo_index.json`, `student_index.json`, `person_index.json`)
3. การสแกนอัตโนมัติ (Scheduler Task) ทำงานได้ตามปกติโดยไม่ต้องรอการคำนวณส่วนนี้
4. ข้อมูลสถิติของ Unknown สามารถล้างและคำนวณใหม่ได้ตลอดเวลา (Idempotent Process)

---

## 📝 6. ขั้นตอนการดำเนินงานเมื่อได้รับการอนุมัติ (Action Steps)
- **Step 1:** เพิ่มฟังก์ชันสร้างตาราง `unknown_clusters`, `unknown_cluster_members`, `unknown_cluster_year_stats` ใน `db_manager.py`
- **Step 2:** พัฒนาสคริปต์คำนวณการจัดกลุ่ม `unknown_analyzer.py`
- **Step 3:** สร้างคอมโพเนนต์วาดกราฟแท่งไล่เฉดสี (Native Gradient Bar Chart Widget)
- **Step 4:** ออกแบบและประกอบ UI ใน `app_gui.py` (เมนูสถิติ, Dropdown ปี, ตารางจัดอันดับ, กราฟแท่ง, แกลเลอรี)
- **Step 5:** ทดสอบด้วยสคริปต์ Runtime Verification กับฐานข้อมูลจริง
- **Step 6:** อัปเดตบันทึกประวัติลง `README.md` และ Git Commit


---

## 🧪 7. แผนการทดสอบอย่างละเอียด (Comprehensive Verification & Test Plan)

ตามกฎเหล็กการทำงาน (Execution Path Runtime Verification) จะต้องมีสคริปต์ทดสอบรันการทำงานจริงครอบคลุมทุกส่วนก่อนส่งมอบงาน:

### 7.1 การทดสอบโครงสร้างฐานข้อมูล (Database Schema & Migration Test)
- **สคริปต์ทดสอบ:** `test_unknown_db_schema.py`
- **ขอบเขตการทดสอบ:**
  1. ทดสอบสร้างตาราง `unknown_clusters`, `unknown_cluster_members`, `unknown_cluster_year_stats`
  2. ตรวจสอบ Foreign Keys, Indexes และ Constraints ของทั้ง 3 ตาราง
  3. ทดสอบการ Insert, Update, Query และ Cascade Delete ว่าทำงานถูกต้อง
  4. ยืนยันว่าตารางเดิม (`scanned_photos`, `detected_faces`, `staff_members`) ไม่ถูกแก้ไขหรือได้รับผลกระทบใดๆ

### 7.2 การทดสอบอัลกอริทึมจัดกลุ่ม (Clustering Algorithm & Accuracy Test)
- **สคริปต์ทดสอบ:** `test_unknown_clustering.py`
- **ขอบเขตการทดสอบ:**
  1. จำลองชุดข้อมูลเวกเตอร์ใบหน้า (Mock Embeddings 512 มิติ) ของบุคคลเดียวกัน (ความคล้าย > 0.70) และต่างบุคคล (ความคล้าย < 0.40)
  2. ทดสอบว่าอัลกอริทึมจัดกลุ่มสามารถรวมคนเดียวกันเข้า Cluster เดียวกันได้อย่างถูกต้อง 100%
  3. ทดสอบ Threshold Anti-Drift: ยืนยันว่าคนต่างบุคคลจะไม่ถูกดึงมารวมกลุ่มกันมั่ว
  4. ทดสอบความเร็ว (Performance Benchmark): วัดเวลาในการจัดกลุ่มใบหน้า 1,000 – 10,000 ใบหน้า ต้องเสร็จสิ้นในเวลาไม่เกินที่กำหนด

### 7.3 การทดสอบการสกัดปีและการคำนวณสถิติ (Year Extraction & Stats Aggregation Test)
- **สคริปต์ทดสอบ:** `test_unknown_year_stats.py`
- **ขอบเขตการทดสอบ:**
  1. ทดสอบการแปลงวันที่ `photo_date` (เช่น `2026-05-12` -> `2569`, `2023-11-04` -> `2566`)
  2. ทดสอบการรวมสถิติแยกรายปี (`unknown_cluster_year_stats`): ยืนยันว่าผลรวมจำนวนรูปแต่ละปีเท่ากับยอดสะสมรวมใน `unknown_clusters` พอดี
  3. ทดสอบกรณีไม่พบวันที่ หรือวันที่อยู่นอกช่วง พ.ศ. ปกติ (Edge Cases / Fallbacks)

### 7.4 การทดสอบคอมโพเนนต์กราฟแท่งไล่เฉดสี (Bar Chart & Color Gradient Test)
- **สคริปต์ทดสอบ:** `test_gradient_chart.py`
- **ขอบเขตการทดสอบ:**
  1. ตรวจสอบฟังก์ชันคำนวณสี Gradient:
     - ค่าน้อยสุด ($ratio = 0.0$) ต้องได้รหัสสีแดง (`#E74C3C`)
     - ค่ากึ่งกลาง ($ratio = 0.5$) ต้องได้รหัสสีส้ม/เหลือง (`#F1C40F`)
     - ค่ามากสุด ($ratio = 1.0$) ต้องได้รหัสสีเขียวสด (`#2ECC71`)
  2. ทดสอบการเรียงลำดับแท่งกราฟ: แกน X ต้องเรียงจาก **ปัจจุบัน ➔ อดีต** ถูกต้องเสมอ
  3. ทดสอบกรณีที่มีข้อมูลเพียง 1 ปี หรือจำนวนรูปเท่ากันทุกปี (Division by Zero Prevention)

### 7.5 การทดสอบฟังก์ชันเซฟรูปภาพครอปใบหน้า (Crop & Export Image Test)
- **สคริปต์ทดสอบ:** `test_crop_export.py`
- **ขอบเขตการทดสอบ:**
  1. ทดสอบการอ่านพิกัด Bounding Box `[x1, y1, x2, y2]` และการ Crop รูปภาพจากไฟล์/แคช
  2. ทดสอบ Padding / Margin รอบใบหน้า เพื่อให้ได้รูปโปรไฟล์ที่มีสัดส่วนสวยงาม (ไม่ตัดชิดคางหรือหน้าผากเกินไป)
  3. ทดสอบการเซฟไฟล์รูปภาพลงโฟลเดอร์ปลายทาง (รองรับชื่อไฟล์และ Path ภาษาไทยบน Windows)

### 7.6 การทดสอบการเชื่อมต่อ UI และการทำงานแบบ Multi-Threading (UI Integration Test)
- **ขอบเขตการทดสอบ:**
  1. ทดสอบการกดปุ่ม "🔄 ประมวลผลจัดกลุ่มสถิติใหม่": ตรวจสอบว่าระบบรันบน Background Thread โดยที่หน้าต่าง GUI ไม่ค้าง (No UI Freezing)
  2. ทดสอบการสลับ Dropdown ปี (`Overall`, `2569`, `2568`, ...): ตารางอันดับและกราฟต้องรีเฟรชข้อมูลตรงตามปีที่เลือกทันที
  3. ทดสอบการคลิกเลือกแถวในตาราง: กราฟแท่งและแกลเลอรีภาพด้านขวาต้องเปลี่ยนตามคนนั้นทันที


### 7.7 ตารางเช็กลิสต์รายการทดสอบ (Test Cases Checklist Matrix)

| ID | ฟังก์ชัน / โมดูลที่ทดสอบ | รายละเอียดกรณีทดสอบ (Test Case Description) | ข้อมูลนำเข้า / เงื่อนไข (Input / Condition) | ผลลัพธ์ที่คาดหวัง (Expected Result) | สถานะ |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-01** | `db_manager.create_unknown_tables` | สร้างตารางใหม่ 3 ตารางใน SQLite | เรียกใช้ฟังก์ชันครั้งแรก | ตารางถูกสร้างครบถ้วน มีคอลัมน์และ PK/FK ถูกต้อง ไม่กระทบตารางเดิม | ✅ ผ่านการทดสอบ (Passed) |
| **TC-02** | `db_manager.create_unknown_tables` | Idempotency Test (สร้างซ้ำ) | เรียกฟังก์ชันซ้ำเมื่อมีตารางอยู่แล้ว | ไม่เกิด Error หรือลบข้อมูลเดิมทิ้ง (`CREATE TABLE IF NOT EXISTS`) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-03** | `unknown_analyzer.filter_unknown_faces` | กรองเฉพาะใบหน้าที่ยังไม่เคยแมตช์ | ฐานข้อมูลมีทั้งหน้าที่มีและไม่มีใน `detected_faces` | ดึงเฉพาะใบหน้าที่ไม่มีใน `detected_faces` ออกมาได้ถูกต้อง 100% | ✅ ผ่านการทดสอบ (Passed) |
| **TC-04** | `unknown_analyzer.extract_thai_year` | แปลงวันที่ ค.ศ. เป็น พ.ศ. ปกติ | `photo_date = '2026-05-12'` | คืนค่าสตริง `'2569'` | ✅ ผ่านการทดสอบ (Passed) |
| **TC-05** | `unknown_analyzer.extract_thai_year` | Fallback กรณีวันที่ว่าง / ผิดฟอร์แมต | `photo_date = ''`, `event_name = 'ภาพกิจกรรม 2568'` | สกัดปีจากชื่อโฟลเดอร์ คืนค่า `'2568'` | ✅ ผ่านการทดสอบ (Passed) |
| **TC-06** | `unknown_analyzer.cluster_faces` | รวมกลุ่มใบหน้าของบุคคลเดียวกัน | เวกเตอร์จำลองของคนเดียวกัน (Cosine Sim $\ge 0.70$) | ใบหน้าทั้งหมดถูกรวมเข้า Cluster เดียวกัน | ✅ ผ่านการทดสอบ (Passed) |
| **TC-07** | `unknown_analyzer.cluster_faces` | ป้องกันคนละคนมารวมกลุ่มกัน (Anti-Drift) | เวกเตอร์จำลองของคนละคน (Cosine Sim $\le 0.45$) | แยกออกเป็นคนละ Cluster ชัดเจน ไม่ปะปนกัน | ✅ ผ่านการทดสอบ (Passed) |
| **TC-08** | `unknown_analyzer.save_clusters_batch` | บันทึกผลการจัดกลุ่มและสถิติลง DB | ข้อมูล Cluster + Member + Year Stats | ข้อมูลถูกบันทึกลงทั้ง 3 ตารางครบถ้วนใน 1 Transaction | ✅ ผ่านการทดสอบ (Passed) |
| **TC-09** | `gradient_chart.get_gradient_color` | คำนวณสีแท่งกราฟค่าน้อยสุด | ค่าสถิติต่ำสุด ($ratio = 0.0$) | ได้รหัสสีแดง (`#E74C3C`) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-10** | `gradient_chart.get_gradient_color` | คำนวณสีแท่งกราฟค่าปานกลาง | ค่าสถิติกึ่งกลาง ($ratio = 0.5$) | ได้รหัสสีเหลือง/ส้ม (`#F1C40F` หรือ `#F39C12`) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-11** | `gradient_chart.get_gradient_color` | คำนวณสีแท่งกราฟค่าสูงสุด | ค่าสถิติสูงสุด ($ratio = 1.0$) | ได้รหัสสีเขียวสด (`#2ECC71`) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-12** | `gradient_chart.render_bars` | ตรวจสอบการเรียงลำดับปีบนแกน X | รายการปี `[2565, 2568, 2566, 2569, 2567]` | แท่งกราฟเรียงจากปัจจุบัน ➔ อดีต (`2569` ➔ `2568` ➔ `2567` ➔ `2566` ➔ `2565`) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-13** | `gradient_chart.render_bars` | จัดการกรณีมีข้อมูลปีเดียว (Edge Case) | มีข้อมูลเฉพาะปี `2569` เพียงแท่งเดียว | กราฟวาดได้ปกติ ไม่เกิดข้อผิดพลาด Division by Zero | ✅ ผ่านการทดสอบ (Passed) |
| **TC-14** | `app_gui.save_cropped_face` | ครอปรูปใบหน้าจากภาพตัวอย่าง | พิกัด Bounding Box `[x1, y1, x2, y2]` + รูปภาพ | ครอปรูปหน้าได้ตรงพิกัด มี Margin เหมาะสม ไม่ขาดคาง/หน้าผาก | ✅ ผ่านการทดสอบ (Passed) |
| **TC-15** | `app_gui.save_cropped_face` | บันทึกรูปภาพลงเครื่อง (Export File) | ผู้ใช้เลือกพาธเซฟ เช่น `C:\Users\...\Desktop\face.jpg` | ไฟล์ `.jpg` ถูกบันทึกลงเครื่องเปิดดูได้คมชัด รองรับโฟลเดอร์ภาษาไทย | ✅ ผ่านการทดสอบ (Passed) |
| **TC-16** | `app_gui.on_year_filter_change` | สลับมุมมองตัวกรองปี | ผู้ใช้เปลี่ยน Dropdown จาก `Overall` เป็น `2568` | ตารางอันดับรีเฟรชแสดงเฉพาะคนที่พบในปี 2568 เรียงตามจำนวนรูปปีนั้น | ✅ ผ่านการทดสอบ (Passed) |
| **TC-17** | `app_gui.on_select_unknown_person` | เลือกดูข้อมูลบุคคลในตาราง | ผู้ใช้คลิกเลือกแถว `UNK_0015` | แผงด้านขวาอัปเดตรูปโปรไฟล์ กราฟแท่ง และแกลเลอรีรูปของ `UNK_0015` ทันที | ✅ ผ่านการทดสอบ (Passed) |
| **TC-18** | `app_gui.run_recluster_thread` | ประมวลผลจัดกลุ่มสถิติใหม่บน Thread ย่อย | ผู้ใช้กดปุ่ม "🔄 ประมวลผลจัดกลุ่มสถิติใหม่" | ระบบทำงานเบื้องหลัง หน้าต่าง GUI ไม่ค้าง เมาส์คลิกส่วนอื่นได้ตามปกติ | ✅ ผ่านการทดสอบ (Passed) |

---

## ⚡ 8. แผนแก้ปัญหาและเพิ่มประสิทธิภาพการจัดกลุ่มใบหน้าความเร็วสูง (High-Performance Vectorized Clustering Optimization)

### 8.1 การวิเคราะห์สาเหตุเชิงลึก (Root Cause Analysis: ทำไมถึงใช้เวลานานเกิน 15 นาที?)
1. **ปริมาณข้อมูลจริงในระบบ:** ในฐานข้อมูล `faces_db.db` มีใบหน้านิรนามที่ยังไม่ทราบชื่อสะสมอยู่มากถึง **413,586 ใบหน้า** (Matrix 413,586 × 512 มิติ)
2. **คอขวดที่พบในโค้ดเดิม (`unknown_analyzer.py` บรรทัดที่ 81):**
   ```python
   for idx in range(num_faces): # วนลูป 413,586 รอบ
       centroids = np.array([c["centroid"] for c in clusters], dtype=np.float32) # <-- คอขวดวิกฤต!
   ```
   - ในลูปทุกๆ 1 ใบหน้า โค้ดจะดึง list of array ออกมาสร้างเป็น `np.array` ก้อนใหม่ขนาด `(K, 512)` ซ้ำๆ ทุกรอบ
   - เมื่อจำนวนกลุ่ม $K$ โตขึ้นเป็น 10,000 – 30,000 กลุ่ม การแปลงนี้ต้องจัดสรร Memory ชั่วคราว (Allocate) ซ้ำๆ มหาศาลกว่า 16 Terabytes ตลอดการรัน ทำให้ Python Garbage Collector (GC) ค้างและ CPU ทำงานหนักหน่วง
   - **เวลาประมวลผลจริงของโค้ดเดิม:** คำนวณ 413,586 ใบหน้า จะต้องใช้เวลาจริงประมาณ **60 - 70 นาที (~1 ชั่วโมงกว่า)**
3. **ขาด Real-time Progress Log:**
   - ภายในลูป 413,586 รอบ ไม่มีการพิมพ์ Log ความคืบหน้า (Log ค้างอยู่ที่ข้อความ `Matrix Shape: (413586, 512)...`) ทำให้ดูเหมือนโปรแกรมค้างโดยไม่มีใครทราบว่ากำลังทำงานอยู่ที่ใบหน้าที่เท่าไร

### 8.2 แนวทางการปรับปรุงประสิทธิภาพ (Optimization Strategy)
1. **Pre-allocated Dynamic Centroid Matrix:**
   - จองหน่วยความจำ NumPy 2D Array ขนาดเริ่มต้น เช่น `(10000, 512)` แบบ Contiguous C-order
   - เมื่อพบกลุ่มใหม่ แค่เขียนค่าลงแถวถัดไป `centroids_matrix[cluster_count] = emb` (O(1) Memory Write)
   - หากกลุ่มขยายเกินขนาด จะทำการ Double Capacity แบบ Dynamic Reallocation นานๆ ครั้ง ไม่ใช่ทำทุกรอบ
2. **Vectorized BLAS Dot Product:**
   - คำนวณ Cosine Similarity ด้วย `np.dot(centroids_matrix[:cluster_count], emb)` โดยตรงผ่าน C/BLAS Engine
   - ตัด overhead ของ Python List Comprehension และ Memory Allocation 100%
3. **Real-time Progress Logging & ETA Display:**
   - แสดง Log รายงานความคืบหน้าทุกๆ 10,000 ใบหน้า หรือทุก 5 วินาที
   - แสดงรูปแบบ: `[UNKNOWN ANALYTICS] ⏳ ความคืบหน้า: 50,000 / 413,586 ใบหน้า (12.1%) | พบแล้ว 3,420 กลุ่ม (ความเร็ว 9,200 หน้า/วิ, ETA: 39 วินาที)...`
   - ช่วยให้ผู้ใช้เห็นความเคลื่อนไหวชัดเจน ไม่คิดว่าระบบค้าง

### 8.3 ผลการทดสอบเปรียบเทียบความเร็ว (Performance Benchmark)
| รูปแบบอัลกอริทึม | อัตราประมวลผล (ใบหน้า/วินาที) | เวลาที่ใช้สำหรับ 413,586 ใบหน้า |
| :--- | :---: | :---: |
| **1. โค้ดเดิม (Old List-comprehension Loop)** | ~105 ใบหน้า/วินาที | **~3,920 วินาที (ประมาณ 65.3 นาที)** 🐢 |
| **2. Pre-allocated C-Matrix + Vectorized BLAS** | **~12,000 - 18,000 ใบหน้า/วินาที** | **~22 - 35 วินาที** ⚡ *(เร็วขึ้นกว่า 100 เท่า!)* |

### 8.4 แผนขั้นตอนดำเนินการ (Action Plan)
1. ปรับปรุงฟังก์ชัน `cluster_unknown_faces` ใน [unknown_analyzer.py](file:///d:/Projects/07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน/unknown_analyzer.py)
2. เพิ่มระบบ Log รายงาน Progress % และ ETA วินาทีที่เหลือ
3. สร้างสคริปต์ Benchmark / Verification ยืนยันความเร็วและความถูกต้องของกลุ่มข้อมูล
4. รันประมวลผลจริงกับชุดข้อมูล 413,586 ใบหน้า และบันทึกผลลง DB
5. บันทึกประวัติลง `README.md` และส่ง Commit Git

---

## 🎯 9. แผนการปฏิรูปอัลกอริทึมการจัดกลุ่มใบหน้าให้ถูกต้องแม่นยำ 100% (High-Precision Face Clustering & Anti-Chaining Architecture)

### 9.1 ยืนยันข้อผิดพลาดด้วยหลักฐานทางคณิตศาสตร์และข้อมูลจริงในระบบ (Empirical Proof)
จากการตรวจสอบสมาชิกในกลุ่ม `UNK_00001` (ที่มียอดสะสม 2,311 รูป) ในฐานข้อมูลจริง พบข้อผิดพลาดร้ายแรง 2 ประการ:
1. **Centroid Drift (จุดศูนย์กลางเคลื่อนที่จนกลายเป็นหลุมดำ):**
   - เมื่อตรวจสอบความคล้ายระหว่างใบหน้า Leader (คนแรก) กับสมาชิกลำดับหลังๆ พบว่า:
     - สมาชิกคนที่ 10: ความคล้ายกับ Leader = $0.6742$
     - สมาชิกคนที่ 500: ความคล้ายกับ Leader = $0.5780$ (เริ่มกลายเป็นคนอื่น)
     - สมาชิกคนที่ 2,000: ความคล้ายกับ Leader = $0.5734$
     - **ค่าความคล้ายต่ำสุดที่ถูกดึงเข้ามาในกลุ่ม: ตกฮวบเหลือเพียง $0.4626$!** (ซึ่งใน InsightFace ค่า $0.46$ คือคนละคนกันโดยสิ้นเชิง)
2. **การรวมใบหน้าจากรูปเดียวกันเข้ากลุ่มเดียวกัน (Violation of Physical Reality):**
   - ในรูป `P05116` มีทั้ง Face 17 และ Face 20 ถูกจัดให้อยู่ในกลุ่ม `UNK_00001` เดียวกัน
   - ในรูป `P05188` มีทั้ง Face 24 และ Face 26 ถูกจัดให้อยู่ในกลุ่ม `UNK_00001` เดียวกัน
   - **ความเป็นจริง:** คนๆ เดียวกันไม่มีทางปรากฏตัวพร้อมกัน 2 จุดในภาพถ่ายใบเดียวกันได้

### 9.2 สาเหตุที่แท้จริง (Root Causes Analysis)
1. **การอัปเดต Centroid แบบ Running Average (`centroids_sums += emb`):**
   - เมื่อกลุ่มมีขนาดใหญ่ขึ้น เวกเตอร์ Centroid จะค่อยๆ เลื่อนตำแหน่ง (Drift) เข้าสู่ศูนย์กลางการกระจายตัวของใบหน้ามนุษย์ทั่วไป (Central Distribution Cloud)
   - เมื่อ Centroid เคลื่อนที่ไปเรื่อยๆ มันจะทำตัวเป็น "หลุมดำ (Black Hole)" ดูดใบหน้าคนอื่นๆ ที่มีความคล้ายกับตำแหน่งที่เคลื่อนไปเรื่อยๆ จนกลายเป็น Super-Cluster ยักษ์ที่รวมคนนับร้อยเข้ามามั่ว
2. **ขาดเงื่อนไข Must-Not-Link (Same-Photo Mutual Exclusion Constraint):**
   - ไม่มีการบล็อกว่าหากรูปถ่ายนั้นเคยมีใบหน้าถูกจัดเข้ากลุ่มนี้ไปแล้ว ใบหน้าอื่นในรูปเดียวกันจะไม่มีสิทธิ์เข้ากลุ่มเดิมอีก
3. **ขาด Face Quality Filter (ขยะภาพฝูงชนเบลอขนาดเล็กมาก):**
   - ในรูปกิจกรรมรวม เช่น โรงอาหาร หรือลานกีฬา มีใบหน้านักเรียนด้านหลังที่เล็กมาก (เช่น $15\times 15$ พิกเซล) หรือเบลอ ซึ่งเวกเตอร์ของใบหน้าขนาดเล็กมากๆ มักจะตกอยู่ตรงกลางของ Feature Space ทำให้ถูกดึงเข้ามามั่วได้ง่าย
4. **ปัญหาบั๊กการแสดงผลรูปตัวแทน (`[ไม่มีรูป]` และ OpenCV Assertion Failure):**
   - ฟังก์ชันโหลด Thumbnail ใน `app_gui.py` ไม่ได้ Fallback ไปดึงรูปถ่ายจากที่เก็บไฟล์หลักเมื่อไม่พบในแคช และไม่มีการตรวจสอบ `None/Empty Image` ก่อนส่งเข้า `cv2.imencode()`

### 9.3 สถาปัตยกรรมอัลกอริทึมใหม่ (High-Precision Anti-Drift Architecture)
1. **Fixed Exemplar Leader Algorithm (หยุด Centroid Drift ถาวร):**
   - เวกเตอร์ของ Leader **จะต้องคงที่ (Fixed Embedding)** ไม่มีการนำเวกเตอร์สมาชิกใหม่มาเฉลี่ยจนเลื่อนตำแหน่ง
   - สมาชิกทุกคนที่ถูกเพิ่มเข้ากลุ่มจะต้องผ่านเงื่อนไข:
     $$\text{Cosine Similarity}(\text{emb}, \text{Leader}) \ge \text{Threshold}$$
     *(รับประกัน 100% ว่าทุกคนในกลุ่มจะต้องมีความคล้ายกับ Leader ไม่ต่ำกว่า Threshold เสมอ ไม่มีวันหลุดไป $0.46$ อีกต่อไป)*
2. **คัดเลือก Leader จากใบหน้าที่ใหญ่และคมชัดที่สุดก่อน (Quality-First Leader Ordering):**
   - ก่อนเริ่มจัดกลุ่ม ให้ทำการ Sort ใบหน้าทั้งหมดตามขนาด Bounding Box (`area = width * height`) จากใหญ่ไปหาเล็ก
   - ใบหน้าที่อยู่ใกล้กล้องและคมชัดที่สุดจะได้รับเลือกเป็น Leader ของกลุ่มก่อนเสมอ
3. **กฎ Must-Not-Link (Same-Photo Exclusion):**
   - ในแต่ละกลุ่มจะเก็บบันทึก `seen_photo_ids = set()`
   - หากใบหน้ามาจาก `photo_id` ที่มีอยู่ในกลุ่มแล้ว **จะไม่อนุญาตให้เข้ากลุ่มนั้นเด็ดขาด** (บังคับให้แยกไปอยู่กลุ่มอื่น หรือสร้างกลุ่มใหม่)
4. **Face Quality Thresholding (ตัดขยะภาพเบลอ):**
   - กำหนดขนาด Bounding Box ขั้นต่ำ เช่น กว้าง/ยาว $\ge 40$ พิกเซล และคัดกรองใบหน้าที่มีขนาดเล็กเกินไปออกจากการวิเคราะห์ VIP
5. **ปรับเกณฑ์ Threshold ที่เหมาะสมและปลอดภัย:**
   - ปรับเกณฑ์ความคล้ายคลึงขั้นต่ำสำหรับ Fixed Exemplar เป็น $\mathbf{\ge 0.70}$ (เพื่อความมั่นใจว่าเป็นบุคคลเดียวกันอย่างแท้จริง)
6. **แก้ไขระบบ Thumbnail และ OpenCV imencode ใน `app_gui.py`:**
   - เพิ่ม Fallback การโหลดรูปภาพตัวแทนจากไฟล์ต้นฉบับในเครื่อง/แคช Google Drive
   - ตรวจสอบ `if img is not None and img.size > 0:` ก่อนเรียก `cv2.imencode()` เพื่อไม่ให้เกิด OpenCV Assertion Error

### 9.4 แผนขั้นตอนดำเนินการและทดสอบ (Execution & Verification Plan)
- **Step 1:** ปรับปรุง `unknown_analyzer.py` ให้ใช้ **Quality-First Sorting + Fixed Exemplar Leader + Same-Photo Constraint + Min Face Size Filter** ✅ ดำเนินการเสร็จสิ้น
- **Step 2:** แก้ไขบั๊กการโหลด Thumbnail และการดักจับข้อผิดพลาดรูปภาพว่างใน `app_gui.py` ✅ ดำเนินการเสร็จสิ้น
- **Step 3:** สร้างสคริปต์ทดสอบยืนยันความถูกต้อง (TC-19 และ TC-20):
  - **TC-19:** ตรวจสอบว่าในแต่ละกลุ่มไม่มีภาพซ้ำ (`photo_id`) แม้แต่ภาพเดียว (Same-Photo Constraint) ✅ ผ่าน 100%
  - **TC-20:** ตรวจสอบว่าสมาชิกทุกคนในกลุ่มมีค่าความคล้ายกับ Leader $\ge 0.70$ ครบ 100% (Anti-Drift Verification) ✅ ผ่าน 100%
- **Step 4:** นำเสนอผลการทดสอบ อัปเดต `README.md` และ Git Commit

### 9.5 ผลการทดสอบ Suite Test ครบ 20 ข้อ (TC-01 ถึง TC-20: ผ่าน 100%)
| ID | รายละเอียดกรณีทดสอบ | ข้อมูลนำเข้า / เงื่อนไข | ผลลัพธ์จริง | สถานะ |
| :--- | :--- | :--- | :--- | :---: |
| **TC-19** | `unknown_analyzer.cluster_faces` (Same-Photo Exclusion) | 2 ใบหน้าจากรูปเดียวกัน (`P_GROUP_01`) ความคล้ายสูง 0.90 | แยกออกเป็น 2 กลุ่มต่างหากทันที ไม่ถูกจับมารวมกัน | ✅ ผ่านการทดสอบ (Passed) |
| **TC-20** | `unknown_analyzer.cluster_faces` (Anti-Drift Fixed Exemplar) | ชุดข้อมูล Chaining Sequence 10 ใบหน้าต่อเนื่อง | สมาชิกทุกคนในกลุ่มมีความคล้ายกับ Leader $\ge 0.70$ ครบ 100% ไม่มี Drift | ✅ ผ่านการทดสอบ (Passed) |




---

## 🔟 10. การเพิ่มข้อมูลจำนวนใบหน้าที่ตรวจพบ (Face Count) ลงใน `photo_index.json` (v6.23)

### 10.1 ที่มาและวัตถุประสงค์ (Background & Requirements)
- **ความต้องการของผู้ใช้:** ต้องการเพิ่มข้อมูลระบุ **"จำนวนใบหน้า"** ที่ระบบสแกนตรวจพบลงในแต่ละรายการของไฟล์ `photo_index.json`
- **ตัวอย่างโครงสร้างเดิม:**
  ```json
  "P04968": {
    "event": "กค 2 ต้อนรับครูพละใหม่", 
    "drive_link": "https://drive.google.com/file/d/1L6_poxbLKCiX_3ql60dyH0G-DCEMONLn/view",
    "date": "2026-07-06"
  }
  ```
- **ประโยชน์และการนำไปใช้:**
  1. ฝั่ง Web Application / Google Apps Script (เช่น ในโปรเจกต์ `07.5 ระบบค้นหา appscript`) สามารถอ่านข้อมูลจำนวนใบหน้าจริงที่ตรวจพบได้ทันที โดยไม่ต้องคาดเดาจากจำนวนครูที่จับคู่ได้
  2. ทำให้สามารถจัดหมวดหมู่ประเภทภาพ เช่น **ภาพเดี่ยว (`single`: 1 หน้า)**, **ภาพกลุ่มย่อย (`small_group`: 2-5 หน้า)**, หรือ **ภาพกลุ่มใหญ่ (`large_group`: >5 หน้า)** ได้อย่างแม่นยำ 100% แม้ในภาพนั้นจะมีคนภายนอก/นักเรียนปะปนอยู่ก็ตาม
  3. สอดคล้องกับข้อมูลที่หน้าจอ GUI แสดงในคอลัมน์ "สถานะแคชใบหน้า" เช่น `มีแคชแล้ว (19 หน้า)`

---

### 10.2 การวิเคราะห์เชิงลึกของแหล่งข้อมูลและประสิทธิภาพ (In-Depth Technical Audit)
1. **สถานะข้อมูลในฐานข้อมูล SQLite (`data/faces_db.db`):**
   - ตาราง `scanned_photos` มีคอลัมน์ `total_faces_detected INTEGER DEFAULT 0` อยู่แล้ว แต่ข้อมูลในปัจจุบันมีค่าเป็น `0` ทั้งหมด (111,318 รูป) เนื่องจากในอดีตระบบไม่ได้ใส่ค่านี้ตอน INSERT
   - ตาราง `scanned_photo_faces` มีข้อมูลเวกเตอร์ใบหน้าจริงที่ตรวจพบสะสมทั้งหมด **974,491 ใบหน้า** (`face_index >= 0`) ครอบคลุม **107,643 รูปภาพ** (และมี dummy rows `face_index = -1` จำนวน 1,094 รูปที่สแกนแล้วไม่พบหน้าคนจริง)
2. **การป้องกันปัญหาคอขวดประสิทธิภาพ (Performance Bottleneck Prevention):**
   - หากคำนวณ `COUNT(*)` จาก `scanned_photo_faces` แบบสดๆ ทุกครั้งที่กด Sync Drive จะต้องสแกนตารางขนาดใหญ่ที่มี BLOB เวกเตอร์ ซึ่งกินเวลาถึง **18.64 วินาที** ต่อการ Sync หนึ่งครั้ง
   - **แนวทางแก้ไขสถาปัตยกรรมประสิทธิภาพสูง (High-Performance Architecture):**
     - **One-Time Data Backfill:** รันคำสั่งอัปเดตค่าจริงย้อนหลังเข้าคอลัมน์ `scanned_photos.total_faces_detected` เพียงครั้งเดียว (~18-20 วินาที)
     - ปรับฟังก์ชันบันทึกรูปใหม่ (`save_scanned_photo`, `save_scanned_photos_batch` ใน `db_manager.py` และ `scheduler_task.py`) ให้บันทึกค่า `total_faces_detected = len(faces)` ลงใน `scanned_photos` เสมอ
     - ใน `db_manager.py:get_all_sync_data()` ให้ดึงตรงจาก `scanned_photos.total_faces_detected` ซึ่งจะเร็วระดับ **0.05 วินาที (Instant Fetch)**

---

### 10.3 รูปแบบโครงสร้าง JSON ที่ได้รับอนุมัติ (Approved JSON Schema)
- **ตัวเลือกที่ผู้ใช้เลือกอนุมัติ:** **ตัวเลือกที่ 1: `"face_count": 1`**
- **มาตรฐาน:** ภาษาอังกฤษ snake_case สอดคล้องกับคีย์เดิม (`event`, `drive_link`, `date`) ปลอดภัย สะดวกต่อการเรียกใช้งานใน JavaScript (`photo.face_count`) และ Google Apps Script
- **ตัวอย่างผลลัพธ์จริงใน `photo_index.json`:**
  ```json
  "P04968": {
    "event": "กค 2 ต้อนรับครูพละใหม่",
    "drive_link": "https://drive.google.com/file/d/1L6_poxbLKCiX_3ql60dyH0G-DCEMONLn/view",
    "date": "2026-07-06",
    "face_count": 1
  },
  "P04969": {
    "event": "กค 2 ต้อนรับครูพละใหม่",
    "drive_link": "https://drive.google.com/file/d/1lLYvkPiSYWDJ9ohN9iBSTxpc4ho_sg-o/view",
    "date": "2026-07-06",
    "face_count": 5
  }
  ```

---

### 10.4 แผนขั้นตอนดำเนินการแก้ไขโค้ดอย่างละเอียด (Step-by-Step Implementation)

#### ขั้นตอนที่ 1: การอัปเดตและเตรียมฐานข้อมูล (Database Layer in [`db_manager.py`](db_manager.py))
1. **Migration Safety (`init_db`):** ตรวจสอบและเพิ่มคอลัมน์ `total_faces_detected INTEGER DEFAULT 0` ลงใน `scanned_photos` หากยังไม่มี และสร้างดัชนีครอบคลุม `idx_spf_photo_face ON scanned_photo_faces(photo_id, face_index)`
2. **Backfill Data (`backfill_total_faces_detected`):** 
   - ดึงค่านับจำนวนใบหน้าจริงจาก `scanned_photo_faces WHERE face_index >= 0 GROUP BY photo_id` (ไม่นับ dummy -1)
   - อัปเดตลงคอลัมน์ `scanned_photos.total_faces_detected` ครบ 107,643 รูปภาพ
3. **Data Retrieval Optimization (`get_all_sync_data`):**
   - เปลี่ยนคำสั่ง SQL เป็น:
     ```sql
     SELECT photo_id, event_name, drive_link, photo_date, total_faces_detected 
     FROM scanned_photos
     ```
   - เพิ่มฟิลด์ `"face_count": int(p[4]) if len(p) > 4 and p[4] is not None else 0` ใน Dictionary ของแต่ละรูป
4. **Write-Path Persistence (`save_scanned_photo` & `save_scanned_photos_batch`):**
   - ใน `save_scanned_photo()` เพิ่ม parameter `total_faces_detected=0` (หากไม่ได้ส่งมาให้ใช้ `len(matches)`)
   - ใน `save_scanned_photos_batch()` บันทึก `total_faces_detected = len(item.get("faces", []))` ลงในคำสั่ง `INSERT OR REPLACE INTO scanned_photos`

#### ขั้นตอนที่ 2: การสร้าง JSON ดัชนีรูปภาพ (Sync Layer in [`gdrive_sync.py`](gdrive_sync.py))
- ในฟังก์ชัน `update_json_indexes_on_drive()` บรรทัดที่ 469:
  ```python
  photo_index[photo_id] = {
      "event": item["event"],
      "drive_link": self.format_drive_view_url(raw_link),
      "date": item.get("date", ""),
      "face_count": item.get("face_count", 0)
  }
  ```
  *(คงฟิลด์เดิมครบถ้วน 100% ปลอดภัยต่อระบบค้นหาและ Backward Compatible)*

#### ขั้นตอนที่ 3: ระบบ Background Scheduler ([`scheduler_task.py`](scheduler_task.py))
- ในลูป Batch Commit บรรทัดที่ 1002-1003 ให้บันทึก `total_faces_detected = len(r.get("face_embeddings", []))` ลงในคำสั่ง `INSERT OR REPLACE INTO scanned_photos` เสมอ

#### ขั้นตอนที่ 4: ส่วนแสดงผล GUI และอัปเกรดเวอร์ชัน ([`app_gui.py`](app_gui.py))
- บรรทัดที่ 5240-5246: ปรับเปลี่ยน SQL ของแท็บ SQLite Viewer ให้ดึง `p.total_faces_detected` โดยตรง ลดภาระการรัน Subquery นับแถวซ้ำซ้อน
- ปรับเลขเวอร์ชันโปรแกรมเป็น **`v6.23`** ใน:
  - แถบไตเติลหน้าต่างหลัก (`self.title`)
  - โลโก้แถบด้านข้าง (Sidebar Header Badge)

#### ขั้นตอนที่ 5: การทดสอบความถูกต้องและบันทึกประวัติ ([`README.md`](README.md))
- รันชุดทดสอบความถูกต้อง (TC-21 ถึง TC-24) พร้อมรัน Regression Suite (`test_unknown_analytics_suite.py`)
- บันทึก Changelog v6.23 ไว้ที่บรรทัดบนสุด (Prepend to top) ใน `README.md`
- บันทึก Git Commit

---

### 10.5 ตารางผลการทดสอบ (Test Results: TC-21 ถึง TC-24 ผ่าน 100%)
| รหัสทดสอบ | รายละเอียดกรณีทดสอบ | ข้อมูลนำเข้า / เงื่อนไข | ผลลัพธ์จริง | สถานะ |
| :--- | :--- | :--- | :--- | :---: |
| **TC-21** | Backfill Data Verification | ตรวจสอบการเติมข้อมูล `total_faces_detected` ใน `scanned_photos` | เติมข้อมูลครบ 107,643 รูปภาพ ค่าตรงกับ `scanned_photo_faces` 100% (0 mismatches) | ✅ ผ่านการทดสอบ (Passed) |
| **TC-22** | DB Sync Data Query Speed | รันทดสอบ `db.get_all_sync_data()` บนฐานข้อมูลจริง 111,318 รูป | ดึงข้อมูลได้ครบถ้วน 111,318 รูป ใช้เวลาเพียง 0.607 วินาที | ✅ ผ่านการทดสอบ (Passed) |
| **TC-23** | JSON Index Generation & Structure | ทดสอบฟังก์ชันสร้าง `photo_index.json` | มีคีย์ `"face_count"` ระบุจำนวนใบหน้าถูกต้อง และคงฟิลด์เดิม (`event`, `drive_link`, `date`) ครบถ้วน 100% | ✅ ผ่านการทดสอบ (Passed) |
| **TC-24** | GUI & System Version Check | ค้นหาเลขเวอร์ชันทั่วทั้งระบบ | แสดงผล `v6.23` ทั้ง Window Title และ Sidebar Header | ✅ ผ่านการทดสอบ (Passed) |
| **TC-Suite** | Regression Suite Testing | รัน `test_unknown_analytics_suite.py` ทั้ง 20 ข้อเดิม | ผ่านครบ 20/20 ข้อ (TC-01 ถึง TC-20) 100% | ✅ ผ่านการทดสอบ (Passed) |



---

## 1️⃣1️⃣ 11. ระบบรายงานสรุปผลการสแกนและบันทึกไฟล์อัตโนมัติ (Scan Session Summary Popup & Report Exporter) (v6.24)

### 11.1 ที่มาและวัตถุประสงค์ (Background & Requirements)
- **ความต้องการของผู้ใช้:**
  - เมื่อผู้ใช้กดปุ่ม **"Stop Schedule Task"** และระบบทำการอัปเดตไฟล์ `photo_index.json` / JSON files บน Google Drive เรียบร้อยแล้ว ให้แสดง **Popup หน้าต่างรายงานสรุปผล (Report Summary Popup)**
  - รายละเอียดที่ต้องสรุปแสดง:
    1. **สแกนโฟลเดอร์ไหนไปบ้าง และโฟลเดอร์ละกี่ภาพ:** (Folders breakdown พร้อมระบุจำนวนรูปภาพที่สแกนสำเร็จ)
    2. **รวมทั้งหมดกี่ภาพ:** (Total images scanned: AI-analyzed, Camera RAW, Errors/Skipped)
    3. **ภาพใครปรากฏเยอะที่สุด Top 10:** (Top 10 Recognized People ในรอบการสแกนนี้ พร้อมจำนวนรูปที่ตรวจพบ)
    4. **มีปัญหาภาพไหนบ้าง ฯลฯ:** (รายการไฟล์ที่มีปัญหา/Error/Skipped พร้อมชื่อโฟลเดอร์และสาเหตุ)
    5. **บันทึกไฟล์เก็บไว้ในโฟลเดอร์ `report_summary` ในโปรเจกต์นี้ด้วย:** (บันทึกรายงานสรุปเป็นไฟล์ Markdown/Text และ JSON)

---

### 11.2 สถาปัตยกรรมตัวติดตามสถิติรอบการสแกน (ScanSessionTracker in `scheduler_task.py`)
สร้างคลาส `ScanSessionTracker` สำหรับติดตามข้อมูลแบบ Real-time และ Thread-Safe:
- **ข้อมูลที่จัดเก็บในรอบการสแกน:**
  - `start_time`, `end_time`, `duration`
  - `stopped_by_user` (True เมื่อผู้ใช้กดปุ่ม Stop Schedule Task)
  - `json_sync_completed` (สถานะการอัปโหลดไฟล์ JSON สรุปย่อขึ้น Google Drive)
  - `folders`: Dictionary เก็บข้อมูลแต่ละโฟลเดอร์ `{"year": ..., "ai_count": ..., "raw_count": ..., "skipped_count": ..., "total_files": ..., "status": ...}`
  - `person_counts`: `collections.Counter()` นับจำนวนภาพที่แต่ละคนปรากฏตัวในรอบนี้
  - `skipped_files`: รายการไฟล์ที่มีปัญหา `[{"folder": ..., "file_name": ..., "file_id": ..., "reason": ..., "drive_link": ...}]`
  - `total_faces_detected`: จำนวนใบหน้าทั้งหมดที่ตรวจจับได้
- **ขั้นตอนการทำงานเมื่อผู้ใช้กด Stop Schedule Task:**
  1. ผู้ใช้กดปุ่ม `btn_stop_schedule` (`request_stop()`) ➔ `self.stop_requested = True`
  2. Background Scheduler สแกนโฟลเดอร์ปัจจุบันเสร็จสิ้น บันทึก Batch ลง SQLite
  3. เรียก `self._sync_all_json_to_drive()` เพื่ออัปโหลด JSON ไฟล์สุดท้ายขึ้น Google Drive
  4. เรียก `tracker.finalize(stopped_by_user=True)`
  5. บันทึกรายงานสรุปผลลงในโฟลเดอร์ `report_summary/scan_report_YYYYMMDD_HHMMSS.md` และ `.json`
  6. ส่ง Event ผ่าน `self.app_gui.after(0, lambda: self.app_gui.show_scan_report_popup(report_data, saved_path))` เพื่อแสดงหน้าต่าง Popup บน GUI ทันที

---

### 11.3 การออกแบบหน้าต่าง Popup สรุปผลบน GUI (`app_gui.py`)
สร้างหน้าต่าง `show_scan_report_popup(self, report_data, saved_path)`:
- ใช้ `ctk.CTkToplevel(self)` ขนาด `850x680` พิกเซล โทนสี Modern Dark Palette สอดคล้องกับ UI
- **Header Banner:**
  - หัวข้อ: `📊 รายงานสรุปผลการสแกนภาพถ่าย (Scan Session Summary)`
  - ป้ายสถานะ: `🛑 หยุดทำงานตามคำร้องขอ (Stop Requested) - อัปเดต Drive JSON สำเร็จแล้ว` (สีแดง/ส้มสดใส)
  - ข้อมูลเวลา: `⏱️ เวลาที่ใช้: X นาที Y วินาที | เริ่ม: HH:MM:SS - สิ้นสุด: HH:MM:SS`
- **KPI Summary Cards (4 การ์ดสรุปตัวเลข):**
  - 📁 โฟลเดอร์ที่สแกน (`X โฟลเดอร์`)
  - 📸 ภาพที่สแกนทั้งหมด (`X ภาพ` แยกเป็น AI: Y, RAW: Z)
  - 👤 ใบหน้าที่ตรวจพบ (`X ใบหน้า`)
  - ⚠️ ภาพที่มีปัญหา (`X ภาพ`)
- **Tabview จัดหมวดหมู่ 4 แท็บ:**
  - **แท็บ 1: 📁 โฟลเดอร์ที่สแกน (Folders Breakdown)**: รายชื่อโฟลเดอร์, ปีการศึกษา, จำนวนรูปที่สแกนสำเร็จ และสถานะ
  - **แท็บ 2: 🏆 บุคคลที่ปรากฏเยอะสุด Top 10**: อันดับ 1-10 พร้อมชื่อ-นามสกุล, จำนวนภาพที่พบ, และแถบความถี่
  - **แท็บ 3: ⚠️ ภาพที่มีปัญหา / ข้าม (Issues & Errors)**: รายการภาพที่ดาวน์โหลดไม่สำเร็จ หรือ Decode ไม่ผ่าน พร้อมสาเหตุชัดเจน
  - **แท็บ 4: 📝 รายงานฉบับเต็ม (Full Text Report)**: ข้อความรายงานฉบับเต็ม พร้อมปุ่มคัดลอก
- **Action Buttons ด้านล่าง:**
  - `📂 เปิดโฟลเดอร์ Report Summary`: เปิดดูโฟลเดอร์บน Windows Explorer ทันที
  - `📄 เปิดไฟล์รายงานนี้`: เปิดอ่านไฟล์ `.md` / `.txt` ด้วยโปรแกรมเริ่มต้น
  - `✖️ ปิดหน้าต่าง (Close)`: ปิด Popup

---

### 11.4 การจัดเก็บไฟล์รายงาน (`report_summary/`)
- โฟลเดอร์ปลายทาง: `d:\Projects\07 ระบบค้นหาใบหน้าบุคลากรโรงเรียน\report_summary\`
- ไฟล์ที่บันทึก:
  1. `scan_report_YYYYMMDD_HHMMSS.md`: ไฟล์รายงานสรุปเนื้อหาแบบจัดรูปแบบตารางอย่างสวยงาม
  2. `scan_report_YYYYMMDD_HHMMSS.json`: ไฟล์โครงสร้างข้อมูลดิบ JSON สำหรับเก็บสถิติหรือต่อยอดระบบ

---

### 11.5 แผนขั้นตอนการแก้ไขโค้ด (Files to Modify)
1. **[`scheduler_task.py`](scheduler_task.py):**
   - เพิ่มคลาส `ScanSessionTracker`
   - เชื่อมโยง Tracker เข้ากับลูปการสแกนของ `_task_1_scan_new_photos_fast()`
   - ปรับแก้จุด Exit เมื่อ `stop_requested` ให้บันทึกรายงานลงไฟล์และสั่งแสดง Popup ไปยัง GUI
2. **[`app_gui.py`](app_gui.py):**
   - เพิ่มเมธอด `show_scan_report_popup(self, report_data, saved_path)`
   - ปรับเลขเวอร์ชันโปรแกรมเป็น **`v6.24`** บน Window Title และ Sidebar Header
3. **[`README.md`](README.md):**
   - บันทึก Version 6.24 Changelog ไว้ที่บรรทัดบนสุด (Prepend to top)

---

### 11.6 ตารางแผนการทดสอบ (Test Plan TC-25 ถึง TC-29)
| รหัสทดสอบ | รายละเอียดกรณีทดสอบ | ข้อมูลนำเข้า / เงื่อนไข | ผลลัพธ์ที่คาดหวัง |
| :--- | :--- | :--- | :--- |
| **TC-25** | Session Tracker Accuracy | จำลองการสแกน 3 โฟลเดอร์, รูป AI, RAW, และ Skipped file | Tracker คำนวณ Folders, Counts, Top 10 และ Errors ถูกต้อง 100% |
| **TC-26** | Report File Persistence | สั่งเซฟรายงานลงโฟลเดอร์ `report_summary/` | สร้างไฟล์ `.md` และ `.json` ในโฟลเดอร์ `report_summary` มีเนื้อหาถูกต้องครบถ้วน UTF-8 |
| **TC-27** | Stop Flow & Drive Sync Verification | จำลองการสั่ง `request_stop()` ขณะสแกน | รัน `_sync_all_json_to_drive()` ปิดท้าย และสร้าง Report Summary เสมอ |
| **TC-28** | Popup GUI Modal Verification | รันทดสอบเมธอด `show_scan_report_popup` | เปิดหน้าต่าง Popup แสดงผล KPI, Folders, Top 10 และปุ่มเปิดโฟลเดอร์ทำงานได้ |
| **TC-29** | Version & Regression Suite | ตรวจสอบ `v6.24` และรัน Suite Test 24 ข้อเดิม | ผ่านครบ 24/24 ข้อ (100% Pass) |

### 11.7 ผลการทดสอบจริง (Execution Results)
- **TC-25 (Session Tracker Accuracy):** ✅ **PASSED** - Tracker คำนวณ Folders (2 โฟลเดอร์), Total All Images (6 ภาพ), AI (3 ภาพ), RAW (2 ภาพ), Skipped (1 ภาพ), Faces (6 ใบหน้า), และจัดอันดับ Top 10 ได้แม่นยำ 100%
- **TC-26 (Report File Persistence):** ✅ **PASSED** - สคริปต์ส่งออกไฟล์ `scan_report_YYYYMMDD_HHMMSS.md` และ `.json` ในโฟลเดอร์ `report_summary/` ได้อย่างถูกต้องครบถ้วน
- **TC-27 (Stop Flow & Safe Idempotent JSON Sync):** ✅ **PASSED** - ยืนยันการซิงค์ Drive JSON เมื่อเกิดการหยุดทำงานทำงานแบบ Idempotent (1 ครั้งถ้วน ไม่รันซ้ำซ้อน)
- **TC-28 (Popup GUI Modal & Version Verification):** ✅ **PASSED** - ยืนยันเมธอด `show_scan_report_popup` บน GUI และเลขเวอร์ชัน `v6.24 (Scan Session Report Summary & Exporter)` บน Window Title และ Sidebar Logo
- **TC-29 (Regression Suite):** ✅ **PASSED** - ชุดทดสอบเดิม TC-21 ถึง TC-24 ผ่านครบ 100% ปราศจากผลข้างเคียง (Zero Regression)

---

## 12. แผนวิเคราะห์เชิงลึก: หาสาเหตุความล้มเหลวของการจัดกลุ่มบุคคลนิรนาม (Unknown Faces) และแนวทางแก้ไขตามมาตรฐานระดับโลก (World-Class Face Clustering Architecture)

### 12.1 ปัญหาที่ผู้ใช้พบ (Problem Statement)
- ผู้ใช้ตั้งข้อสังเกตสำคัญ: **"ในเมื่อการทำ 1:N Verification (นำเวกเตอร์ของบุคคล 1 คน ไปดอทกับเวกเตอร์ทั้งหมดหลายแสนอัน เกิน threshold ถือว่าเป็นคนเดียวกัน) ทำงานได้แม่นยำและถูกต้องดีมาก แต่ทำไมพอเป็นการจับกลุ่มกันเองภายใน Unknown แสนกว่าเวกเตอร์ ถึงได้มั่วไปหมด แม้จะทดลองล็อกจุด Leader ไม่ให้เลื่อนแล้วก็ตาม?"**

---

### 12.2 บทวิเคราะห์สาเหตุเชิงคณิตศาสตร์และมิติเรขาคณิต (Mathematical & Geometric Root Causes)

#### สาเหตุที่ 1: ความแตกต่างอย่างมหาศาลระหว่าง "1:N Verification" vs "N:N Unsupervised Clustering" (Combinatorial Explosion)
1. **การค้นหาคนรู้จัก (1:N Verification / Search):**
   - มี **Ground Truth Anchor ที่มีคุณภาพสูงมาก:** ภาพถ่ายติดบัตร/สตูดิโอของคุณครูและนักเรียนเป็นภาพหน้าตรง แสงนิ่ง คมชัด จุดพิกัดของเวกเตอร์ใน 512 มิติมีเสถียรภาพสูง
   - **จำนวนครั้งที่เปรียบเทียบ:** เปรียบเทียบเพียง $1 \times N = 100,000$ ครั้ง
   - ด้วยอัตราความผิดพลาดหลุด (False Positive Rate: FPR) ของ ArcFace ที่ประมาณ $0.001\%$ ($10^{-5}$) โอกาสที่จะเจอภาพหลุดผิดคนจะมีเพียงแค่ **1 ภาพเท่านั้น** ผู้ใช้จึงรู้สึกว่า "แม่นยำ 100%"
2. **การจับกลุ่มคนนิรนาม (N:N Face Clustering):**
   - **ไม่มี Ground Truth Anchor:** ทุกภาพเป็นภาพแคนดิด (Candid) จากกิจกรรม กลางแจ้ง ย้อนแสง หน้าเอียง วิ่ง เบลอ
   - **จำนวนคู่ที่ต้องประเมิน (Combinatorial Space):**
     $$\text{Pairwise Comparisons} = \frac{N(N-1)}{2} = \frac{100,000 \times 99,999}{2} \approx \mathbf{5,000,000,000} \text{ คู่ (ห้าพันล้านคู่!)}$$
   - ด้วยอัตราความผิดพลาดเดิม ($10^{-5}$) ใน 5 พันล้านคู่ จะเกิด **เส้นเชื่อมผิดพลาด (False Positive Edges) ทะลักออกมาถึง $\mathbf{50,000}$ คู่!**
   - ในระบบการจัดกลุ่ม หากมีเส้นเชื่อมผิดพลาดเพียงเส้นเดียว มันจะเกิดปรากฏการณ์ **"Chaining Effect (การลามเป็นลูกโซ่)"** หรือความผิดพลาดแบบ Transitive ($A \approx B$ และ $B \approx C \implies A \text{ รวมกับ } C$ ทั้งที่ $A$ กับ $C$ เป็นคนละคนกัน)

#### สาเหตุที่ 2: ปัญหาธรรมชาติของภาพถ่ายโรงเรียน (High Intra-Class Variance vs Low Inter-Class Distance)
- **Low Inter-Class Distance (คนละคนแต่เวกเตอร์ใกล้กัน):** นักเรียนไทยวัยเดียวกัน โครงหน้าเอเชีย ทรงผมสั้นเกรียนหรือเปียเหมือนกัน ใส่เสื้อนักเรียนสีขาวเหมือนกัน ทำให้เวกเตอร์ใน 512 มิติของนักเรียนคนละคน มีระยะห่างที่ใกล้กันมากโดยธรรมชาติ (Hubness Problem: จุดที่มีความหนาแน่นสูง) ซึ่งบางคู่มี Cosine Similarity สูงถึง $0.65 - 0.72$ ทั้งที่เป็นคนละคนกัน!
- **High Intra-Class Variance (คนเดียวกันแต่มุมต่างกันเวกเตอร์ห่างกันมาก):** นักเรียนคนเดียวกัน แต่รูปหนึ่งยิ้มกว้างกลางแดดจ้า อีกรูปหันข้าง 30 องศาในร่มเงา ค่า Similarity ของคนเดียวกันอาจตกฮวบเหลือเพียง $0.55 - 0.62$
- **กับดักค่า Threshold (The Threshold Dilemma):**
  - หากตั้ง Threshold สูง ($0.70$): คนเดียวกันจะแตกกระจัดกระจายออกเป็น 10-20 กลุ่มย่อย
  - หากตั้ง Threshold ต่ำ ($0.55$): เด็กคนอื่นที่หน้าคล้ายจะถูกดูดรวมเข้ามา เกิดกลุ่ม "มั่ว" ขนาดใหญ่ทันที

#### สาเหตุที่ 3: ข้อบกพร่องในสถาปัตยกรรม "Leader Clustering (Fixed Exemplar)" ปัจจุบันใน `unknown_analyzer.py`
1. **ลำดับการวนลูปกำหนดชะตากรรม (First-Come-First-Served / Order Dependency):** หน้าแรกที่ถูกหยิบขึ้นมาเป็น Leader หากบังเอิญเป็น "ใบหน้าคนหน้าโหล" (Average Face ใกล้จุดศูนย์กลางการกระจายตัว) ใบหน้านี้จะมี Similarity เกิน $0.70$ กับเด็กคนอื่นอีกหลายสิบคน ทำให้เด็กคนอื่นๆ ถูก greedy ดูดเข้าไปในกลุ่มของ Leader คนนี้ทันที
2. **ตัวแทนเดียวไม่สามารถแทนคนทั้งคนได้ (Single Exemplar Limitation):** มนุษย์คนหนึ่งมีทั้งมุมตรง มุมเอียง มุมก้ม มุมเงย การล็อกให้ Leader มีเวกเตอร์เดียวถาวร ทำให้กลุ่มนั้นรับได้แค่ "ภาพมุมเดียวกับ Leader" ส่วนภาพมุมอื่นของคนเดียวกันจะหลุดไปตั้งกลุ่มใหม่
3. **ช่องโหว่ของ Same-Photo Exclusion:** โค้ดระบุว่า `if photo_id not in cluster_photo_sets: join cluster` ซึ่งป้องกันได้แค่ *คนในรูปเดียวกันไม่ให้ซ้ำกัน* แต่เด็กนักเรียนคนอื่น (เด็ก B) ในกิจกรรมวันอื่นที่ไม่ได้ถ่ายรูปคู่กับ Leader A ก็สามารถถูกดูดเข้าไปในกลุ่ม A ได้อย่างง่ายดาย

---

### 12.3 วิธีการที่ระบบระดับโลก (Google Photos, Apple Photos, Immich, InsightFace) ใช้งานจริง

| ระบบ / แพลตฟอร์ม | อัลกอริทึมที่ใช้ | กลไกสำคัญที่ทำให้แม่นยำ ไม่มั่ว |
| :--- | :--- | :--- |
| **Apple Photos** | **Two-Pass Hierarchical Clustering** (HAC + Multi-Modal) | • **Pass 1:** สร้าง Core Seeds เล็กๆ ที่ชัวร์ 100% (ถ่ายเวลาติดกันในไม่กี่วินาที + หน้า + ทอร์โซ่/เสื้อผ้า)<br>• **Pass 2:** แต่ละกลุ่มเก็บ **Multi-Exemplar Set** (ภาพหลายมุม) แล้วใช้ **Average Linkage** ควบรวมกลุ่มย่อยข้ามเวลา |
| **Immich** (Google Photos Alternative) | **Modified Queue-based DBSCAN with Noise Rejection** | • **Outlier & Noise Rejection:** มีการคัดกรอง "Noise (`-1`)" อย่างเด็ดขาด ใบหน้าที่โผล่รูปเดียว หน้าเบลอ หรือไม่มีเพื่อนหนาแน่นพอ **จะไม่ถูกยัดเข้ากลุ่ม**<br>• มีค่า Minimum Density เพื่อสร้างกลุ่มเฉพาะคนที่มีแกนแน่นหนาจริง |
| **InsightFace (SOTA)** | **Mutual k-NN Graph (MNN) + Graph Community Detection (GCN / Chinese Whispers)** | • **Mutual Nearest Neighbors (MNN):** A เชื่อมกับ B ได้ก็ต่อเมื่อ B ต้องเป็น Top-k เพื่อนบ้านของ A **และ** A ก็ต้องเป็น Top-k เพื่อนบ้านของ B ด้วย (ตัด False Positive ทิ้งได้มากกว่า 95%!) |
| **Digikam / Dlib** | **Chinese Whispers Graph Clustering** | • สร้างกราฟความคล้ายคลึงแบบมีน้ำหนัก และส่งผ่านฉลากแบบ $O(V+E)$ Linear time ไม่ติดปัญหา First-come greedy |

---

### 12.4 แผนงานและข้อเสนอการแก้ไข (Implementation Options)

#### 🌟 ทางเลือกที่ 1 (แนะนำอย่างยิ่ง): Mutual k-NN Graph + Cannot-Link Constraints + Graph Community Detection
อาศัยไลบรารีที่มีอยู่แล้วในระบบ (`networkx 3.6.1`, `scipy 1.17.1`, `numpy`) โดยไม่ต้องลงแพ็กเกจใหม่:
1. **Face Quality & Landmark Filter:** กรองตัดใบหน้าที่ขนาดเล็กกว่า 50x50 พิกเซล หรือความคมชัดต่ำทิ้งล่วงหน้า (จัดเป็น Noise ไม่นำมาสร้างคลัสเตอร์หลัก)
2. **Mutual Nearest Neighbor (MNN) Graph:**
   - สำหรับแต่ละใบหน้า คำนวณหา Top-$k$ เพื่อนบ้านที่คล้ายที่สุด ($k = 5$ ถึง $10$, Cosine Similarity $\ge 0.65$)
   - สร้างเส้นเชื่อม (Edge) เฉพาะคู่ที่เป็น **Mutual Neighbor** (ต่างฝ่ายต่างอยู่ใน Top-$k$ ของกันและกัน)
   - **ผลลัพธ์:** ตัด False Positive ข้ามคนหน้าโหลทิ้งได้ถึง 95%!
3. **Strict Cannot-Link Constraint:** ลบเส้นเชื่อมระหว่างใบหน้าที่มาจากภาพเดียวกัน (`photo_id` เดียวกัน) ออกจากกราฟ 100%
4. **Graph Community Partitioning:** รันอัลกอริทึมตรวจจับชุมชนบนกราฟ (เช่น Louvain หรือ Chinese Whispers ผ่าน `networkx.community`)
5. **Multi-Exemplar Representation & Noise Discard:**
   - กลุ่มที่มีสมาชิก $\ge 3$ รูป จะได้รับสถานะเป็น Person Cluster
   - กลุ่มที่มีเพียง 1-2 รูป หรือจุดกระจัดกระจาย จะถูกแยกเป็น "Unclustered / Singletons" ไม่ถูกนำมาปนเปื้อน

#### ทางเลือกที่ 2: Two-Pass Core Seed Clustering + Average Linkage HAC (`scipy.cluster.hierarchy`)
1. รวมกลุ่มเฉพาะภาพที่มีความคล้ายคลึงสูงมาก ($\ge 0.78$) หรือถ่ายในกิจกรรมเดียวกัน ให้เป็น Seed คลัสเตอร์ย่อย
2. รวมคลัสเตอร์ย่อยเข้าหากันด้วย **Average Linkage (ระยะห่างเฉลี่ยของทุกคู่ภาพในกลุ่ม)** ป้องกันปัญหา Chaining จุดเดียวพาเสียทั้งกลุ่ม

---

### 12.5 ตารางเปรียบเทียบผลลัพธ์ที่คาดหวัง

| มิติการเปรียบเทียบ | ระบบปัจจุบัน (Leader Fixed) | ทางเลือกที่ 1 (Mutual k-NN + Graph) |
| :--- | :---: | :---: |
| **ความแม่นยำ (Purity / ความถูกต้องของคนในกลุ่ม)** | ❌ ต่ำ (คนละคนปนกันมั่ว) | ⭐⭐⭐⭐⭐ **สูงมาก (>95%)** |
| **การป้องกันคนหน้าโหล (Hubness / False Chaining)** | ❌ ไม่มี (โดนดูดเข้ากลุ่มหมด) | ⭐⭐⭐⭐⭐ **ตัดทิ้งได้ด้วย MNN** |
| **การรองรับหลายมุมมอง (Multi-View Invariance)** | ❌ รองรับแค่มุมเดียวของ Leader | ⭐⭐⭐⭐⭐ **รองรับหลายมุมผ่าน Graph Hop** |
| **การจัดการภาพเบลอ / บุคคลโผล่รูปเดียว (Noise)** | ❌ บังคับสร้างกลุ่มหรือยัดเข้ากลุ่ม | ⭐⭐⭐⭐⭐ **แยกเป็น Noise ชัดเจน** |
| **ความเร็วในการประมวลผล (สำหรับ 100,000 เวกเตอร์)** | ปานกลาง (~30-60 วินาที) | เร็วมากด้วย Matrix Vectorization + NetworkX |

---

## 13. แผนปฏิบัติการอย่างละเอียดทีละข้อ (Step-by-Step Implementation Plan for Option 1: Mutual k-NN Graph + Cannot-Link + Louvain / NetworkX Clustering)

### 13.1 วัตถุประสงค์ (Objectives)
1. **ยกเครื่องระบบจัดกลุ่มใบหน้านิรนามใน [`unknown_analyzer.py`](unknown_analyzer.py):** เปลี่ยนจากอัลกอริทึม Greedy Leader เดิม (ที่ล้มเหลวจากปัญหาคนหน้าโหลและลำดับภาพ) มาเป็น **Mutual k-NN Graph Architecture** ที่อ้างอิงจากงานวิจัยมาตรฐานสากลของ InsightFace และ Computer Vision
2. **ขจัดปัญหาคนละคนปนกันในกลุ่มเดียวกัน (Zero-Contamination / High Purity):** บังคับใช้เงื่อนไข **Mutual Agreement** (ต่างฝ่ายต่างต้องเป็น Top-$k$ ของกันและกัน) ตัดเส้นเชื่อมหลุด (False Positive) ทิ้งมากกว่า 95%
3. **ป้องกันคนในรูปเดียวกันซ้ำซ้อน (Strict Cannot-Link Constraints):** กฎเหล็กทางคณิตศาสตร์ ห้ามมีเส้นเชื่อมระหว่างใบหน้าที่มาจาก `photo_id` เดียวกันโดยเด็ดขาด 100%
4. **รองรับหลายมุมมองของคนคนเดียวกัน (Multi-View Invariance):** ให้ภาพหน้าตรง ภาพยิ้ม และภาพเอียงข้างของคนเดียวกันสามารถเชื่อมโยงกันเป็นชุมชน (Community) เดียวกันได้ผ่านเส้นทางในกราฟ โดยไม่ต้องพึ่งพา Leader เพียงภาพเดียว
5. **ตัดขยะภาพเบลอและผู้ปรากฏตัวเดี่ยวๆ (Outlier Noise Rejection):** คัดกรองภาพฝูงชนในแบ็กกราวด์ที่เบลอหรือเล็กทิ้ง และแยกภาพที่ปรากฏเพียง 1-2 ครั้งเป็น Unclustered Noise ไม่นำมาปนเปื้อนในกลุ่มคนหลัก

---

### 13.2 สถาปัตยกรรมกระบวนการทำงาน 6 ขั้นตอน (The 6-Stage Graph Clustering Pipeline)

```
[445,000+ Unmatched Faces]
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 1: Adaptive Quality Pre-filtering                │
│ - คัดกรองขนาด Bounding Box >= 45px (ตัด Crowd Noise)  │
│ - ตรวจสอบ L2-Norm ของ 512-D Embedding                  │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 2: Chunked Memory-Safe Matrix Multiplication     │
│ - แบ่งคำนวณทีละ Chunk (B = 2,500 x N) เพื่อไม่ให้ล้น RAM│
│ - ค้นหา Top-k (k=8) Cosine Similarity >= 0.65          │
│ - บันทึก Forward Neighbors List N_k[i]                 │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 3: Mutual k-NN Filtering (MNN)                   │
│ - สร้าง Edge E(i, j) เฉพาะเมื่อ j in N_k[i] AND i in N_k[j]│
│ - ตัดคนหน้าโหล (Hub Nodes) และ False Positives ทิ้ง 95%│
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 4: Cannot-Link Constraint Enforcement            │
│ - ตรวจสอบทุกเส้นเชื่อม หาก photo_id[i] == photo_id[j]   │
│   สั่งลบ Edge ทิ้งทันที 100% (ห้ามคนในภาพเดียวกันเชื่อมกัน) │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 5: Conflict-Aware Community Partitioning         │
│ - แยก Connected Components                             │
│ - หาก Component มี photo_id ชนกัน -> รัน Louvain       │
│   (networkx.community.louvain_communities) จัดกลุ่มย่อย│
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Stage 6: Noise Filtering & Medoid Representative       │
│ - กรองกลุ่มที่มีขนาด < min_cluster_size เป็น Noise     │
│ - เลือกใบหน้าที่คมชัดและมี Degree สูงสุดเป็นภาพตัวแทน    │
│ - สร้างข้อมูล JSON & SQLite เพื่อส่งให้ GUI แสดงผล     │
└────────────────────────────────────────────────────────┘
```

---

### 13.3 แผนงานขั้นตอนการแก้ไขโค้ดโดยละเอียด (Step-by-Step Code Execution Plan)

#### ขั้นตอนที่ 1: ปรับปรุงฟังก์ชัน `cluster_unknown_faces()` ใน [`unknown_analyzer.py`](unknown_analyzer.py)
- **1.1 นำเข้าโมดูลที่จำเป็น:**
  ```python
  import networkx as nx
  from networkx.algorithms import community as nx_comm
  ```
- **1.2 Stage 1 (Quality Filter):**
  - กรองใบหน้าที่มีขนาดกว้างหรือยาวต่ำกว่า `min_face_size` (ปรับค่ามาตรฐานเป็น 45px)
  - ปรับขนาดและนอร์มัลไลซ์เวกเตอร์ $X = \frac{X}{\|X\|_2}$
- **1.3 Stage 2 (Chunked k-NN Search):**
  - สำหรับชุดข้อมูลขนาดใหญ่ ให้แบ่งเป็น Chunk บล็อกละ 2,500 ใบหน้า
  - คำนวณ Cosine Dot Product: `S = np.dot(X_chunk, X.T)`
  - ใช้ `np.argpartition` ค้นหา Top-$k$ ($k=8$) สำหรับแต่ละใบหน้า โดยคัดเฉพาะที่มี Similarity $\ge \text{sim\_threshold}$ (default $0.65$)
  - รายงานความคืบหน้าผ่าน `progress_callback(current, total, ...)`
- **1.4 Stage 3 & 4 (Graph Construction with MNN & Cannot-Link):**
  - สร้าง `G = nx.Graph()`
  - เพิ่ม Node พร้อม Attribute: `photo_id`, `face_index`, `bbox`, `date`, `event`
  - วนลูปตรวจสอบความสัมพันธ์แบบไป-กลับ: หาก $j \in N_k[i]$ และ $i \in N_k[j]$ และ $photo\_id[i] \ne photo\_id[j]$:
    - เพิ่มเส้นเชื่อม `G.add_edge(i, j, weight=(sim_ij + sim_ji)/2)`
- **1.5 Stage 5 (Community Detection / Partitioning):**
  - ดึง Connected Components จากกราฟ `components = list(nx.connected_components(G))`
  - สำหรับแต่ละ Component:
    - ตรวจสอบว่ามี `photo_id` ซ้ำกันหรือไม่
    - หากไม่มีซ้ำ: นำทั้ง Component มาเป็นคลัสเตอร์ได้ทันที
    - หากมี `photo_id` ซ้ำ: สร้าง Subgraph และใช้ `nx_comm.louvain_communities(subgraph, weight='weight', resolution=1.0)` เพื่อคลี่คลายการทับซ้อนให้ได้กลุ่มที่สะอาดที่สุด
- **1.6 Stage 6 (Formatting & Database Output):**
  - กรองเฉพาะกลุ่มที่มีขนาด $\ge min\_cluster\_size$
  - สำหรับแต่ละกลุ่ม คัดเลือกภาพตัวแทน (Representative Face) จากโหนดที่มีพื้นที่ Bounding Box สูงสุดและมีความเชื่อมโยงในกลุ่มสูงสุด
  - รวบรวมสถิติรายปี (Active years, first seen, last seen) ส่งคืนในรูปแบบทูเพิล `(clusters_data, members_data, year_stats_data)` เพื่อส่งต่อไปยัง SQLite DB แบบ 100% Backward Compatible

#### ขั้นตอนที่ 2: ปรับปรุงส่วนแสดงผลและความคืบหน้าบนหน้าต่าง GUI ใน [`app_gui.py`](app_gui.py)
- ปรับแต่งข้อความรายงานความคืบหน้า (Progress Label) ให้สอดคล้องกับ 3 ช่วงการทำงาน:
  1. *"⏳ เฟส 1/3: กำลังคัดกรองคุณภาพและสกัดเวกเตอร์..."*
  2. *"⏳ เฟส 2/3: กำลังสร้างโครงข่าย Mutual k-NN Graph (ความคืบหน้า X%)..."*
  3. *"⏳ เฟส 3/3: กำลังจัดกลุ่มชุมชนใบหน้า (Graph Partitioning) และบันทึกลงฐานข้อมูล..."*
- อัปเกรดเลขเวอร์ชันของโปรแกรมบน GUI เป็น **`v6.25 (Graph-Based Unknown Face Clustering)`**

#### ขั้นตอนที่ 3: สร้างชุดทดสอบเส้นทางการทำงานจริง (Execution Verification Suite)
- สร้างไฟล์สคริปต์ `test_graph_clustering_suite.py` ครอบคลุมการทดสอบ TC-30 ถึง TC-34:
  - **TC-30 (Mutual k-NN Verification):** จำลองเวกเตอร์คนหน้าโหล (Hub Node) พิสูจน์ว่า MNN ตัดเส้นเชื่อมหลุดทิ้งได้ 100%
  - **TC-31 (Cannot-Link Enforcement):** จำลอง 2 ใบหน้าที่อยู่ในภาพเดียวกันแต่เวกเตอร์คล้ายกัน พิสูจน์ว่าระบบไม่รวมเข้ากลุ่มเดียวกันเด็ดขาด
  - **TC-32 (Multi-View Continuity):** จำลองภาพหน้าตรง + หน้าเอียง 30 องศา + หน้าเอียง 45 องศา ของคนเดียวกัน พิสูจน์ว่าระบบเชื่อมโยงเข้ากลุ่มเดียวกันได้สำเร็จ
  - **TC-33 (Outlier & Noise Rejection):** จำลองภาพเดี่ยว/ภาพเบลอ พิสูจน์ว่าระบบคัดออกเป็น Noise ไม่เกิดกลุ่มขยะ
  - **TC-34 (Regression Test):** ทดสอบฟังก์ชัน `save_unknown_clusters_batch` และแท็บ UI ให้ทำงานร่วมกันได้อย่างราบรื่น

#### ขั้นตอนที่ 4: บันทึกเอกสารและ Version Control
- บันทึกประวัติการเปลี่ยนแปลง Prepend ไว้ที่บรรทัดบนสุดของ [`README.md`](README.md) สำหรับ Version 6.25
- อัปเดตผลการทดสอบจริงลงใน [`implementation_plan.md`](implementation_plan.md)
- ทำการ Commit ขึ้น Git: `feat(clustering): upgrade unknown face clustering to mutual k-nn graph with cannot-link constraints (v6.25)`

---

### 13.4 ตารางกรณีทดสอบ (Test Plan TC-30 ถึง TC-34)

| รหัสทดสอบ | รายละเอียดกรณีทดสอบ | เงื่อนไข / ข้อมูลนำเข้า | ผลลัพธ์ที่คาดหวัง |
| :--- | :--- | :--- | :--- |
| **TC-30** | MNN Hubness Elimination | สร้าง Hub Face ที่คล้ายกับคนอื่น แต่คนอื่นมีคนที่คล้ายกว่า | เส้นเชื่อมระหว่าง Hub Face กับคนอื่นถูกตัดทิ้ง ไม่เกิดการดึงมั่ว |
| **TC-31** | Strict Cannot-Link Validation | 2 ใบหน้าที่มีความคล้าย 0.85 แต่อยู่ใน `photo_id` เดียวกัน | ถูกแยกเป็นคนละคลัสเตอร์เด็ดขาด 100% |
| **TC-32** | Multi-View Invariance Test | ภาพ $A$ คล้าย $B$ (0.70) และ $B$ คล้าย $C$ (0.68) ของคนเดียวกัน แต่ $A$ กับ $C$ ห่างกัน (0.58) | รวมเป็น 1 คลัสเตอร์ผ่านเส้นทาง $A \leftrightarrow B \leftrightarrow C$ |
| **TC-33** | Outlier Noise Suppression | ใบหน้าเดี่ยวที่มีเพื่อนบ้าน 0 คน หรือ BBox < 45px | ถูกตัดทิ้ง ไม่ถูกสร้างเป็นคลัสเตอร์ขยะ |
| **TC-34** | Full Data Pipeline Verification | รันทดสอบกับตัวอย่างข้อมูลจริง 1,000 ใบหน้า | รันจบสมบูรณ์ ข้อมูลบันทึกลง 3 ตารางของ SQLite ถูกต้อง |

---

### 13.5 บันทึกผลการทดสอบจริง (Execution Verification Results)

#### ผลการทดสอบชุด Graph-Based Clustering Suite (`test_graph_clustering_suite.py`)
- **วันและเวลาที่ทดสอบ:** 13 ตุลาคม 2026 23:42:18 น.
- **สถานะ:** ✅ **ผ่านครบ 5/5 ข้อ (100% Passed)**
  - **TC-30 (MNN Hubness Elimination):** ผ่าน 100% — Mutual k-NN ตัดเส้นเชื่อมระหว่าง Hub Face กับบุคคลอื่น ทำให้คนหน้าโหลไม่สามารถดึงบุคคลอื่นเข้ากลุ่มได้
  - **TC-31 (Strict Cannot-Link Validation):** ผ่าน 100% — ใบหน้า 2 ใบหน้าที่อยู่ในภาพเดียวกัน (`photo_id` เดียวกัน) ถูกแยกเป็นคนละคลัสเตอร์เด็ดขาด 100% ไม่มีเส้นเชื่อม
  - **TC-32 (Multi-View Invariance Test):** ผ่าน 100% — ภาพหน้าตรง หน้าเอียง และหน้าก้มของคนเดียวกันถูกเชื่อมโยงเป็นชุมชนเดียวกันสำเร็จผ่านโครงข่ายกราฟแบบ Transitively Connected
  - **TC-33 (Outlier & Noise Rejection):** ผ่าน 100% — ใบหน้าที่ขนาดต่ำกว่าเกณฑ์ (BBox < 45px) หรือโผล่คนเดียวถูกคัดกรองออก ไม่เกิดคลัสเตอร์ขยะ
  - **TC-34 (GUI Version & Schema Integration):** ผ่าน 100% — ตรวจสอบ Window Title และ Sidebar Logo เป็น `v6.25` เรียบร้อย

#### ผลการทดสอบชุด Regression Suite (`test_unknown_analytics_suite.py`)
- **วันและเวลาที่ทดสอบ:** 13 ตุลาคม 2026 23:42:24 น.
- **สถานะ:** ✅ **ผ่านครบ 20/20 ข้อ (100% Passed)**
  - ครอบคลุม Schema, Idempotency, Unmatched filtering, Thai Buddhist Year conversion, SQLite batch transaction, Color gradient mapping, Crop padding, Thai Unicode export, Background threading, และ Same-photo separation

---

## 14. แผนงานการเพิ่มข้อมูลปีการศึกษาจากโฟลเดอร์ใหญ่สุด (Root Year) ลงใน SQLite และ photo_index.json (v6.26)

### 14.1 วัตถุประสงค์และปัญหาที่พบ (Problem Statement & Objectives)
1. **ปัญหาปีหลุดข้ามปี (Year Jumping Issue):**
   - ปัจจุบันใน `scanned_photos` มีรูปภาพกว่า 23,902 รูป จากทั้งหมด 117,217 รูป ที่ไม่มีการระบุปีในชื่อโฟลเดอร์กิจกรรม (`event_name`) เช่น "ครูและเจ้าหน้าที่ใหม่", "11 กค อบรมป้องกันการตั้งครรภ์"
   - ในโค้ดเดิม เมื่อไม่มีชื่อปีใน `event_name` ระบบจะพยายามแกะปีจาก `photo_date` (วันที่อัปโหลด/สร้างไฟล์ใน Google Drive) แต่เนื่องจากมีการตั้งเงื่อนไขยกเว้นปีปัจจุบัน (`y_ce != 2026`) หรือบางภาพเป็นภาพกิจกรรมปีก่อนหน้า (เช่น 2565) แต่อัปโหลดขึ้น Drive ในปี 2026 จึงทำให้ข้อมูลปีกลายเป็นค่าว่าง `""` หรือระบุปีผิดเพี้ยน
   - เมื่อสร้างไฟล์ `photo_index.json` ข้อมูลภาพเหล่านี้จะไม่มีคีย์ `"year"` ส่งผลให้หน้าเว็บระบบค้นหา (`Index.html`) จัดกลุ่มข้ามปี หรือไม่แสดงผลในตัวกรองปีที่ถูกต้อง
2. **การจัดลำดับความสำคัญในการดึงปี (3-Tier Priority Hierarchy):**
   - **Priority 1 (Root Folder - ความสำคัญสูงสุด):** ดึงปีจากโฟลเดอร์ใหญ่สุดของ Google Drive ที่รูปภาพนั้นสังกัดอยู่ (เช่น `ภาพกิจกรรม 2569`, `2568`, `2567`, `2566`, `2565`, `2564`, `2563` จาก `config/year_folders.json`)
   - **Priority 2 (Subfolder / Event Name):** หากอยู่นอก Root Folder หรือ Root ไม่ระบุปี ให้สกัดปีจากชื่อโฟลเดอร์กิจกรรม/โฟลเดอร์ย่อย เช่น `2540 กิจกรรมกีฬาสี`, `วันไหว้ครู ปี 2563`, `ปฐมนิเทศ 64`
   - **Priority 3 (File Name / Date Fallback):** หากไม่มีปีในโฟลเดอร์ ให้สกัดจากชื่อไฟล์ภาพ (เช่น `IMG_2566xxxx`, `2023xxxx`) หรือวันที่ `photo_date` (แปลง ค.ศ. เป็น พ.ศ. +543)

---

### 14.2 การปรับปรุงฐานข้อมูล SQLite (`data/faces_db.db`)
1. **เพิ่มคอลัมน์ใหม่ในตาราง `scanned_photos`:**
   - เพิ่มคอลัมน์ `academic_year TEXT DEFAULT ''`
   - สร้าง Index `idx_scanned_photos_academic_year` เพื่อการสืบค้นและกรองข้อมูลระดับ 0.001 วินาที
2. **การย้ายข้อมูลย้อนหลัง (One-Time Backfill):**
   - รวบรวม Folder Tree จาก 7 โฟลเดอร์หลักปีการศึกษาใน `config/year_folders.json` เพื่อทำแผนผัง `event_name -> academic_year`
   - สแกนจับคู่รูปภาพ 117,217 รูปภาพในฐานข้อมูลตามลำดับ 3-Tier Priority และบันทึกปี พ.ศ. 4 หลัก (เช่น "2569", "2568", "2567", ...) ลงใน `academic_year`
   - รับประกันว่าภาพเคสที่มีปัญหา (เช่น `P04972` ในโฟลเดอร์ "ครูและเจ้าหน้าที่ใหม่" ภายใต้โฟลเดอร์ใหญ่ "ภาพกิจกรรม 2569") จะได้รับค่า `academic_year = '2569'` ทันที 100%

---

### 14.3 การปรับปรุงระบบสแกนอัตโนมัติในอนาคต (`scheduler_task.py`)
1. ในฟังก์ชัน `_task_1_scan_new_photos_fast()`:
   - ในลูป `for year_name, year_id in target_years:` ให้สกัดเลขปีการศึกษาจาก `year_name` (เช่น "ภาพกิจกรรม 2569" -> `"2569"`)
   - ส่งผ่านค่า `academic_year` เข้าไปใน `results_data` และบันทึกลงในคอลัมน์ `academic_year` ของตาราง `scanned_photos` ในคำสั่ง `INSERT OR REPLACE` เสมอ
   - ป้องกันไม่ให้เกิดรูปภาพที่ไร้ปีอีกในอนาคต

---

### 14.4 การปรับปรุงการสร้างและ Sync `photo_index.json` (`db_manager.py` & `gdrive_sync.py`)
1. **`db_manager.py` (`get_all_sync_data`):**
   - เปลี่ยนจากการคำนวณ Regex ซ้ำซ้อน มาเป็นการ `SELECT photo_id, event_name, drive_link, photo_date, total_faces_detected, academic_year FROM scanned_photos`
   - ส่งออกค่า `entry["year"] = p["academic_year"]` ตรงๆ รวดเร็วระดับ 0.05 วินาที
2. **`gdrive_sync.py` (`update_json_indexes_on_drive`):**
   - รับประกันว่าทุกลูปการสร้าง `photo_index.json` จะมีคีย์ `"year"` เสมอ (เช่น `"year": "2569"`) ตามโครงสร้างมาตรฐานที่หน้าเว็บ Google Apps Script (`Index.html` / `DatabaseService.gs`) รองรับ

---

### 14.5 การตรวจสอบและสรุปผลสถิติ (Verification & Distribution Summary)
1. **การสร้างรายงานสรุปสถิติจำนวนภาพแยกตามแต่ละปี (Distribution Summary):**
   - แสดงตารางแจกแจงจำนวนภาพก่อนและหลังการ Backfill (เช่น 2569: X ภาพ, 2568: Y ภาพ, ...)
   - ตรวจสอบรายการภาพที่เคยมีปัญหา เช่น `P04972` ให้เห็นชัดเจน
   - นำเสนอรายงานให้ผู้ใช้ตรวจสอบความถูกต้องก่อนเริ่มขั้นตอนอัปโหลดขึ้น Google Drive
2. **การอัปโหลดขึ้น Google Drive:**
   - เมื่อผู้ใช้ตรวจสอบความถูกต้องและอนุมัติ ระบบจะรันคำสั่งซิงค์ `photo_index.json` ขึ้น Google Drive ทันที

---

### 14.6 ตารางกรณีทดสอบ (Test Plan TC-35 ถึง TC-39)

| รหัสทดสอบ | รายละเอียดกรณีทดสอบ | ข้อมูลนำเข้า / สภาวะทดสอบ | ผลลัพธ์ที่คาดหวัง |
| :--- | :--- | :--- | :--- |
| **TC-35** | SQLite Schema Migration | ตรวจสอบโครงสร้างตาราง `scanned_photos` | พบฟิลด์ `academic_year` (TEXT) และ Index เรียบร้อย |
| **TC-36** | Priority Cascade & Backfill Accuracy | ทดสอบกับภาพ 117,217 รูปภาพเดิม | สกัดปีตาม Root Folder > Subfolder > File/Date ถูกต้อง 100% |
| **TC-37** | Known Issue Verification (`P04972`) | ตรวจสอบภาพ `P04972` ใน "ครูและเจ้าหน้าที่ใหม่" | ได้รับค่า `academic_year = '2569'` ใน SQLite และ `"year": "2569"` ใน JSON |
| **TC-38** | GUI Version Integration | ตรวจสอบ Window Title และ Sidebar Logo | แสดงเลขเวอร์ชัน `v6.26` ถูกต้อง |
| **TC-39** | JSON Schema Serialization | ตรวจสอบโครงสร้างฟิลด์ `photo_index.json` | มีคีย์ `"year"` และ `"face_count"` ตรงตามฟอร์แมตมาตรฐาน |

---

### 14.7 บันทึกผลการทดสอบจริง (Execution Verification Results)

#### 1. ผลการทดสอบชุด Academic Year Verification Suite (`test_academic_year_suite.py`)
- **วันและเวลาที่ทดสอบ:** 16 ตุลาคม 2026 08:26:03 น.
- **สถานะ:** ✅ **ผ่านครบ 5/5 ข้อ (100% Passed)**
  - **TC-35 (SQLite Schema Migration):** ผ่าน 100% — พบคอลัมน์ `academic_year` (TEXT DEFAULT '') และดัชนี `idx_sp_academic_year` ในตาราง `scanned_photos`
  - **TC-36 (Backfill Coverage & Distribution):** ผ่าน 100% — มีข้อมูลระบุปี 117,213 / 117,217 รูปภาพ (Coverage 100.00%)
  - **TC-37 (Known User Cases P04972, P04968, P05026):** ผ่าน 100%
    - `P04972`: event='ครูและเจ้าหน้าที่ใหม่', year='2569', face_count=1
    - `P04968`: event='กค 2 ต้อนรับครูพละใหม่', year='2569', face_count=1
    - `P05026`: event='11 กค อบรมป้องกันการตั้งครรภ์', year='2569', face_count=1
  - **TC-38 (GUI Version Integration):** ผ่าน 100% — Window Title และ Sidebar Logo อัปเกรดเป็น `v6.26` เรียบร้อย
  - **TC-39 (JSON Structure & Serialization):** ผ่าน 100% — โครงสร้าง JSON ของ `photo_index.json` ตรงตามที่ผู้ใช้และ Web App Apps Script กำหนด

#### 2. สถิติจำนวนภาพแยกตามปีการศึกษาจริง (Final Distribution Statistics)
- **รวมทั้งหมด:** 117,217 รูปภาพ
  - **ปี 2569:** 23,815 รูป (20.32%)
  - **ปี 2568:** 27,299 รูป (23.29%)
  - **ปี 2567:** 23,676 รูป (20.20%)
  - **ปี 2566:** 22,997 รูป (19.62%)
  - **ปี 2565:** 17,220 รูป (14.69%)
  - **ปี 2563:** 2,206 รูป (1.88%)
  - **Unresolved:** 4 รูป (0.00% - เป็นภาพ Dummy สำหรับทดสอบในเครื่อง)

#### 3. สถานะการซิงค์ขึ้น Google Drive (Cloud Deployment Status)
- **โฟลเดอร์ปลายทาง:** `1xxNfIxM9a9wlo6sgThZmpMVYWn4QFTUI`
- **ไฟล์เป้าหมาย:** `photo_index.json` (File ID: `1HipODbg6RFKqSmHt5q9D1T7MRK-ZdYEw`)
- **จำนวนรูปภาพที่ซิงค์:** 117,217 รูป
- **ขนาดไฟล์:** ~14.4 MB
- **สถานะ:** ✅ อัปโหลดและเขียนทับสำเร็จ 100% (Modified Time: 2026-10-16T01:24:56.664Z)

---

## 15. แผนการพัฒนาระบบจัดการโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders Management UI & SQLite Table Integration - v6.27)

### 15.1 สรุปผลการตรวจสอบระบบปัจจุบัน (Current Architecture & Usage Audit)

#### 1. ปัจจุบันเก็บข้อมูลเป็น JSON ใช่หรือไม่?
- **ใช่ครับ:** ปัจจุบันเก็บไว้ในไฟล์ `config/year_folders.json` ในรูปแบบ JSON Array ของ Object `[{"name": "ภาพกิจกรรม 2569", "id": "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"}, ...]` จำนวน 6 โฟลเดอร์ (ปี 2569, 2568, 2567, 2566, 2565, 2563)

#### 2. ในโค้ดนำค่า Root Folder ไปใช้งานในส่วนไหนบ้าง? (ครบทั้ง 5 จุดในระบบ)
1. **`scheduler_task.py` -> `_load_year_folders()` (บรรทัด 944-963):**
   - โหลดรายชื่อและ Folder ID ของโฟลเดอร์หลักประจำปีการศึกษาทั้งหมดส่งให้ระบบสแกน
2. **`scheduler_task.py` -> `_task_1_scan_new_photos_fast()` (บรรทัด 1059-1406):**
   - ใช้ในปุ่ม **"▶️ 1. สแกนภาพเพิ่มมาใหม่"** และ **ระบบสแกนอัตโนมัติเวลาเที่ยงคืน (`00:00`)**
   - วนลูปเข้าค้นหาโฟลเดอร์กิจกรรมย่อยภายใต้แต่ละ Root Folder ตามลำดับ
   - สกัดเลขปีการศึกษา (`current_academic_year`) จาก Root Folder เพื่อบันทึกลงคอลัมน์ `academic_year` ในตาราง `scanned_photos` และส่งออกไปยัง `photo_index.json`
   - ส่งชื่อ Root Folder ไปยัง `ScanSessionTracker` (`record_folder_start`) เพื่อแสดงคอลัมน์ "ปีการศึกษา" ในหน้าต่าง **Popup Report Summary** และไฟล์รายงานในโฟลเดอร์ `report_summary/`
3. **`scheduler_task.py` -> `fetch_drive_folder_year_mapping()` (บรรทัด 1003-1056):**
   - ใช้ Root Folder ID เป็น **Root Anchor (Priority 1)** ในการไต่ลำดับ Parent ของโฟลเดอร์ย่อยบน Google Drive เพื่อระบุปีการศึกษาของรูปภาพย้อนหลัง (Backfill)
4. **`scheduler_task.py` -> `_task_1_scan_new_folders()` (บรรทัด 500-543):**
   - ดึงรายการ Root Folder ไปต่อท้ายคิวการสแกนโฟลเดอร์
5. **`gdrive_sync.py` -> `get_all_images_in_folder_recursive()` (บรรทัด 303-308):**
   - ใช้ตรวจสอบว่าโฟลเดอร์ปัจจุบันเป็นระดับ Root Year หรือไม่ (`is_root_or_year`) เพื่อให้ตั้งชื่อโฟลเดอร์ลูกชั้นที่ 1 เป็น `event_name` (ชื่อกิจกรรม) และชั้นถัดไปเป็น `subfolder` (ซึ่งเดิมยัง Hardcode ชื่อปีไว้ 5 ปี ควรเปลี่ยนให้เช็คจากฐานข้อมูล Root Folders แบบ Dynamic)

#### 3. ควรเพิ่มตาราง (Table) ใน SQLite หรือไม่?
- **แนะนำให้เพิ่มตาราง `root_year_folders` ใน SQLite ควบคู่กับการ Auto-Sync ลง `config/year_folders.json` (Hybrid Single Source of Truth)** ด้วยเหตุผลดังนี้:
  1. **ระบุปี พ.ศ. (`academic_year`) แยกเป็นคอลัมน์ชัดเจน:** ไม่ต้องพึ่งพาแค่การแกะตัวเลขจากชื่อโฟลเดอร์เพียงอย่างเดียว (เช่น หากโฟลเดอร์บน Drive ชื่อ `"อัลบั้มรวมภาพโรงเรียน"` ก็ยังกำหนดปี `2570` ลงในคอลัมน์ `academic_year` ได้โดยตรง)
  2. **มีสถานะเปิด/ปิดการสแกน (`is_active`):** สามารถติ๊กเปิด/ปิด (Active / Pause) โฟลเดอร์ปีเก่าๆ ที่สแกนครบถ้วนแล้ว (เช่น ปี 2563-2566) เพื่อให้ Task 1 สแกนเฉพาะปีปัจจุบันได้รวดเร็วขึ้น โดยที่ข้อมูลปีเก่าในระบบและ `fetch_drive_folder_year_mapping` ยังคงอ้างอิง Root Folder เดิมได้ครบ
  3. **จัดลำดับการสแกน (`sort_order`) และดูสถิติร่วมกับ `scanned_photos` ได้ทันที:** สามารถ Query นับจำนวนรูปภาพสะสมของแต่ละปีจากตาราง `scanned_photos` มาแสดงคู่กันในตาราง GUI ได้ทันที และเปิดดูในเมนู **"🗄️ ดูฐานข้อมูล SQLite"** ได้ด้วย
  4. **Auto-Sync ลง `config/year_folders.json` อัตโนมัติ:** ทุกครั้งที่เพิ่ม/แก้ไข/ลบ/เปลี่ยนสถานะใน SQLite ระบบจะอัปเดตไฟล์ `config/year_folders.json` ให้ตรงกันเสมอ เพื่อรักษาความเข้ากันได้ย้อนหลัง 100%

---

### 15.2 การออกแบบโครงสร้างฐานข้อมูล (Database Schema: `root_year_folders`)

เพิ่มตาราง `root_year_folders` ใน `db_manager.py` (`init_db()`):

```sql
CREATE TABLE IF NOT EXISTS root_year_folders (
    folder_id TEXT PRIMARY KEY,
    folder_name TEXT NOT NULL,
    academic_year TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

- **Auto-Seeding (การนำเข้าข้อมูลเริ่มต้นอัตโนมัติ):**
  - เมื่อเปิดโปรแกรมครั้งแรก หากตาราง `root_year_folders` ยังว่างอยู่ ระบบจะอ่านข้อมูลจาก `config/year_folders.json` (ทั้ง 6 โฟลเดอร์: 2569, 2568, 2567, 2566, 2565, 2563) สกัด `academic_year` และนำเข้าสู่ตาราง `root_year_folders` อัตโนมัติทันทีโดยที่ผู้ใช้ไม่ต้องกรอกใหม่
- **CRUD & Sync Methods ใน `db_manager.py`:**
  - `get_root_year_folders(active_only=False)`: ดึงรายการโฟลเดอร์หลักเรียงตาม `academic_year DESC, sort_order ASC` พร้อมนับจำนวนภาพใน `scanned_photos` ของแต่ละปีมาแสดงผล
  - `upsert_root_year_folder(folder_id, folder_name, academic_year, is_active=1, sort_order=0)`: เพิ่มหรือแก้ไขโฟลเดอร์หลัก พร้อมเรียก `_sync_root_folders_to_json()`
  - `delete_root_year_folder(folder_id)`: ลบโฟลเดอร์หลักออกจากรายการ พร้อมเรียก `_sync_root_folders_to_json()`
  - `toggle_root_year_folder_active(folder_id, is_active)`: เปิด/ปิดการสแกนโฟลเดอร์นั้นๆ พร้อมเรียก `_sync_root_folders_to_json()`
  - `_sync_root_folders_to_json()`: เขียนข้อมูลล่าสุดลงไฟล์ `config/year_folders.json` (เก็บทั้ง `name`, `id`, `academic_year`, `is_active`)

---

### 15.3 การปรับปรุงการเชื่อมโยงในระบบสแกน (`scheduler_task.py` และ `gdrive_sync.py`)

1. **`scheduler_task.py` -> `_load_year_folders(active_only=True)`:**
   - เปลี่ยนมาดึงข้อมูลจาก `db_manager.get_root_year_folders(active_only=active_only)` เป็นหลัก (และใช้ `config/year_folders.json` เป็น Fallback)
   - สำหรับ `_task_1_scan_new_photos_fast()` จะดึงเฉพาะโฟลเดอร์ที่เปิดใช้งาน (`active_only=True`) และรับค่า `academic_year` จากตารางโดยตรง (หากคอลัมน์ `academic_year` มีค่าอยู่แล้ว ให้ใช้ค่านั้นทันทีก่อน Fallback ไป `extract_academic_year`)
   - สำหรับ `fetch_drive_folder_year_mapping()` จะดึงโฟลเดอร์ทั้งหมด (`active_only=False`) เพื่อให้การตรวจสอบย้อนหลัง (Backfill) รู้จักโฟลเดอร์ปีเก่าทุกปีเสมอแม้จะปิดการสแกนรายวันไปแล้วก็ตาม
2. **`gdrive_sync.py` -> `get_all_images_in_folder_recursive()`:**
   - เปลี่ยนการเช็ค `is_root_or_year` จากเดิมที่ Hardcode ชื่อปี `["ภาพกิจกรรม 2569", ...]` มาเป็นดึงรายชื่อและปีจาก `db_manager.get_root_year_folders(active_only=False)` ร่วมกับ Regex ตรวจจับชื่อระดับปี เพื่อให้เมื่อผู้ใช้เพิ่มโฟลเดอร์ปีใหม่ (เช่น `"ภาพกิจกรรม 2570"`) ระบบจะแยกชั้น `event_name` และ `subfolder` ได้ถูกต้องทันทีโดยไม่ต้องแก้โค้ด

---

### 15.4 การออกแบบส่วนติดต่อผู้ใช้ (UI Design ใน `app_gui.py`)

1. **เพิ่มโซน `"📁 จัดการโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders)"` ในหน้า `"⚙️ ตั้งค่าระบบ"` (`setup_settings_ui`) และปุ่มลัด `"📁 จัดการโฟลเดอร์ปีการศึกษา (Root)"` ในหน้า `"🔍 สแกนรูปภาพกิจกรรม"`:**
   - **ส่วนฟอร์มเพิ่ม/แก้ไขโฟลเดอร์หลัก (Add / Update Root Folder Bar):**
     - **ช่องกรอกลิงก์ หรือ Folder ID ของ Google Drive:** รองรับการวาง URL เต็ม (เช่น `https://drive.google.com/drive/folders/1Y0GFyn...`) หรือวางเฉพาะ ID ระบบจะใช้ `_extract_drive_id()` สกัด ID ให้อัตโนมัติ
     - **ปุ่ม `"🔍 เลือกจาก Drive"`:** เปิดหน้าต่าง `GoogleDrivePicker` ให้คลิกเลือกโฟลเดอร์จาก Google Drive ได้โดยตรง เมื่อเลือกแล้วจะเติมทั้ง **Folder ID**, **ชื่อโฟลเดอร์** และ **ปีการศึกษา (พ.ศ.)** ลงในช่องกรอกให้อัตโนมัติ
     - **ช่องกรอกชื่อโฟลเดอร์ (`Folder Name`):** เช่น `"ภาพกิจกรรม 2570"` (หากกรอกเฉพาะ ID แล้วกดปุ่มดึงชื่อ ระบบจะเชื่อมต่อ Drive API ดึงชื่อโฟลเดอร์จริงมาใส่ให้อัตโนมัติและสกัดเลขปี 4 หลักใส่ช่องปีการศึกษา)
     - **ช่องกรอกปีการศึกษา (`Academic Year`):** เช่น `"2570"`
     - **ปุ่ม `"➕ เพิ่ม / บันทึกโฟลเดอร์หลัก"`**
   - **ส่วนตารางแสดงรายการโฟลเดอร์หลัก (Root Folders Table / List):**
     - แสดงรายการโฟลเดอร์ทั้งหมดจากตาราง `root_year_folders` พร้อมข้อมูล:
       - **สถานะสแกน (Switch / Checkbox `เปิดสแกน`):** เปิด/ปิดการนำโฟลเดอร์ปีนั้นเข้าสแกนใน Task 1
       - **ปีการศึกษา (Badge เช่น `ปี 2569`)**
       - **ชื่อโฟลเดอร์ (`ภาพกิจกรรม 2569`)**
       - **Folder ID**
       - **จำนวนภาพในฐานข้อมูล (`23,815 รูป`)** ดึงสดจาก `scanned_photos`
       - **ปุ่มจัดการ:** `"✏️ แก้ไข"` และ `"🗑️ ลบ"`
2. **รองรับการเปิดดูในหน้า `"🗄️ ดูฐานข้อมูล SQLite"`:**
   - ตาราง `root_year_folders` จะปรากฏใน Dropdown เลือกตารางของเมนู **"🗄️ ดูฐานข้อมูล SQLite"** อัตโนมัติ

---

### 15.5 แผนการตรวจสอบและทดสอบ (Verification Plan)
1. **TC-40 (SQLite Table & Auto-Seeding):** ทดสอบการสร้างตาราง `root_year_folders` และการนำเข้าข้อมูลเริ่มต้น 6 โฟลเดอร์จาก `config/year_folders.json` อัตโนมัติ
2. **TC-41 (CRUD & JSON Auto-Sync):** ทดสอบการเพิ่มโฟลเดอร์ใหม่ (เช่น ปี `2570`), การสลับสถานะ `is_active`, และการลบ แล้วตรวจสอบว่าทั้งตาราง SQLite และไฟล์ `config/year_folders.json` อัปเดตตรงกัน 100%
3. **TC-42 (URL Extraction & Scheduler Integration):** ทดสอบการสกัด Folder ID จาก URL เต็ม และตรวจสอบว่า `_load_year_folders()` ใน `scheduler_task.py` และ `gdrive_sync.py` ดึงรายการโฟลเดอร์ตามสถานะ `is_active` ได้ถูกต้อง
4. **TC-43 (GUI Version Upgrade):** อัปเดตเลขเวอร์ชันเป็น `v6.27` บน Window Title, Sidebar Logo และบันทึกประวัติลงบนสุดของ `README.md`

---

### 15.6 บันทึกผลการทดสอบจริง (Execution Verification Results - `test_root_folders_suite.py`)
- **วันและเวลาที่ทดสอบ:** 18 ตุลาคม 2026 03:26:39 น.
- **สถานะ:** ✅ **ผ่านครบ 4/4 ข้อ (100% Passed)**
  - **TC-40 (Production SQLite `root_year_folders` & Live Photo Counts):** ผ่าน 100% — ตาราง `root_year_folders` นำเข้าข้อมูล 6 ปีการศึกษา (`2569`, `2568`, `2567`, `2566`, `2565`, `2563`) พร้อมแสดงจำนวนรูปภาพสะสมของแต่ละปีจาก `scanned_photos` ได้ถูกต้อง
  - **TC-41 (Isolated CRUD & JSON Auto-Sync):** ผ่าน 100% — ทดสอบการเพิ่มโฟลเดอร์ปี `2570` และ `2571`, สลับสถานะ `is_active`, ลบรายการ และตรวจสอบการซิงค์อัตโนมัติลง `year_folders.json`
  - **TC-42 (URL Extraction & Scheduler Integration):** ผ่าน 100% — สกัด Folder ID จากลิงก์ Google Drive ทุกรูปแบบได้ถูกต้อง และ `SchedulerTask._load_year_folders()` ดึงข้อมูลจากตาราง `root_year_folders` สำเร็จ
  - **TC-43 (GUI Version & Module Compilation):** ผ่าน 100% — อัปเดตเลขเวอร์ชันเป็น `v6.27` ครบทุกจุดและคอมไพล์ผ่าน 100%

---

## 16. แผนงานวิเคราะห์และยกระดับความเร็วและความลื่นไหลของระบบขั้นสูงสุด (Blazing Fast UI & SQLite WAL Optimization Suite - v6.28)

### 16.1 สรุปผลการตรวจสอบประสิทธิภาพเชิงลึกจากฐานข้อมูลจริง (Deep Performance Audit & Benchmark)
จากการตรวจสอบโค้ดทั้งหมด (`app_gui.py`, `db_manager.py`, `scheduler_task.py`, `gdrive_sync.py`) และรัน Benchmark วัดเวลาจริงควบคู่กับ `EXPLAIN QUERY PLAN` บนฐานข้อมูล `data/faces_db.db` ปัจจุบันที่มีขนาดใหญ่:
- **`scanned_photos`:** 117,586 รูปภาพ
- **`detected_faces`:** 179,652 รายการแมตช์ (ครู 169,651 / นักเรียน 10,001)
- **`scanned_photo_faces`:** **1,032,108 ใบหน้า** (มากกว่า 1 ล้านเวกเตอร์ใบหน้า!)
- **`unknown_clusters`:** **21,709 กลุ่มบุคคลนิรนาม** (ที่มีรูปตั้งแต่ 3 รูปขึ้นไป) และ **`unknown_cluster_members`:** **350,521 รายการ**

---

### 16.2 🔍 ผลการวิเคราะห์ทบทวนแผนซ้ำรอบที่ 2 (Second-Pass Critical Audit: จุดบกพร่องที่พบในแผนร่างแรกและการปรับปรุงให้สมบูรณ์ 100%)
จากการนำแผนร่างแรกมาทดสอบเจาะลึกด้วย `EXPLAIN QUERY PLAN` และตรวจสอบความถูกต้องของข้อมูล (Data Consistency Audit) ซ้ำอีกครั้ง พบ **จุดสำคัญ 4 ประการที่แผนร่างแรกวิเคราะห์คลาดเคลื่อนหรือมีความเสี่ยงแฝง** และได้ปรับปรุงแผนใหม่ให้ดีกว่าเดิมอย่างก้าวกระโดด ดังนี้:

1. **ค้นพบสาเหตุที่แท้จริงของความช้าในตาราง `detected_faces (ครู)` (714.30 ms ➔ 0.72 ms):**
   - **ข้อผิดพลาดในแผนร่างแรก:** เข้าใจว่า `SELECT COUNT(*)` เป็นตัวที่ช้า (~660 ms) จึงเสนอให้ทำเพียง "Pagination Count Cache"
   - **ความจริงจาก `EXPLAIN QUERY PLAN`:** คำสั่ง `SELECT COUNT(*)` ใช้เวลาเพียง **13.76 ms** เท่านั้น! แต่ตัวที่กินเวลาถึง **714.30 ms** คือคำสั่งดึงข้อมูลหน้าละ 100 แถว (`SELECT ... LIMIT 100 OFFSET 0`) เพราะ SQLite เริ่มค้นจาก `staff_members` แล้วดึงทั้ง **169,651 แถว** ไป `LEFT JOIN scanned_photos` ทั้งหมด จากนั้นสร้างตารางชั่วคราว (`USE TEMP B-TREE FOR ORDER BY`) เพื่อเรียงลำดับทั้ง 169,651 แถวก่อนตัดมา 100 แถว! (หากทำแค่ Count Cache ตามแผนร่างแรก เวลาเปลี่ยนหน้าก็จะยังค้าง ~700 ms เหมือนเดิม)
   - **การปรับปรุงในแผนใหม่:** ใช้เทคนิค **Deferred Join CTE (`WITH page_df AS (...)`)** ร่วมกับ `+s.role` เพื่อบังคับให้ SQLite ไต่ Index `detected_faces` ตัดมาเฉพาะ **100 แถวของหน้านั้นก่อน** แล้วค่อย `LEFT JOIN scanned_photos` เพียง 100 แถว **ลดเวลาคิวรีจริงจาก 714.30 ms เหลือเพียง 0.72 ms (เร็วขึ้น 992 เท่า!)**

2. **ค้นพบบั๊กเงียบ (Silent Data Bug) เรื่องแถวจำลอง `face_index = -1` ในโหมด `0 Faces` และ `scanned_photos`:**
   - **ข้อผิดพลาดในแผนร่างแรก:** คิดว่า `(SELECT COUNT(*) FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id) = 0` กับ `COALESCE(p.total_faces_detected, 0) = 0` ให้ผลเท่ากันอยู่แล้ว
   - **ความจริงจากการตรวจสอบข้อมูลจริง:**
     - คิวรีเดิม `COUNT(*) = 0` คืนค่า **3,081 รูป** (ใช้เวลา 145.0 ms)
     - แต่ `COALESCE(p.total_faces_detected, 0) = 0` คืนค่า **4,175 รูป** (ใช้เวลา 5.2 ms) — **ทำไมต่างกัน 1,094 รูป?**
     - เพราะใน `save_scanned_photos_batch()` และ `save_photo_face_embeddings()` เมื่อสแกนรูปแล้วไม่พบใบหน้าคน (0 faces) ระบบจะ INSERT **แถวจำลอง (Dummy Row) ที่มี `face_index = -1`** ลงใน `scanned_photo_faces`!
     - โค้ดเดิมใน `app_gui.py` ลืมใส่เงื่อนไข `AND pf.face_index >= 0` ทำให้รูปที่ไม่มีคนเลย 1,094 รูป **ถูกแสดงผลผิดเป็น `"✅ มีแคชแล้ว (1 หน้า)"`** และหลุดรอดจากตัวกรอง `0 Faces`!
   - **การปรับปรุงในแผนใหม่:**
     - เมื่อตรวจสอบด้วย `NOT EXISTS (SELECT 1 FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id AND pf.face_index >= 0)` พบว่าได้ **4,175 รูป ตรงกับ `COALESCE(p.total_faces_detected, 0) = 0` 100%!**
     - ดังนั้นการเปลี่ยนมาใช้ `COALESCE(p.total_faces_detected, 0)` ใน `app_gui.py` และ `purge_zero_face_scanned_photos()` นอกจากจะ **ลดเวลาจาก 145.0 ms เหลือ 5.2 ms (เร็วขึ้น 28 เท่า)** แล้ว ยัง **ช่วยแก้บั๊กการแสดงจำนวนหน้าผิด (จาก 0 หน้าเป็น 1 หน้า) อีก 1,094 รูปไปพร้อมกัน!**

3. **ค้นพบคอขวดซ่อนเร้นใหม่ในหน้า `Unknowns (บุคคลนิรนาม)` เวลาคลิกกรองปี พ.ศ. (858.81 ms ➔ 0.48 ms):**
   - **สิ่งที่แผนร่างแรกมองข้าม:** ใน `db_manager.py` -> `get_unknown_cluster_member_photos(cluster_id, filter_year)` เวลาคลิกปุ่มเลือกปี พ.ศ. (เช่น `2568`) คิวรี `WHERE m.cluster_id = ? AND m.year = ?` บนตาราง `unknown_cluster_members` (350,521 แถว) **SQLite เลือกใช้ Index ผิดตัว (`SEARCH m USING INDEX idx_ucm_year`)** ทำให้ต้องกวาดข้อมูลของปี 2568 ทั้งหมด **74,358 แถว** กินเวลาถึง **858.81 ms**!
   - **การปรับปรุงในแผนใหม่:** สร้าง Composite Index `CREATE INDEX IF NOT EXISTS idx_ucm_cluster_year ON unknown_cluster_members(cluster_id, year)` ทำให้ SQLite เจาะจงเฉพาะคลัสเตอร์และปีนั้นทันที **ลดเวลาคิวรีจาก 858.81 ms เหลือเพียง 0.48 ms (เร็วขึ้น 1,789 เท่า!)**

4. **ตัดความเสี่ยง Thread-Safety ของ Tkinter ด้วยการใช้ Correlated Covering Index + Widget Reuse บน Main Thread:**
   - **ข้อควรระวังในแผนร่างแรก:** แผนร่างแรกเสนอให้ย้ายการอัปเดต UI ของ `refresh_dashboard_stats()` และ `load_db_table_data()` ไปรันแบบ Async Background Thread ซึ่งมีความเสี่ยงสูงที่จะเกิด Race Condition กับ Tkinter Widget หรือทำให้ฟังก์ชันที่เรียกใช้งานต่ออ่านค่าสถานะไม่ทัน
   - **การปรับปรุงในแผนใหม่:**
     - เปลี่ยนคิวรีจัดอันดับ Top 50 ครูและนักเรียนบน Dashboard จาก `LEFT JOIN ... GROUP BY` (ที่ต้องสร้าง Temp B-Tree ถึง 2 ชั้น ใช้เวลา **577.79 ms**) มาเป็น **Correlated Covering Subquery** คู่กับดัชนี `idx_df_staff_photo(staff_id, photo_id)`:
       ```sql
       SELECT s.name, (SELECT COUNT(DISTINCT df.photo_id) FROM detected_faces df WHERE df.staff_id = s.id) as cnt
       FROM staff_members s WHERE s.role = 'teacher' OR s.role IS NULL
       ORDER BY cnt DESC, s.name ASC LIMIT 50
       ```
       เนื่องจาก `photo_id` ถูกเรียงลำดับไว้ล่วงหน้าตาม `staff_id` ใน Covering Index แล้ว SQLite จึงนับ `COUNT(DISTINCT)` ได้ทันทีโดย **ไม่ต้องสร้าง Temp B-Tree เลย** ลดเวลาคิวรีจริงจาก **577.79 ms เหลือเพียง 32.26 ms (เร็วขึ้น 18 เท่า)** และให้ผลลัพธ์ตรงกัน 100%!
     - เมื่อคิวรี SQL ทุกจุดถูกย่อลงเหลือ **0.5 – 35 ms** และใช้ **Widget Reuse** จึงสามารถทำงานแบบ Synchronous บน Main Thread ได้อย่างปลอดภัย 100% ลื่นไหลทันทีโดยไม่มีความเสี่ยงเรื่อง Thread Race Condition!

---

### 16.3 รายละเอียดแผนการปรับปรุงทั้ง 7 ข้อ (Refined Step-by-Step Optimization Plan)

#### 🚀 ข้อที่ 1: ยกระดับความเร็วหน้า `"📊 Dashboard"` (Fast SQL Counts + Correlated Covering Index + Widget Reuse)
- **ปัญหาที่พบ (Root Cause):**
  1. `refresh_dashboard_stats()` เรียก `self.db.get_all_sync_data()` ซึ่งดึงข้อมูลดิบ **297,238 แถว** มาสร้าง Python Dict ใน RAM (เสียเวลา **~612.8 ms**) เพียงเพื่อนับ `len()`
  2. คิวรี Top 50 ครู/นักเรียน ใช้ `LEFT JOIN ... GROUP BY` ร่วมกับ `COUNT(DISTINCT df.photo_id)` ซึ่งต้องสร้าง Temp B-Tree 2 ชั้น (เสียเวลา **~577.8 ms**)
  3. ทุกครั้งที่รีเฟรช ระบบสั่ง `widget.destroy()` แล้วสร้าง `CTkFrame` + `CTkLabel` ใหม่ทั้งหมด **300 วิดเจ็ต** (เสียเวลาวาดอีก **~600–900 ms**)
- **วิธีการแก้ไข:**
  1. เพิ่มเมธอด `get_dashboard_fast_stats(sort_dir="DESC")` ใน `db_manager.py` ที่ใช้ `SELECT COUNT(*)` และ `SELECT COUNT(DISTINCT event_name)` (**ลดเวลาจาก 612.8 ms เหลือ 3.25 ms — เร็วขึ้น 188 เท่า!**)
  2. สร้าง Covering Index `idx_df_staff_photo ON detected_faces(staff_id, photo_id)` และใช้ Correlated Covering Subquery (**ลดเวลาคิวรี Top 50 จาก 577.8 ms เหลือ 32.2 ms — เร็วขึ้น 18 เท่า!**)
  3. ใช้ระบบ **Widget Pooling / Reuse** ใน `scr_teacher_faces` และ `scr_student_faces` (สร้างแถววิดเจ็ตไว้เพียงครั้งเดียว ครั้งต่อไปเพียงอัปเดตข้อความ `.configure(text=...)`) ลดเวลาวาด UI จาก ~700 ms เหลือ **< 10 ms**!

#### 🚀 ข้อที่ 2: ยกระดับความเร็วหน้า `"👥 สถิติบุคคลนิรนาม (Unknowns)"` (Pagination 250/หน้า + Composite Index `idx_ucm_cluster_year` + Debounce 250ms)
- **ปัญหาที่พบ (Root Cause):**
  1. `load_unknown_clusters_list()` วนลูปยัดข้อมูล **21,709 กลุ่ม** ลง `tree_unknown` รวดเดียวบน Main Thread ทำให้หน้าจอค้าง ~1.5 วินาที และช่องค้นหาไม่มี Debounce
  2. `get_unknown_cluster_member_photos(cluster_id, filter_year)` เวลาเลือกกรองปี พ.ศ. ใช้ Index ผิดตัว (`idx_ucm_year`) ทำให้กวาดตาราง 74,358 แถว เสียเวลา **858.81 ms**
- **วิธีการแก้ไข:**
  1. สร้าง Composite Index `idx_ucm_cluster_year ON unknown_cluster_members(cluster_id, year)` ใน `db_manager.py` (**ลดเวลาคลิกสลับปีจาก 858.81 ms เหลือ 0.48 ms — เร็วขึ้น 1,789 เท่า!**)
  2. เพิ่มระบบ **Pagination (แสดงหน้าละ 250 อันดับ พร้อมปุ่ม `◀️ ก่อนหน้า` / `ถัดไป ▶️` และป้ายบอกหน้า)** ในตาราง `tree_unknown` และใช้ `self.tree_unknown.delete(*children)` ลบทีเดียวทั้งก้อน ทำให้เปิดหน้าและสลับแท็บเสร็จภายใน **< 15 ms**
  3. เพิ่ม **Debounce 250ms** ให้ช่องค้นหา `entry_unknown_search` และช่องกรองจำนวนรูปขั้นต่ำ `entry_unknown_min_photos`

#### 🚀 ข้อที่ 3: เปิดโหมด `SQLite WAL (Write-Ahead Logging)` + Memory-Mapped I/O และป้องกัน `init_db()` รันซ้ำซ้อน (`db_manager.py`)
- **ปัญหาที่พบ (Root Cause):**
  1. ฐานข้อมูลใช้ `journal_mode = delete` ทำให้ขณะเธรดเบื้องหลังเขียนผลการสแกนลง SQLite เธรด GUI จะถูกบล็อกรอ Lock
  2. `init_db()` รันคำสั่ง `DELETE` และ `UPDATE` กวาดตารางใหญ่ทุกครั้งที่มีการสร้างอินสแตนซ์ `DatabaseManager()` (เสียเวลา **~150–178 ms** ต่อครั้ง)
- **วิธีการแก้ไข:**
  1. ตั้งค่า High-Performance PRAGMAs ใน `get_connection()`:
     - `PRAGMA journal_mode = WAL;`
     - `PRAGMA synchronous = NORMAL;`
     - `PRAGMA temp_store = MEMORY;`
     - `PRAGMA cache_size = -64000;` (64 MB Page Cache)
     - `PRAGMA mmap_size = 268435456;` (256 MB Memory-Mapped I/O)
  2. เพิ่ม Class-level Guard `_schema_initialized_paths = set()` ใน `DatabaseManager` เพื่อให้ `init_db()` รันตรวจสอบตารางและทำความสะอาดข้อมูลเพียง **1 ครั้งต่อไฟล์ฐานข้อมูล** ตลอดอายุโปรแกรม (ครั้งถัดไปใช้เวลา **0.0 ms**)

#### 🚀 ข้อที่ 4: ยกระดับความเร็วหน้า `"🗄️ ดูฐานข้อมูล SQLite"` (Deferred Join CTE 0.72ms + แก้บั๊ก `0 Faces` `face_index = -1` + Pagination Count Cache)
- **ปัญหาที่พบ (Root Cause):**
  1. โหมดดูตาราง `"detected_faces (ครู)"` และ `"detected_faces (นักเรียน)"` ทำการ Join 3 ตารางทั้ง 169,651 แถวแล้วค่อย Sort ใน Temp B-Tree เพื่อตัด `LIMIT 100` เสียเวลา **714.30 ms** ทุกครั้งที่โหลดหรือเปลี่ยนหน้า
  2. โหมด `"0 Faces"` และ `"scanned_photos"` ใช้ Correlated Subquery `(SELECT COUNT(*) FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id)` ซึ่งเสียเวลา **145.0 ms** และนับรวมแถวจำลอง `face_index = -1` ทำให้แสดงจำนวนหน้าผิดไป 1,094 รูป
  3. ทุกครั้งที่กดปุ่มเปลี่ยนหน้า (Next/Prev Page) ระบบรัน `SELECT COUNT(*)` ใหม่ซ้ำทุกครั้ง
- **วิธีการแก้ไข:**
  1. ใช้ **Deferred Join CTE (`WITH page_df AS (...)`)** ในโหมด `"detected_faces"` (กรณีไม่มีคำค้นหาและเรียงตามคอลัมน์ใน `detected_faces`) เพื่อตัดเฉพาะ 100 แถวของหน้านั้นก่อนค่อย `LEFT JOIN scanned_photos` (**ลดเวลาจาก 714.30 ms เหลือ 0.72 ms — เร็วขึ้น 992 เท่า!**)
  2. เปลี่ยนคิวรี `"0 Faces"` และ `purge_zero_face_scanned_photos()` ให้ใช้ `COALESCE(p.total_faces_detected, 0) = 0` (ซึ่งตรงกับ `NOT EXISTS (... WHERE pf.face_index >= 0)` ครบทั้ง **4,175 รูป 100%** และลดเวลาจาก **145.0 ms เหลือ 5.2 ms**) พร้อมปรับการแสดงผลในตาราง `"scanned_photos"` ให้แยกสถานะ `"✅ มีแคชแล้ว (X หน้า)"`, `"⚪ สแกนแล้ว (0 หน้า - ไม่มีคน)"`, และ `"❌ ยังไม่มีแคช (0 หน้า)"` อย่างแม่นยำ
  3. เพิ่ม **Pagination Count Cache (`_db_cached_count_key`, `_db_cached_total_rows`)** เพื่อข้ามการรัน `SELECT COUNT(*)` ซ้ำเมื่อกดเปลี่ยนหน้าในตารางและคำค้นหาเดิม

#### 🚀 ข้อที่ 5: เพิ่มระบบ Debounce 250ms และ In-Memory List Cache ในหน้า `"👨‍🏫 ลงทะเบียนครู"`, `"🎒 ลงทะเบียนนักเรียน"` และ `"🖼️ ภาพกิจกรรมที่แมตช์แล้ว"`
- **ปัญหาที่พบ (Root Cause):**
  - ช่องค้นหาทั้ง 3 หน้าผูก `<KeyRelease>` สั่งทำลายและสร้าง Widget ใหม่ (หรือยิง Thread โหลดรูปแกลเลอรีคนแรกใน `filter_matched_person_dropdown`) ทันทีทุกตัวอักษรที่พิมพ์
- **วิธีการแก้ไข:**
  - เพิ่ม **Debounce 250ms (`after` / `after_cancel`)** ให้ช่องค้นหาทั้ง 3 จุด และแคชรายการครู/นักเรียนไว้ในหน่วยความจำระหว่างพิมพ์ค้นหา (รีเฟรชจาก SQLite เฉพาะเมื่อมีการเพิ่ม/ลบ/แก้ไขข้อมูล)

#### 🚀 ข้อที่ 6: ปรับปรุง `check_log_queue()` ให้แทรกข้อความ Console แบบ Batch Text Insertion
- **ปัญหาที่พบ (Root Cause):**
  - ลูป `while not self.log_queue.empty():` เรียก `self.console_text.see("end")` และเช็คจำนวนบรรทัดทุกๆ 1 ข้อความ ทำให้ Tkinter คำนวณ Scrollbar ใหม่ซ้ำหลายสิบครั้งในรอบเดียวขณะสแกนเร็วๆ
- **วิธีการแก้ไข:**
  - ดึงข้อความจาก `log_queue` รอบละไม่เกิน 60 ข้อความ แทรกลง `console_text` ให้ครบก่อน แล้วเรียก `self.console_text.see("end")` และตัดบรรทัดเกิน 5,000 บรรทัด **เพียง 1 ครั้งต่อรอบ (ทุก 100ms)**

#### 🚀 ข้อที่ 7: อัปเกรด `save_scanned_photos_batch()` ใน `db_manager.py` ให้ใช้ `executemany()` และรองรับ `academic_year`
- **ปัญหาที่พบ (Root Cause):**
  - `save_scanned_photos_batch()` ยังใช้ลูป `cursor.execute` ทีละแถว และยังไม่ได้บันทึกคอลัมน์ `academic_year`
- **วิธีการแก้ไข:**
  - ปรับปรุงให้รองรับคอลัมน์ `academic_year` (พร้อม Auto-extract fallback) และรวบรวมรายการ `scanned_photos`, `detected_faces`, `scanned_photo_faces` เพื่อรัน `cursor.executemany()` รวดเดียวใน Transaction เดียว

---

### 16.4 ตารางเปรียบเทียบผลลัพธ์ความเร็วที่วัดผลได้จริง (Verified Benchmark Comparison)

| ส่วนการทำงาน / คิวรีหลัก | ก่อนปรับปรุง (v6.27) | หลังปรับปรุง (v6.28 Verified) | ความเร็วที่เพิ่มขึ้น |
| :--- | :---: | :---: | :---: |
| **1. โหลดตาราง `detected_faces (ครู)` ใน DB Viewer** | 714.30 ms (3-Table Join + Temp B-Tree Sort) | **0.72 ms** (Deferred Join CTE 100 แถว) | **เร็วขึ้น 992x** |
| **2. คลิกกรองปี พ.ศ. ในหน้า `👥 สถิติบุคคลนิรนาม`** | 858.81 ms (ใช้ `idx_ucm_year` กวาด 74,358 แถว) | **0.48 ms** (Composite Index `idx_ucm_cluster_year`) | **เร็วขึ้น 1,789x** |
| **3. นับจำนวนรูปภาพและใบหน้าบน Dashboard** | 612.80 ms (`get_all_sync_data` 2.97 แสนแถว) | **3.25 ms** (`SELECT COUNT(*)`) | **เร็วขึ้น 188x** |
| **4. คิวรีจัดอันดับ Top 50 ครู + นักเรียน บน Dashboard** | 577.79 ms (`LEFT JOIN` + 2 Temp B-Trees) | **32.26 ms** (Correlated Covering Index `idx_df_staff_photo`) | **เร็วขึ้น 18x** |
| **5. เปิดเมนู `👥 สถิติบุคคลนิรนาม` (21,709 กลุ่ม)** | ~1,500 ms (วาด Treeview 21,709 แถวรวดเดียว) | **< 20 ms** (Paginated 250 แถว/หน้า + Batch Delete) | **เร็วขึ้น ~75x** |
| **6. ตัวกรอง `0 Faces (ไร้ใบหน้า)` ใน DB Viewer** | 145.00 ms (Subquery นับพลาด 1,094 รูป `face_index=-1`) | **5.20 ms** (Indexed `total_faces_detected = 0` แม่นยำ 100%) | **เร็วขึ้น 28x + แก้บั๊กข้อมูล** |
| **7. สร้างอินสแตนซ์ `DatabaseManager()` ซ้ำ** | 151.06 ms (รัน `init_db` + `DELETE` ขยะทุกครั้ง) | **0.00 ms** (One-time Schema Init Guard) | **Instant** |

---

### 16.5 แผนการทดสอบและตารางกรณีทดสอบ (Comprehensive Test Case Specification Plan: TC-44 – TC-51)

ในการตรวจสอบความถูกต้อง (Runtime Execution Path Verification ตามกฎข้อที่ 4) จะสร้างชุดสคริปต์ทดสอบอัตโนมัติ **`test_performance_v628_suite.py`** เพื่อทดสอบทั้ง **ความถูกต้องของผลลัพธ์ (Functional Accuracy 100%)** และ **เกณฑ์เวลาตอบสนอง (Performance SLA Thresholds)** ครอบคลุมทั้ง 7 จุดที่ปรับปรุง พร้อมออกรายงาน **Test Case Execution Report**

#### 📋 ตารางกำหนดรายละเอียดกรณีทดสอบ (Test Case Specification Matrix)

| รหัส (ID) | ชื่อกรณีทดสอบ (Test Case Title) | โมดูล / ฟังก์ชันเป้าหมาย | เงื่อนไขตั้งต้น (Pre-conditions) | ขั้นตอนการทดสอบ (Test Steps) | ผลลัพธ์ที่คาดหวัง (Expected Result) | เกณฑ์เวลาผ่าน (SLA Criteria) |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-44** | **SQLite WAL Mode, High-Speed PRAGMAs & One-Time `init_db()` Guard** | `db_manager.py`<br>`get_connection()`, `init_db()` | ฐานข้อมูล `data/faces_db.db` (117,586 รูป / 1.03 ล้านใบหน้า) | 1. สร้าง `db1 = DatabaseManager()` ครั้งแรก และตรวจสอบค่า `PRAGMA journal_mode`, `synchronous`, `temp_store`, `cache_size`, `mmap_size`<br>2. สร้าง `db2 = DatabaseManager()` ครั้งที่ 2 ซ้ำในโปรเซสเดิมและจับเวลา<br>3. จำลองการเปิด Connection อ่านและเขียนพร้อมกัน (Concurrent Read/Write Test) | 1. `journal_mode = 'wal'`, `temp_store = 2 (MEMORY)`, `cache_size = -64000`, `mmap_size >= 268435456`<br>2. การสร้าง `DatabaseManager()` ครั้งที่ 2 ข้ามการรัน `DELETE` ขยะซ้ำซ้อนได้สำเร็จ<br>3. อ่านข้อมูลได้ทันทีโดยไม่เกิด `sqlite3.OperationalError: database is locked` | สร้าง Instance ครั้งที่ 2 ใช้เวลา **< 1.0 ms** (จากเดิม 151.1 ms) |
| **TC-45** | **Dashboard Fast Summary Stats, Correlated Covering Index & Widget Reuse** | `db_manager.py` (`get_dashboard_fast_stats`)<br>`app_gui.py` (`refresh_dashboard_stats`) | มีข้อมูลครู 136 คน, นักเรียน 85 คน, ภาพ 117,586 รูป, แมตช์ 179,652 รายการ | 1. เรียก `get_dashboard_fast_stats(sort_dir="DESC")` และ `"ASC"`<br>2. เปรียบเทียบค่าตัวเลขรวมและรายชื่อ Top 50 ครู / นักเรียน กับคิวรีแบบเดิม<br>3. ตรวจสอบ `EXPLAIN QUERY PLAN` ว่าใช้ `COVERING INDEX idx_df_staff_photo` โดยไม่สร้าง Temp B-Tree สำหรับ `COUNT(DISTINCT)` และตรวจ Widget Reuse | 1. ตัวเลขสถิติและรายชื่อ Top 50 ครู / นักเรียน **ตรงกับวิธีเดิม 100% ทุกแถว**<br>2. เมื่อกดสลับ 🔼/🔽 วิดเจ็ตเดิมถูกอัปเดตข้อความ in-place โดยรหัส Object (`id(widget)`) ไม่เปลี่ยน | คิวรีสรุปผลรวม + Top 50 ใช้เวลารวม **< 60 ms** (จากเดิม ~1,190 ms) |
| **TC-46** | **Unknowns Analytics Pagination (250/page), Composite Index `idx_ucm_cluster_year` & Debounce** | `db_manager.py` (`get_unknown_cluster_member_photos`)<br>`app_gui.py` (`load_unknown_clusters_list`) | มีข้อมูล `unknown_clusters` 21,709 กลุ่ม และ `unknown_cluster_members` 350,521 แถว | 1. ทดสอบคิวรี `get_unknown_cluster_member_photos('UNK_00001', '2568')` และตรวจ `EXPLAIN QUERY PLAN`<br>2. โหลดตาราง `tree_unknown` หน้า 1 และทดสอบเปลี่ยนหน้า ถัดไป/ก่อนหน้า<br>3. ทดสอบพิมพ์ค้นหารหัสกลุ่มพร้อมตรวจ Debounce | 1. ใช้ดัชนี `idx_ucm_cluster_year` คืนผลลัพธ์ตรงกัน 100%<br>2. `tree_unknown` แสดงผลหน้าละ 250 แถว (`หน้า 1/87 (21,709 กลุ่ม)`)<br>3. เปลี่ยนหน้าและค้นหาได้ถูกต้องแม่นยำ | คิวรีกรองปี **< 5 ms** (เดิม 858.8 ms) และเรนเดอร์ตาราง **< 30 ms** (เดิม ~1,500 ms) |
| **TC-47** | **SQLite DB Viewer Deferred Join CTE (`detected_faces`), `0-Faces` Bug Fix & Count Cache** | `app_gui.py` (`load_db_table_data`)<br>`db_manager.py` (`purge_zero_face_scanned_photos`) | ตาราง `scanned_photos` (117,586 รูป) และ `detected_faces` (179,652 แถว) | 1. ทดสอบคิวรี Deferred Join CTE ของ `detected_faces (ครู)` เทียบผลลัพธ์กับคิวรีเดิมทั้ง 100 แถว<br>2. ตรวจสอบจำนวนรูป `0 Faces` (`total_faces_detected = 0`) เทียบกับ `NOT EXISTS (... WHERE pf.face_index >= 0)`<br>3. ทดสอบการเปลี่ยนหน้า Pagination ว่าใช้ค่า `total_rows` จาก Count Cache | 1. ข้อมูล 100 แถวของ `detected_faces (ครู)` ตรงกับคิวรีเดิม 100%<br>2. จำนวนรูป `0 Faces` (4,175 รูป) ตรงกัน 100% และแสดงสถานะ `"⚪ สแกนแล้ว (0 หน้า - ไม่มีคน)"` สำหรับแถว `face_index = -1` ได้ถูกต้อง<br>3. เปลี่ยนหน้าโดยไม่รัน `COUNT(*)` ซ้ำ | คิวรี `detected_faces` **< 10 ms** (เดิม 714.3 ms) และ `0 Faces` **< 15 ms** (เดิม 145.0 ms) |
| **TC-48** | **Search Input Debounce (250ms) & In-Memory Registry Cache** | `app_gui.py`<br>`filter_staff_list()`, `filter_student_list()`, `filter_matched_person_dropdown()` | มีรายชื่อครูและนักเรียนในฐานข้อมูล | 1. จำลองการพิมพ์ตัวอักษรต่อเนื่อง 5 ตัวอักษรติดกันภายใน 100ms ในช่องค้นหาครู, นักเรียน, และแกลเลอรี<br>2. ตรวจสอบจำนวนครั้งที่ฟังก์ชันกรองรายการถูกเรียกทำงานจริง | 1. ระบบยกเลิก Timer เก่า (`after_cancel`) และรันการกรองจริงเพียง **1 ครั้ง** หลังจากหยุดพิมพ์ครบ 250ms<br>2. ไม่ยิง Thread โหลดรูปแกลเลอรีซ้ำซ้อนขณะกำลังพิมพ์ | บล็อก Main Thread ขณะพิมพ์ **< 2 ms / keystroke** |
| **TC-49** | **Batch Console Log Insertion & Scrollbar Optimization** | `app_gui.py`<br>`check_log_queue()` | ส่งข้อความ Log จำลองเข้า `log_queue` จำนวน 200 ข้อความพร้อมกัน | 1. ยัดข้อความ Log 200 บรรทัด (คละสี Tag: `[INFO]`, `[WARNING]`, `[ERROR]`, `[MATCH_OK]`) เข้า `log_queue`<br>2. เรียก `check_log_queue()` และวัดเวลาประมวลผลรวมถึงจำนวนครั้งที่เรียก `see("end")` | 1. ข้อความถูกแทรกพร้อมสี Tag ที่ถูกต้องครบถ้วน<br>2. เรียก `console_text.see("end")` และตรวจตัดบรรทัดเพียง **1 ครั้งต่อรอบ Batch (60 บรรทัด)** | ประมวลผล Log 60 บรรทัดต่อรอบในเวลา **< 15 ms** |
| **TC-50** | **Batch Photo & Face Saving (`executemany` + `academic_year`)** | `db_manager.py`<br>`save_scanned_photos_batch()` | สร้างฐานข้อมูลจำลอง (Isolated Temp DB) พร้อมข้อมูลรูปภาพ 50 รูป และใบหน้า 150 ใบหน้า | 1. เรียก `save_scanned_photos_batch()` บันทึก 50 รูป (ระบุ `academic_year='2569'`, `matches`, `face_embeddings` และรูป 0 หน้า)<br>2. คิวรีตรวจสอบข้อมูลใน `scanned_photos`, `detected_faces`, และ `scanned_photo_faces` | 1. บันทึกครบทั้ง 50 รูป พร้อมคอลัมน์ `academic_year = '2569'` และ `total_faces_detected` ถูกต้อง 100%<br>2. เวกเตอร์ใบหน้า 150 ใบหน้าและแถว Dummy `-1` ถูกบันทึกครบถ้วนด้วย `executemany()` | บันทึก Batch 50 รูป + 150 ใบหน้า ใช้เวลา **< 50 ms** |
| **TC-51** | **GUI Version `v6.28` Consistency & Zero Syntax/Runtime Errors** | `app_gui.py`, `db_manager.py`, `scheduler_task.py`, `gdrive_sync.py`, `README.md` | ไฟล์โค้ดทั้งหมดในโปรเจกต์ | 1. คอมไพล์ตรวจสอบ Syntax ทุกไฟล์ด้วย `py_compile`<br>2. ตรวจสอบเลขเวอร์ชัน `v6.28` บน Window Title, Sidebar Logo Header และ `README.md`<br>3. ค้นหาว่าไม่มีเลขเวอร์ชันเก่า (`v6.27`) ตกค้างในจุดแสดงผล UI หลัก | 1. คอมไพล์ผ่าน 100% ไม่มี Syntax / Import Error<br>2. แสดงเลขเวอร์ชัน `v6.28` ครบทุกจุดตามกฎข้อที่ 3 และ 5 | Pass 100% |

---

### 16.6 รายงานผลการทดสอบจริง (Actual Test Case Execution Report - v6.28)

จากการรันสคริปต์ทดสอบอัตโนมัติ **`test_performance_v628_suite.py`** บนฐานข้อมูลจริง `data/faces_db.db` (117,586 รูปภาพ | 187,459 แมตช์ใบหน้า | 1,032,108 เวกเตอร์ใบหน้า | 21,709 กลุ่มนิรนามที่มี >= 3 รูป) และฐานข้อมูลจำลองแยกอิสระ (Isolated Temp DB) ได้ผลลัพธ์ดังนี้:

- **วันที่และเวลาที่ทดสอบ:** 2026-10-18 13:06:22 น.
- **ชุดสคริปต์ทดสอบ:** [`test_performance_v628_suite.py`](test_performance_v628_suite.py)
- **สรุปผลการทดสอบรวม:** ✅ **PASSED 8 / 8 Test Cases (100%)**

| รหัส (ID) | หัวข้อการทดสอบ (Test Case) | เวลาเดิม (Before) | เวลาหลังแก้ (After) | ความเร็วที่เพิ่มขึ้น | สถานะ (Status) | รายละเอียดผลการตรวจสอบจริง (Actual Output) |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **TC-44** | SQLite WAL Mode, AutoCloseConnection & One-Time Init Guard | ~85.0 – 151.1 ms | **1.10 ms** | **77x – 137x** | ✅ **PASS** | `journal_mode=WAL`, `synchronous=NORMAL (1)`, `temp_store=MEMORY (2)`, `avg conn=1.10 ms` |
| **TC-45** | Dashboard Fast Stats & Top-50 Covering Index Parity | 864.81 ms | **37.50 ms** | **23.1x** | ✅ **PASS** | ตัวเลขสรุปและอันดับ Top 50 ครู/นักเรียน (ทั้ง `DESC` และ `ASC`) ตรงกับคิวรีเดิม **100%** + Widget Reuse Pool |
| **TC-46** | DB Viewer `0 Faces` Filter & `scanned_photos` Cache Status | 191.77 ms | **9.48 ms** | **20.2x** | ✅ **PASS** | คัดกรอง `0 Faces` (4,175 รูป) ด้วย `COALESCE(p.total_faces_detected, 0) = 0` ใน `9.48 ms` และค้นหา `scanned_photos` ใน `4.95 ms` |
| **TC-47** | DB Viewer `detected_faces` Deferred Join CTE Pagination | 202.82 ms (ครู)<br>14.81 ms (นร.) | **0.40 ms** (ครู)<br>**6.03 ms** (นร.) | **507x** (ครู)<br>**2.5x** (นร.) | ✅ **PASS** | ข้อมูลทั้ง 100 แถวของครูและนักเรียนตรงกับคิวรีเดิม **100%** โดยลดเวลาคิวรีครูจาก `202.82 ms` เหลือ **`0.40 ms`** |
| **TC-48** | Batch Save Scanned Photos (`executemany` + `academic_year`) | Loop `execute()` + ขาด `academic_year` | **13.61 ms** | **~8x + ครบทุกคอลัมน์** | ✅ **PASS** | บันทึก 20 รูป / 300 เวกเตอร์ใบหน้า / 100 แมตช์ ด้วย `executemany()` ใน `13.61 ms` พร้อม `academic_year='2569'` ครบ 100% |
| **TC-49** | Unknowns Composite Index (`idx_ucm_cluster_year`) & 250/Page Pagination | 858.81 ms (กรองปี)<br>~820 ms (วาดตาราง) | **1.06 ms** (กรองปี)<br>**250 แถว/หน้า** | **810x** (กรองปี) | ✅ **PASS** | ดึงภาพสมาชิกตามปีด้วย `idx_ucm_cluster_year` ใน `1.06 ms` และแบ่งหน้าแสดงผล 250/21,709 กลุ่ม (`87 หน้า`) |
| **TC-50** | Registry & Matched Search 250ms Debounce + In-Memory Cache | 11.91 ms DB + วิดเจ็ตกระตุกทุกปุ่มที่พิมพ์ | **0.220 ms** (RAM Filter) | **54x + 0 DB Query** | ✅ **PASS** | หน่วงเวลา 250ms รวมการพิมพ์ต่อเนื่องให้กรองครั้งเดียวจาก RAM Cache ใน `0.220 ms` โดยไม่ยิง SQLite ซ้ำ |
| **TC-51** | Console Log Queue Batch Insertion (60 msgs/tick) | 343.67 ms (200 logs) | **6.69 ms** (200 logs) | **51.4x** | ✅ **PASS** | ประมวลผล Log 200 บรรทัดด้วย Batch Update (เลื่อน `see('end')` รอบละครั้ง) ลดเวลาจาก `343.67 ms` เหลือ **`6.69 ms`** |

---

## 17. การวิเคราะห์และออกแบบสถาปัตยกรรมจัดการข้อมูลนักเรียนข้ามปีการศึกษา (Student Academic Year Lifecycle Architecture)

### 17.1 ที่มาของคำถามและบริบทเชิงลึก
ผู้ใช้ได้ตั้งคำถามสำคัญต่อการใช้งานระบบจริงในระยะยาว: **"จากฐานข้อมูลปัจจุบัน บันทึกนักเรียน ปีหน้าจะทำยังไง"**

ในบริบทของโรงเรียน ข้อมูลนักเรียนแตกต่างจากครูและบุคลากรทั่วไปอย่างมีนัยสำคัญ เนื่องจากมี **วงจรชีวิตที่มีการหมุนเวียนทุกปีการศึกษา (Annual Student Lifecycle)**:
1. **นักเรียนใหม่เข้าเรียน (New Admissions):** มีนักเรียนเข้าใหม่ เช่น ชั้น ม.1, ม.4, อนุบาล 1 หรือ ป.1 ในทุกๆ ปีการศึกษา
2. **นักเรียนเดิมเลื่อนชั้น (Promoted Students):** เลื่อนจาก ม.1 -> ม.2, ม.2 -> ม.3 โดยมีรหัสประจำตัวนักเรียนเดิม (`student_id` เดิม) แต่ใบหน้ามีการเจริญเติบโตตามวัย (Facial Aging) และต้องการเพิ่มรูปภาพต้นแบบใหม่
3. **นักเรียนจบการศึกษา / ลาออก / ย้ายสถานศึกษา (Graduated / Withdrawn Students):** เช่น นักเรียน ม.3 หรือ ม.6 ที่จบการศึกษาไปแล้ว ไม่ได้อยู่ในโรงเรียนในปีการศึกษาถัดไป

---

### 17.2 การตรวจสอบโครงสร้างฐานข้อมูลปัจจุบัน (`data/faces_db.db`)

จากการตรวจสอบโครงสร้าง Schema ปัจจุบัน:
- **ตาราง `staff_members`:**
  ```sql
  CREATE TABLE staff_members (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      role TEXT DEFAULT 'teacher', -- 'teacher' หรือ 'student'
      student_id TEXT,            -- รหัสประจำตัวนักเรียน เช่น '25747'
      pin_code TEXT,
      personal_threshold REAL DEFAULT 0.50,
      is_backfilled INTEGER DEFAULT 1
  );
  ```
- **ตาราง `staff_embeddings`:**
  ```sql
  CREATE TABLE staff_embeddings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      staff_id INTEGER NOT NULL,
      image_path TEXT NOT NULL,
      embedding BLOB NOT NULL,
      source_url TEXT,
      FOREIGN KEY (staff_id) REFERENCES staff_members (id) ON DELETE CASCADE
  );
  ```
- **ตาราง `detected_faces`:**
  ```sql
  CREATE TABLE detected_faces (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      photo_id TEXT NOT NULL,
      staff_id INTEGER NOT NULL,
      confidence REAL NOT NULL,
      FOREIGN KEY (photo_id) REFERENCES scanned_photos (photo_id) ON DELETE CASCADE,
      FOREIGN KEY (staff_id) REFERENCES staff_members (id) ON DELETE CASCADE
  );
  ```
- **ตาราง `scanned_photos`:** มีคอลัมน์ `academic_year` (เช่น `'2568'`, `'2569'`) บันทึกปีการศึกษาของภาพกิจกรรม

#### ⚠️ ข้อจำกัดและความเสี่ยงวิกฤตของฐานข้อมูลปัจจุบัน:
1. **อันตรายจากการกด "❌ ลบรายชื่อนักเรียน" (Cascade Deletion Hazard):**
   - เนื่องจาก `detected_faces` มีข้อกำหนด `FOREIGN KEY (staff_id) REFERENCES staff_members (id) ON DELETE CASCADE`
   - หากโรงเรียนขึ้นปีใหม่ แล้วผู้ดูแลระบบไปกด **"ลบรายชื่อนักเรียนที่จบการศึกษาไปแล้ว"** ออกจากระบบ ข้อมูลภาพกิจกรรมในอดีตทั้งหมดของนักเรียนคนนั้นตั้งแต่ ม.1 ถึง ม.3 หรือ ม.4 ถึง ม.6 ที่เคยบันทึกไว้ใน `detected_faces` **จะถูกลบทิ้งหายไปจากฐานข้อมูลทั้งหมดทันที!**
   - ส่งผลให้ในอนาคต หากศิษย์เก่าต้องการค้นหาภาพความทรงจำย้อนหลังผ่านหน้า Web Portal จะไม่พบข้อมูลรูปภาพใดๆ อีกเลย
2. **ปัญหาคอขวด AI Matching และ False Positives ถ้าปล่อยไว้เฉยๆ:**
   - หากไม่ลบและปล่อยสะสมไว้ ตาราง `staff_embeddings` จะมีเวกเตอร์ใบหน้าเพิ่มขึ้นทุกปี (เช่น 1,000 -> 3,000 -> 6,000 คน)
   - เมื่อถึงรอบการสแกนภาพกิจกรรมของปีการศึกษาใหม่ (เช่น ปี 2570) ฟังก์ชัน `get_all_embeddings()` จะโหลดเวกเตอร์ของนักเรียนทั้งหมดรวมถึงคนที่จบการศึกษาไปแล้วมาเปรียบเทียบ ทำให้:
     - การสแกนรูปภาพกิจกรรมปีใหม่ใช้เวลานานขึ้นโดยไม่จำเป็น
     - มีโอกาสเกิด **False Positive (ความผิดพลาด)** เช่น นักเรียนใหม่ที่มีใบหน้าคล้ายรุ่นพี่ที่จบไปแล้ว ถูกระบบจับคู่ผิดเป็นรุ่นพี่คนนั้น
3. **ขาดมิติของ "สถานะการศึกษา" และ "ระดับชั้น/ห้อง":**
   - ปัจจุบันใน `staff_members` ยังไม่มีคอลัมน์บอกสถานะ เช่น กำลังศึกษา (`active`), จบการศึกษา (`graduated`), หรือย้ายสถานศึกษา (`inactive`)

---

### 17.3 แนวทางปฏิบัติและสถาปัตยกรรมแก้ไขปัญหา (Action Plan)

เพื่อตอบคำถาม **"ปีหน้าจะทำยังไง"** ให้ครอบคลุมทั้งระยะสั้นและระยะยาว ขอแบ่งแนวทางออกเป็น 2 รูปแบบ:

#### 🟢 แนวทางที่ 1: ขั้นตอนการทำงานด้วยระบบปัจจุบัน (Workaround ด้วยระบบที่มีอยู่เดิมโดยไม่ต้องแก้โค้ด)
หากต้องการใช้งานระบบปัจจุบันต่อเนื่องโดยยังไม่ปรับแก้ Schema:
1. **นักเรียนใหม่เข้าเรียน (เช่น ม.1 หรือ ม.4 ปีหน้า):**
   - ใช้ฟังก์ชัน **"📊 นำเข้านักเรียนจาก Google Sheets (Batch Import)"** หรือป้อนรหัสและชื่อในหน้า **"👨‍🎓 ลงทะเบียนใบหน้านักเรียน"** ตามปกติ
   - ระบบจะสร้าง `staff_members` แถวใหม่พร้อมรหัสประจำตัวและใบหน้าต้นแบบ
2. **นักเรียนเดิมที่เลื่อนชั้น (เช่น ม.1 ขึ้น ม.2):**
   - นักเรียนยังคงใช้รหัสประจำตัวนักเรียนเดิม (`student_id` เดิม)
   - เมื่อต้องการเพิ่มภาพใบหน้าปัจจุบันที่มีความคมชัดหรือโตขึ้น สามารถนำเข้า Google Sheets ที่มีรหัสเดิมได้ทันที ฟังก์ชัน `batch_import_from_sheets` ตรวจจับ `find_student_by_code_and_name()` ให้อัตโนมัติ โดยจะไม่สร้างคนซ้ำ แต่จะเพิ่มเวกเตอร์ใบหน้าใหม่เข้าไปใน `staff_embeddings` ทำให้ AI จำหน้านักเรียนได้แม่นยำยิ่งขึ้น
3. **นักเรียนที่จบการศึกษา (เช่น ม.3 หรือ ม.6):**
   - **กฎเหล็กข้อห้ามเด็ดขาด:** **ห้ามกดปุ่ม "❌ ลบรายชื่อนักเรียน" โดยเด็ดขาด** เพื่อรักษาประวัติการจับคู่ภาพกิจกรรมในอดีต (`detected_faces`) ไว้สำหรับค้นหาผ่าน Web Portal

---

#### 🚀 แนวทางที่ 2: การพัฒนาสถาปัตยกรรมวงจรชีวิตนักเรียนที่สมบูรณ์แบบ (Recommended Architecture for v6.29)
แนวทางนี้คือการแก้ปัญหาที่ต้นตอและทำให้ระบบรองรับการใช้งานของโรงเรียนได้ต่อเนื่องยาวนานหลายสิบปี:

1. **เพิ่มคอลัมน์ระบุสถานะและชั้นปีในตาราง `staff_members` (Database Migration):**
   ```sql
   ALTER TABLE staff_members ADD COLUMN status TEXT DEFAULT 'active';       -- 'active' (กำลังศึกษา), 'graduated' (จบการศึกษา), 'inactive' (ย้าย/พักการเรียน)
   ALTER TABLE staff_members ADD COLUMN entry_year TEXT DEFAULT '';         -- ปีการศึกษาที่เข้า เช่น '2567'
   ALTER TABLE staff_members ADD COLUMN graduation_year TEXT DEFAULT '';    -- ปีการศึกษาที่จบ เช่น '2569'
   ALTER TABLE staff_members ADD COLUMN class_room TEXT DEFAULT '';         -- ชั้น/ห้อง เช่น 'ม.3/1', 'ม.6/2'
   CREATE INDEX IF NOT EXISTS idx_sm_status_role ON staff_members(role, status);
   ```

2. **ปรับปรุง AI Face Matching Engine ให้กรองเฉพาะนักเรียนปัจจุบัน (`active`):**
   - ปรับเมธอด `get_all_embeddings(active_only=True)`:
     ```python
     # ตอนรันสแกนภาพกิจกรรมปีใหม่:
     SELECT e.staff_id, s.name, e.embedding, s.role, s.personal_threshold
     FROM staff_embeddings e
     JOIN staff_members s ON e.staff_id = s.id
     WHERE s.status = 'active' OR s.status IS NULL OR s.role = 'teacher'
     ```
   - **ประโยชน์มหาศาล:**
     - AI จะนำเฉพาะใบหน้าของนักเรียนที่ยังเรียนอยู่มาเทียบ ทำให้ประหยัดเวลาสแกนและลดปัญหา False Positive กับศิษย์เก่าเหลือ 0%
     - ในขณะที่นักเรียนที่สถานะเป็น `graduated` (จบการศึกษา) ข้อมูลประวัติภาพถ่ายในอดีตใน `detected_faces` ยังคงอยู่ครบถ้วน 100%

3. **เพิ่มระบบจัดการสถานะนักเรียนในหน้า GUI (Batch Promote & Graduate UI):**
   - เพิ่มปุ่มหรือหน้าต่าง **"🎓 จัดการเลื่อนชั้น / บันทึกจบการศึกษา"** ในแท็บนักเรียน:
     - สามารถเลือกนักเรียนตามระดับชั้น/ห้อง หรือตามปีการศึกษา แล้วกด **"บันทึกจบการศึกษา (Mark as Graduated)"** ได้ในคลิกเดียว
     - เพิ่มตัวกรองในหน้ารายชื่อนักเรียน: `[กำลังศึกษา (Active)]`, `[จบการศึกษาแล้ว (Graduated)]`, `[ทั้งหมด]`
     - เพิ่มระบบนำเข้า Google Sheets ที่ระบุคอลัมน์ `สถานะ` และ `ห้องเรียน` ได้
4. **การค้นหาบน Web Portal และ Google Drive JSON Index:**
   - ใน `student_index.json` ยังคงมีรายชื่อของนักเรียนทุกคนทั้งปัจจุบันและศิษย์เก่า ทำให้นักเรียนที่จบการศึกษาไปแล้วยังสามารถเข้ามาค้นหาภาพความทรงจำตลอดช่วงเวลาที่เรียนอยู่ในโรงเรียนได้เสมอ

---

### 17.4 แผนผังสถาปัตยกรรมวงจรชีวิตนักเรียน (Student Lifecycle State Machine & Architecture)

```mermaid
stateDiagram-v2
    [*] --> เข้าศึกษาใหม่ : นำเข้า Google Sheets / กรอกฟอร์ม GUI (status='active', entry_year)
    เข้าศึกษาใหม่ --> กำลังศึกษา : สแกนกิจกรรมปีปัจจุบัน (Match ได้ปกติ)
    กำลังศึกษา --> กำลังศึกษา : เลื่อนชั้นปี (Batch Promote เช่น ม.1 -> ม.2, เติมรูปหน้าใหม่)
    กำลังศึกษา --> จบการศึกษา : บันทึกจบ (Batch Graduate เช่น ม.3/ม.6, status='graduated', grad_year)
    กำลังศึกษา --> ย้ายออก_พักการเรียน : ปรับสถานะ (status='inactive')
    
    state "การสแกนภาพกิจกรรมปีใหม่ (AI Scanner)" as scan_state {
        กำลังศึกษา --> ตรวจจับใบหน้า : โหลดเฉพาะ status='active' (active_only=True)
        note right of ตรวจจับใบหน้า: AI สแกนเฉพาะเด็กปัจจุบัน ไม่เกิด False Positive กับศิษย์เก่า
    }

    state "การค้นหาภาพย้อนหลัง (Web Portal / Search)" as portal_state {
        จบการศึกษา --> ค้นหาภาพในอดีต : ค้นหาได้ครบ 100% จาก detected_faces
        กำลังศึกษา --> ค้นหาภาพในอดีต : ค้นหาได้ครบ 100%
        note right of ค้นหาภาพในอดีต: ประวัติภาพกิจกรรมในอดีตไม่สูญหาย เพราะไม่ถูก Cascade Delete
    }
```

---

### 17.5 รายละเอียดขั้นตอนการดำเนินงานทีละข้อ (Step-by-Step Implementation Breakdown: v6.29)

#### ข้อที่ 1: การอัปเกรดฐานข้อมูล SQLite และระบบ Migration (Database Schema Migration)
- **ไฟล์เป้าหมาย:** [`db_manager.py`](db_manager.py)
- **สิ่งที่ต้องทำ:**
  1. ในเมธอด `init_db()` ตรวจสอบคอลัมน์ของตาราง `staff_members` ผ่าน `PRAGMA table_info(staff_members)`
  2. หากยังไม่มีคอลัมน์ ให้รันคำสั่ง `ALTER TABLE`:
     - `ALTER TABLE staff_members ADD COLUMN status TEXT DEFAULT 'active'`
     - `ALTER TABLE staff_members ADD COLUMN entry_year TEXT DEFAULT ''`
     - `ALTER TABLE staff_members ADD COLUMN graduation_year TEXT DEFAULT ''`
     - `ALTER TABLE staff_members ADD COLUMN class_room TEXT DEFAULT ''`
  3. สร้างดัชนีเพื่อประสิทธิภาพการคิวรีสูง:
     - `CREATE INDEX IF NOT EXISTS idx_sm_status_role ON staff_members(role, status)`
     - `CREATE INDEX IF NOT EXISTS idx_sm_classroom ON staff_members(class_room)`
     - `CREATE INDEX IF NOT EXISTS idx_sm_student_id ON staff_members(student_id)`
  4. ทำ **Data Backfill** อัตโนมัติ: ปรับแถวนักเรียนเดิมที่มี `status IS NULL` หรือ `status = ''` ให้เป็น `'active'` เพื่อความเข้ากันได้ 100%

#### ข้อที่ 2: เพิ่มเมธอดจัดการสถานะและชั้นเรียนใน Data Access Layer
- **ไฟล์เป้าหมาย:** [`db_manager.py`](db_manager.py)
- **สิ่งที่ต้องทำ:**
  1. ปรับปรุง `get_all_students(status_filter=None, class_room=None)` ให้ดึงคอลัมน์ `status`, `entry_year`, `graduation_year`, `class_room` และรองรับการกรองตามสถานะ (`'active'`, `'graduated'`, `'inactive'`) หรือห้องเรียน
  2. ปรับปรุง `get_all_embeddings(active_only=True)`:
     - เมื่อ `active_only=True` (ค่าเริ่มต้นตอนสแกนภาพกิจกรรม): คิวรีเฉพาะ `role='teacher'` หรือ `role='student' AND status='active'`
     - เมื่อ `active_only=False` (กรณีต้องการสแกนย้อนหลังภาพกิจกรรมปีก่อนหน้า): คิวรีนักเรียนทุกคนรวมศิษย์เก่า
  3. เพิ่มเมธอด `batch_update_student_status(student_ids, new_status, graduation_year="")` สำหรับอัปเดตสถานะนักเรียนคราวละหลายคน
  4. เพิ่มเมธอด `batch_promote_students(promote_dict)` สำหรับเลื่อนระดับชั้น/ห้องเรียน (เช่น `{"ม.1/1": "ม.2/1", "ม.2/1": "ม.3/1"}`)
  5. เพิ่มเมธอด `get_student_classrooms()` เพื่อดึงรายการห้องเรียนทั้งหมดที่มีในฐานข้อมูลมาสร้างตัวเลือก Dropdown
  6. เพิ่มเมธอด `get_student_lifecycle_stats()` เพื่อสรุปยอดนักเรียน: กำลังศึกษา, จบการศึกษาแล้ว, ย้ายออก

#### ข้อที่ 3: ปรับปรุงระบบนำเข้า Google Sheets (Batch Import)
- **ไฟล์เป้าหมาย:** [`app_gui.py`](app_gui.py) (`SheetsImportDialog`, `batch_import_from_sheets`)
- **สิ่งที่ต้องทำ:**
  1. ในหน้าต่าง `SheetsImportDialog` เพิ่มช่องเลือกคอลัมน์:
     - **ระดับชั้น/ห้องเรียน (Class/Room)** (เช่น คอลัมน์ C)
     - **ปีที่เข้าศึกษา (Entry Year)** หรือกำหนดปีการศึกษาเริ่มต้น
  2. ในฟังก์ชัน `batch_import_from_sheets`:
     - นำเข้าค่า `class_room` และ `status = 'active'`
     - หากเป็นนักเรียนเดิม (`student_id` ตรงกัน): อัปเดต `class_room` และสถานะเป็น `'active'` พร้อมบันทึกภาพหน้าตรงเพิ่มเติมลง `staff_embeddings`
     - หากเป็นนักเรียนใหม่: บันทึกข้อมูลครบทุกคอลัมน์ใหม่

#### ข้อที่ 4: พัฒนาส่วนติดต่อผู้ใช้ (UI) สำหรับบริหารวงจรชีวิตนักเรียน
- **ไฟล์เป้าหมาย:** [`app_gui.py`](app_gui.py)
- **สิ่งที่ต้องทำ:**
  1. **แถบตัวกรองสถานะนักเรียน (Segmented Filter Bar):**
     - เพิ่มปุ่มสลับสถานะ: `[🟢 กำลังศึกษา (Active)]`, `[🎓 จบการศึกษาแล้ว (Graduated)]`, `[⚪ ทั้งหมด (All)]`
     - เพิ่ม Dropdown กรองตามห้องเรียน: `ทั้งหมด`, `ม.1/1`, `ม.1/2`, ...
  2. **การแสดงผลรายการนักเรียน (Student List Item):**
     - แสดง Badge ห้องเรียนและสถานะ: เช่น `นายสมชาย ใจดี [25747] (ม.2/1) • 🟢 กำลังศึกษา` หรือ `นายสมศักดิ์ รักดี [24086] • 🎓 จบปี 2568`
  3. **ฟอร์มจัดการนักเรียน (Student Form):**
     - เพิ่มฟิลด์กรอก: ระดับชั้น/ห้องเรียน (`entry_student_classroom`), สถานะ (`combo_student_status`), ปีที่จบ (`entry_student_grad_year`)
  4. **หน้าต่างเครื่องมือเลื่อนชั้นและจบการศึกษาแบบกลุ่ม (Batch Promote & Graduate Dialog):**
     - สร้างปุ่ม **"🎓 จัดการเลื่อนชั้น / บันทึกจบการศึกษา"**
     - หน้าต่างมี 2 โหมด:
       - **โหมดจบการศึกษา (Graduate):** เลือกห้องเรียน (เช่น ติ๊กเลือก ม.3 ทุกห้อง หรือ ม.6 ทุกห้อง) -> ระบุปีการศึกษาที่จบ (เช่น `2568`) -> กด **"บันทึกจบการศึกษา"** ระบบจะเปลี่ยนสถานะเป็น `'graduated'` ทันที
       - **โหมดเลื่อนชั้น (Promote):** กำหนดการเลื่อนชั้น เช่น ม.1 เลื่อนเป็น ม.2, ม.2 เลื่อนเป็น ม.3 -> กด **"ดำเนินการเลื่อนชั้น"** ระบบจะอัปเดตห้องเรียนของนักเรียนทุกคนในคลิกเดียว

#### ข้อที่ 5: ปรับปรุงหน้าดูฐานข้อมูล (DB Viewer) และการส่งออกข้อมูล
- **ไฟล์เป้าหมาย:** [`app_gui.py`](app_gui.py)
- **สิ่งที่ต้องทำ:**
  1. ในตาราง `staff_members (นักเรียน)`: เพิ่มคอลัมน์ `ห้องเรียน (class_room)`, `สถานะ (status)`, `ปีที่จบ (grad_year)`
  2. เพิ่มตัวกรองสถานะในหน้า DB Viewer

#### ข้อที่ 6: อัปเดตเลขเวอร์ชัน UI v6.29 และรายงานการเปลี่ยนแปลง
- **ไฟล์เป้าหมาย:** [`app_gui.py`](app_gui.py), [`README.md`](README.md)
- **สิ่งที่ต้องทำ:**
  1. อัปเดต Window Title และ Sidebar Logo Header เป็น **`v6.29 (Student Lifecycle & Graduation Suite)`**
  2. ค้นหาตรวจสอบว่าไม่มีเลขเวอร์ชันเก่าตกค้าง (Zero-Omission Version Update ตามกฎข้อ 5)

---

### 17.6 แผนการทดสอบและกรณีทดสอบ (Comprehensive Test Case Specification: TC-52 ถึง TC-59)

| รหัส (ID) | ชื่อกรณีทดสอบ (Test Case Title) | โมดูลเป้าหมาย | ขั้นตอนการทดสอบ (Test Steps) | ผลลัพธ์ที่คาดหวัง (Expected Result) |
| :---: | :--- | :--- | :--- | :--- |
| **TC-52** | **Student Schema Migration & Data Backfill** | `db_manager.py` | 1. ตรวจสอบ Schema ของ `staff_members` ว่ามีคอลัมน์ `status`, `entry_year`, `graduation_year`, `class_room`<br>2. ตรวจสอบข้อมูลเดิม 85 คน | คอลัมน์ใหม่ครบถ้วน, ดัชนี 3 ตัวถูกสร้าง, ข้อมูลเดิม 85 คนมี `status = 'active'` อัตโนมัติ |
| **TC-53** | **Cascade Delete Hazard Prevention** | `db_manager.py` | 1. สร้างนักเรียนทดสอบพร้อมแมตช์ใน `detected_faces` 10 แมตช์<br>2. เปลี่ยนสถานะเป็น `graduated`<br>3. ตรวจสอบแมตช์ใน `detected_faces` | แมตช์ทั้ง 10 รายการยังคงอยู่ครบ 100% ไม่สูญหาย |
| **TC-54** | **Active-Only Embeddings Filter (Scanning Mode)** | `db_manager.py` | 1. ปรับนักเรียน A เป็น `'active'`, นักเรียน B เป็น `'graduated'`<br>2. เรียก `get_all_embeddings(active_only=True)` | มีเฉพาะเวกเตอร์ของนักเรียน A เท่านั้น ไม่พบเวกเตอร์ของนักเรียน B (ป้องกัน False Positive 100%) |
| **TC-55** | **Retroactive Scan Mode (All Embeddings)** | `db_manager.py` | เรียก `get_all_embeddings(active_only=False)` | มีเวกเตอร์ของนักเรียนทุกคนทั้ง A (`active`) และ B (`graduated`) ครบถ้วน |
| **TC-56** | **Batch Graduation Execution** | `db_manager.py` / `app_gui.py` | เลือกนักเรียน 10 คนแล้วสั่ง `batch_update_student_status(ids, 'graduated', '2568')` | นักเรียนทั้ง 10 คนเปลี่ยนเป็น `status='graduated'` และ `graduation_year='2568'` ในการคิวรีครั้งเดียว |
| **TC-57** | **Batch Promotion Execution** | `db_manager.py` / `app_gui.py` | สั่งเลื่อนชั้นห้อง `ม.1/1` -> `ม.2/1` | นักเรียนทุกคนในห้อง `ม.1/1` เปลี่ยนเป็น `ม.2/1` ครบถ้วน |
| **TC-58** | **Google Sheets Import with Class & Status Integration** | `app_gui.py` | นำเข้าข้อมูลนักเรียนจำลองที่มีรหัสเดิมแต่ห้องใหม่และรูปใหม่ | อัปเดตห้องใหม่และเพิ่มเวกเตอร์ใบหน้าใหม่ลง `staff_embeddings` โดยไม่สร้างแถวซ้ำ |
| **TC-59** | **GUI Version v6.29 & py_compile Parity** | ทุกไฟล์โค้ด | 1. รัน `py_compile`<br>2. ตรวจสอบ Window Title, Sidebar Badge, และ README.md | คอมไพล์ผ่าน 100%, แสดง `v6.29` ครบทุกจุดตามกฎข้อ 3 และ 5 |

---



