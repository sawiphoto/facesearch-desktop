import os
import time
import json
import logging
import threading
import traceback
import schedule
from datetime import datetime

logger = logging.getLogger("FaceSearchApp")

# เปิดใช้งานโหมด Debug การซิงค์นักเรียน
DEBUG_SYNC_MODE = True

class SchedulerTask:
    def __init__(self, db_manager, sync_manager, face_analyzer, app_gui):
        self.db = db_manager
        self.sync_manager = sync_manager
        self.analyzer = face_analyzer
        self.app_gui = app_gui
        self.is_running = False
        self.stop_requested = False
        
        # Schedule midnight trigger
        schedule.every().day.at("00:00").do(self.run_scheduled_tasks)
        
        # Start background thread
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()

    def request_stop(self):
        if self.is_running:
            self.stop_requested = True
            logger.info("[SCHEDULE] ร้องขอการหยุดทำงานชั่วคราว... กำลังสรุปผลในรอบปัจจุบัน")

    def _scheduler_loop(self):
        while True:
            schedule.run_pending()
            time.sleep(60)
            
    def run_scheduled_tasks_manual(self):
        if self.is_running:
            logger.info("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self.run_scheduled_tasks, daemon=True).start()

    def run_task_2_manual(self):
        if self.is_running:
            logger.info("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self._run_task_2_only, daemon=True).start()

    def _run_task_2_only(self):
        self.is_running = True
        self.stop_requested = False
        try:
            logger.info("="*50)
            logger.info("[SCHEDULE] เริ่มทำงาน Task 2 เฉพาะกิจ (v1.8.3)")
            if not self.sync_manager.connected:
                self.sync_manager.connect()
            self._task_2_sync_new_students()
            from datetime import datetime, timedelta, timezone
            bkk_tz = timezone(timedelta(hours=7))
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[SCHEDULE] Task 2 เสร็จสมบูรณ์ ({bkk_time} BKK)")
            logger.info("="*50)
        except Exception as e:
            logger.error(f"[SCHEDULE Error] {e}", exc_info=True)
        finally:
            self.is_running = False
            self.stop_requested = False

    def run_scheduled_tasks(self):
        if self.is_running:
            return
            
        self.is_running = True
        self.stop_requested = False
        try:
            logger.info("="*50)
            logger.info("[SCHEDULE] เริ่มทำงาน Task อัตโนมัติ (v1.8)")
            logger.info("="*50)
            
            # Ensure Google API is connected
            if not self.sync_manager.connected:
                self.sync_manager.connect()
                
            # Ensure Analyzer is initialized
            if self.analyzer is None:
                try:
                    from face_analyzer import FaceAnalyzer
                    self.analyzer = FaceAnalyzer(use_gpu=False)
                    self.analyzer.initialize()
                except Exception as e:
                    logger.error(f"[SCHEDULE] Warning: FaceAnalyzer init failed: {e}")
            
            # Task 1: Check New Folders
            self._task_1_scan_new_folders()
            
            if not self.stop_requested:
                # Task 2: Check New Students
                self._task_2_sync_new_students()
            
            from datetime import datetime, timedelta, timezone
            bkk_tz = timezone(timedelta(hours=7))
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[SCHEDULE] กระบวนการทำงานอัตโนมัติเสร็จสมบูรณ์ ({bkk_time} BKK)")
            logger.info("="*50)
            
        except Exception as e:
            logger.error(f"[SCHEDULE] เกิดข้อผิดพลาดระหว่างทำงาน: {e}", exc_info=True)
        finally:
            self.is_running = False
            self.stop_requested = False

    def _get_unscanned_subfolder(self, root_folder_id):
        """ค้นหาโฟลเดอร์ย่อย 1 โฟลเดอร์ที่มีรูปยังไม่ได้สแกน"""
        query_dirs = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subdirs = []
        page_token = None
        while True:
            try:
                results = self.sync_manager.drive_service.files().list(
                    q=query_dirs, fields="nextPageToken, files(id, name)", pageToken=page_token, pageSize=100
                ).execute()
                subdirs.extend(results.get("files", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                logger.error(f"Error fetching subdirs for {root_folder_id}: {e}")
                break
                
        # ดึงรายชื่อไฟล์ที่สแกนแล้วจาก DB
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT drive_file_id FROM scanned_photos")
            scanned_ids = set(row[0] for row in c.fetchall())

        for subdir in subdirs:
            subdir_id = subdir['id']
            # เช็คไฟล์รูปในโฟลเดอร์นี้
            query_files = f"'{subdir_id}' in parents and (mimeType contains 'image/') and trashed = false"
            try:
                f_results = self.sync_manager.drive_service.files().list(
                    q=query_files, fields="files(id)", pageSize=500
                ).execute()
                files = f_results.get("files", [])
                
                # ตรวจสอบว่ามีรูปไหนที่ยังไม่อยู่ใน scanned_ids
                for f in files:
                    if f['id'] not in scanned_ids:
                        return subdir # เจอโฟลเดอร์สีแดง (มีรูปยังไม่สแกน)
            except Exception:
                pass
                
        return None # สีเขียวหมดแล้ว

    def _task_1_scan_new_folders(self):
        logger.info("[SCHEDULE] กำลังทำ task โฟลเดอร์ใหม่...")
        target_folders = [
            ("ภาพกิจกรรม 2569", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
            ("ภาพกิจกรรม 2568", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
            ("ภาพกิจกรรม 2565-2567", "1BjYQwoso9FKv42XK6RJi1gPS8kyK_jCg")
        ]
        
        scanned_in_this_run = set()
        for year_name, year_id in target_folders:
            if self.stop_requested: break
            while True:
                if self.stop_requested: break
                red_folder = self._get_unscanned_subfolder(year_id)
                if not red_folder or red_folder['id'] in scanned_in_this_run:
                    break
                scanned_in_this_run.add(red_folder['id'])
                    
                logger.info(f"[SCHEDULE] เริ่มทำการสแกนรูปภาพในโฟลเดอร์: {red_folder['name']}")
                # เรียกใช้กระบวนการสแกนของระบบ (ใช้ background scan logic)
                try:
                    if hasattr(self.app_gui, 'process_scanning_headless'):
                        success = self.app_gui.process_scanning_headless([red_folder['id']], folder_name=red_folder['name'])
                        if not success:
                            logger.error(f"[SCHEDULE] Error: process_scanning_headless aborted for {red_folder['name']}")
                            break # หลุดจาก while เพื่อป้องกัน infinite loop
                        logger.info(f"[SCHEDULE] สแกนโฟลเดอร์ {red_folder['name']} เสร็จสิ้นเรียบร้อย")
                    else:
                        logger.error(f"[SCHEDULE] Error: app_gui does not have process_scanning_headless")
                        break
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error scanning {red_folder['name']}: {e}")
                    break # หลุดจาก while เพื่อไม่ให้ค้าง
                    
    def _extract_drive_id(self, url):
        """ดึง ID จากลิงก์ Google Drive (รองรับ /d/, uc?id=, open?id=, และ raw ID)"""
        if not isinstance(url, str):
            return None
        url = url.strip()
        if not url:
            return None
            
        # 1. ลิงก์รูปแบบ /d/ID หรือ /file/d/ID
        if '/d/' in url:
            parts = url.split('/d/')
            if len(parts) > 1:
                return parts[1].split('/')[0].split('?')[0].split('&')[0]
                
        # 2. ลิงก์รูปแบบ id=ID (เช่น uc?id=..., open?id=...)
        if 'id=' in url:
            parts = url.split('id=')
            if len(parts) > 1:
                return parts[1].split('&')[0].split('/')[0].split('?')[0]
                
        # 3. หากเป็น Raw Google Drive File ID ตรงๆ ( alphanumeric ความยาว >= 25)
        if len(url) >= 25 and '/' not in url and '=' not in url:
            return url
            
        return None

    def _ensure_analyzer(self):
        """ตรวจสอบและโหลด FaceAnalyzer AI Model หากยังไม่ได้สร้าง"""
        if self.analyzer is not None:
            return True
            
        if hasattr(self.app_gui, 'analyzer') and self.app_gui.analyzer is not None:
            self.analyzer = self.app_gui.analyzer
            return True

        try:
            logger.info("[SCHEDULE] กำลังโหลด FaceAnalyzer AI Model...")
            from face_analyzer import FaceAnalyzer
            use_gpu = False
            if hasattr(self.app_gui, 'chk_use_gpu'):
                try:
                    use_gpu = bool(self.app_gui.chk_use_gpu.get())
                except Exception:
                    use_gpu = False
            self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if self.analyzer.initialize():
                logger.info("[SCHEDULE] โหลด FaceAnalyzer AI Model สำเร็จ")
                if hasattr(self.app_gui, 'analyzer'):
                    self.app_gui.analyzer = self.analyzer
                return True
            else:
                logger.error("[SCHEDULE] ไม่สามารถสร้าง FaceAnalyzer AI Model ได้")
                return False
        except Exception as e:
            logger.error(f"[SCHEDULE] เกิดข้อผิดพลาดในการสร้าง FaceAnalyzer: {e}", exc_info=True)
            return False

    def debug_compare_sheet_vs_db(self, data, col_id, col_name, col_pin, col_img1, col_img2, col_img3):
        """โหมดสืบสวน: นำข้อมูลจาก Sheet มาเทียบกับ DB แล้วพ่น Log ออกมาทีเดียว"""
        logger.info("[DEBUG] ================= เริ่มโหมดตรวจสอบ Sheet vs DB =================")
        
        not_in_db = []
        mismatched_data = []
        invalid_urls = []
        missing_photos_in_db = []
        db_orphans = []
        
        total_in_sheet = 0
        sheet_student_ids = set()
        
        # 1. เช็คข้อมูลจาก Sheet -> DB
        for row in data:
            std_id = str(row.get(col_id, "")).strip()
            if not std_id:
                continue
                
            total_in_sheet += 1
            sheet_student_ids.add(std_id)
            
            std_name = str(row.get(col_name, "")).strip()
            pin_code = str(row.get(col_pin, "")).strip()
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, "")), str(row.get(col_img3, ""))]
            valid_imgs = [img for img in imgs if img.strip()]
            
            # ตรวจสอบลิงก์ที่ผิดปกติ
            for img in valid_imgs:
                if "drive.google.com" not in img and "google.com" not in img:
                    invalid_urls.append((std_id, std_name, img))
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT id, name, pin_code FROM staff_members WHERE student_id = ? AND role = 'student'", (std_id,))
                db_row = c.fetchone()
                
                if not db_row:
                    if len(valid_imgs) == 0:
                        not_in_db.append(f"{std_name} ({std_id}) - *ยังไม่มีรูปใน Sheet*")
                    else:
                        not_in_db.append(f"{std_name} ({std_id}) - มีรูปใน Sheet {len(valid_imgs)} รูป")
                else:
                    staff_id_check = db_row[0]
                    db_name = db_row[1]
                    db_pin = db_row[2]
                    
                    if db_name != std_name or db_pin != pin_code:
                        mismatched_data.append(f"{std_id}: Sheet(Name='{std_name}', PIN='{pin_code}') vs DB(Name='{db_name}', PIN='{db_pin}')")
                    
                    # เช็ครูปภาพ
                    c.execute("SELECT image_path, source_url FROM staff_embeddings WHERE staff_id = ?", (staff_id_check,))
                    existing_records = c.fetchall()
                    existing_file_ids = set()
                    for r in existing_records:
                        img_p, src_u = r[0] or "", r[1] or ""
                        if "drive:" in img_p:
                            existing_file_ids.add(img_p.replace("drive:", "").strip())
                        ext_p = self._extract_drive_id(img_p)
                        if ext_p: existing_file_ids.add(ext_p)
                        ext_u = self._extract_drive_id(src_u)
                        if ext_u: existing_file_ids.add(ext_u)
                    
                    missing_files = []
                    for img in valid_imgs:
                        f_id = self._extract_drive_id(img)
                        if f_id and f_id not in existing_file_ids:
                            missing_files.append(f_id)
                    
                    if missing_files:
                        missing_photos_in_db.append(f"{std_name} ({std_id}): ขาดหายไป {len(missing_files)} รูป (File ID: {', '.join(missing_files)})")

        # 2. เช็คข้อมูลจาก DB -> Sheet (หาคนที่โดนลบจาก Sheet ไปแล้ว)
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT student_id, name FROM staff_members WHERE role = 'student' AND student_id IS NOT NULL")
            db_students = c.fetchall()
            for r in db_students:
                db_std_id = r[0]
                db_std_name = r[1]
                if db_std_id not in sheet_student_ids:
                    db_orphans.append(f"{db_std_name} ({db_std_id})")

        # พ่น Log สรุปทีเดียว
        logger.info(f"[DEBUG] 📊 สรุปผลการเปรียบเทียบ:")
        logger.info(f"[DEBUG] - พบนักเรียนใน Sheet ทั้งหมด: {total_in_sheet} คน")
        logger.info(f"[DEBUG] - พบใน DB แต่ไม่มีใน Sheet (Orphans): {len(db_orphans)} คน")
        if db_orphans:
            logger.info(f"[DEBUG]   รายชื่อ Orphans: {', '.join(db_orphans)}")
            
        logger.info(f"[DEBUG] - พบใน Sheet แต่ไม่มีในฐานข้อมูล: {len(not_in_db)} คน")
        if not_in_db:
            for n in not_in_db:
                logger.info(f"[DEBUG]   - {n}")
                
        logger.info(f"[DEBUG] - ข้อมูล Name/PIN ไม่ตรงกัน: {len(mismatched_data)} คน")
        if mismatched_data:
            for m in mismatched_data:
                logger.info(f"[DEBUG]   - {m}")
                
        logger.info(f"[DEBUG] - ลิงก์รูปภาพใน Sheet ผิดรูปแบบ: {len(invalid_urls)} ลิงก์")
        if invalid_urls:
            for iv in invalid_urls:
                logger.info(f"[DEBUG]   - {iv[1]} ({iv[0]}): {iv[2]}")
                
        logger.info(f"[DEBUG] - มีรูปใน Sheet แต่ไม่มีใน DB (ขาดหาย): {len(missing_photos_in_db)} คน")
        if missing_photos_in_db:
            for mp in missing_photos_in_db:
                logger.info(f"[DEBUG]   - {mp}")
                
        logger.info("[DEBUG] ===============================================================")

    def _task_2_sync_new_students(self):
        logger.info("[SCHEDULE] กำลังทำ task นักเรียนใหม่...")
        sheet_id = "1bz81BDC0NkuX1-jzw_glntYZ1xkmuI9xJSi8op_x7To"
        
        try:
            # เชื่อมต่อเพื่ออ่าน Sheet ข้อมูลนักเรียน (โดยไม่สร้างแท็บ photos/faces ซ้ำซ้อน)
            if not self.sync_manager.connect(sheet_id, ensure_worksheets=False):
                logger.error("[SCHEDULE] ไม่สามารถเชื่อมต่อกับ Google Sheet ข้อมูลนักเรียนได้")
                return
            sheet = self.sync_manager.gspread_client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
            logger.info(f"[SCHEDULE] อ่านข้อมูลจาก Sheet ข้อมูลนักเรียนสำเร็จ พบทั้งหมด {len(data)} แถว")
        except Exception as e:
            logger.error(f"[SCHEDULE] ไม่สามารถอ่าน Sheet ข้อมูลนักเรียนได้: {e}", exc_info=True)
            return

        if not data:
            logger.warning("[SCHEDULE] Sheet ข้อมูลนักเรียน ไม่มีข้อมูลหรือเป็นค่าว่าง")
            return
            
        sample_keys = list(data[0].keys())
        logger.info(f"[SCHEDULE] พบคอลัมน์ใน Sheet ข้อมูลนักเรียน: {sample_keys}")

        # ฟังก์ชันจับคู่ชื่อคอลัมน์แบบยืดหยุ่น
        def find_col(possible_names):
            for k in sample_keys:
                clean_k = str(k).replace(" ", "").replace("-", "").strip()
                for name in possible_names:
                    clean_name = str(name).replace(" ", "").replace("-", "").strip()
                    if clean_k == clean_name:
                        return k
            return None

        col_id = find_col(["รหัสนักเรียน", "รหัสประจำตัว", "รหัส"]) or "รหัสนักเรียน"
        col_name = find_col(["ชื่อ สกุล", "ชื่อ-นามสกุล", "ชื่อนามสกุล", "ชื่อสุกล"]) or "ชื่อ สกุล"
        col_pin = find_col(["รหัสส่วนตัว 6 หลัก", "PIN", "รหัสส่วนตัว"]) or "รหัสส่วนตัว 6 หลัก"
        col_img1 = find_col(["ภาพใบหน้าตรง", "รูปถ่าย", "ภาพถ่าย"]) or "ภาพใบหน้าตรง"
        col_img2 = find_col(["ภาพใบหน้าเพิ่มเติม1", "ภาพใบหน้าเพิ่มเติม 1"]) or "ภาพใบหน้าเพิ่มเติม1"
        col_img3 = find_col(["ภาพใบหน้าเพิ่มเติม2", "ภาพใบหน้าเพิ่มเติม 2"]) or "ภาพใบหน้าเพิ่มเติม2"

        logger.info(f"[SCHEDULE] ใช้ชื่อคอลัมน์ -> ID: '{col_id}', Name: '{col_name}', PIN: '{col_pin}', Img1: '{col_img1}'")

        if DEBUG_SYNC_MODE:
            self.debug_compare_sheet_vs_db(data, col_id, col_name, col_pin, col_img1, col_img2, col_img3)

        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_sync_temp.json")
        old_data = {}
        if os.path.exists(temp_file):
            try:
                with open(temp_file, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
            except Exception as e:
                logger.warning(f"[SCHEDULE] อ่านไฟล์แคช student_sync_temp.json ไม่สำเร็จ: {e}")
                
        new_data = {}
        matched_faces_to_process = []
        
        valid_rows_count = 0
        for row in data:
            std_id = str(row.get(col_id, "")).strip()
            if not std_id:
                continue
            valid_rows_count += 1
                
            std_name = str(row.get(col_name, "")).strip()
            pin_code = str(row.get(col_pin, "")).strip()
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, "")), str(row.get(col_img3, ""))]
            
            # เก็บ State
            std_state = {
                "name": std_name,
                "pin": pin_code,
                "imgs": imgs
            }
            new_data[std_id] = std_state
            
            # เปรียบเทียบไฟล์แคช JSON
            is_new = False
            new_imgs = []
            
            if std_id not in old_data:
                is_new = True
                new_imgs = [img for img in imgs if img.strip()]
            else:
                old_imgs = old_data[std_id].get("imgs", [])
                # หาลิงก์รูปที่เพิ่งเพิ่มมาใหม่หรือเปลี่ยนไป
                for i in range(3):
                    if imgs[i].strip() and (i >= len(old_imgs) or imgs[i] != old_imgs[i]):
                        new_imgs.append(imgs[i])

            # ตรวจสอบเพิ่มเติมกับ SQLite DB: หากรูปภาพใดยังไม่มี embedding ใน DB ให้จัดเข้า new_imgs ด้วย
            # ดึง ID มาตรวจสอบโดยไม่บันทึกลง DB ทันที เพื่อป้องกันรายชื่อขยะ
            staff_id_check = None
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM staff_members WHERE student_id = ? AND role = 'student'", (std_id,))
                row = c.fetchone()
                if row:
                    staff_id_check = row[0]
            
            if staff_id_check:
                with self.db.get_connection() as conn:
                    c = conn.cursor()
                    c.execute("SELECT image_path, source_url FROM staff_embeddings WHERE staff_id = ?", (staff_id_check,))
                    existing_records = c.fetchall()
                    existing_file_ids = set()
                    for r in existing_records:
                        img_p, src_u = r[0] or "", r[1] or ""
                        if "drive:" in img_p:
                            existing_file_ids.add(img_p.replace("drive:", "").strip())
                        ext_p = self._extract_drive_id(img_p)
                        if ext_p: existing_file_ids.add(ext_p)
                        ext_u = self._extract_drive_id(src_u)
                        if ext_u: existing_file_ids.add(ext_u)
                    
                    for img_url in imgs:
                        if img_url.strip():
                            f_id = self._extract_drive_id(img_url)
                            if f_id and f_id not in existing_file_ids and img_url not in new_imgs:
                                new_imgs.append(img_url)
            else:
                # กรณีที่ใน DB ไม่มีเลย (อาจถูกลบไปแล้ว) ต้องบังคับ is_new=True
                is_new = True
                for img_url in imgs:
                    if img_url.strip() and img_url not in new_imgs:
                        new_imgs.append(img_url)

            if is_new and new_imgs:
                logger.info(f"[SCHEDULE] พบนักเรียนใหม่: {std_name} ({std_id})")
            elif new_imgs:
                logger.info(f"[SCHEDULE] พบนักเรียนเก่าอัปเดตรูป: {std_name} ({std_id}) [จำนวน {len(new_imgs)} รูปภาพ]")
                
            if new_imgs:
                # ตรวจสอบและโหลด FaceAnalyzer Model หากยังไม่มี
                if not self._ensure_analyzer():
                    logger.error(f"[SCHEDULE] ข้ามการสกัดใบหน้าของ {std_name} เนื่องจากไม่สามารถโหลด AI Model ได้")
                    continue

                # ลงทะเบียน DB
                staff_id = self.db.register_member(std_name, role='student', student_id=std_id, pin_code=pin_code)
                
                # โหลดภาพและสกัดเวกเตอร์
                for img_url in new_imgs:
                    file_id = self._extract_drive_id(img_url)
                    if file_id:
                        try:
                            logger.info(f"[SCHEDULE] กำลังดาวน์โหลดรูปภาพ {file_id} ของ {std_name}...")
                            img_bytes = self.sync_manager.download_image_bytes(file_id)
                            import numpy as np
                            import cv2
                            nparr = np.frombuffer(img_bytes, np.uint8)
                            img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img_cv is not None:
                                faces = self.analyzer.app.get(img_cv)
                                if faces:
                                    # เอาหน้าแรกที่ชัดที่สุด
                                    face = faces[0]
                                    emb = face.embedding
                                    # เซฟลง staff_embeddings
                                    conn = self.db.get_connection()
                                    c = conn.cursor()
                                    c.execute("INSERT INTO staff_embeddings (staff_id, image_path, embedding, source_url) VALUES (?, ?, ?, ?)",
                                             (staff_id, f"drive:{file_id}", emb.tobytes(), img_url))
                                    conn.commit()
                                    # เตรียมสำหรับ Retroactive Match
                                    matched_faces_to_process.append({
                                        "staff_id": staff_id,
                                        "name": std_name,
                                        "emb": emb
                                    })
                                    logger.info(f"[SCHEDULE] สกัดเวกเตอร์ใบหน้าสำเร็จสำหรับ {std_name} (File ID: {file_id})")
                                else:
                                    logger.warning(f"[SCHEDULE] ไม่พบใบหน้าในรูปภาพ {file_id} ของ {std_name}")
                            else:
                                logger.warning(f"[SCHEDULE] ไม่สามารถแปลงรูปภาพ {file_id} ของ {std_name} ได้")
                        except Exception as e:
                            logger.error(f"[SCHEDULE] Error processing image {file_id} for {std_name}: {e}")
                    else:
                        logger.error(f"[SCHEDULE] ไม่สามารถดึง Google Drive File ID จาก URL: {img_url}")
                            
        logger.info(f"[SCHEDULE] ตรวจสอบข้อมูลนักเรียนเสร็จสิ้น ({valid_rows_count} แถวมีรหัสนักเรียนถูกต้อง)")

        # Save temp JSON
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SCHEDULE] บันทึกไฟล์แคช student_sync_temp.json ไม่สำเร็จ: {e}")
            
        # Retroactive Matching สำหรับหน้าที่เพิ่มมาใหม่
        if matched_faces_to_process:
            logger.info(f"[SCHEDULE] กำลังทำ task นักเรียนใหม่ -> Retroactive Match จำนวน {len(matched_faces_to_process)} ใบหน้า...")
            if hasattr(self.app_gui, 'process_retroactive_match_headless'):
                self.app_gui.process_retroactive_match_headless(matched_faces_to_process)
            else:
                logger.error("[SCHEDULE] Error: app_gui does not have process_retroactive_match_headless")
            logger.info("[SCHEDULE] ซิงค์นักเรียนและอัปเดตใบหน้าเสร็จสิ้น")
        else:
            logger.info("[SCHEDULE] ไม่มีนักเรียนอัปเดตรูปภาพใหม่")
