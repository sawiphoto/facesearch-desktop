import os
import json
import logging
import io
import time
import socket
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread

# ตั้งเวลา timeout 30 วินาที ป้องกัน network call ค้างแบบไร้ขีดจำกัด
socket.setdefaulttimeout(30)

logger = logging.getLogger("FaceSearchApp")

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

class GoogleSyncManager:
    def __init__(self, credentials_path=None):
        if credentials_path is None:
            project_root = os.path.dirname(os.path.abspath(__file__))
            credentials_path = os.path.join(project_root, "config", "service_account.json")
            
        self.credentials_path = credentials_path
        self.credentials = None
        self.drive_service = None
        self.gspread_client = None
        self.spreadsheet_id = None
        self.connected = False
        import threading
        self.drive_lock = threading.Lock()

    def connect(self, spreadsheet_id=None, ensure_worksheets=True):
        """เชื่อมต่อกับ Google APIs"""
        self.connected = False
        logger.info(f"Attempting to load Google credentials from: {self.credentials_path}")
        
        if not os.path.exists(self.credentials_path):
            logger.error(f"Google credentials file not found. Please place service_account.json in the config/ directory.")
            return False
            
        try:
            self.credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self.drive_service = build('drive', 'v3', credentials=self.credentials)
            self.gspread_client = gspread.authorize(self.credentials)
            self.connected = True
            logger.info("Connected to Google Drive API & Sheets API successfully.")
            
            if spreadsheet_id:
                self.spreadsheet_id = spreadsheet_id
                return self.verify_spreadsheet(spreadsheet_id, ensure_worksheets=ensure_worksheets)
            return True
        except Exception as e:
            logger.error(f"Error connecting to Google Services: {e}", exc_info=True)
            return False

    def _execute_with_retry(self, func, max_retries=3, initial_delay=2):
        """
        ครอบการทำงานของการเชื่อมต่อ Google API ด้วยระบบลองใหม่อัตโนมัติ (Exponential Backoff Auto-Retry)
        เพื่อป้องกันข้อผิดพลาดชั่วคราว เช่น HTTP 503 (Service Unavailable), 500 (Internal Error), 429 (Rate Limit)
        """
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

    def verify_spreadsheet(self, spreadsheet_id, ensure_worksheets=True):
        """ตรวจสอบว่าเชื่อมต่อและจัดการ Spreadsheet ID ที่ระบุได้จริงหรือไม่ และเตรียมแผ่นงานในชีท"""
        if not self.connected:
            return False
            
        try:
            sheet = self._execute_with_retry(lambda: self.gspread_client.open_by_key(spreadsheet_id), max_retries=3, initial_delay=2)
            self.spreadsheet_id = spreadsheet_id
            logger.info(f"Verified Google Sheet access: '{sheet.title}'")
            
            if ensure_worksheets:
                # ตรวจสอบและสร้าง Worksheet ที่จำเป็น
                self._ensure_worksheets(sheet)
            return True
        except Exception as e:
            logger.error(f"Cannot access Google Sheet (ID: {spreadsheet_id}): {e}")
            return False

    def _ensure_worksheets(self, spreadsheet):
        """ตรวจสอบและสร้างชีทย่อย photos และ faces ตามโครงสร้างข้อมูล"""
        # 1. ชีท photos (photo_id | event | drive_link)
        try:
            photos_sheet = spreadsheet.worksheet("photos")
            logger.debug("Worksheet 'photos' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            photos_sheet = spreadsheet.add_worksheet(title="photos", rows="100", cols="3")
            photos_sheet.append_row(["photo_id", "event", "drive_link"])
            logger.info("Created new worksheet 'photos'.")

        # 2. ชีท faces (face_id | person | photo_id)
        try:
            faces_sheet = spreadsheet.worksheet("faces")
            logger.debug("Worksheet 'faces' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            faces_sheet = spreadsheet.add_worksheet(title="faces", rows="100", cols="3")
            faces_sheet.append_row(["face_id", "person", "photo_id"])
            logger.info("Created new worksheet 'faces'.")

    @staticmethod
    def parse_smart_photo_date(folder_name="", file_name="", file_meta=None):
        """
        สกัดวันที่รูปภาพ (YYYY-MM-DD) อย่างชาญฉลาด (v5.60)
        Priority 1: วันที่ถ่ายจริงจากกล้อง (imageMediaMetadata.time ใน Google Drive)
        Priority 2: รูปแบบวันที่ระบุชัดเจนในชื่อโฟลเดอร์หรือชื่อไฟล์ (เช่น 14-07-63, 14_07_2563, 2020-07-14)
        Priority 3: ปี พ.ศ. ในชื่อโฟลเดอร์ (เช่น ปี 2563, 2563) พร้อมจับคู่เดือนตามหมวดหมู่กิจกรรม
        Priority 4: วันที่อัปโหลด/สร้างไฟล์ (createdTime จาก Google Drive API)
        """
        import re

        if file_meta is None:
            file_meta = {}

        combined_text = f"{folder_name} {file_name}"

        # 1. ตรวจสอบ EXIF Date จาก Google Drive imageMediaMetadata (Priority 1)
        media_meta = file_meta.get("imageMediaMetadata")
        if media_meta and isinstance(media_meta, dict):
            exif_time = media_meta.get("time", "")
            if exif_time:
                # รูปแบบ "YYYY:MM:DD HH:MM:SS" หรือ "YYYY-MM-DD"
                m_exif = re.match(r'^(\d{4})[:\-](\d{2})[:\-](\d{2})', exif_time)
                if m_exif:
                    ey, em, ed = int(m_exif.group(1)), int(m_exif.group(2)), int(m_exif.group(3))
                    if 1990 <= ey <= 2050 and 1 <= em <= 12 and 1 <= ed <= 31:
                        return f"{ey:04d}-{em:02d}-{ed:02d}"

        # 2. ตรวจสอบรูปแบบวันที่เฉพาะเจาะจงในชื่อ (Priority 2)
        # ตัวอย่าง: "14-07-63", "14_07_2563", "14.07.63", "2020-07-14"
        # 2.1 รูปแบบ YYYY-MM-DD หรือ YYYY_MM_DD
        m_ymd = re.search(r'(?<!\d)(19\d{2}|20\d{2}|25\d{2})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)', combined_text)
        if m_ymd:
            raw_y, raw_m, raw_d = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
            if 1 <= raw_m <= 12 and 1 <= raw_d <= 31:
                ce_y = raw_y - 543 if raw_y >= 2500 else raw_y
                if 1990 <= ce_y <= 2050:
                    return f"{ce_y:04d}-{raw_m:02d}-{raw_d:02d}"

        # 2.2 รูปแบบ DD-MM-YY หรือ DD-MM-YYYY (เช่น 14-07-63, 14-07-2563, 05_12_2563)
        m_dmy = re.search(r'(?<!\d)(\d{1,2})[-_./](\d{1,2})[-_./](\d{2,4})(?!\d)', combined_text)
        if m_dmy:
            raw_d, raw_m, raw_y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
            if 1 <= raw_m <= 12 and 1 <= raw_d <= 31:
                if raw_y >= 2500:
                    ce_y = raw_y - 543
                elif 40 <= raw_y <= 99:
                    ce_y = (2500 + raw_y) - 543 # 63 -> 2563 -> 2020
                elif 0 <= raw_y <= 39:
                    ce_y = 2000 + raw_y # 20 -> 2020
                else:
                    ce_y = raw_y
                if 1990 <= ce_y <= 2050:
                    return f"{ce_y:04d}-{raw_m:02d}-{raw_d:02d}"

        # 3. ตรวจสอบปี พ.ศ. 4 หลัก (Priority 3: เช่น 2563, ปี 2563, ปีการศึกษา 2563)
        m_thai_year = re.search(r'(?:ปี(?:การศึกษา)?\s*|พ\.?ศ\.?\s*)?(25[3-7]\d)', folder_name)
        if not m_thai_year:
            m_thai_year = re.search(r'(?<!\d)(25[3-7]\d)(?!\d)', combined_text)

        if m_thai_year:
            th_year = int(m_thai_year.group(1))
            ce_year = th_year - 543

            # วิเคราะห์เดือนตามชื่อกิจกรรมยอดนิยมในโรงเรียน
            f_lower = folder_name.lower()
            if any(k in f_lower for k in ["ปฐมนิเทศ", "มอบตัว", "เปิดเทอม", "เปิดภาคเรียน", "ต้นเทอม", "รถรับส่ง"]):
                return f"{ce_year:04d}-05-15"
            elif any(k in f_lower for k in ["ไหว้ครู", "สภานักเรียน", "เลือกตั้ง"]):
                return f"{ce_year:04d}-06-15"
            elif any(k in f_lower for k in ["เฉลิมพระชนม", "ร.10", "รัชกาลที่ 10", "เยี่ยม รร"]):
                return f"{ce_year:04d}-07-28"
            elif any(k in f_lower for k in ["วันแม่", "กำเนิด รร", "วันคล้ายวันกำเนิด", "วิทยาศาสตร์"]):
                return f"{ce_year:04d}-08-12"
            elif any(k in f_lower for k in ["เกษียณ", "มุทิตาจิต"]):
                return f"{ce_year:04d}-09-30"
            elif any(k in f_lower for k in ["วันปิยะ", "ปิดเทอม", "ออกพรรษา"]):
                return f"{ce_year:04d}-10-15"
            elif any(k in f_lower for k in ["ลอยกระทง"]):
                return f"{ce_year:04d}-11-15"
            elif any(k in f_lower for k in ["วันพ่อ", "วันชาติ", "ปีใหม่", "คริสต์มาส", "ส่งท้ายปี"]):
                return f"{ce_year:04d}-12-25"
            elif any(k in f_lower for k in ["วันเด็ก", "วันครู", "กีฬา"]):
                return f"{ce_year:04d}-01-16"
            elif any(k in f_lower for k in ["ปัจฉิม", "บัณฑิตน้อย", "จบการศึกษา", "โอเน็ต", "onet"]):
                return f"{ce_year:04d}-02-25"
            elif any(k in f_lower for k in ["สอบเข้า", "รับสมัคร", "สอบ ม.", "ความสามารถพิเศษ", "ปลายภาค", "จัดสอบ"]):
                return f"{ce_year:04d}-03-15"
            elif any(k in f_lower for k in ["สงกรานต์", "ปีใหม่ไทย"]):
                return f"{ce_year:04d}-04-13"
            
            # หากไม่มีคีย์เวิร์ดเฉพาะ ให้ดึงเดือนจาก createdTime (ถ้ามี) หรือ default เป็น พ.ค.
            created_time = file_meta.get("createdTime", "")
            if created_time and len(created_time) >= 10:
                try:
                    c_month = int(created_time[5:7])
                    c_day = int(created_time[8:10])
                    if 1 <= c_month <= 12 and 1 <= c_day <= 31:
                        return f"{ce_year:04d}-{c_month:02d}-{c_day:02d}"
                except Exception:
                    pass
            return f"{ce_year:04d}-05-01"

        # 4. Fallback: ใช้วันที่ createdTime จาก Google Drive (Priority 4)
        created_time = file_meta.get("createdTime", "")
        if created_time and len(created_time) >= 10:
            return created_time[:10]

        return ""

    def fetch_drive_folder_images_recursive(self, folder_id):
        """
        ดึงไฟล์รูปภาพจาก Google Drive แบบย้อนกลับ (Recursive)
        คืนค่า: รายการของ dict ที่มีข้อมูล {'file_name', 'file_id', 'drive_link', 'event', 'date'}
        """
        if not self.connected:
            logger.error("Not connected to Google Drive API.")
            return []

        logger.info(f"Scanning folder ID: {folder_id} recursively...")
        
        # ดึงรายละเอียดชื่อของโฟลเดอร์เริ่มต้นก่อน
        folder_metadata = self.drive_service.files().get(fileId=folder_id, fields="name").execute()
        root_folder_name = folder_metadata.get("name", "Unknown Folder")
        logger.info(f"Starting root folder name: {root_folder_name}")

        all_images = []
        
        # ฟังก์ชันค้นหาไฟล์ในโฟลเดอร์ recursively
        def walk_folder(curr_folder_id, curr_event_name):
            logger.info(f"Listing contents of Google Drive folder: {curr_event_name} (ID: {curr_folder_id})")
            
            # 1. ค้นหาโฟลเดอร์ย่อยทั้งหมด (เพิ่ม pagination เผื่อกรณีโฟลเดอร์เยอะมาก)
            query_dirs = f"'{curr_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            subdirs = []
            page_token = None
            while True:
                dirs_results = self.drive_service.files().list(
                    q=query_dirs, fields="nextPageToken, files(id, name)", pageToken=page_token
                ).execute()
                subdirs.extend(dirs_results.get("files", []))
                page_token = dirs_results.get("nextPageToken")
                if not page_token:
                    break
            
            # 2. ค้นหาไฟล์ทั้งหมดในโฟลเดอร์นี้ แล้วนำมากรองประเภทรูปภาพในระดับแอปพลิเคชัน (เพิ่ม pagination ลูปดึงไฟล์จนครบ พร้อม imageMediaMetadata v5.60)
            query_files = f"'{curr_folder_id}' in parents and trashed = false"
            all_files = []
            page_token = None
            while True:
                files_results = self.drive_service.files().list(
                    q=query_files, fields="nextPageToken, files(id, name, mimeType, webViewLink, createdTime, imageMediaMetadata)", 
                    pageSize=500, pageToken=page_token
                ).execute()
                all_files.extend(files_results.get("files", []))
                page_token = files_results.get("nextPageToken")
                if not page_token:
                    break
            
            # กรองเฉพาะไฟล์รูปภาพจาก MimeType (เนื่องจากไฟล์บนคลาวด์บางไฟล์อาจไม่มีนามสกุล) แต่บังคับข้ามไฟล์ RAW (v1.7.8 Hotfix)
            raw_exts = ('.cr2', '.nef', '.arw', '.dng', '.orf', '.rw2')
            files = [f for f in all_files if f.get("mimeType", "").startswith("image/") and not f.get("name", "").lower().endswith(raw_exts)]
            
            logger.info(f"Found {len(subdirs)} subfolders and {len(files)} supported images in folder '{curr_event_name}'")

            # เก็บไฟล์รูปภาพพร้อมวันที่อัจฉริยะ (Smart Photo Date v5.60)
            for file in files:
                date_str = self.parse_smart_photo_date(folder_name=curr_event_name, file_name=file.get("name", ""), file_meta=file)
                all_images.append({
                    "file_name": file.get("name"),
                    "file_id": file.get("id"),
                    "drive_link": file.get("webViewLink"),
                    "event": curr_event_name,
                    "date": date_str
                })
                logger.debug(f"Queued file: {file.get('name')} (smart date: {date_str}) in event '{curr_event_name}'")

            # เรียกใช้งานแบบ recursive ลงไปในโฟลเดอร์ย่อย
            for subdir in subdirs:
                subdir_id = subdir.get("id")
                subdir_name = subdir.get("name")
                
                # หากโฟลเดอร์ปัจจุบันคือโฟลเดอร์ระดับรากหรือระดับปี ("ภาพกิจกรรม...")
                # โฟลเดอร์ลูกชั้นแรกใต้ปีคือชื่อกิจกรรมหลัก (Main Event)
                # แต่หากเป็นโฟลเดอร์ย่อยลงไปอีก (Subfolder) ให้คงชื่อกิจกรรมหลักเดิมไว้เสมอ (v6.24)
                is_root_or_year = "ภาพกิจกรรม" in curr_event_name or curr_event_name in ["Unknown Folder", "ภาพกิจกรรม 2569", "ภาพกิจกรรม 2568", "ภาพกิจกรรม 2567", "ภาพกิจกรรม 2566", "ภาพกิจกรรม 2565", "ภาพกิจกรรม 2563"]
                next_event_name = subdir_name if is_root_or_year else curr_event_name
                walk_folder(subdir_id, next_event_name)

        walk_folder(folder_id, root_folder_name)
        logger.info(f"Recursive scan completed. Total images found: {len(all_images)}")
        return all_images

    def download_image_thumbnail_bytes(self, file_id):
        """ดึงไบต์รูปภาพ Thumbnail ความละเอียดต่ำจาก Google Drive (ขนาดไฟล์เล็กมากและโหลดเร็วมาก)"""
        if not self.connected:
            return None
        try:
            with self.drive_lock:
                file_meta = self.drive_service.files().get(fileId=file_id, fields="thumbnailLink").execute()
            thumbnail_url = file_meta.get("thumbnailLink")
            
            if not thumbnail_url:
                return self.download_image_bytes(file_id)
                
            # สร้าง HTTP client ใหม่ต่อแต่ละเธรด (thread-safe, ไม่แชร์ SSL connection)
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
            authed_http = AuthorizedHttp(self.credentials, http=httplib2.Http())
            resp, content = authed_http.request(thumbnail_url, "GET")
            if resp.status == 200 and content:
                return content
            else:
                logger.warning(f"Failed to fetch thumbnail HTTP {resp.status}")
                return None
        except Exception as e:
            logger.error(f"Error fetching thumbnail for file ID {file_id}: {e}")
            return None

    def download_image_bytes(self, file_id):
        """ดาวน์โหลดไบต์รูปภาพจาก Google Drive มาไว้ใน Memory (ไม่ต้องบันทึกลงดิสก์)"""
        if not self.connected:
            return None
        try:
            with self.drive_lock:
                request = self.drive_service.files().get_media(fileId=file_id)
                data_payload = request.execute()
            img_bytes = io.BytesIO(data_payload)
            return img_bytes.read()
        except Exception as e:
            logger.error(f"Error downloading file ID {file_id} from Drive: {e}")
            return None

    def download_image_bytes_with_stats(self, file_id, file_name="Unknown"):
        """
        ดาวน์โหลดไบต์รูปภาพพร้อมบันทึกสถิติเวลา (วินาที), ขนาดไฟล์ (MB) และความเร็ว (MB/s) ลงใน Log
        คืนค่า: (img_bytes, elapsed_seconds, size_bytes)
        """
        if not self.connected:
            return None, 0.0, 0
        t0 = time.time()
        try:
            with self.drive_lock:
                request = self.drive_service.files().get_media(fileId=file_id)
                data_payload = request.execute()
            t1 = time.time()
            elapsed = t1 - t0
            img_bytes = io.BytesIO(data_payload).read()
            size_bytes = len(img_bytes)
            size_mb = size_bytes / (1024 * 1024)
            speed_mbps = size_mb / elapsed if elapsed > 0 else 0.0
            logger.info(f"[DOWNLOAD] ดาวน์โหลดไฟล์ {file_name} ({size_mb:.2f} MB) สำเร็จใน {elapsed:.1f} วินาที ({speed_mbps:.2f} MB/s)")
            return img_bytes, elapsed, size_bytes
        except Exception as e:
            logger.error(f"[DOWNLOAD] เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์ {file_name} (ID: {file_id}): {e}")
            return None, 0.0, 0

    def sync_to_google_sheet(self, sync_data):
        """
        อัปเดตข้อมูลขึ้น Google Sheet
        (v2.7 Optimization: ยกเลิกการเขียน photos และ faces 40,000+ แถวขึ้น Google Sheets
         เพื่อป้องกันอาการค้างและเพิ่มความเร็ว โดยหันมาใช้ระบบ Google Drive JSON Index แทน)
        """
        logger.info("[GSHEETS] Optimized (v2.7): Skipped legacy 'photos' & 'faces' worksheets bulk writing (Using Google Drive JSON Index instead).")
        return True

    def save_local_excel_mirror(self, sync_data):
        """
        สร้างไฟล์ Excel (.xlsx) เป็น mirror เลียนแบบข้อมูลบน Google Sheet สำรองไว้ในโฟลเดอร์โครงการ
        """
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            
            # 1. จัดทำข้อมูลแผ่นงาน photos
            ws_photos = wb.active
            ws_photos.title = "photos"
            ws_photos.append(["photo_id", "event", "drive_link", "date"])
            for item in sync_data["photos"]:
                ws_photos.append([item["photo_id"], item["event"], item["drive_link"], item.get("date", "")])
                
            # 2. จัดทำข้อมูลแผ่นงาน faces
            ws_faces = wb.create_sheet(title="faces")
            ws_faces.append(["face_id", "person", "photo_id"])
            for item in sync_data["faces"]:
                ws_faces.append([item["face_id"], item["person"], item["photo_id"]])
                
            # บันทึกไฟล์ทับไฟล์เดิมในโฟลเดอร์โปรเจกต์
            project_root = os.path.dirname(os.path.abspath(__file__))
            backup_path = os.path.join(project_root, "sheet_mirror_backup.xlsx")
            wb.save(backup_path)
            logger.info(f"[EXCEL BACKUP] Successfully saved local Excel mirror at {backup_path}")
            return True
        except Exception as e:
            logger.error(f"[EXCEL BACKUP] Error saving local Excel mirror: {e}", exc_info=True)
            return False

    def update_json_indexes_on_drive(self, sync_data, json_folder_id, scan_mode="all"):
        """
        สร้างข้อมูลดัชนี JSON สามไฟล์ (person_index.json (ครู), student_index.json (นักเรียน) และ photo_index.json) 
        แล้วทำการอัปโหลดทับ (Overwrite) ไฟล์เป้าหมายที่มีอยู่แล้วบน Google Drive ในโฟลเดอร์ที่แอดมินระบุไว้
        โดยจะเลือกสร้างและอัปโหลดเฉพาะไฟล์ที่มีส่วนเกี่ยวข้องกับการสแกนเพื่อลดโหลดเครือข่ายและ API
        """
        if not self.connected or not self.drive_service:
            logger.error("Google Drive service not connected.")
            return False

        if not json_folder_id:
            logger.warning("JSON folder ID is empty. Skipping Drive JSON index update.")
            return False

        try:
            # 🌟 ถ้า sync_data ส่งมาเป็น None ให้ดึงจาก SQLite DB ให้อัตโนมัติ (v4.19)
            if sync_data is None:
                from db_manager import DatabaseManager
                db = DatabaseManager()
                sync_data = db.get_all_sync_data()

            if not sync_data or not isinstance(sync_data, dict):
                logger.warning("sync_data is empty or invalid. Skipping Drive JSON index update.")
                return False

            # 1. แยกกลุ่มและสร้างดัชนีสำหรับ person_index.json (ครู) และ student_index.json (นักเรียน)
            person_index = {}
            student_index = {}
            has_teachers = False
            has_students = False

            for item in sync_data["faces"]:
                role = item.get("role", "teacher")
                person = item["person"]
                photo_id = item["photo_id"]
                
                if role == "student":
                    has_students = True
                    if person not in student_index:
                        student_index[person] = []
                    if photo_id not in student_index[person]:
                        student_index[person].append(photo_id)
                else:
                    has_teachers = True
                    if person not in person_index:
                        person_index[person] = []
                    if photo_id not in person_index[person]:
                        person_index[person].append(photo_id)

            # 2. สร้างโครงสร้างข้อมูลสำหรับ photo_index.json (แปลงลิงก์ให้เป็น Web View URL เสมอ, รวม face_count v6.23 และ academic_year v6.26)
            photo_index = {}
            for item in sync_data["photos"]:
                photo_id = item["photo_id"]
                raw_link = item["drive_link"]
                entry = {
                    "event": item["event"],
                    "drive_link": self.format_drive_view_url(raw_link),
                    "date": item.get("date", ""),
                    "face_count": item.get("face_count", 0)
                }
                if item.get("year"):
                    entry["year"] = str(item["year"]).strip()
                if item.get("subfolder"):
                    entry["subfolder"] = item["subfolder"]
                photo_index[photo_id] = entry

            # พิจารณาการอัปโหลดตามโหมดสแกน
            upload_person = False
            upload_student = False

            if scan_mode == "all":
                # โหมดสแกนทั้งหมด/Manual Sync: อัปโหลดตามข้อมูลที่มีจริง
                if has_teachers:
                    upload_person = True
                if has_students:
                    upload_student = True
            elif scan_mode in ["teachers", "selected_teachers"]:
                # สแกนเฉพาะครู: อัปโหลดเฉพาะครู
                upload_person = True
            elif scan_mode in ["students", "selected_students"]:
                # สแกนเฉพาะนักเรียน: อัปโหลดเฉพาะนักเรียน
                upload_student = True

            # ฟังก์ชันช่วยอัปโหลดทับไฟล์เดิมบน Google Drive
            def upload_overwrite_json(file_name, data_dict):
                json_content = json.dumps(data_dict, ensure_ascii=False, indent=2)
                
                # ค้นหา ID ของไฟล์เดิมในโฟลเดอร์ที่แอดมินกำหนด
                query = f"'{json_folder_id}' in parents and name = '{file_name}' and trashed = false"
                search_results = self.drive_service.files().list(q=query, fields="files(id)").execute()
                files = search_results.get("files", [])
                
                media = MediaIoBaseUpload(
                    io.BytesIO(json_content.encode('utf-8')),
                    mimetype='application/json',
                    resumable=True
                )
                
                if files:
                    file_id = files[0]['id']
                    logger.info(f"[GDRIVE JSON] Updating existing file '{file_name}' (ID: {file_id}) in specified folder...")
                    self.drive_service.files().update(
                         fileId=file_id,
                         media_body=media
                    ).execute()
                    logger.info(f"[GDRIVE JSON] Successfully updated '{file_name}' on Google Drive.")
                else:
                    # ถ้าหาในโฟลเดอร์ที่ระบุไม่เจอ ให้ทำการค้นหาทั่วไดรฟ์ (Global search) เผื่อไปวางสลับที่กัน
                    logger.warning(f"[GDRIVE JSON] File '{file_name}' not found in folder '{json_folder_id}'. Searching globally...")
                    global_query = f"name = '{file_name}' and trashed = false"
                    global_search_results = self.drive_service.files().list(q=global_query, fields="files(id)").execute()
                    global_files = global_search_results.get("files", [])
                    
                    if global_files:
                        file_id = global_files[0]['id']
                        logger.info(f"[GDRIVE JSON] Found file globally (ID: {file_id}). Overwriting global file...")
                        self.drive_service.files().update(
                            fileId=file_id,
                            media_body=media
                        ).execute()
                        logger.info(f"[GDRIVE JSON] Successfully updated '{file_name}' globally on Google Drive.")
                    else:
                        # สร้างไฟล์ใหม่ถ้ายังไม่พบเลย
                        logger.warning(f"[GDRIVE JSON] File '{file_name}' not found anywhere. Creating in specified folder...")
                        file_metadata = {
                            'name': file_name,
                            'mimeType': 'application/json',
                            'parents': [json_folder_id]
                        }
                        new_file = self.drive_service.files().create(
                            body=file_metadata,
                            media_body=media,
                            fields='id'
                        ).execute()
                        logger.info(f"[GDRIVE JSON] Created new '{file_name}' (ID: {new_file.get('id')}) on Drive.")

            # ดำเนินการอัปเดตไฟล์ตามความเกี่ยวข้อง
            if upload_person:
                upload_overwrite_json("person_index.json", person_index)
            if upload_student:
                upload_overwrite_json("student_index.json", student_index)
                
            # ดัชนีรูปภาพอัปโหลดเสมอหากมีการอัปเดต
            if upload_person or upload_student:
                upload_overwrite_json("photo_index.json", photo_index)
                
            return True
        except Exception as e:
            logger.error(f"[GDRIVE JSON] Error updating JSON search indexes: {e}", exc_info=True)
            return False

    def format_drive_view_url(self, raw_url):
        """แปลง Drive URL ให้เป็นลิงก์เปิดดูบน Web Browser เสมอ (ไม่บังคับดาวน์โหลด)"""
        file_id = self.extract_file_id_from_url(raw_url)
        if file_id:
            return f"https://drive.google.com/file/d/{file_id}/view"
        return raw_url

    def extract_file_id_from_url(self, url):
        """แปลง Google Drive URL เป็น File ID"""
        if not url:
            return None

        # รูปแบบ: https://drive.google.com/file/d/FILE_ID/view
        if '/file/d/' in url:
            parts = url.split('/file/d/')
            if len(parts) > 1:
                file_id = parts[1].split('/')[0]
                return file_id

        # รูปแบบ: https://drive.google.com/open?id=FILE_ID หรือ uc?id=FILE_ID
        if 'id=' in url:
            parts = url.split('id=')
            if len(parts) > 1:
                file_id = parts[1].split('&')[0]
                return file_id

        logger.warning(f"Could not extract file ID from URL: {url}")
        return None

    def download_image_from_url(self, url, local_path=None):
        """ดาวน์โหลดรูปจาก Google Drive URL และบันทึกเป็นไฟล์ (หรือคืน bytes)"""
        file_id = self.extract_file_id_from_url(url)
        if not file_id:
            return None

        image_bytes = self.download_image_bytes(file_id)
        if not image_bytes:
            return None

        if local_path:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(image_bytes)
            return local_path

        return image_bytes

    def read_sheet_data(self, spreadsheet_id, sheet_name=None):
        """อ่านข้อมูลทั้งหมดจาก Google Sheets"""
        if not self.connected:
            return None

        try:
            sheet = self._execute_with_retry(lambda: self.gspread_client.open_by_key(spreadsheet_id), max_retries=3, initial_delay=2)
            if sheet_name:
                worksheet = sheet.worksheet(sheet_name)
            else:
                worksheet = sheet.sheet1

            data = worksheet.get_all_values()
            logger.info(f"Read {len(data)} rows from sheet '{worksheet.title}'")
            return data
        except Exception as e:
            logger.error(f"Error reading sheet: {e}")
            return None

    def list_spreadsheets(self):
        """
        ดึงรายการ Spreadsheet ทั้งหมดจาก Google Drive
        คืนค่า: list ของ dict ที่มีคีย์ {'id', 'name', 'url'}
        """
        if not self.connected:
            return []

        try:
            # ค้นหาไฟล์ประเภท Spreadsheet ทั้งหมดใน Drive
            query = "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, webViewLink)",
                pageSize=100
            ).execute()

            files = results.get("files", [])
            spreadsheets = []
            for file in files:
                spreadsheets.append({
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "url": file.get("webViewLink")
                })

            logger.info(f"Found {len(spreadsheets)} spreadsheets in Google Drive")
            return spreadsheets
        except Exception as e:
            logger.error(f"Error listing spreadsheets: {e}")
            return []

    def list_spreadsheets_with_folders(self):
        """
        ดึงรายการ Spreadsheet และ Folder ทั้งหมดจาก Google Drive
        คืนค่า: dict ที่มีคีย์ "sheets" (list) และ "folders" (list)
        """
        if not self.connected:
            return {"sheets": [], "folders": []}

        try:
            # ดึงเฉพาะ Spreadsheet
            sheets_query = "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            sheets_results = self.drive_service.files().list(
                q=sheets_query,
                fields="files(id, name, parents, webViewLink)",
                pageSize=200
            ).execute()
            sheets = sheets_results.get("files", [])

            # ดึงเฉพาะ Folder
            folders_query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            folders_results = self.drive_service.files().list(
                q=folders_query,
                fields="files(id, name, parents)",
                pageSize=200
            ).execute()
            folders = folders_results.get("files", [])

            logger.info(f"Found {len(sheets)} spreadsheets and {len(folders)} folders in Google Drive")
            return {"sheets": sheets, "folders": folders}
        except Exception as e:
            logger.error(f"Error listing spreadsheets with folders: {e}")
            return {"sheets": [], "folders": []}

