import os
import json
import logging
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread

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

    def connect(self, spreadsheet_id=None):
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
                return self.verify_spreadsheet(spreadsheet_id)
            return True
        except Exception as e:
            logger.error(f"Error connecting to Google Services: {e}", exc_info=True)
            return False

    def verify_spreadsheet(self, spreadsheet_id):
        """ตรวจสอบว่าเชื่อมต่อและจัดการ Spreadsheet ID ที่ระบุได้จริงหรือไม่ และเตรียมแผ่นงานในชีท"""
        if not self.connected:
            return False
            
        try:
            sheet = self.gspread_client.open_by_key(spreadsheet_id)
            self.spreadsheet_id = spreadsheet_id
            logger.info(f"Verified Google Sheet access: '{sheet.title}'")
            
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

    def fetch_drive_folder_images_recursive(self, folder_id):
        """
        ดึงไฟล์รูปภาพจาก Google Drive แบบย้อนกลับ (Recursive)
        คืนค่า: รายการของ dict ที่มีข้อมูล {'file_name', 'file_id', 'drive_link', 'event'}
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
            
            # 1. ค้นหาโฟลเดอร์ย่อยทั้งหมด
            query_dirs = f"'{curr_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            dirs_results = self.drive_service.files().list(
                q=query_dirs, fields="files(id, name)"
            ).execute()
            subdirs = dirs_results.get("files", [])
            
            # 2. ค้นหาไฟล์ทั้งหมดในโฟลเดอร์นี้ แล้วนำมากรองประเภทรูปภาพในระดับแอปพลิเคชัน
            query_files = f"'{curr_folder_id}' in parents and trashed = false"
            files_results = self.drive_service.files().list(
                q=query_files, fields="files(id, name, mimeType, webViewLink, createdTime)", pageSize=200
            ).execute()
            all_files = files_results.get("files", [])
            
            # กรองเฉพาะไฟล์รูปภาพ (MimeType ขึ้นต้นด้วย 'image/' หรือนามสกุลไฟล์ลงท้ายด้วย .cr2) เพื่อความเสถียรและหลีกเลี่ยง API 400 Error
            files = [f for f in all_files if f.get("mimeType", "").startswith("image/") or f.get("name", "").lower().endswith(".cr2")]
            
            logger.info(f"Found {len(subdirs)} subfolders and {len(files)} images in folder '{curr_event_name}'")

            # เก็บไฟล์รูปภาพ
            for file in files:
                created_time = file.get("createdTime", "")
                date_str = created_time[:10] if created_time else ""
                all_images.append({
                    "file_name": file.get("name"),
                    "file_id": file.get("id"),
                    "drive_link": file.get("webViewLink"),
                    "event": curr_event_name,
                    "date": date_str
                })
                logger.debug(f"Queued file: {file.get('name')} (date: {date_str}) in event '{curr_event_name}'")

            # เรียกใช้งานแบบ recursive ลงไปในโฟลเดอร์ย่อย
            for subdir in subdirs:
                subdir_id = subdir.get("id")
                subdir_name = subdir.get("name")
                
                # หากโฟลเดอร์เริ่มต้นคือ "ภาพกิจกรรม" โฟลเดอร์ระดับล่างก็ควรชื่อตามโฟลเดอร์นั้น
                # เช่น ภาพกิจกรรม -> 2569 -> วันแม่ (event = วันแม่)
                walk_folder(subdir_id, subdir_name)

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

    def sync_to_google_sheet(self, sync_data):
        """
        อัปเดตข้อมูลขึ้น Google Sheet
        sync_data: ผลลัพธ์จาก db_manager.get_all_sync_data() ที่มีคีย์ {"photos": [...], "faces": [...]}
        """
        if not self.connected or not self.spreadsheet_id:
            logger.error("Google Sheets sync failed: Connection or Spreadsheet ID is missing.")
            return False

        try:
            sheet = self.gspread_client.open_by_key(self.spreadsheet_id)
            
            # 1. เขียนข้อมูลแผ่นงาน photos
            photos_sheet = sheet.worksheet("photos")
            # เคลียร์ค่าเก่ายกเว้นหัวคอลัมน์ (row 1)
            photos_sheet.clear()
            photos_sheet.append_row(["photo_id", "event", "drive_link", "date"])
            
            photo_rows = []
            for item in sync_data["photos"]:
                photo_rows.append([item["photo_id"], item["event"], item["drive_link"], item.get("date", "")])
            
            if photo_rows:
                # เขียนข้อมูลแบบ Bulk ในครั้งเดียว
                photos_sheet.append_rows(photo_rows)
                logger.info(f"Successfully synced {len(photo_rows)} rows to 'photos' worksheet.")

            # 2. เขียนข้อมูลแผ่นงาน faces
            faces_sheet = sheet.worksheet("faces")
            faces_sheet.clear()
            faces_sheet.append_row(["face_id", "person", "photo_id"])
            
            face_rows = []
            for item in sync_data["faces"]:
                face_rows.append([item["face_id"], item["person"], item["photo_id"]])
                
            if face_rows:
                faces_sheet.append_rows(face_rows)
                logger.info(f"Successfully synced {len(face_rows)} rows to 'faces' worksheet.")
                
            return True
        except Exception as e:
            logger.error(f"Error syncing data to Google Sheets: {e}", exc_info=True)
            return False

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

    def update_json_indexes_on_drive(self, sync_data, json_folder_id):
        """
        สร้างข้อมูลดัชนี JSON สองไฟล์ (person_index.json และ photo_index.json) 
        แล้วทำการอัปโหลดทับ (Overwrite) ไฟล์เป้าหมายที่มีอยู่แล้วบน Google Drive ในโฟลเดอร์ที่แอดมินระบุไว้
        """
        if not self.connected or not self.drive_service:
            logger.error("Google Drive service not connected.")
            return False

        if not json_folder_id:
            logger.warning("JSON folder ID is empty. Skipping Drive JSON index update.")
            return False

        try:
            # 1. สร้างโครงสร้างข้อมูลสำหรับ person_index.json
            person_index = {}
            for item in sync_data["faces"]:
                person = item["person"]
                photo_id = item["photo_id"]
                if person not in person_index:
                    person_index[person] = []
                if photo_id not in person_index[person]:
                    person_index[person].append(photo_id)

            # 2. สร้างโครงสร้างข้อมูลสำหรับ photo_index.json
            photo_index = {}
            for item in sync_data["photos"]:
                photo_id = item["photo_id"]
                photo_index[photo_id] = {
                    "event": item["event"],
                    "drive_link": item["drive_link"],
                    "date": item.get("date", "")
                }

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

            # ดำเนินการอัปเดตไฟล์ทั้งสอง
            upload_overwrite_json("person_index.json", person_index)
            upload_overwrite_json("photo_index.json", photo_index)
            return True
        except Exception as e:
            logger.error(f"[GDRIVE JSON] Error updating JSON search indexes: {e}", exc_info=True)
            return False

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

        # รูปแบบ: https://drive.google.com/open?id=FILE_ID
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
            sheet = self.gspread_client.open_by_key(spreadsheet_id)
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

