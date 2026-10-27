import os
import json
import logging
import io
import time
from datetime import datetime
import socket
import ssl
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from google.oauth2 import service_account
import mimetypes
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaFileUpload
from googleapiclient.errors import HttpError, ResumableUploadError
import gspread

# ตั้งเวลา timeout 120 วินาที เพื่อรองรับการอัปโหลดไฟล์ดัชนี JSON ขนาดใหญ่ และป้องกัน connection drop บน Wi-Fi/เครือข่ายโรงเรียน (v6.35)
socket.setdefaulttimeout(120)

logger = logging.getLogger("FaceSearchApp")

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

GENERIC_SUBFOLDER_KEYWORDS = {
    'นักเรียน', 'ครู', 'ภาพ', 'รวม', 'targetfolder', 'doc', 'คำสั่ง', 
    'vdo', 'ไวนิล', 'ภาพถ่าย', 'รูปภาพ', 'ภาพอำเภอ', 'ผลงานครู',
    'thana', "jim's", 'ครูธนา', 'ครูอ้อย', 'น้านัน', 'อาสุ', 'unknown', 'unknown folder'
}

def is_generic_folder_name(name):
    if not name:
        return True
    cleaned = str(name).strip().lower()
    return cleaned in GENERIC_SUBFOLDER_KEYWORDS or cleaned.startswith("targetfolder")

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
            # ตั้ง timeout 120s บนระดับ HTTP Client และปิด discovery cache
            http = AuthorizedHttp(self.credentials, http=httplib2.Http(timeout=120))
            self.drive_service = build('drive', 'v3', http=http, cache_discovery=False)
            self.gspread_client = gspread.authorize(self.credentials)
            self.connected = True
            logger.info("Connected to Google Drive API & Sheets API successfully (with 120s HTTP timeout).")
            
            if spreadsheet_id:
                self.spreadsheet_id = spreadsheet_id
                return self.verify_spreadsheet(spreadsheet_id, ensure_worksheets=ensure_worksheets)
            return True
        except Exception as e:
            logger.error(f"Error connecting to Google Services: {e}", exc_info=True)
            return False

    def reconnect_drive_service(self):
        """
        สร้าง Drive API Service Client ใหม่เพื่อล้าง Socket Pool เก่าที่ตายแล้ว
        (Self-Healing on Network/SSL Drop หรือเมื่อมีการสลับ Wi-Fi) v6.35
        """
        try:
            if not self.credentials and os.path.exists(self.credentials_path):
                self.credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_path, scopes=SCOPES
                )
            if self.credentials:
                http = AuthorizedHttp(self.credentials, http=httplib2.Http(timeout=120))
                with self.drive_lock:
                    self.drive_service = build('drive', 'v3', http=http, cache_discovery=False)
                logger.info("[GDRIVE] Refreshed Google Drive API client & reset connection pool successfully (v6.35).")
                return True
            else:
                logger.warning("[GDRIVE] Cannot reconnect Drive API: credentials not loaded.")
                return False
        except Exception as re_err:
            logger.warning(f"[GDRIVE] Failed to refresh Drive API client: {re_err}")
            return False

    def _execute_with_retry(self, func, max_retries=3, initial_delay=2):
        """
        ครอบการทำงานของการเชื่อมต่อ Google API ด้วยระบบลองใหม่อัตโนมัติ (Exponential Backoff Auto-Retry)
        เพื่อป้องกันข้อผิดพลาดชั่วคราว เช่น HTTP 503 (Service Unavailable), 500 (Internal Error), 429 (Rate Limit)
        """
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
    def parse_smart_photo_date(folder_name="", file_name="", file_meta=None, academic_year=""):
        """
        สกัดวันที่รูปภาพ (YYYY-MM-DD) อย่างชาญฉลาด (v6.45)
        Priority 1: วันที่ถ่ายจริงจากกล้อง (imageMediaMetadata.time ใน Google Drive)
        Priority 2: วันที่ซ่อนอยู่ในชื่อไฟล์ LINE Album (_YYMMDD_) รองรับทั้งเลขอารบิกและเลขไทย
        Priority 3: รูปแบบวันที่ระบุชัดเจนในชื่อโฟลเดอร์หรือชื่อไฟล์ (เช่น 14-07-63, 14_07_2563, 2020-07-14, 23 พย, 21 มีค)
        Priority 4: ปี พ.ศ. ในชื่อโฟลเดอร์ (4 หลัก หรือ 2 หลัก หรือจาก academic_year) พร้อมจับคู่เดือนตามหมวดหมู่กิจกรรม
        Priority 5: วันที่อัปโหลด/สร้างไฟล์ (createdTime จาก Google Drive API) โดยมี Guard ป้องกันการข้ามปี
        """
        import re

        if file_meta is None:
            file_meta = {}

        # แปลงเลขไทยเป็นเลขอารบิกเพื่อความแม่นยำสูง (Thai Numerals Normalization)
        thai_to_arabic = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')
        f_norm = (folder_name or "").translate(thai_to_arabic)
        fn_norm = (file_name or "").translate(thai_to_arabic)
        combined_text = f"{f_norm} {fn_norm}"

        # 1. ตรวจสอบ EXIF Date จาก Google Drive imageMediaMetadata (Priority 1)
        media_meta = file_meta.get("imageMediaMetadata")
        if media_meta and isinstance(media_meta, dict):
            exif_time = media_meta.get("time", "")
            if exif_time:
                m_exif = re.match(r'^(\d{4})[:\-](\d{2})[:\-](\d{2})', exif_time)
                if m_exif:
                    ey, em, ed = int(m_exif.group(1)), int(m_exif.group(2)), int(m_exif.group(3))
                    if 1990 <= ey <= 2050 and 1 <= em <= 12 and 1 <= ed <= 31:
                        return f"{ey:04d}-{em:02d}-{ed:02d}"

        # 2. ตรวจสอบชื่อไฟล์ LINE Album รูปแบบ _YYMMDD_ (Priority 2)
        # ตัวอย่าง: LINE_ALBUM_วันม่วงเหลือง64_๒๒๐๓๒๒_163.jpg หรือ LINE_ALBUM_วันเพ็ญ64_211119_267.jpg
        m_line = re.search(r'_(\d{2})(\d{2})(\d{2})_', fn_norm)
        if m_line:
            yy, mm, dd = int(m_line.group(1)), int(m_line.group(2)), int(m_line.group(3))
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                ce_y = 2000 + yy if yy <= 40 else (2500 + yy) - 543
                if 1990 <= ce_y <= 2050:
                    return f"{ce_y:04d}-{mm:02d}-{dd:02d}"

        # 3. ตรวจสอบรูปแบบวันที่เฉพาะเจาะจงในชื่อ (Priority 3)
        # 3.1 รูปแบบ YYYY-MM-DD หรือ YYYY_MM_DD
        m_ymd = re.search(r'(?<!\d)(19\d{2}|20\d{2}|25\d{2})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)', combined_text)
        if m_ymd:
            raw_y, raw_m, raw_d = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
            if 1 <= raw_m <= 12 and 1 <= raw_d <= 31:
                ce_y = raw_y - 543 if raw_y >= 2500 else raw_y
                if 1990 <= ce_y <= 2050:
                    return f"{ce_y:04d}-{raw_m:02d}-{raw_d:02d}"

        # 3.2 รูปแบบ DD-MM-YY หรือ DD-MM-YYYY (เช่น 14-07-63, 14-07-2563, 26-1-64)
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

        # 3.3 ตรวจสอบชื่อเดือนภาษาไทย (เช่น "23 พย", "21 มีค", "14 ก.ค.")
        thai_months = {
            'ม.ค.': 1, 'มค': 1, 'ก.พ.': 2, 'กพ': 2, 'มี.ค.': 3, 'มีค': 3,
            'เม.ย.': 4, 'เมย': 4, 'พ.ค.': 5, 'พค': 5, 'มิ.ย.': 6, 'มิย': 6,
            'ก.ค.': 7, 'กค': 7, 'ส.ค.': 8, 'สค': 8, 'ก.ย.': 9, 'กย': 9,
            'ต.ค.': 10, 'ตค': 10, 'พ.ย.': 11, 'พย': 11, 'ธ.ค.': 12, 'ธค': 12
        }
        for m_txt, m_num in thai_months.items():
            m_th = re.search(r'(?<!\d)(\d{1,2})\s*' + re.escape(m_txt), combined_text)
            if m_th:
                t_day = int(m_th.group(1))
                if 1 <= t_day <= 31:
                    # หาปี พ.ศ. จากชื่อโฟลเดอร์/ชื่อไฟล์ หรือจาก academic_year
                    m_yr = re.search(r'(?<!\d)(25[3-7]\d)(?!\d)', combined_text)
                    if not m_yr:
                        m_yr = re.search(r'(?:ปี\s*|พ\.?ศ\.?\s*|[^\d]|^)(6[0-9])(?!\d)', combined_text)
                    raw_y = None
                    if m_yr:
                        raw_y = int(m_yr.group(1))
                    elif academic_year and str(academic_year).strip().isdigit():
                        raw_y = int(str(academic_year).strip())
                    if raw_y:
                        th_y = raw_y if raw_y >= 2500 else 2500 + raw_y
                        base_ce = th_y - 543
                        t_year = base_ce if m_num >= 5 else base_ce + 1
                        return f"{t_year:04d}-{m_num:02d}-{t_day:02d}"

        # 4. ตรวจสอบปี พ.ศ. 4 หลัก หรือ 2 หลัก หรือ academic_year (Priority 4)
        m_thai_year = re.search(r'(?:ปี(?:การศึกษา)?\s*|พ\.?ศ\.?\s*)?(25[3-7]\d)', f_norm)
        if not m_thai_year:
            m_thai_year = re.search(r'(?<!\d)(25[3-7]\d)(?!\d)', combined_text)
        if not m_thai_year:
            m_short_yr = re.search(r'(?:ปี|พ\.?ศ\.?|\s|^|[^\d])(6[0-9])(?!\d)', combined_text)
            if m_short_yr:
                th_year = 2500 + int(m_short_yr.group(1))
            elif academic_year and str(academic_year).strip().isdigit():
                ay_val = int(str(academic_year).strip())
                th_year = ay_val if ay_val >= 2500 else 2500 + ay_val
            else:
                th_year = None
        else:
            th_year = int(m_thai_year.group(1))

        if th_year:
            ce_year = th_year - 543
            f_lower = f_norm.lower()

            if "1-65" in f_lower:
                return "2022-05-15"
            elif any(k in f_lower for k in ["ปฐมนิเทศ", "มอบตัว", "เปิดเทอม", "เปิดภาคเรียน", "ต้นเทอม", "รถรับส่ง"]):
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
            elif any(k in f_lower for k in ["ลอยกระทง", "วันเพ็ญ"]):
                return f"{ce_year:04d}-11-15"
            elif any(k in f_lower for k in ["ธรรมศึกษา"]):
                return f"{ce_year:04d}-11-20"
            elif any(k in f_lower for k in ["วันพ่อ", "วันชาติ", "กีฬาแห่งชาติ", "ฟุตบอล", "บอล"]):
                return f"{ce_year:04d}-12-10"
            elif any(k in f_lower for k in ["ปีใหม่", "คริสต์มาส", "ส่งท้ายปี"]):
                return f"{ce_year:04d}-12-25"
            elif any(k in f_lower for k in ["วันเด็ก", "วันครู", "กีฬา"]):
                return f"{ce_year+1:04d}-01-16"
            elif any(k in f_lower for k in ["ตรุษจีน", "ศรร 26-1"]):
                return f"{ce_year+1:04d}-01-26"
            elif any(k in f_lower for k in ["onet", "โอเน็ต"]):
                return f"{ce_year+1:04d}-02-12"
            elif any(k in f_lower for k in ["ปัจฉิม", "วันม่วงเหลือง", "บัณฑิตน้อย", "จบการศึกษา"]):
                return f"{ce_year+1:04d}-03-22"
            elif any(k in f_lower for k in ["สอบเข้า", "รับสมัคร", "สอบ ม.", "ความสามารถพิเศษ", "ปลายภาค", "จัดสอบ"]):
                return f"{ce_year+1:04d}-03-15"
            elif any(k in f_lower for k in ["สงกรานต์", "ปีใหม่ไทย"]):
                return f"{ce_year+1:04d}-04-13"
            elif any(k in f_lower for k in ["เปิดเรียน2", "เปิดเทอม2"]):
                return f"{ce_year:04d}-11-01"
            
            # หากไม่มีคีย์เวิร์ดเฉพาะ ให้ดึงเดือนจาก createdTime (ถ้าปีใน createdTime สอดคล้องกับปีการศึกษา)
            created_time = file_meta.get("createdTime", "")
            if created_time and len(created_time) >= 10:
                try:
                    c_year = int(created_time[:4])
                    # ป้องกันการเอา createdTime ปีปัจจุบันมาเขียนทับโฟลเดอร์ในอดีต (Google Drive Upload Pollution Guard)
                    if c_year in (ce_year, ce_year + 1):
                        c_month = int(created_time[5:7])
                        c_day = int(created_time[8:10])
                        if 1 <= c_month <= 12 and 1 <= c_day <= 31:
                            return f"{c_year:04d}-{c_month:02d}-{c_day:02d}"
                except Exception:
                    pass
            return f"{ce_year:04d}-08-15"

        # 5. Fallback: ใช้วันที่ createdTime จาก Google Drive (Priority 5)
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
        known_root_names = {"Unknown Folder", "ภาพกิจกรรม 2569", "ภาพกิจกรรม 2568", "ภาพกิจกรรม 2567", "ภาพกิจกรรม 2566", "ภาพกิจกรรม 2565", "ภาพกิจกรรม 2563"}
        known_root_ids = set()
        try:
            from db_manager import DatabaseManager
            _db = DatabaseManager()
            for r in _db.get_root_year_folders(active_only=False):
                if r.get("name"):
                    known_root_names.add(r["name"].strip())
                if r.get("id"):
                    known_root_ids.add(r["id"].strip())
        except Exception as e:
            logger.debug(f"Could not load dynamic root folders in gdrive_sync: {e}")
        
        # สกัดปี พ.ศ. เริ่มต้นจากชื่อโฟลเดอร์หลัก (v6.45)
        import re
        m_root_yr = re.search(r'25[3-7]\d', root_folder_name)
        initial_year = m_root_yr.group(0) if m_root_yr else ""

        # ฟังก์ชันค้นหาไฟล์ในโฟลเดอร์ recursively พร้อมสืบทอดปีการศึกษา (v6.45)
        def walk_folder(curr_folder_id, curr_event_name, parent_year=initial_year):
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

            # ตรวจสอบปี พ.ศ. ของโฟลเดอร์ปัจจุบันเพื่อสืบทอดไปยังการสกัดวันที่ (v6.45)
            m_curr_yr = re.search(r'25[3-7]\d', curr_event_name)
            if not m_curr_yr:
                m_short_f = re.search(r'(?:ปี|พ\.?ศ\.?|\s|^|[^\d])(6[0-9])(?!\d)', curr_event_name)
                effective_year = ("25" + m_short_f.group(1)) if m_short_f else parent_year
            else:
                effective_year = m_curr_yr.group(0)

            # เก็บไฟล์รูปภาพพร้อมวันที่อัจฉริยะ (Smart Photo Date v6.45)
            for file in files:
                date_str = self.parse_smart_photo_date(folder_name=curr_event_name, file_name=file.get("name", ""), file_meta=file, academic_year=effective_year)
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
                # แต่หากเป็นโฟลเดอร์ย่อยลงไปอีก (Subfolder) ให้คงชื่อกิจกรรมหลักเดิมไว้เสมอ (v6.24/v6.27 Dynamic Root Check)
                is_root_or_year = (
                    "ภาพกิจกรรม" in curr_event_name
                    or curr_event_name in known_root_names
                    or curr_folder_id in known_root_ids
                )
                if is_root_or_year:
                    next_event_name = subdir_name
                else:
                    next_event_name = curr_event_name

                # Anti-Generic Guard (v6.32): หาก next_event_name เป็นคำ Generic และ curr_event_name ไม่ใช่ Root Year ให้คงชื่อกิจกรรมหลักเดิมไว้
                if is_generic_folder_name(next_event_name) and not is_root_or_year:
                    next_event_name = curr_event_name

                walk_folder(subdir_id, next_event_name, parent_year=effective_year)

        walk_folder(folder_id, root_folder_name, parent_year=initial_year)
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
        สร้างข้อมูลดัชนี JSON แบบ Sharded Architecture พร้อม Dual-Write (v6.30 / v6.38):
        1. staff_index.json (บุคลากรปัจจุบัน ~15-30 KB - v6.38)
        2. former_staff_index.json (อดีตบุคลากร/ย้าย/เกษียณ - v6.38)
        3. student_index_active.json (นักเรียนปัจจุบัน ~120 KB)
        4. student_index_alumni.json (ศิษย์เก่า)
        5. photo_index_YYYY.json (แยกรายปีการศึกษา เช่น 2569, 2568, 2567, 2566...)
        6. photo_index_archive.json (รูปภาพปีก่อนหน้าและรูปที่ไม่มีปี)
        7. photo_manifest.json (สารบัญระบุรายการปีและชื่อไฟล์สำหรับ Lazy Loading)
        8. Dual-Write Legacy: student_index.json, photo_index.json, person_index.json
        9. บีบอัดด้วย Compact JSON (separators=(',', ':')) ลดขนาดลง 15-20%
        อัปโหลดทับ/สร้างในโฟลเดอร์ที่แอดมินกำหนด (json_folder_id)
        """
        if not self.connected or not self.drive_service:
            logger.error("Google Drive service not connected.")
            return False

        if not json_folder_id:
            logger.warning("JSON folder ID is empty. Skipping Drive JSON index update.")
            return False

        try:
            from db_manager import DatabaseManager
            db = DatabaseManager()

            # 🌟 ดึงข้อมูลแบบ Sharded เต็มรูปแบบ
            sharded_data = db.get_sync_data_sharded()
            if not sharded_data:
                logger.warning("Could not extract sharded sync data from database.")
                return False

            active_students = sharded_data["active_students"]
            alumni_students = sharded_data["alumni_students"]
            active_staff = sharded_data.get("active_staff", sharded_data.get("teachers", {}))
            former_staff = sharded_data.get("former_staff", {})
            teachers = sharded_data.get("teachers", active_staff)
            photos_by_shard = sharded_data["photos_by_shard"]
            manifest = sharded_data["manifest"]
            legacy_photos = sharded_data["photos"]

            # โครงสร้างสำหรับ Legacy student_index.json (Dual-Write)
            # student_name: [photo_ids...] และเพิ่ม alias สำหรับ student_id
            legacy_student_index = {}
            for s_name, s_info in active_students.items():
                p_list = s_info["photos"]
                legacy_student_index[s_name] = p_list
                s_id = s_info.get("student_id")
                if s_id and s_id not in legacy_student_index:
                    legacy_student_index[s_id] = p_list

            for s_name, s_info in alumni_students.items():
                p_list = s_info["photos"]
                if s_name not in legacy_student_index:
                    legacy_student_index[s_name] = p_list
                s_id = s_info.get("student_id")
                if s_id and s_id not in legacy_student_index:
                    legacy_student_index[s_id] = p_list

            # โครงสร้างสำหรับ Legacy photo_index.json (Dual-Write)
            legacy_photo_index = {}
            for item in legacy_photos:
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
                legacy_photo_index[photo_id] = entry

            # จัดเตรียม Sharded Photo Indexes (แปลง drive_link ให้เป็น Web View URL)
            formatted_shards = {}
            for shard_key, shard_dict in photos_by_shard.items():
                formatted_shard = {}
                for pid, item in shard_dict.items():
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
                    formatted_shard[pid] = entry
                formatted_shards[shard_key] = formatted_shard

            # Pre-fetch existing file IDs in json_folder_id (1 Single API Call แทนที่จะยิง 10 ครั้ง ลด Roundtrip 50%)
            existing_files_map = {}
            try:
                folder_query = f"'{json_folder_id}' in parents and trashed = false"
                list_res = self.drive_service.files().list(
                    q=folder_query, fields="files(id, name)", pageSize=100
                ).execute()
                for f in list_res.get("files", []):
                    existing_files_map[f["name"]] = f["id"]
                logger.info(f"[GDRIVE JSON] Pre-fetched {len(existing_files_map)} existing files from target folder cache.")
            except Exception as cache_err:
                logger.warning(f"[GDRIVE JSON] Could not pre-fetch folder files list: {cache_err}")

            # ฟังก์ชันช่วยอัปโหลดทับไฟล์เดิมบน Google Drive พร้อมระบบ Self-Healing และ Auto-Retry 3 ครั้ง (v6.35)
            def upload_overwrite_json(file_name, data_dict, use_compact=True):
                if use_compact:
                    json_content = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
                else:
                    json_content = json.dumps(data_dict, ensure_ascii=False, indent=2)
                
                content_bytes = json_content.encode('utf-8')
                content_size_mb = len(content_bytes) / (1024 * 1024)
                
                # Adaptive Resumable: ไฟล์ < 5MB ใช้ Simple Multipart Upload (resumable=False)
                # เพื่อลด HTTP Roundtrips และป้องกัน Timeout จากการเจรจา Resumable Session (v6.35)
                is_resumable = (content_size_mb >= 5.0)

                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    try:
                        # สร้าง media stream ใหม่ในแต่ละรอบที่ retry เพื่อให้ pointer อยู่ที่จุดเริ่มต้นเสมอ
                        media = MediaIoBaseUpload(
                            io.BytesIO(content_bytes),
                            mimetype='application/json',
                            resumable=is_resumable
                        )

                        # ค้นหา ID ของไฟล์เดิมจาก Cache ก่อน
                        file_id = existing_files_map.get(file_name)
                        if not file_id:
                            query = f"'{json_folder_id}' in parents and name = '{file_name}' and trashed = false"
                            search_results = self.drive_service.files().list(q=query, fields="files(id)").execute()
                            files = search_results.get("files", [])
                            if files:
                                file_id = files[0]['id']
                                existing_files_map[file_name] = file_id

                        if file_id:
                            logger.info(f"[GDRIVE JSON] Updating existing file '{file_name}' (ID: {file_id}, Size: {content_size_mb:.2f} MB, Resumable: {is_resumable})...")
                            self.drive_service.files().update(
                                fileId=file_id,
                                media_body=media
                            ).execute()
                            logger.info(f"[GDRIVE JSON] Successfully updated '{file_name}' on Google Drive.")
                            return True
                        else:
                            # ป้องกัน 403 Service Account Quota: ขอให้ Web App ช่วยสร้างไฟล์เปล่าเป็นของ sawiphoto@sawi.ac.th ก่อน
                            logger.info(f"[GDRIVE JSON] File '{file_name}' not found in folder. Requesting placeholder creation via Web App...")
                            try:
                                import requests
                                app_url = 'https://script.google.com/macros/s/AKfycbyw1clju8DOf_Oqm8OZ-nBg9TLuAu-slOAkQZB1K3YzoaTQXrIlmb-_FLr08ikg84FV/exec'
                                r = requests.get(app_url, params={'action': 'createPlaceholders', 'secret': 'sawi_sharding_2026', 'files': file_name}, timeout=30)
                                if r.status_code == 200 and r.json().get('ok'):
                                    search_results = self.drive_service.files().list(q=f"'{json_folder_id}' in parents and name = '{file_name}' and trashed = false", fields="files(id)").execute()
                                    files = search_results.get("files", [])
                                    if files:
                                        file_id = files[0]['id']
                                        existing_files_map[file_name] = file_id
                            except Exception as ep:
                                logger.warning(f"Could not request placeholder creation via Web App: {ep}")

                            if file_id:
                                logger.info(f"[GDRIVE JSON] Updating newly created placeholder '{file_name}' (ID: {file_id}, Size: {content_size_mb:.2f} MB)...")
                                self.drive_service.files().update(
                                    fileId=file_id,
                                    media_body=media
                                ).execute()
                                logger.info(f"[GDRIVE JSON] Successfully updated '{file_name}' on Google Drive.")
                                return True
                            else:
                                logger.info(f"[GDRIVE JSON] Creating new file '{file_name}' (Size: {content_size_mb:.2f} MB) in target folder '{json_folder_id}'...")
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
                                new_id = new_file.get('id')
                                if new_id:
                                    existing_files_map[file_name] = new_id
                                logger.info(f"[GDRIVE JSON] Created new '{file_name}' (ID: {new_id}) on Drive.")
                                return True

                    except (socket.timeout, TimeoutError, ssl.SSLEOFError, ssl.SSLError, ConnectionError, OSError, HttpError, ResumableUploadError) as net_err:
                        if attempt < max_retries:
                            wait_time = 2 * attempt
                            logger.warning(
                                f"[GDRIVE JSON] Network/API glitch uploading '{file_name}' (Attempt {attempt}/{max_retries}): {net_err}. "
                                f"Healing connection pool and retrying in {wait_time}s..."
                            )
                            self.reconnect_drive_service()
                            time.sleep(wait_time)
                        else:
                            logger.error(f"[GDRIVE JSON] ❌ Failed to upload '{file_name}' after {max_retries} attempts: {net_err}")
                            return False
                    except Exception as fatal_err:
                        logger.error(f"[GDRIVE JSON] Unexpected error uploading '{file_name}': {fatal_err}", exc_info=True)
                        return False
                return False

            # พิจารณาการอัปโหลดตาม scan_mode
            upload_teachers = (scan_mode in ["all", "teachers", "selected_teachers"])
            upload_students = (scan_mode in ["all", "students", "selected_students"])
            sync_results = {}

            # 1. ดัชนีครู/บุคลากร (staff_index.json & former_staff_index.json + Dual-Write person_index.json - v6.38)
            if upload_teachers:
                # Sharded Staff: ครูปัจจุบัน
                sync_results["staff_index.json"] = upload_overwrite_json("staff_index.json", active_staff, use_compact=True)
                # Sharded Former Staff: อดีตครู/ย้าย/เกษียณ
                sync_results["former_staff_index.json"] = upload_overwrite_json("former_staff_index.json", former_staff, use_compact=True)
                # Legacy Person Index (Dual-Write Compatibility)
                sync_results["person_index.json"] = upload_overwrite_json("person_index.json", teachers, use_compact=True)

            # 2. ดัชนีนักเรียนแบบ Sharded และ Legacy
            if upload_students:
                # Sharded Students
                sync_results["student_index_active.json"] = upload_overwrite_json("student_index_active.json", active_students, use_compact=True)
                sync_results["student_index_alumni.json"] = upload_overwrite_json("student_index_alumni.json", alumni_students, use_compact=True)
                # Legacy Student Index (Dual-Write)
                sync_results["student_index.json"] = upload_overwrite_json("student_index.json", legacy_student_index, use_compact=True)

            # 3. ดัชนีรูปภาพแบบ Sharded และ Manifest
            if upload_teachers or upload_students:
                # Photo Manifest
                sync_results["photo_manifest.json"] = upload_overwrite_json("photo_manifest.json", manifest, use_compact=False)
                
                # Sharded Photo Files
                year_file_map = manifest["year_file_map"]
                for shard_key, shard_data in formatted_shards.items():
                    shard_filename = year_file_map.get(shard_key, f"photo_index_{shard_key}.json")
                    sync_results[shard_filename] = upload_overwrite_json(shard_filename, shard_data, use_compact=True)

                # Legacy Photo Index (Dual-Write)
                sync_results["photo_index.json"] = upload_overwrite_json("photo_index.json", legacy_photo_index, use_compact=True)

                # 4. ดัชนีภาพกิจกรรมในอดีต (2562-25xx) แบบข้อมูลทั่วไป (v6.70)
                try:
                    archive_crowdsource_data = db.get_archive_crowdsource_data(academic_year="25xx", sync_manager=self)
                    arc_photos = archive_crowdsource_data.get("photos", {}) if archive_crowdsource_data else {}
                    arc_total_photos = len(arc_photos) if isinstance(arc_photos, (dict, list)) else 0

                    if archive_crowdsource_data and arc_total_photos > 0:
                        sync_results["archive_crowdsource_index.json"] = upload_overwrite_json(
                            "archive_crowdsource_index.json", archive_crowdsource_data, use_compact=True
                        )
                        manifest["archive_crowdsource_file"] = "archive_crowdsource_index.json"
                        manifest["archive_crowdsource_photos"] = arc_total_photos
                        # ตัดการนับจำนวนใบหน้าออกทั้งหมดตามความต้องการของผู้ใช้ (v6.70)
                        manifest.pop("archive_crowdsource_faces", None)
                        # อัปเดต photo_manifest.json ให้มีคีย์ของไฟล์ภาพในอดีตนี้ด้วย
                        sync_results["photo_manifest.json"] = upload_overwrite_json("photo_manifest.json", manifest, use_compact=False)
                        logger.info(f"[GDRIVE JSON] Synced archive_crowdsource_index.json ({arc_total_photos} photos).")
                except Exception as arc_err:
                    logger.warning(f"[GDRIVE JSON] Could not sync archive_crowdsource_index.json: {arc_err}")

            failed_uploads = [fn for fn, ok in sync_results.items() if not ok]
            if failed_uploads:
                logger.warning(f"[GDRIVE JSON] Warning: {len(failed_uploads)}/{len(sync_results)} files encountered issues: {failed_uploads}")
            else:
                logger.info(f"[GDRIVE JSON] All {len(sync_results)} Sharded & Dual-Write JSON Indexes successfully synchronized.")
            return len(failed_uploads) == 0
        except Exception as e:
            logger.error(f"[GDRIVE JSON] Error updating JSON search indexes: {e}", exc_info=True)
            return False

    def sync_archive_crowdsource_only(self, json_folder_id="1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L", db=None):
        """
        ซิงค์เฉพาะไฟล์ archive_crowdsource_index.json และอัปเดต photo_manifest.json (v6.49)
        สำหรับปุ่ม Manual Sync ในหน้าตั้งค่าโฟลเดอร์ หรือ Task 1
        """
        if not self.connected or not self.drive_service:
            logger.info("[GDRIVE JSON] Drive service not connected. Attempting auto-connect (v6.51)...")
            if not self.connect():
                logger.error("[GDRIVE JSON] Google Drive service auto-connect failed.")
                return False, "ไม่ได้เชื่อมต่อ Google Drive Service (เชื่อมต่อไม่สำเร็จ)"

        if not json_folder_id:
            logger.warning("[GDRIVE JSON] JSON folder ID is empty.")
            return False, "ยังไม่ได้ระบุโฟลเดอร์ Google Drive สำหรับเก็บ JSON"

        try:
            if db is None:
                from db_manager import DatabaseManager
                db = DatabaseManager()

            archive_data = db.get_archive_crowdsource_data(academic_year="25xx", sync_manager=self)
            photos_map = archive_data.get("photos", {}) if archive_data else {}
            total_photos = len(photos_map) if isinstance(photos_map, (dict, list)) else 0
            if not archive_data or total_photos == 0:
                return False, "ไม่พบข้อมูลรูปภาพในโฟลเดอร์ภาพกิจกรรม 2562-25xx ในอดีต"

            # Pre-fetch existing files map
            existing_files_map = {}
            try:
                folder_query = f"'{json_folder_id}' in parents and trashed = false"
                list_res = self.drive_service.files().list(
                    q=folder_query, fields="files(id, name)", pageSize=100
                ).execute()
                for f in list_res.get("files", []):
                    existing_files_map[f["name"]] = f["id"]
            except Exception as cache_err:
                logger.warning(f"[GDRIVE JSON] Could not pre-fetch folder files list: {cache_err}")

            def upload_overwrite_json(file_name, data_dict, use_compact=True):
                if use_compact:
                    json_content = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
                else:
                    json_content = json.dumps(data_dict, ensure_ascii=False, indent=2)
                content_bytes = json_content.encode('utf-8')
                media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype='application/json', resumable=False)
                file_id = existing_files_map.get(file_name)
                if not file_id:
                    try:
                        import requests
                        app_url = 'https://script.google.com/macros/s/AKfycbyw1clju8DOf_Oqm8OZ-nBg9TLuAu-slOAkQZB1K3YzoaTQXrIlmb-_FLr08ikg84FV/exec'
                        r = requests.get(app_url, params={'action': 'createPlaceholders', 'secret': 'sawi_sharding_2026', 'files': file_name}, timeout=30)
                        if r.status_code == 200 and r.json().get('ok'):
                            search_results = self.drive_service.files().list(q=f"'{json_folder_id}' in parents and name = '{file_name}' and trashed = false", fields="files(id)").execute()
                            files = search_results.get("files", [])
                            if files:
                                file_id = files[0]['id']
                                existing_files_map[file_name] = file_id
                    except Exception as ep:
                        logger.warning(f"[GDRIVE JSON] Could not request placeholder creation via Web App: {ep}")

                if file_id:
                    self.drive_service.files().update(fileId=file_id, media_body=media).execute()
                    return True
                else:
                    file_metadata = {'name': file_name, 'mimeType': 'application/json', 'parents': [json_folder_id]}
                    new_file = self.drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    if new_file.get('id'):
                        existing_files_map[file_name] = new_file.get('id')
                    return True

            ok1 = upload_overwrite_json("archive_crowdsource_index.json", archive_data, use_compact=True)

            # อัปเดต photo_manifest.json
            try:
                manifest_file_id = existing_files_map.get("photo_manifest.json")
                manifest = {}
                if manifest_file_id:
                    content = self.drive_service.files().get_media(fileId=manifest_file_id).execute()
                    manifest = json.loads(content.decode('utf-8'))
                manifest["archive_crowdsource_file"] = "archive_crowdsource_index.json"
                manifest["archive_crowdsource_photos"] = total_photos
                manifest.pop("archive_crowdsource_faces", None)
                manifest["updated_at"] = datetime.now().isoformat()
                upload_overwrite_json("photo_manifest.json", manifest, use_compact=False)
            except Exception as m_err:
                logger.warning(f"[GDRIVE JSON] Could not update photo_manifest.json: {m_err}")

            if ok1:
                return True, f"อัปโหลดสำเร็จ {total_photos} รูป"
            return False, "อัปโหลด archive_crowdsource_index.json ไม่สำเร็จ"
        except Exception as e:
            logger.error(f"[GDRIVE JSON] Error in sync_archive_crowdsource_only: {e}", exc_info=True)
            return False, str(e)

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

    def sync_staff_reference_photos_to_drive(self, staff_list=None, root_folder_id="1m45wZdZebU0jDrhCYKp3mu18_rTuTzwI", progress_callback=None):
        """
        ซิงก์รูปภาพอ้างอิงใบหน้าบุคลากรจาก SQLite ขึ้น Google Drive (v6.41)
        - โฟลเดอร์เป้าหมายหลัก: root_folder_id (บุคลากรโรงเรียน)
        - บุคลากรปัจจุบัน (Active): เข้าโฟลเดอร์กลุ่มสาระใต้ Root
        - อดีตบุคลากร (Inactive): เข้าโฟลเดอร์กลุ่มสาระย่อยใต้ 'อดีตบุคลากร'
        - หากมีไฟล์อยู่แล้วในกลุ่มสาระและสถานะที่ถูกต้อง -> ข้าม (Skip)
        - หากตรวจพบว่าไฟล์อยู่ผิดกลุ่มสาระ หรือสถานะเปลี่ยนไป -> ย้ายไฟล์ (addParents/removeParents) และเปลี่ยนชื่อให้ตรง
        - หากยังไม่มีไฟล์บน Drive -> อัปโหลดไฟล์จากเครื่องขึ้นไป
        - รองรับ In-Memory Caching และ Batch Queries ให้ทำงานได้เร็วที่สุด ไม่สะดุด
        """
        if not self.connected or not self.drive_service:
            if not self.connect():
                return {
                    "success": False,
                    "error": "ไม่สามารถเชื่อมต่อ Google Drive API ได้ (กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือ service account)",
                    "total_staff": 0,
                    "skipped_count": 0,
                    "uploaded_count": 0,
                    "relocated_count": 0,
                    "failed_count": 0,
                    "skipped": [],
                    "uploaded": [],
                    "relocated": [],
                    "failed": []
                }

        from db_manager import clean_department_name
        import re

        def normalize_teacher_name(n):
            if not n:
                return ""
            n = os.path.splitext(str(n))[0]
            for pre in ["ว่าที่ร้อยตรีหญิง", "ว่าที่ร้อยตรี", "ว่าที่ ร.ต.หญิง", "ว่าที่ ร.ต.", 
                        "นางสาว", "น.ส.", "นาย", "นาง", "ดร.", "คุณครู", "ครู", "อาจารย์", "อ.", 
                        "Mr.", "Mrs.", "Ms.", "Miss"]:
                if n.startswith(pre):
                    n = n[len(pre):]
                    break
            return re.sub(r'[\s\.\-_]+', '', n).lower()

        if staff_list is None:
            from db_manager import DatabaseManager
            db = DatabaseManager()
            staff_list = db.get_all_teachers()

        report = {
            "success": True,
            "total_staff": len(staff_list),
            "skipped_count": 0,
            "uploaded_count": 0,
            "relocated_count": 0,
            "failed_count": 0,
            "skipped": [],
            "uploaded": [],
            "relocated": [],
            "failed": []
        }

        if progress_callback:
            progress_callback(0, len(staff_list), "กำลังสำรวจโครงสร้างโฟลเดอร์บน Google Drive...")

        # 1. สำรวจ Root Folders
        root_query = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        root_res = self._execute_with_retry(lambda: self.drive_service.files().list(
            q=root_query, fields="files(id, name)", pageSize=100
        ).execute())
        root_folders = root_res.get("files", []) if root_res else []

        former_root_id = None
        active_dept_folders = {}
        for f in root_folders:
            fname = clean_department_name(f['name'])
            if f['name'] == 'อดีตบุคลากร' or fname == 'อดีตบุคลากร':
                former_root_id = f['id']
            else:
                active_dept_folders[fname] = f['id']

        if not former_root_id:
            create_former_body = {
                'name': 'อดีตบุคลากร',
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [root_folder_id]
            }
            former_created = self._execute_with_retry(lambda: self.drive_service.files().create(
                body=create_former_body, fields='id, name'
            ).execute())
            former_root_id = former_created.get('id')
            logger.info(f"Created 'อดีตบุคลากร' folder on Drive: {former_root_id}")

        # 2. สำรวจโฟลเดอร์ย่อยใน อดีตบุคลากร
        former_query = f"'{former_root_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        former_res = self._execute_with_retry(lambda: self.drive_service.files().list(
            q=former_query, fields="files(id, name)", pageSize=100
        ).execute())
        former_subfolders = former_res.get("files", []) if former_res else []
        former_dept_folders = {}
        for f in former_subfolders:
            fname = clean_department_name(f['name'])
            former_dept_folders[fname] = f['id']

        def get_or_create_target_folder(dept_name, is_former):
            dept_clean = clean_department_name(dept_name) or "อื่นๆ"
            target_map = former_dept_folders if is_former else active_dept_folders
            target_parent_id = former_root_id if is_former else root_folder_id

            if dept_clean in target_map:
                return target_map[dept_clean]

            folder_body = {
                'name': dept_clean,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [target_parent_id]
            }
            created_folder = self._execute_with_retry(lambda: self.drive_service.files().create(
                body=folder_body, fields='id, name'
            ).execute())
            new_fid = created_folder.get('id')
            target_map[dept_clean] = new_fid
            logger.info(f"Created department folder on Drive: {dept_clean} (ID: {new_fid}, is_former={is_former})")
            return new_fid

        # 3. สร้างแคตตาล็อกไฟล์เดิมทั้งหมดบน Drive แบบ In-Memory Catalog
        if progress_callback:
            progress_callback(0, len(staff_list), "กำลังสร้างดัชนีรูปภาพบุคลากรทั้งหมดบน Drive...")

        all_monitored_folders = []
        for dname, fid in active_dept_folders.items():
            all_monitored_folders.append((fid, dname, False))
        for dname, fid in former_dept_folders.items():
            all_monitored_folders.append((fid, dname, True))

        drive_catalog = {}
        for fid, dname, is_f in all_monitored_folders:
            q_files = f"'{fid}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
            files_res = self._execute_with_retry(lambda: self.drive_service.files().list(
                q=q_files, fields="files(id, name, mimeType)", pageSize=200
            ).execute())
            for fl in (files_res.get('files', []) if files_res else []):
                cleaned_key = normalize_teacher_name(fl['name'])
                if cleaned_key:
                    drive_catalog[cleaned_key] = {
                        'file_id': fl['id'],
                        'file_name': fl['name'],
                        'parent_id': fid,
                        'dept_name': dname,
                        'is_former': is_f
                    }

        logger.info(f"[GDRIVE_SYNC] Indexed {len(drive_catalog)} existing teacher files on Google Drive.")

        # 4. ประมวลผลบุคลากรทีละราย
        for idx, teacher in enumerate(staff_list):
            s_id = teacher.get('id')
            s_name = str(teacher.get('name', '')).strip()
            s_dept = clean_department_name(teacher.get('department') or 'อื่นๆ')
            s_status = str(teacher.get('status', 'active')).lower()
            is_former = (s_status == 'inactive')
            orig_path = teacher.get('original_image_path', '')
            crop_path = teacher.get('cropped_image_path', '')
            avatar_path = teacher.get('avatar_path', '')
            # เลือกไฟล์ภาพต้นฉบับฉบับเต็ม (Full Uncropped Photo) เป็นอันดับแรกเสมอ หากไม่มีจึง fallback ไปภาพ crop (v6.42)
            upload_source_path = orig_path if (orig_path and os.path.exists(orig_path)) else avatar_path
            if not upload_source_path or not os.path.exists(upload_source_path):
                upload_source_path = crop_path

            if progress_callback:
                progress_callback(idx + 1, len(staff_list), f"กำลังประมวลผล: {s_name} ({idx + 1}/{len(staff_list)})")

            target_folder_id = get_or_create_target_folder(s_dept, is_former)
            norm_name = normalize_teacher_name(s_name)

            if norm_name in drive_catalog:
                matched_item = drive_catalog[norm_name]
                file_id = matched_item['file_id']
                current_parent_id = matched_item['parent_id']

                if current_parent_id == target_folder_id:
                    # ตรงทั้งสถานะและกลุ่มสาระ -> ข้าม (Skip)
                    report['skipped'].append({
                        'id': s_id,
                        'name': s_name,
                        'department': s_dept,
                        'status': s_status,
                        'file_name': matched_item['file_name']
                    })
                else:
                    # อยู่ผิดกลุ่มสาระ หรือสถานะเปลี่ยนไป -> ย้ายไฟล์ (addParents/removeParents)
                    old_dept_name = matched_item['dept_name']
                    old_is_former = matched_item['is_former']
                    try:
                        self._execute_with_retry(lambda: self.drive_service.files().update(
                            fileId=file_id,
                            addParents=target_folder_id,
                            removeParents=current_parent_id,
                            fields='id, parents'
                        ).execute())

                        ext = os.path.splitext(matched_item['file_name'])[1] or '.png'
                        expected_file_name = f"{s_name}{ext}"
                        if matched_item['file_name'] != expected_file_name:
                            self._execute_with_retry(lambda: self.drive_service.files().update(
                                fileId=file_id,
                                body={'name': expected_file_name},
                                fields='id, name'
                            ).execute())
                            matched_item['file_name'] = expected_file_name

                        matched_item['parent_id'] = target_folder_id
                        matched_item['dept_name'] = s_dept
                        matched_item['is_former'] = is_former

                        report['relocated'].append({
                            'id': s_id,
                            'name': s_name,
                            'from_dept': old_dept_name,
                            'to_dept': s_dept,
                            'from_status': 'inactive' if old_is_former else 'active',
                            'to_status': s_status,
                            'file_name': matched_item['file_name'],
                            'file_id': file_id
                        })
                        logger.info(f"[GDRIVE_SYNC] Relocated '{s_name}' from '{old_dept_name}' to '{s_dept}' (ID: {file_id})")
                    except Exception as move_err:
                        logger.error(f"[GDRIVE_SYNC] Failed to relocate '{s_name}': {move_err}")
                        report['failed'].append({
                            'id': s_id,
                            'name': s_name,
                            'department': s_dept,
                            'reason': f"ย้ายไฟล์ไม่สำเร็จ: {move_err}"
                        })
            else:
                # ยังไม่มีไฟล์บน Drive -> อัปโหลดไฟล์จากเครื่อง (ภาพ original ฉบับเต็ม)
                if not upload_source_path or not os.path.exists(upload_source_path):
                    report['failed'].append({
                        'id': s_id,
                        'name': s_name,
                        'department': s_dept,
                        'reason': f"ไม่พบไฟล์รูปภาพในเครื่อง ({upload_source_path})"
                    })
                    continue

                try:
                    ext = os.path.splitext(upload_source_path)[1] or '.jpg'
                    upload_file_name = f"{s_name}{ext}"
                    mime_type, _ = mimetypes.guess_type(upload_source_path)
                    if not mime_type:
                        mime_type = "image/png" if ext.lower() == '.png' else "image/jpeg"

                    new_fid = None
                    # 1. อัปโหลดผ่าน Google Apps Script Web App (สิทธิ์ sawiphoto@sawi.ac.th เพื่อเลี่ยง 403 Service Account Quota)
                    try:
                        import base64
                        import requests
                        with open(upload_source_path, 'rb') as af:
                            b64_content = base64.b64encode(af.read()).decode('utf-8')

                        app_url = 'https://script.google.com/macros/s/AKfycbyw1clju8DOf_Oqm8OZ-nBg9TLuAu-slOAkQZB1K3YzoaTQXrIlmb-_FLr08ikg84FV/exec'
                        payload = {
                            'action': 'uploadFile',
                            'secret': 'sawi_sharding_2026',
                            'folderId': target_folder_id,
                            'fileName': upload_file_name,
                            'mimeType': mime_type,
                            'base64Data': b64_content
                        }
                        r = requests.post(app_url, json=payload, timeout=60)
                        if r.status_code == 200 and r.json().get('ok'):
                            new_fid = r.json().get('fileId')
                    except Exception as app_ex:
                        logger.warning(f"[GDRIVE_SYNC] Web App upload fallback to Drive API: {app_ex}")

                    # 2. ถ้า Web App ไม่สำเร็จ ให้ Fallback ผ่าน Drive API
                    if not new_fid:
                        media = MediaFileUpload(avatar_path, mimetype=mime_type, resumable=False)
                        upload_body = {
                            'name': upload_file_name,
                            'parents': [target_folder_id]
                        }
                        uploaded_file = self._execute_with_retry(lambda: self.drive_service.files().create(
                            body=upload_body,
                            media_body=media,
                            fields='id, name'
                        ).execute())
                        new_fid = uploaded_file.get('id') if uploaded_file else ""

                    if not new_fid:
                        raise RuntimeError("ไม่ได้รับ File ID จาก Google Drive")

                    drive_catalog[norm_name] = {
                        'file_id': new_fid,
                        'file_name': upload_file_name,
                        'parent_id': target_folder_id,
                        'dept_name': s_dept,
                        'is_former': is_former
                    }

                    report['uploaded'].append({
                        'id': s_id,
                        'name': s_name,
                        'department': s_dept,
                        'status': s_status,
                        'file_name': upload_file_name,
                        'file_id': new_fid
                    })
                    logger.info(f"[GDRIVE_SYNC] Uploaded '{s_name}' to '{s_dept}' (File ID: {new_fid})")
                except Exception as up_err:
                    logger.error(f"[GDRIVE_SYNC] Failed to upload '{s_name}': {up_err}")
                    report['failed'].append({
                        'id': s_id,
                        'name': s_name,
                        'department': s_dept,
                        'reason': f"อัปโหลดไม่สำเร็จ: {up_err}"
                    })

        report['skipped_count'] = len(report['skipped'])
        report['uploaded_count'] = len(report['uploaded'])
        report['relocated_count'] = len(report['relocated'])
        report['failed_count'] = len(report['failed'])

        logger.info(f"[GDRIVE_SYNC] Completed personnel photo sync: {report['uploaded_count']} uploaded, "
                    f"{report['relocated_count']} relocated, {report['skipped_count']} skipped, {report['failed_count']} failed.")
        return report

