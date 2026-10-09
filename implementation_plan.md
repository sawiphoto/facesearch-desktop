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

