import os
import time
import json
import logging
import threading
import traceback
import schedule
from datetime import datetime

logger = logging.getLogger("FaceSearchApp")

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
            print("[SCHEDULE] ร้องขอการหยุดทำงานชั่วคราว... กำลังสรุปผลในรอบปัจจุบัน")

    def _scheduler_loop(self):
        while True:
            schedule.run_pending()
            time.sleep(60)
            
    def run_scheduled_tasks_manual(self):
        if self.is_running:
            print("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self.run_scheduled_tasks, daemon=True).start()

    def run_scheduled_tasks(self):
        if self.is_running:
            return
            
        self.is_running = True
        self.stop_requested = False
        try:
            print("="*50)
            print("[SCHEDULE] เริ่มทำงาน Task อัตโนมัติ (v1.8)")
            print("="*50)
            
            # Ensure Google API is connected
            if not self.sync_manager.connected:
                self.sync_manager.connect()
                
            # Ensure Analyzer is initialized
            if self.analyzer is None:
                try:
                    from face_ai import FaceAnalyzer
                    self.analyzer = FaceAnalyzer(use_gpu=False)
                    self.analyzer.initialize()
                except Exception as e:
                    logger.error(f"[SCHEDULE] Warning: FaceAnalyzer init failed: {e}")
            
            # Task 1: Check New Folders
            self._task_1_scan_new_folders()
            
            if not self.stop_requested:
                # Task 2: Check New Students
                self._task_2_sync_new_students()
            
            import pytz
            bkk_tz = pytz.timezone('Asia/Bangkok')
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[SCHEDULE] กระบวนการทำงานอัตโนมัติเสร็จสมบูรณ์ ({bkk_time} BKK)")
            print("="*50)
            
        except Exception as e:
            print(f"[SCHEDULE] เกิดข้อผิดพลาดระหว่างทำงาน: {e}")
            logger.error(f"[SCHEDULE Error] {e}")
            logger.debug(traceback.format_exc())
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
        print("[SCHEDULE] กำลังทำ task โฟลเดอร์ใหม่...")
        target_folders = [
            ("ภาพกิจกรรม 2569", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
            ("ภาพกิจกรรม 2568", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
            ("ภาพกิจกรรม 2565-2567", "1BjYQwoso9FKv42XK6RJi1gPS8kyK_jCg")
        ]
        
        for year_name, year_id in target_folders:
            if self.stop_requested: break
            while True:
                if self.stop_requested: break
                red_folder = self._get_unscanned_subfolder(year_id)
                if not red_folder:
                    break
                    
                print(f"[SCHEDULE] เริ่มทำการสแกนรูปภาพในโฟลเดอร์: {red_folder['name']}")
                # เรียกใช้กระบวนการสแกนของระบบ (ใช้ background scan logic)
                try:
                    if hasattr(self.app_gui, 'process_scanning_headless'):
                        self.app_gui.process_scanning_headless([red_folder['id']])
                        print(f"[SCHEDULE] สแกนโฟลเดอร์ {red_folder['name']} เสร็จสิ้นเรียบร้อย")
                    else:
                        print(f"[SCHEDULE] Error: app_gui does not have process_scanning_headless")
                        break
                except Exception as e:
                    print(f"[SCHEDULE] Error scanning {red_folder['name']}: {e}")
                    break # หลุดจาก while เพื่อไม่ให้ค้าง
                    
    def _extract_drive_id(self, url):
        """ดึง ID จากลิงก์ Google Drive"""
        if not isinstance(url, str):
            return None
        if '/d/' in url:
            parts = url.split('/d/')
            if len(parts) > 1:
                return parts[1].split('/')[0]
        return None

    def _task_2_sync_new_students(self):
        print("[SCHEDULE] กำลังทำ task นักเรียนใหม่...")
        sheet_id = "1bz81BDC0NkuX1-jzw_glntYZ1xkmuI9xJSi8op_x7To"
        
        try:
            # ใช้ gspread อ่านข้อมูลจาก Sheet
            self.sync_manager.connect(sheet_id)
            sheet = self.sync_manager.gspread_client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
        except Exception as e:
            print(f"[SCHEDULE] ไม่สามารถอ่าน Sheet ข้อมูลนักเรียนได้: {e}")
            return
            
        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_sync_temp.json")
        old_data = {}
        if os.path.exists(temp_file):
            try:
                with open(temp_file, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
            except:
                pass
                
        new_data = {}
        matched_faces_to_process = []
        
        # คอลัมน์: รหัสนักเรียน | ชื่อ สกุล | รหัสส่วนตัว 6 หลัก | ภาพใบหน้าตรง | ภาพใบหน้าเพิ่มเติม1 | ภาพใบหน้าเพิ่มเติม2
        col_id = "รหัสนักเรียน"
        col_name = "ชื่อ สกุล"
        col_pin = "รหัสส่วนตัว 6 หลัก"
        col_img1 = "ภาพใบหน้าตรง"
        col_img2 = "ภาพใบหน้าเพิ่มเติม1"
        col_img3 = "ภาพใบหน้าเพิ่มเติม2"
        
        for row in data:
            std_id = str(row.get(col_id, "")).strip()
            if not std_id:
                continue
                
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
            
            # เปรียบเทียบ
            is_new = False
            new_imgs = []
            
            if std_id not in old_data:
                is_new = True
                new_imgs = [img for img in imgs if img.strip()]
            else:
                old_imgs = old_data[std_id]["imgs"]
                # หาลิงก์รูปที่เพิ่งเพิ่มมาใหม่หรือเปลี่ยนไป
                for i in range(3):
                    if imgs[i].strip() and (i >= len(old_imgs) or imgs[i] != old_imgs[i]):
                        new_imgs.append(imgs[i])
                        
            if is_new and new_imgs:
                print(f"[SCHEDULE] พบนักเรียนใหม่: {std_name} ({std_id})")
            elif new_imgs:
                print(f"[SCHEDULE] พบนักเรียนเก่าอัปเดตรูป: {std_name} ({std_id})")
                
            if new_imgs:
                # ลงทะเบียน DB
                staff_id = self.db.register_member(std_name, role='student', student_id=std_id, pin_code=pin_code)
                
                # โหลดภาพและสกัดเวกเตอร์
                for img_url in new_imgs:
                    file_id = self._extract_drive_id(img_url)
                    if file_id:
                        try:
                            img_bytes = self.sync_manager.download_image_bytes(file_id)
                            import numpy as np
                            import cv2
                            nparr = np.frombuffer(img_bytes, np.uint8)
                            img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img_cv is not None:
                                faces = self.analyzer.get_faces(img_cv)
                                if faces:
                                    # เอาหน้าแรกที่ชัดที่สุด
                                    face = faces[0]
                                    emb = face.embedding
                                    # เซฟลง staff_embeddings
                                    conn = self.db.get_connection()
                                    c = conn.cursor()
                                    c.execute("INSERT INTO staff_embeddings (staff_id, image_path, embedding) VALUES (?, ?, ?)",
                                             (staff_id, f"drive:{file_id}", emb.tobytes()))
                                    conn.commit()
                                    # เตรียมสำหรับ Retroactive Match
                                    matched_faces_to_process.append({
                                        "staff_id": staff_id,
                                        "name": std_name,
                                        "emb": emb
                                    })
                        except Exception as e:
                            print(f"[SCHEDULE] Error processing image {file_id} for {std_name}: {e}")
                            
        # Save temp JSON
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
            
        # Retroactive Matching สำหรับหน้าที่เพิ่มมาใหม่
        if matched_faces_to_process:
            print(f"[SCHEDULE] กำลังทำ task นักเรียนใหม่ -> Retroactive Match จำนวน {len(matched_faces_to_process)} ใบหน้า...")
            if hasattr(self.app_gui, 'process_retroactive_match_headless'):
                self.app_gui.process_retroactive_match_headless(matched_faces_to_process)
            else:
                print("[SCHEDULE] Error: app_gui does not have process_retroactive_match_headless")
            print("[SCHEDULE] ซิงค์นักเรียนและอัปเดตใบหน้าเสร็จสิ้น")
        else:
            print("[SCHEDULE] ไม่มีนักเรียนอัปเดตรูปภาพใหม่")
