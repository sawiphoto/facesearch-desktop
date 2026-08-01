import os
import time
import json
import logging
import threading
import concurrent.futures
import queue
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
        self.gpu_lock = threading.Lock()
        
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
            logger.info("[SCHEDULE] เริ่มทำงาน Task 2 เฉพาะกิจ (v4.0 - Bulk Sync)")
            if not self.sync_manager.connected:
                self.sync_manager.connect()
            self._ensure_analyzer()
            self._task_2_sync_new_students_bulk()
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
            logger.info("[SCHEDULE] เริ่มทำงาน Task อัตโนมัติ (v4.0 - High Speed)")
            logger.info("="*50)
            
            # Ensure Google API is connected
            if not self.sync_manager.connected:
                self.sync_manager.connect()
                
            # Ensure Analyzer is initialized
            self._ensure_analyzer()
            
            # Task 1: Scan New Photos (High-Speed)
            self._task_1_scan_new_photos_fast()
            
            if not self.stop_requested:
                # Task 2: Sync New Students (Bulk)
                self._task_2_sync_new_students_bulk()
            
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

    def _get_unscanned_subfolder(self, root_folder_id, force_rescan=False, scanned_in_this_run=None):
        """ค้นหาโฟลเดอร์ย่อยที่มีรูปภาพและต้องการสแกน (หรือ Re-scan)"""
        if scanned_in_this_run is None:
            scanned_in_this_run = set()

        query_dirs = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subdirs = []
        page_token = None
        while True:
            if self.stop_requested: break
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

        # ถ้า root_folder_id ไม่มีโฟลเดอร์ย่อย ให้คืนค่า root_folder เองหากมีรูป
        if not subdirs:
            subdirs = [{"id": root_folder_id, "name": "TargetFolder"}]
                
        # ดึงรายชื่อไฟล์ที่สแกนแล้วจาก DB
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT drive_file_id FROM scanned_photos")
            scanned_ids = set(row[0] for row in c.fetchall())

        total_subdirs = len(subdirs)
        for idx, subdir in enumerate(subdirs):
            if self.stop_requested: break
            subdir_id = subdir['id']
            if subdir_id in scanned_in_this_run:
                continue

            # พ่น Log แสดงสถานะความก้าวหน้าเรียลไทม์
            logger.info(f"[SCHEDULE] กำลังตรวจสอบโฟลเดอร์ย่อย ({idx+1}/{total_subdirs}): {subdir['name']}")

            # เช็คไฟล์รูปในโฟลเดอร์นี้
            query_files = f"'{subdir_id}' in parents and (mimeType contains 'image/') and trashed = false"
            try:
                f_results = self.sync_manager.drive_service.files().list(
                    q=query_files, fields="files(id)", pageSize=500
                ).execute()
                files = f_results.get("files", [])
                if not files:
                    continue

                if force_rescan:
                    # ถ้าเปิด Re-scan ➔ ส่งคืนโฟลเดอร์นี้ไปทำ Re-scan ทันที
                    return subdir

                # ถ้าปิด Re-scan ➔ ตรวจสอบว่ามีรูปไหนยังไม่อยู่ใน DB หรือไม่
                for f in files:
                    if f['id'] not in scanned_ids:
                        return subdir # เจอโฟลเดอร์มีรูปใหม่ยังไม่เคยสแกน
            except Exception:
                pass
                
        return None # สแกนครบถ้วนหมดแล้ว

    def _task_1_scan_new_folders(self):
        logger.info("[SCHEDULE] กำลังทำ task โฟลเดอร์ใหม่...")
        
        # ดึงการตั้งค่าจาก GUI 100% (Threshold, Re-scan, Fast Rescan, Target matching)
        scan_settings = self.app_gui.get_current_scan_settings() if hasattr(self.app_gui, 'get_current_scan_settings') else {}
        rescan = scan_settings.get("rescan", False)
        fast_rescan = scan_settings.get("fast_rescan", False)
        
        target_folders = []
        # 1. เพิ่ม ID โฟลเดอร์กิจกรรมหลักที่ตั้งค่าในช่อง GUI ก่อนเสมอ
        if hasattr(self.app_gui, 'entry_drive_folder_id'):
            gui_folder_id = self.app_gui.entry_drive_folder_id.get().strip()
            if gui_folder_id:
                target_folders.append(("โฟลเดอร์หลักใน GUI", gui_folder_id))

        # 2. เพิ่มโฟลเดอร์ประจำปีการศึกษา
        target_folders.extend([
            ("ภาพกิจกรรม 2569", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
            ("ภาพกิจกรรม 2568", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
            ("ภาพกิจกรรม 2565-2567", "1BjYQwoso9FKv42XK6RJi1gPS8kyK_jCg")
        ])
        
        scanned_in_this_run = set()
        for year_name, year_id in target_folders:
            if self.stop_requested: break
            while True:
                if self.stop_requested: break
                red_folder = self._get_unscanned_subfolder(year_id, force_rescan=rescan, scanned_in_this_run=scanned_in_this_run)
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
        """ตรวจสอบและอ้างอิง FaceAnalyzer AI Model เพียงอินสแตนซ์เดียวทั้งระบบ"""
        if hasattr(self.app_gui, 'analyzer') and self.app_gui.analyzer is not None:
            self.analyzer = self.app_gui.analyzer
            return True

        if self.analyzer is not None:
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

    def debug_compare_sheet_vs_db(self, data, col_id, col_name, col_img1, col_img2, col_img3):
        """โหมดสืบสวน: นำข้อมูลจาก Sheet มาเทียบกับ DB แล้วพ่น Log ออกมาทีเดียว"""
        logger.info("[DEBUG] ================= เริ่มโหมดตรวจสอบ Sheet vs DB =================")
        
        not_in_db = []
        no_photo_in_sheet_count = 0
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
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, ""))]
            valid_imgs = [img for img in imgs if img.strip()]
            
            # ตรวจสอบลิงก์ที่ผิดปกติ
            for img in valid_imgs:
                if "drive.google.com" not in img and "google.com" not in img:
                    invalid_urls.append((std_id, std_name, img))
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT id, name FROM staff_members WHERE student_id = ? AND role = 'student'", (std_id,))
                db_row = c.fetchone()
                
                if not db_row:
                    if len(valid_imgs) == 0:
                        no_photo_in_sheet_count += 1
                    else:
                        not_in_db.append(f"{std_name} ({std_id}) - มีรูปใน Sheet {len(valid_imgs)} รูป")
                else:
                    staff_id_check = db_row[0]
                    db_name = db_row[1]
                    
                    if db_name != std_name:
                        mismatched_data.append(f"{std_id}: Sheet(Name='{std_name}') vs DB(Name='{db_name}')")
                    
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
        
        if no_photo_in_sheet_count > 0:
            logger.info(f"[DEBUG] - พบนักเรียนที่ยังไม่มีรูปใน Sheet (และยังไม่ถูกบันทึก) ทั้งหมด: {no_photo_in_sheet_count} คน")
            
        logger.info(f"[DEBUG] - พบใน DB แต่ไม่มีใน Sheet (Orphans): {len(db_orphans)} คน")
        if db_orphans:
            logger.info(f"[DEBUG]   รายชื่อ Orphans: {', '.join(db_orphans)}")
            
        logger.info(f"[DEBUG] - พบใน Sheet แต่ไม่มีในฐานข้อมูล (รอลงทะเบียน): {len(not_in_db)} คน")
        if not_in_db:
            for n in not_in_db:
                logger.info(f"[DEBUG]   - {n}")
                
        logger.info(f"[DEBUG] - ข้อมูล Name ไม่ตรงกัน: {len(mismatched_data)} คน")
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

        col_id = find_col(["รหัสนักเรียน", "รหัสประจำตัว", "รหัส"]) or (sample_keys[0] if len(sample_keys) > 0 else "รหัสนักเรียน")
        col_name = find_col(["ชื่อ สกุล", "ชื่อ-นามสกุล", "ชื่อนามสกุล", "ชื่อสุกล"]) or (sample_keys[1] if len(sample_keys) > 1 else "ชื่อ สกุล")
        col_img1 = find_col(["ภาพใบหน้าตรงตอนเด็ก", "ภาพใบหน้าตรง ตอนเด็ก", "ภาพใบหน้าตรง", "รูปถ่าย", "ภาพถ่าย"]) or (sample_keys[3] if len(sample_keys) > 3 else "ภาพใบหน้าตรง ตอนเด็ก")
        col_img2 = find_col(["ภาพใบหน้าตรงตอนวัยรุ่น", "ภาพใบหน้าตรง ตอนวัยรุ่น", "ภาพใบหน้าตรง2", "ภาพใบหน้าเพิ่มเติม1", "ภาพใบหน้าเพิ่มเติม 1", "ภาพใบหน้าตรงอัปเดต"]) or (sample_keys[4] if len(sample_keys) > 4 else "ภาพใบหน้าตรง ตอนวัยรุ่น")

        logger.info(f"[SCHEDULE] ใช้ชื่อคอลัมน์นักเรียน (A-E) -> ID: '{col_id}', Name: '{col_name}', Img1: '{col_img1}', Img2: '{col_img2}' (รองรับสูงสุด 2 ภาพหน้าตรงต่างช่วงวัย)")

        if DEBUG_SYNC_MODE:
            self.debug_compare_sheet_vs_db(data, col_id, col_name, col_img1, col_img2, None)

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
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, ""))]
            
            # เก็บ State (เอา PIN ออกแล้ว)
            std_state = {
                "name": std_name,
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
                # หาลิงก์รูปที่เพิ่งเพิ่มมาใหม่หรือเปลี่ยนไป (ตรวจสูงสุด 2 รูปหน้าตรง)
                for i in range(min(2, len(imgs))):
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

                # ลงทะเบียน DB (ส่งค่า pin_code เป็นสตริงว่าง)
                staff_id = self.db.register_member(std_name, role='student', student_id=std_id, pin_code="")
                
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
                                if not faces:
                                    # Fallback สำหรับภาพครอบตัดแน่นชิดใบหน้า (Tight Crop)
                                    h, w = img_cv.shape[:2]
                                    pad = int(max(h, w) * 0.5)
                                    img_padded = cv2.copyMakeBorder(img_cv, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=[128, 128, 128])
                                    faces = self.analyzer.app.get(img_padded)

                                if faces:
                                    # เอาหน้าแรกที่ชัดที่สุด
                                    face = faces[0]
                                    emb = face.embedding
                                    
                                    # ตัดใบหน้าและบันทึกลงเครื่อง
                                    h, w = img_cv.shape[:2]
                                    x1, y1, x2, y2 = face.bbox
                                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                                    pad_x = int(0.15 * (x2 - x1))
                                    pad_y = int(0.15 * (y2 - y1))
                                    x1 = max(0, x1 - pad_x)
                                    y1 = max(0, y1 - pad_y)
                                    x2 = min(w, x2 + pad_x)
                                    y2 = min(h, y2 + pad_y)
                                    cropped = img_cv[y1:y2, x1:x2]
                                    
                                    import time
                                    student_face_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "registered_students")
                                    os.makedirs(student_face_dir, exist_ok=True)
                                    student_filename = f"student_{std_id}_{int(time.time())}_{file_id}.jpg"
                                    local_img_path = os.path.join(student_face_dir, student_filename)
                                    
                                    success, img_encoded = cv2.imencode('.jpg', cropped)
                                    if success:
                                        img_encoded.tofile(local_img_path)
                                        db_img_path = local_img_path
                                    else:
                                        db_img_path = f"drive:{file_id}"
                                    
                                    # เซฟลง staff_embeddings
                                    conn = self.db.get_connection()
                                    c = conn.cursor()
                                    c.execute("INSERT INTO staff_embeddings (staff_id, image_path, embedding, source_url) VALUES (?, ?, ?, ?)",
                                             (staff_id, db_img_path, emb.tobytes(), img_url))
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

    
    
    def _load_year_folders(self):
        """โหลดรายชื่อโฟลเดอร์หลักปีการศึกษาจาก config/year_folders.json"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "year_folders.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return [(item["name"], item["id"]) for item in data if "name" in item and "id" in item]
            except Exception as e:
                logger.error(f"[SCHEDULE] Error reading config/year_folders.json: {e}")
                
        # Default Fallback (5 โฟลเดอร์หลัก)
        return [
            ("ภาพกิจกรรม 2569", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
            ("ภาพกิจกรรม 2568", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
            ("ภาพกิจกรรม 2567", "1ocR4srmu1tA1nYgJOhoM9I0KDVMmbRGF"),
            ("ภาพกิจกรรม 2566", "1ZMhLENv8u-onIhVzwBTxCzjJVQVCriVd"),
            ("ภาพกิจกรรม 2565", "1cN-3d_mz_9CAbAwLOFKil22bBr0xgasL")
        ]

    def _get_all_subfolders_recursive(self, parent_id, parent_name=""):
        """ดึงรายชื่อโฟลเดอร์ย่อยทั้งหมดทุกระดับชั้นแบบ Recursive"""
        all_subfolders = []
        try:
            query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            page_token = None
            subdirs = []
            while True:
                res = self.sync_manager.drive_service.files().list(
                    q=query, fields="nextPageToken, files(id, name)", pageToken=page_token, pageSize=1000
                ).execute()
                subdirs.extend(res.get("files", []))
                page_token = res.get("nextPageToken")
                if not page_token or self.stop_requested: break
                
            for subdir in subdirs:
                if self.stop_requested: break
                s_id = subdir['id']
                s_name = subdir['name']
                all_subfolders.append({"id": s_id, "name": s_name})
                
                # มุดลงไปดึงโฟลเดอร์ชั้นในซ้อนชั้นอีก (Recursive)
                inner_subdirs = self._get_all_subfolders_recursive(s_id, s_name)
                all_subfolders.extend(inner_subdirs)
        except Exception as e:
            logger.error(f"[SCHEDULE] Error fetching recursive subfolders for {parent_name}: {e}")
        return all_subfolders

    
    
    def _task_1_scan_new_photos_fast(self):
        logger.info("[SCHEDULE] 🚀 เริ่มต้น Task 1: สแกนโฟลเดอร์ใหม่เรียงลำดับปีการศึกษา (5 โฟลเดอร์หลัก - Single GPU Consumer)")
        
        target_years = self._load_year_folders()
        
        # 1. โหลดข้อมูลเป้าหมายจากฐานข้อมูลมาไว้ใน Memory
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, personal_threshold FROM staff_members")
            staff_data = c.fetchall()
            
            c.execute("SELECT staff_id, embedding FROM staff_embeddings")
            emb_data = c.fetchall()

            c.execute("SELECT drive_file_id FROM scanned_photos")
            scanned_ids = set(row[0] for row in c.fetchall())

        if not staff_data or not emb_data:
            logger.warning("[SCHEDULE] ⚠️ ไม่มีข้อมูลนักเรียน/บุคลากรในฐานข้อมูล หรือไม่มีเวกเตอร์ภาพ")
            return
            
        import numpy as np
        template_embeddings = []
        template_staff_ids = []
        template_names = []
        personal_threshold_dict = {row[0]: row[2] for row in staff_data}
        template_thresholds = []

        for staff_id, emb_blob in emb_data:
            try:
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                template_embeddings.append(emb)
                template_staff_ids.append(staff_id)
                name = next((r[1] for r in staff_data if r[0] == staff_id), "Unknown")
                template_names.append(name)
                thresh = personal_threshold_dict.get(staff_id, 0.50)
                template_thresholds.append(thresh)
            except Exception as e:
                logger.error(f"[SCHEDULE] Error loading embedding for staff_id {staff_id}: {e}")

        if not template_embeddings:
            logger.warning("[SCHEDULE] ⚠️ โหลด Template เวกเตอร์ไม่สำเร็จ")
            return

        template_embeddings = np.array(template_embeddings, dtype=np.float32)
        
        import concurrent.futures
        import queue
        import cv2

        for year_name, year_id in target_years:
            if self.stop_requested: break
            
            subfolders = self._get_all_subfolders_recursive(year_id, year_name)
            if not subfolders:
                subfolders = [{"id": year_id, "name": year_name}]
                
            logger.info(f"[SCHEDULE] 🔍 กำลังตรวจหาโฟลเดอร์ใหม่ใน '{year_name}' (พบ {len(subfolders)} โฟลเดอร์ย่อย)...")
            
            folders_to_scan = []
            for subdir in subfolders:
                if self.stop_requested: break
                f_id = subdir['id']
                f_name = subdir['name']
                
                try:
                    q_imgs = f"'{f_id}' in parents and (mimeType contains 'image/') and trashed = false"
                    img_res = self.sync_manager.drive_service.files().list(
                        q=q_imgs, fields="files(id, name, webContentLink, createdTime)", pageSize=1000
                    ).execute()
                    imgs = img_res.get("files", [])
                    
                    if not imgs:
                        continue
                        
                    unscanned = [img for img in imgs if img['id'] not in scanned_ids]
                    if unscanned:
                        folders_to_scan.append({
                            "folder_id": f_id,
                            "folder_name": f_name,
                            "files_to_scan": unscanned
                        })
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error checking folder {f_name}: {e}")

            total_in_year = len(folders_to_scan)
            if total_in_year == 0:
                logger.info(f"[SCHEDULE] ✅ '{year_name}' สแกนสมบูรณ์แล้ว 100% (ไม่พบรูปภาพใหม่)")
                continue
                
            folder_names_summary = [f['folder_name'] for f in folders_to_scan[:5]]
            more_suffix = f" ...และอีก {total_in_year-5} โฟลเดอร์" if total_in_year > 5 else ""
            logger.info(f"[SCHEDULE] 🎯 '{year_name}' พบ {total_in_year} โฟลเดอร์ที่ต้องทำ Full Scan: [{', '.join(folder_names_summary)}{more_suffix}]")

            # 3. สแกนทีละโฟลเดอร์ย่อยของปีนี้ (Sequential Thread-Safe Pattern)
            for idx, target in enumerate(folders_to_scan):
                if self.stop_requested: break
                
                folder_id = target["folder_id"]
                folder_name = target["folder_name"]
                files_to_process = target["files_to_scan"]
                total_files = len(files_to_process)
                
                logger.info(f"[FULLSCAN] 🚀 [{year_name}] ({idx+1}/{total_in_year}) สแกนโฟลเดอร์: {folder_name} ({total_files} รูป)")
                
                results_data = []
                skipped_files = []
                processed_count = 0
                
                # Sequential Loop: โหลดทีละรูป และยิง InsightFace บน Thread เดียวแบบ 100% Thread-Safe
                for file_info in files_to_process:
                    if self.stop_requested: break
                    
                    f_id = file_info['id']
                    f_name = file_info['name']
                    f_link = file_info.get('webContentLink', f"https://drive.google.com/file/d/{f_id}/view")
                    p_date = file_info.get('createdTime', '').split('T')[0] if 'createdTime' in file_info else datetime.now().strftime("%Y-%m-%d")

                    logger.info(f"[AI SCAN] ({processed_count+1}/{total_files}) 📥 โหลดรูปภาพจาก Drive: {f_name} (ID: {f_id})")
                    
                    try:
                        # 1. ดาวน์โหลดรูปภาพจาก Drive (Single Thread - Safe Google API Call)
                        t_dl_start = time.time()
                        req = self.sync_manager.drive_service.files().get_media(fileId=f_id)
                        img_bytes = req.execute()
                        t_dl = time.time() - t_dl_start
                        
                        if not img_bytes:
                            logger.warning(f"[AI SCAN] ⚠️ ไม่สามารถดาวน์โหลดไฟล์ได้: {f_name}")
                            skipped_files.append((f_id, f_name, "SKIPPED_DOWNLOAD_EMPTY"))
                            scanned_ids.add(f_id)
                            processed_count += 1
                            continue

                        # 2. Decode OpenCV
                        np_arr = np.frombuffer(img_bytes, np.uint8)
                        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                        
                        if img is None:
                            logger.warning(f"[AI SCAN] ⚠️ ไม่สามารถ Decode ไฟล์ภาพได้ (Skipped): {f_name}")
                            skipped_files.append((f_id, f_name, "SKIPPED_UNREADABLE_IMAGE"))
                            scanned_ids.add(f_id)
                            processed_count += 1
                            continue

                        # 3. สแกนด้วย InsightFace GPU
                        t0 = time.time()
                        faces = self.analyzer.get_faces_optimized(img)
                        t_ai = time.time() - t0
                        
                        photo_matches = []
                        face_embeddings = []
                        match_names = []
                        
                        if faces and len(faces) > 0:
                            detected_embs = [f.embedding for f in faces if f is not None and hasattr(f, 'embedding')]
                            if detected_embs:
                                detected_embs = np.array(detected_embs, dtype=np.float32)
                                
                                matches = self.analyzer.match_faces_matrix(
                                    detected_embs, template_embeddings, template_names, template_staff_ids, 
                                    threshold=0.50, template_thresholds=template_thresholds
                                )
                                
                                for i, face in enumerate(faces):
                                    if i < len(matches) and matches[i] is not None and isinstance(matches[i], dict):
                                        best_match = matches[i]
                                        if best_match.get('name', 'Unknown') != "Unknown":
                                            photo_matches.append((best_match['staff_id'], best_match['confidence']))
                                            match_names.append(best_match['name'])
                                            
                                    if hasattr(face, 'bbox') and face.bbox is not None:
                                        bbox = face.bbox
                                        face_embeddings.append({
                                            'face_index': i,
                                            'bbox': [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                                            'embedding': face.embedding.astype(np.float32).tobytes()
                                        })

                        match_str = f"-> [MATCH_OK] เจอ: {', '.join(match_names)}" if match_names else "-> ไม่พบคนในระบบ"
                        logger.info(f"[AI SCAN] ({processed_count+1}/{total_files}) ✅ {f_name} | DL: {t_dl:.2f}s | AI: {t_ai:.2f}s | พบ {len(faces) if faces else 0} ใบหน้า {match_str}")
                        
                        # Save Thumbnail Cache
                        try:
                            thumb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "thumbnails")
                            os.makedirs(thumb_dir, exist_ok=True)
                            thumb_path = os.path.join(thumb_dir, f"{f_id}.jpg")
                            if not os.path.exists(thumb_path):
                                h, w = img.shape[:2]
                                scale = 300 / max(h, w)
                                thumb_img = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img
                                cv2.imwrite(thumb_path, thumb_img)
                        except Exception: pass

                        results_data.append({
                            "photo_id": f_id,
                            "drive_file_id": f_id,
                            "event_name": folder_name,
                            "drive_link": f_link,
                            "photo_date": p_date,
                            "matches": photo_matches,
                            "face_embeddings": face_embeddings
                        })
                        
                        processed_count += 1
                            
                    except Exception as e:
                        logger.error(f"[AI SCAN] ❌ Error analyzing faces for {f_name}: {e}")
                        skipped_files.append((f_id, f_name, f"ERROR_{e}"))

                # Single Transaction Batch Save
                if results_data or skipped_files:
                    with self.db.get_connection() as conn:
                        c = conn.cursor()
                        if results_data:
                            scanned_rows = [(r["photo_id"], r["drive_file_id"], r["event_name"], r["drive_link"], r["photo_date"]) for r in results_data]
                            c.executemany("INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date) VALUES (?, ?, ?, ?, ?)", scanned_rows)
                            
                            photo_ids_batch = [r["photo_id"] for r in results_data]
                            if photo_ids_batch:
                                placeholders_del = ",".join("?" for _ in photo_ids_batch)
                                c.execute(f"DELETE FROM detected_faces WHERE photo_id IN ({placeholders_del})", photo_ids_batch)

                            match_rows = []
                            for r in results_data:
                                for staff_id, conf in r["matches"]: match_rows.append((r["photo_id"], staff_id, conf))
                            if match_rows:
                                c.executemany("INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)", match_rows)
                                
                            emb_rows = []
                            for r in results_data:
                                for f in r["face_embeddings"]:
                                    emb_rows.append((r["photo_id"], f["face_index"], f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3], f["embedding"]))
                            if emb_rows:
                                c.executemany("INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)", emb_rows)

                        if skipped_files:
                            skipped_rows = [(f_id, f_id, folder_name, f"https://drive.google.com/file/d/{f_id}/view", reason) for f_id, f_name, reason in skipped_files]
                            c.executemany("INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date) VALUES (?, ?, ?, ?, ?)", skipped_rows)

                        conn.commit()

                if hasattr(self.app_gui, 'record_matched_folder'):
                    self.app_gui.record_matched_folder(folder_id, folder_name)
                    
                for r in results_data: scanned_ids.add(r["photo_id"])
                for f_id, _, _ in skipped_files: scanned_ids.add(f_id)
                
            logger.info(f"[SCHEDULE] 🎉 เสร็จสิ้นการทำ Full Scan สำหรับโฟลเดอร์หลัก: '{year_name}'")



    def _task_2_sync_new_students_bulk(self):
        logger.info("[SCHEDULE] 🚀 เริ่มต้น Task 2: Sync New Students & Bulk Matching")
        sheet_id = "1bz81BDC0NkuX1-jzw_glntYZ1xkmuI9xJSi8op_x7To"
        
        try:
            if not self.sync_manager.connect(sheet_id, ensure_worksheets=False):
                logger.error("[SCHEDULE] ไม่สามารถเชื่อมต่อกับ Google Sheet ได้")
                return
            sheet = self.sync_manager.gspread_client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
            logger.info(f"[SCHEDULE] อ่านข้อมูลจาก Sheet สำเร็จ พบ {len(data)} แถว")
        except Exception as e:
            logger.error(f"[SCHEDULE] ไม่สามารถอ่าน Sheet ได้: {e}", exc_info=True)
            return

        if not data:
            logger.warning("[SCHEDULE] Sheet ไม่มีข้อมูล")
            return
            
        sample_keys = list(data[0].keys())
        def find_col(possible_names):
            for k in sample_keys:
                clean_k = str(k).replace(" ", "").replace("-", "").strip()
                for name in possible_names:
                    if clean_k == str(name).replace(" ", "").replace("-", "").strip(): return k
            return None

        col_id = find_col(["รหัสนักเรียน", "รหัสประจำตัว", "รหัส"]) or (sample_keys[0] if len(sample_keys) > 0 else "รหัสนักเรียน")
        col_name = find_col(["ชื่อ สกุล", "ชื่อ-นามสกุล", "ชื่อนามสกุล"]) or (sample_keys[1] if len(sample_keys) > 1 else "ชื่อ สกุล")
        col_img1 = find_col(["ภาพใบหน้าตรงตอนเด็ก", "ภาพใบหน้าตรง ตอนเด็ก", "ภาพใบหน้าตรง", "รูปถ่าย"]) or (sample_keys[3] if len(sample_keys) > 3 else "ภาพใบหน้าตรง ตอนเด็ก")
        col_img2 = find_col(["ภาพใบหน้าตรงตอนวัยรุ่น", "ภาพใบหน้าตรง ตอนวัยรุ่น", "ภาพใบหน้าตรง2"]) or (sample_keys[4] if len(sample_keys) > 4 else "ภาพใบหน้าตรง ตอนวัยรุ่น")

        # อ่านสถานะจาก json เพื่อดูว่าลิงก์รูปเปลี่ยนไหม
        import json
        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_sync_temp.json")
        old_data = {}
        if os.path.exists(temp_file):
            try:
                with open(temp_file, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
            except: pass
                
        new_data = {}
        processed_students = 0
        
        self._ensure_analyzer()
        
        import numpy as np
        import cv2

        for row in data:
            if self.stop_requested: break
            
            s_id = str(row.get(col_id, "")).strip()
            s_name = str(row.get(col_name, "")).strip()
            if not s_id or not s_name:
                continue
                
            url1 = str(row.get(col_img1, "")).strip()
            url2 = str(row.get(col_img2, "")).strip()
            
            # (หากไม่มีรูประบบจะไม่บันทึกและปล่อยผ่าน)
            if not url1 and not url2:
                continue
                
            urls = []
            if url1: urls.append(url1)
            if url2: urls.append(url2)
            
            new_data[s_id] = {"name": s_name, "urls": urls}
            
            is_new_or_updated = False
            if s_id not in old_data:
                is_new_or_updated = True
            else:
                old_urls = set(old_data[s_id].get("urls", []))
                new_urls = set(urls)
                if old_urls != new_urls:
                    is_new_or_updated = True
                    
            if is_new_or_updated:
                logger.info(f"[SCHEDULE] 🔄 พบการอัปเดตรูปของนักเรียน: {s_name} ({s_id})")
                try:
                    staff_id = self.db.register_member(s_name, role='student', student_id=s_id)
                    # ลบเวกเตอร์เดิม
                    self.db.clear_staff_embeddings(staff_id)
                    
                    added_faces = 0
                    for url in urls:
                        try:
                            img_path = self.sync_manager.download_image_from_url(url)
                            if not img_path: continue
                            
                            img = cv2.imread(img_path)
                            if img is not None:
                                faces = self.analyzer.detect_and_extract_faces_from_image(img)
                                if faces:
                                    best_face = faces[0]
                                    self.db.add_staff_embedding(staff_id, img_path, best_face.embedding.tolist(), source_url=url)
                                    added_faces += 1
                        except Exception as e:
                            logger.error(f"[SCHEDULE] Error embedding for {s_name}: {e}")
                            
                    if added_faces > 0:
                        self.db.set_staff_backfill_status(staff_id, 0)
                        processed_students += 1
                        logger.info(f"[SCHEDULE] ✅ อัปเดตเวกเตอร์ใหม่ให้ {s_name} ({added_faces} รูป)")
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error process sync for {s_name}: {e}")
                    
        # เซฟประวัติ
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
        except: pass
        
        # ----------------------------------------------------
        # Bulk Backfill Matching
        # ----------------------------------------------------
        logger.info("[SCHEDULE] 🔍 กำลังค้นหานักเรียน/บุคลากรที่ต้องทำ Bulk Backfill Matching...")
        unbackfilled = self.db.get_unbackfilled_students()
        
        if unbackfilled:
            logger.info(f"[SCHEDULE] พบ {len(unbackfilled)} คน ที่ต้องการทำจับคู่ย้อนหลัง")
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                # 1. ดึงเวกเตอร์ของนักเรียนใหม่
                c.execute("SELECT staff_id, embedding FROM staff_embeddings")
                all_embs = c.fetchall()
                
                target_staff_ids = [s["staff_id"] for s in unbackfilled]
                
                new_student_embeddings = []
                new_student_ids = []
                new_student_names = []
                new_student_thresholds = []
                
                # Fetch personal_thresholds
                c.execute("SELECT id, personal_threshold FROM staff_members")
                threshold_dict = {row[0]: row[1] for row in c.fetchall()}
                
                name_dict = {s["staff_id"]: s["name"] for s in unbackfilled}
                
                for staff_id, emb_blob in all_embs:
                    if staff_id in target_staff_ids:
                        emb = np.frombuffer(emb_blob, dtype=np.float32)
                        new_student_embeddings.append(emb)
                        new_student_ids.append(staff_id)
                        new_student_names.append(name_dict[staff_id])
                        new_student_thresholds.append(threshold_dict.get(staff_id, 0.50))
                        
                if new_student_embeddings:
                    new_student_embeddings = np.array(new_student_embeddings, dtype=np.float32)
                    
                    # 2. ดึงเวกเตอร์ของรูปในกิจกรรมทั้งหมดเพื่อมาจับคู่
                    logger.info("[SCHEDULE] 💾 กำลังดึงข้อมูลรูปภาพกิจกรรมทั้งหมดจาก SQLite เพื่อทำ Matrix Matching...")
                    c.execute("SELECT photo_id, face_index, embedding FROM scanned_photo_faces")
                    photo_faces = c.fetchall()
                    
                    logger.info(f"[SCHEDULE] 🚀 กำลังจับคู่ Matrix {len(photo_faces)} ใบหน้ากิจกรรมกับ {len(new_student_embeddings)} ใบหน้านักเรียนใหม่...")
                    
                    batch_matches = []
                    # การวนลูปรูปทีละหน้าเพื่อเอาเวกเตอร์มาเทียบกับ Array นักเรียนใหม่ทั้งหมด
                    for photo_id, face_idx, emb_blob in photo_faces:
                        photo_emb = np.frombuffer(emb_blob, dtype=np.float32)
                        photo_emb = np.array([photo_emb], dtype=np.float32)
                        
                        res = self.analyzer.match_faces_matrix(
                            photo_emb, new_student_embeddings, new_student_names, new_student_ids, 
                            threshold=0.50, template_thresholds=new_student_thresholds
                        )
                        
                        best_match = res[0]
                        if best_match['name'] != "Unknown":
                            batch_matches.append((photo_id, best_match['staff_id'], best_match['confidence']))
                            
                    if batch_matches:
                        # 3. เซฟลง detected_faces แบบ Batch
                        logger.info(f"[SCHEDULE] ✅ พบรูปภาพย้อนหลังทั้งหมด {len(batch_matches)} แมตช์ กำลังเซฟลงฐานข้อมูล...")
                        c.executemany("INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)", batch_matches)
                        conn.commit()
                        
            # Mark backfilled
            self.db.mark_students_backfilled(target_staff_ids)
            
            # ----------------------------------------------------
            # Bulk JSON Update (3 โฟลเดอร์หลัก)
            # ----------------------------------------------------
            logger.info("[SCHEDULE] 📤 กำลังเตรียมอัปเดตไฟล์ JSON บน Google Drive 3 โฟลเดอร์หลักใหญ่...")
            top_folders = [item["id"] for item in self._load_year_folders()]
            
            for folder_id in top_folders:
                try:
                    self.sync_manager.update_json_indexes_on_drive(None, folder_id, scan_mode="all")
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error updating JSON for root folder {folder_id}: {e}")
                    
            logger.info("[SCHEDULE] 🎉 การ Bulk Sync New Students เสร็จสมบูรณ์แล้ว!")
        else:
            logger.info("[SCHEDULE] ✅ ไม่มีนักเรียนใหม่หรือรูปอัปเดตที่ต้องทำ Backfill Matching ในรอบนี้")

