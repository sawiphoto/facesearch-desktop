import sqlite3
import re
import os
import json
from datetime import datetime
import numpy as np
import logging

logger = logging.getLogger("FaceSearchApp")

# แผนผังนามสกุลไฟล์ภาพดิบกล้องดิจิทัลสากลและยี่ห้อกล้อง (v6.10 Camera RAW Support)
RAW_EXTENSIONS_MAP = {
    '.arw': 'Sony',
    '.sr2': 'Sony',
    '.srf': 'Sony',
    '.cr2': 'Canon',
    '.cr3': 'Canon',
    '.crw': 'Canon',
    '.nef': 'Nikon',
    '.nrw': 'Nikon',
    '.raf': 'Fujifilm',
    '.rw2': 'Panasonic',
    '.raw': 'Panasonic/Leica',
    '.orf': 'Olympus',
    '.dng': 'Adobe DNG / Leica / Pentax',
    '.pef': 'Pentax',
    '.rwl': 'Leica',
    '.3fr': 'Hasselblad',
    '.fff': 'Hasselblad',
    '.x3f': 'Sigma',
    '.iiq': 'Phase One'
}

def get_camera_brand_from_filename(filename):
    """คืนค่าชื่อยี่ห้อกล้องจากนามสกุลไฟล์ RAW หากไม่ใช่ไฟล์ RAW ให้คืนค่า None (v6.10)"""
    if not filename:
        return None
    ext = os.path.splitext(filename)[1].lower()
    return RAW_EXTENSIONS_MAP.get(ext, None)

# รายการหมวดหมู่สังกัดมาตรฐานของโรงเรียนสวีวิทยา (ตัดคำนำหน้า 'กลุ่มสาระ' ออกทั้งหมดตาม v6.34)
SW_DEPARTMENTS = [
    "การงานอาชีพ",
    "คณิตศาสตร์",
    "ภาษาต่างประเทศ",
    "ภาษาไทย",
    "วิทยาศาสตร์และเทคโนโลยี",
    "ศิลปะ",
    "สังคมศึกษาฯ",
    "สุขศึกษาฯ",
    "กิจกรรมแนะแนว",
    "คณะผู้บริหาร",
    "ลูกจ้างชั่วคราว",
    "เจ้าหน้าที่สำนักงาน",
    "อื่นๆ (ระบุเอง)"
]

def clean_department_name(dept_str: str) -> str:
    """ตัดคำนำหน้ากลุ่มสาระฯ ออก ให้เหลือเฉพาะชื่อสังกัดสั้นกระชับ (v6.34) และ Normalize ชื่อสังกัดมาตรฐาน (v6.41)"""
    if not dept_str:
        return ""
    clean = re.sub(r'^(?:กลุ่มสาระฯ|กลุ่มสาระการเรียนรู้|กลุ่มสาระ)\s*', '', str(dept_str).strip())
    if clean == "ผู้บริหาร":
        clean = "คณะผู้บริหาร"
    elif clean == "สังคมศึกษา":
        clean = "สังคมศึกษาฯ"
    return clean

THAI_PREFIXES = [
    r'ว่าที่\s*ร้อยตรี\s*หญิง',
    r'ว่าที่\s*ร้อยตรี',
    r'ว่าที่\s*ร\.ต\.หญิง',
    r'ว่าที่\s*ร\.ต\.',
    r'นางสาว',
    r'น\.ส\.',
    r'นาย',
    r'นาง',
    r'ดร\.',
    r'ผศ\.ดร\.',
    r'รศ\.ดร\.',
    r'ศ\.ดร\.',
    r'ผศ\.',
    r'รศ\.',
    r'ศ\.',
    r'อาจารย์',
    r'อ\.',
    r'คุณครู',
    r'ครู',
    r'Mr\.',
    r'Mrs\.',
    r'Miss',
    r'Ms\.',
]

def parse_teacher_filename(filename):
    """
    แยกวิเคราะห์ชื่อไฟล์ครูออกเป็น (main_name, department, photo_index)
    ตัวอย่าง:
      'นายสมชาย ใจดี วิทยาศาสตร์  1.jpg' -> ('นายสมชาย ใจดี', 'วิทยาศาสตร์', 1)
      'นายสมชาย ใจดี วิทยาศาสตร์  2.jpg' -> ('นายสมชาย ใจดี', 'วิทยาศาสตร์', 2)
      'นางสาวสมหญิง สดใส คณิตศาสตร์ (2).png' -> ('นางสาวสมหญิง สดใส', 'คณิตศาสตร์', 2)
      'นายวิชาญ การงาน ภาษาไทย.jpg' -> ('นายวิชาญ การงาน', 'ภาษาไทย', 1)
      'นายสมศักดิ์ รักดี 1.jpg' -> ('นายสมศักดิ์ รักดี', '', 1)
    """
    base_name = os.path.splitext(os.path.basename(filename))[0].strip()
    photo_index = 1
    idx_match = re.search(r'[\s_\-\(\[\{]+(\d+)[\s\)\]\}]*$', base_name)
    if idx_match:
        try:
            photo_index = int(idx_match.group(1))
            base_name = base_name[:idx_match.start()].strip()
        except Exception:
            photo_index = 1
            
    clean_text = re.sub(r'\s+', ' ', base_name).strip()
    if not clean_text:
        return ("", "", photo_index)
        
    prefix_matched = None
    had_space = False
    remaining_after_prefix = clean_text
    
    for prefix_pat in THAI_PREFIXES:
        match = re.match(r'^(' + prefix_pat + r')(\s*)(.*)$', clean_text, re.IGNORECASE)
        if match:
            prefix_matched = match.group(1).strip()
            had_space = bool(match.group(2))
            remaining_after_prefix = match.group(3).strip()
            break
            
    if prefix_matched:
        tokens = [t for t in remaining_after_prefix.split(' ') if t]
        no_space_prefixes = ('นาย', 'นาง', 'นางสาว', 'น.ส.', 'ครู', 'คุณครู', 'ดร.')
        join_char = "" if (prefix_matched in no_space_prefixes and not had_space) else " "
        
        if len(tokens) == 0:
            main_name = prefix_matched
            department = ""
        elif len(tokens) == 1:
            main_name = f"{prefix_matched}{join_char}{tokens[0]}".strip()
            department = ""
        elif len(tokens) == 2:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = ""
        else:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = " ".join(tokens[2:]).strip()
    else:
        tokens = [t for t in clean_text.split(' ') if t]
        if len(tokens) == 1:
            main_name = tokens[0]
            department = ""
        elif len(tokens) == 2:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = ""
        else:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = " ".join(tokens[2:]).strip()
            
    return (main_name.strip(), clean_department_name(department), photo_index)

class CachedFace:
    def __init__(self, bbox, embedding):
        self.bbox = bbox
        self.embedding = embedding


class _AutoCloseConnection(sqlite3.Connection):
    """SQLite Connection ที่ทำการ commit/rollback และปิด Connection อัตโนมัติทันทีที่ออกจากบล็อก with (v6.28)"""
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            try:
                self.close()
            except Exception:
                pass


class DatabaseManager:
    _schema_initialized_paths = set()

    def __init__(self, db_path=None, year_folders_json_path=None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        default_db_dir = os.path.join(base_dir, "data")
        default_db_path = os.path.join(default_db_dir, "faces_db.db")
        default_json_path = os.path.join(base_dir, "config", "year_folders.json")

        if db_path is None:
            os.makedirs(default_db_dir, exist_ok=True)
            db_path = default_db_path

        self.db_path = db_path
        self._default_year_folders_json_path = default_json_path
        if year_folders_json_path is not None:
            self.year_folders_json_path = year_folders_json_path
        elif os.path.abspath(self.db_path) == os.path.abspath(default_db_path):
            self.year_folders_json_path = default_json_path
        else:
            self.year_folders_json_path = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "year_folders.json")

        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0, factory=_AutoCloseConnection)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -64000")
        conn.execute("PRAGMA mmap_size = 268435456")
        return conn

    def init_db(self, force=False):
        abs_db_path = os.path.abspath(self.db_path)
        if not force and abs_db_path in DatabaseManager._schema_initialized_paths:
            if os.path.exists(abs_db_path) and os.path.getsize(abs_db_path) > 4096:
                return

        logger.debug(f"Initializing SQLite database at: {self.db_path}")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. ตารางเก็บรายชื่อครูและนักเรียน
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'teacher',
                student_id TEXT,
                pin_code TEXT,
                personal_threshold REAL DEFAULT 0.50
            )
            """)

            # 2. ตารางเก็บเวกเตอร์ใบหน้า (รองรับ 1 คน หลายรูป)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                embedding BLOB NOT NULL,
                source_url TEXT,
                FOREIGN KEY (staff_id) REFERENCES staff_members (id) ON DELETE CASCADE
            )
            """)

            # 3. ตารางเก็บประวัติรูปภาพในกิจกรรมที่เคยสแกนไปแล้ว (เพื่อข้ามไม่สแกนซ้ำ)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scanned_photos (
                photo_id TEXT PRIMARY KEY,
                drive_file_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                drive_link TEXT NOT NULL,
                photo_date TEXT,
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 4. ตารางเก็บผลการจับคู่ใบหน้าในรูปกิจกรรม (Many-to-Many)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS detected_faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id TEXT NOT NULL,
                staff_id INTEGER NOT NULL,
                confidence REAL NOT NULL,
                FOREIGN KEY (photo_id) REFERENCES scanned_photos (photo_id) ON DELETE CASCADE,
                FOREIGN KEY (staff_id) REFERENCES staff_members (id) ON DELETE CASCADE
            )
            """)

            # 5. ตารางเก็บประวัติเวกเตอร์ใบหน้าทั้งหมดในรูปภาพกิจกรรม (Embedding Cache)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scanned_photo_faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id TEXT NOT NULL,
                face_index INTEGER NOT NULL,
                bbox_x1 REAL NOT NULL,
                bbox_y1 REAL NOT NULL,
                bbox_x2 REAL NOT NULL,
                bbox_y2 REAL NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (photo_id) REFERENCES scanned_photos (photo_id) ON DELETE CASCADE
            )
            """)

            # 6. ตารางเก็บข้อมูลไฟล์ภาพดิบจากกล้องดิจิทัล (Camera RAW Files) (v6.10)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_camera_photos (
                photo_id TEXT PRIMARY KEY,
                drive_file_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                drive_link TEXT NOT NULL,
                photo_date TEXT,
                file_name TEXT,
                file_extension TEXT,
                camera_brand TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # Indexes สำหรับตาราง raw_camera_photos (v6.10)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_brand ON raw_camera_photos(camera_brand)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ext ON raw_camera_photos(file_extension)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_event ON raw_camera_photos(event_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_drive_id ON raw_camera_photos(drive_file_id)")
                logger.info("Executed database migration v6.10: created raw_camera_photos table and indexes.")
            except Exception as e:
                logger.warning(f"Could not create raw_camera_photos indexes: {e}")
            
            # ตรวจสอบและอัปเดตตารางเก่าให้มีคอลัมน์ photo_date (Alter Table)
            try:
                cursor.execute("ALTER TABLE scanned_photos ADD COLUMN photo_date TEXT")
                logger.info("Executed database migration: added photo_date to scanned_photos.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            # Migration: เพิ่มคอลัมน์ role ใน staff_members (v1.7)
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN role TEXT DEFAULT 'teacher'")
                logger.info("Executed database migration: added role to staff_members.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            # อัปเดตข้อมูลเดิมให้มีค่า role = 'teacher' (สำหรับข้อมูลที่มีอยู่ก่อน migration)
            try:
                cursor.execute("UPDATE staff_members SET role = 'teacher' WHERE role IS NULL")
                conn.commit()
                logger.info("Migration: updated existing staff_members to role='teacher'.")
            except Exception as e:
                logger.warning(f"Could not update role for existing staff: {e}")

            # Migration: เพิ่มคอลัมน์ student_id ใน staff_members (v1.7.1)
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN student_id TEXT")
                logger.info("Executed database migration: added student_id to staff_members.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            # Migration: เพิ่มคอลัมน์ pin_code (v1.7.9)
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN pin_code TEXT")
                logger.info("Executed database migration: added pin_code to staff_members.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            # Migration: เพิ่มคอลัมน์ personal_threshold ใน staff_members (v3.5)
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN personal_threshold REAL DEFAULT 0.50")
                logger.info("Executed database migration: added personal_threshold to staff_members.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            try:
                cursor.execute("UPDATE staff_members SET personal_threshold = 0.50 WHERE personal_threshold IS NULL")
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not update personal_threshold for existing staff: {e}")

            # Migration: เพิ่มคอลัมน์ is_backfilled ใน staff_members (v4.0)
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN is_backfilled INTEGER DEFAULT 1")
                logger.info("Executed database migration: added is_backfilled to staff_members.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            try:
                cursor.execute("UPDATE staff_members SET is_backfilled = 1 WHERE is_backfilled IS NULL")
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not update is_backfilled for existing staff: {e}")

            # Migration: เพิ่มคอลัมน์ source_url ใน staff_embeddings (v1.7.2)
            try:
                cursor.execute("ALTER TABLE staff_embeddings ADD COLUMN source_url TEXT")
                logger.info("Executed database migration: added source_url to staff_embeddings.")
            except Exception:
                pass # คอลัมน์อาจจะมีอยู่แล้ว

            # สร้าง unique index สำหรับ student_id (เฉพาะนักเรียน)
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS unique_student_id
                    ON staff_members(student_id)
                    WHERE student_id IS NOT NULL AND role = 'student'
                """)
                conn.commit()
                logger.info("Migration: created unique index for student_id.")
            except Exception as e:
                logger.warning(f"Could not create unique index for student_id: {e}")

            # Migration: เพิ่ม Indexes เพื่อความเร็วสูงในการสืบค้นฐานข้อมูล (v5.70 / v6.28 Blazing Fast Covering Indexes)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_spf_photo_id ON scanned_photo_faces(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_event_name ON scanned_photos(event_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_drive_file_id ON scanned_photos(drive_file_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_staff_id ON detected_faces(staff_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_photo_id ON detected_faces(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_staff_photo ON detected_faces(staff_id, photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_photo_id ON scanned_photos(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_date ON scanned_photos(photo_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_role ON staff_members(role)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_name ON staff_members(name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_student_id ON staff_members(student_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_se_staff_id ON staff_embeddings(staff_id)")
                logger.info("Migration v5.70/v6.28: created performance & covering indexes for instant search.")
            except Exception as e:
                logger.warning(f"Could not create performance indexes: {e}")

            # Migration: ทำความสะอาดขยะประวัติการตรวจจับใบหน้าที่ไม่มีรูปจริงแล้ว (v4.21 Cleanup - Optimized NOT EXISTS)
            try:
                cursor.execute("""
                    DELETE FROM detected_faces
                    WHERE NOT EXISTS (
                        SELECT 1 FROM scanned_photos p WHERE p.photo_id = detected_faces.photo_id
                    )
                """)
                deleted_cnt = cursor.rowcount
                if deleted_cnt > 0:
                    logger.info(f"Migration v4.21: Cleaned up {deleted_cnt} orphan face records from detected_faces.")
            except Exception as e:
                logger.warning(f"Could not clean up orphan detected_faces: {e}")

            # Migration v5.80: ล้างประวัติภาพที่เคยติด Error จากเน็ตหลุดในอดีต (ERROR_ / SKIPPED_) ออกจาก scanned_photos เพื่อให้สแกนใหม่ได้
            try:
                cursor.execute("""
                    DELETE FROM scanned_photos 
                    WHERE photo_date LIKE 'ERROR%' 
                       OR photo_date LIKE 'SKIPPED%' 
                       OR drive_link LIKE 'ERROR%' 
                       OR drive_link LIKE 'SKIPPED%'
                """)
                purged_cnt = cursor.rowcount
                if purged_cnt > 0:
                    logger.info(f"Migration v5.80: Purged {purged_cnt} dummy error photos from scanned_photos for automatic rescan.")
            except Exception as e:
                logger.warning(f"Could not purge dummy error photos: {e}")

            # Migration v6.00: เพิ่มคอลัมน์ file_name และ file_extension ใน scanned_photos
            try:
                cursor.execute("ALTER TABLE scanned_photos ADD COLUMN file_name TEXT")
                logger.info("Executed database migration v6.00: added file_name to scanned_photos.")
            except Exception:
                pass

            try:
                cursor.execute("ALTER TABLE scanned_photos ADD COLUMN file_extension TEXT")
                logger.info("Executed database migration v6.00: added file_extension to scanned_photos.")
            except Exception:
                pass

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_file_name ON scanned_photos(file_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_file_ext ON scanned_photos(file_extension)")
            except Exception as e:
                logger.warning(f"Could not create file_name/file_extension indexes: {e}")

            # Migration v6.23: เพิ่มคอลัมน์ total_faces_detected และดัชนีครอบคลุม idx_spf_photo_face
            try:
                cursor.execute("ALTER TABLE scanned_photos ADD COLUMN total_faces_detected INTEGER DEFAULT 0")
                logger.info("Executed database migration v6.23: added total_faces_detected to scanned_photos.")
            except Exception:
                pass

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_total_faces ON scanned_photos(total_faces_detected)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_spf_photo_face ON scanned_photo_faces(photo_id, face_index)")
            except Exception as e:
                logger.warning(f"Could not create total_faces/photo_face indexes: {e}")

            # Migration v6.26: เพิ่มคอลัมน์ academic_year และดัชนี idx_sp_academic_year ใน scanned_photos
            try:
                cursor.execute("ALTER TABLE scanned_photos ADD COLUMN academic_year TEXT DEFAULT ''")
                logger.info("Executed database migration v6.26: added academic_year to scanned_photos.")
            except Exception:
                pass

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_academic_year ON scanned_photos(academic_year)")
            except Exception as e:
                logger.warning(f"Could not create academic_year index: {e}")

            # Migration v6.29: เพิ่มคอลัมน์ status, class_room, entry_year, graduation_year ใน staff_members (Student Lifecycle Architecture)
            new_sm_cols = [
                ("status", "TEXT DEFAULT 'active'"),
                ("class_room", "TEXT DEFAULT ''"),
                ("entry_year", "TEXT DEFAULT ''"),
                ("graduation_year", "TEXT DEFAULT ''")
            ]
            for col_name, col_def in new_sm_cols:
                try:
                    cursor.execute(f"ALTER TABLE staff_members ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Executed database migration v6.29: added {col_name} to staff_members.")
                except Exception:
                    pass

            # Backfill ข้อมูลเดิมใน staff_members ให้มี status = 'active' อัตโนมัติ (Idempotent Backfill)
            try:
                cursor.execute("UPDATE staff_members SET status = 'active' WHERE status IS NULL OR status = ''")
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not backfill status in staff_members: {e}")

            # ดัชนีครอบคลุมความเร็วสูงสำหรับวงจรชีวิตนักเรียนและการแมตช์ใบหน้า (v6.29 Composite & Covering Indexes)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_status_role ON staff_members(role, status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_classroom ON staff_members(class_room)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_grad_year ON staff_members(graduation_year)")
                logger.info("Executed database migration v6.29: created indexes for staff_members lifecycle.")
            except Exception as e:
                logger.warning(f"Could not create student lifecycle indexes: {e}")

            # Migration v6.33: เพิ่มคอลัมน์ department (กลุ่มสาระ/สังกัด) ใน staff_members
            try:
                cursor.execute("ALTER TABLE staff_members ADD COLUMN department TEXT DEFAULT ''")
                logger.info("Executed database migration v6.33: added department to staff_members.")
            except Exception:
                pass

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_department ON staff_members(department)")
            except Exception as e:
                logger.warning(f"Could not create department index: {e}")

            # Migration v6.34: Normalize department names in staff_members (strip 'กลุ่มสาระฯ' prefix)
            try:
                cursor.execute("SELECT id, department FROM staff_members WHERE department LIKE 'กลุ่มสาระ%'")
                rows_to_clean = cursor.fetchall()
                for row_id, raw_dept in rows_to_clean:
                    cleaned_dept = clean_department_name(raw_dept)
                    cursor.execute("UPDATE staff_members SET department = ? WHERE id = ?", (cleaned_dept, row_id))
                if rows_to_clean:
                    logger.info(f"Executed database migration v6.34: normalized {len(rows_to_clean)} department names.")
            except Exception as e:
                logger.warning(f"Could not clean department names: {e}")

            # Migration v6.40: Assign unassigned teachers (empty/null department) to 'อื่นๆ'
            try:
                cursor.execute("""
                    UPDATE staff_members 
                    SET department = 'อื่นๆ' 
                    WHERE (role = 'teacher' OR role IS NULL OR role = '') 
                      AND (department IS NULL OR TRIM(department) = '' OR department = 'ไม่ระบุ')
                """)
                if cursor.rowcount > 0:
                    logger.info(f"Executed database migration v6.40: assigned {cursor.rowcount} teachers to 'อื่นๆ'.")
            except Exception as e:
                logger.warning(f"Could not assign default department: {e}")

            # Migration v6.41: Normalize legacy department names ('ผู้บริหาร' -> 'คณะผู้บริหาร', 'สังคมศึกษา' -> 'สังคมศึกษาฯ')
            try:
                cursor.execute("UPDATE staff_members SET department = 'คณะผู้บริหาร' WHERE department = 'ผู้บริหาร'")
                cursor.execute("UPDATE staff_members SET department = 'สังคมศึกษาฯ' WHERE department = 'สังคมศึกษา'")
            except Exception as e:
                logger.warning(f"Could not normalize v6.41 department names: {e}")

            # Migration v6.42: Add original_image_path and cropped_image_path to staff_members
            try:
                cursor.execute("PRAGMA table_info(staff_members)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'original_image_path' not in columns:
                    cursor.execute("ALTER TABLE staff_members ADD COLUMN original_image_path TEXT DEFAULT ''")
                    logger.info("Executed database migration v6.42: added original_image_path to staff_members.")
                if 'cropped_image_path' not in columns:
                    cursor.execute("ALTER TABLE staff_members ADD COLUMN cropped_image_path TEXT DEFAULT ''")
                    logger.info("Executed database migration v6.42: added cropped_image_path to staff_members.")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_orig_img ON staff_members(original_image_path)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_crop_img ON staff_members(cropped_image_path)")
            except Exception as e:
                logger.warning(f"Could not execute v6.42 migration: {e}")

            # Migration v6.49: เพิ่มคอลัมน์ image_width และ image_height ใน scanned_photos
            try:
                cursor.execute("PRAGMA table_info(scanned_photos)")
                sp_cols = [col[1] for col in cursor.fetchall()]
                if 'image_width' not in sp_cols:
                    cursor.execute("ALTER TABLE scanned_photos ADD COLUMN image_width INTEGER DEFAULT 0")
                    logger.info("Executed database migration v6.49: added image_width to scanned_photos.")
                if 'image_height' not in sp_cols:
                    cursor.execute("ALTER TABLE scanned_photos ADD COLUMN image_height INTEGER DEFAULT 0")
                    logger.info("Executed database migration v6.49: added image_height to scanned_photos.")
            except Exception as e:
                logger.warning(f"Could not execute v6.49 migration: {e}")


            # 7. ตารางระบบสถิติและจัดกลุ่มใบหน้าบุคคลนิรนาม (v6.20 Unknown VIP & Yearly Analytics)
            conn.commit()
        
        self.create_unknown_tables()
        self.create_root_year_folders_table()
        self.reconcile_photo_dates()
        DatabaseManager._schema_initialized_paths.add(abs_db_path)
        logger.info("SQLite database initialized successfully.")

    def create_unknown_tables(self):
        """สร้างตารางสำหรับระบบสถิติบุคคลนิรนาม (v6.20 Idempotent Method)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_clusters (
                cluster_id TEXT PRIMARY KEY,
                photo_count INTEGER DEFAULT 0,
                event_count INTEGER DEFAULT 0,
                rep_photo_id TEXT,
                rep_face_index INTEGER,
                rep_bbox TEXT,
                first_seen_year TEXT,
                last_seen_year TEXT,
                active_years TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_cluster_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT NOT NULL,
                photo_id TEXT NOT NULL,
                face_index INTEGER NOT NULL,
                year TEXT NOT NULL,
                event_name TEXT,
                confidence REAL,
                FOREIGN KEY (cluster_id) REFERENCES unknown_clusters (cluster_id) ON DELETE CASCADE
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_cluster_year_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT NOT NULL,
                year TEXT NOT NULL,
                photo_count INTEGER DEFAULT 0,
                rep_photo_id TEXT,
                rep_face_index INTEGER,
                FOREIGN KEY (cluster_id) REFERENCES unknown_clusters (cluster_id) ON DELETE CASCADE
            )
            """)

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_uc_photo_count ON unknown_clusters(photo_count DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_uc_last_year ON unknown_clusters(last_seen_year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_cluster_id ON unknown_cluster_members(cluster_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_cluster_year ON unknown_cluster_members(cluster_id, year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_photo_id ON unknown_cluster_members(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_year ON unknown_cluster_members(year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_cluster_id ON unknown_cluster_year_stats(cluster_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_year ON unknown_cluster_year_stats(year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_photo_count ON unknown_cluster_year_stats(year, photo_count DESC)")
                conn.commit()
                logger.info("Executed database migration v6.20/v6.28: created unknown_clusters, unknown_cluster_members, and unknown_cluster_year_stats tables and indexes.")
            except Exception as e:
                logger.warning(f"Could not create unknown analytics indexes: {e}")

    def purge_error_scanned_photos(self):
        """ลบรายการภาพที่เคยติด Error/Skipped ออกจาก scanned_photos เพื่อให้สามารถดึงมาสแกนใหม่ได้ทันที (v5.80)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM scanned_photos 
                WHERE photo_date LIKE 'ERROR%' 
                   OR photo_date LIKE 'SKIPPED%' 
                   OR drive_link LIKE 'ERROR%' 
                   OR drive_link LIKE 'SKIPPED%'
            """)
            deleted_cnt = cursor.rowcount
            conn.commit()
            return deleted_cnt

    def backfill_total_faces_detected(self):
        """
        อัปเดตจำนวนใบหน้าที่ตรวจพบจริง (face_index >= 0) จาก scanned_photo_faces
        ย้อนหลังลงในคอลัมน์ total_faces_detected ของตาราง scanned_photos (v6.23)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            logger.info("[MIGRATION v6.23] Calculating face counts per photo from scanned_photo_faces...")
            cursor.execute("""
                SELECT photo_id, COUNT(*) 
                FROM scanned_photo_faces 
                WHERE face_index >= 0 
                GROUP BY photo_id
            """)
            counts = cursor.fetchall()
            logger.info(f"[MIGRATION v6.23] Found {len(counts)} photos with valid detected faces. Backfilling to scanned_photos...")
            cursor.executemany(
                "UPDATE scanned_photos SET total_faces_detected = ? WHERE photo_id = ?",
                [(cnt, pid) for pid, cnt in counts]
            )
            conn.commit()
            logger.info(f"[MIGRATION v6.23] Successfully backfilled total_faces_detected for {len(counts)} photos.")
            return len(counts)

    def backfill_academic_year(self, event_to_years=None):
        """
        อัปเดตข้อมูลปีการศึกษา (academic_year) ย้อนหลังลงในตาราง scanned_photos (v6.26)
        โดยใช้ 3-Tier Priority Cascade:
        - Priority 1: Google Drive Root Year Mapping (จาก event_to_years map)
        - Priority 2: Event Subfolder Name Regex (25XX, 20XX, ปี 6X)
        - Priority 3: File Name / Date Fallback (photo_date / file_name)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            logger.info("[MIGRATION v6.26] Reading all photos from scanned_photos for academic_year backfill...")
            cursor.execute("SELECT photo_id, event_name, photo_date, file_name FROM scanned_photos")
            photos = cursor.fetchall()
            
            updates = []
            year_counts = {}
            source_counts = {
                'priority_1_root_folder': 0,
                'priority_2_event_regex': 0,
                'priority_3_date_filename': 0,
                'unresolved': 0
            }

            for pid, ev, dt, fn in photos:
                ev_clean = (ev or '').strip()
                dt_clean = (dt or '').strip()
                fn_clean = (fn or '').strip()
                
                resolved_year = None
                source = None
                
                # Priority 1: จาก Google Drive Root Folder mapping
                if event_to_years and ev_clean in event_to_years:
                    possible_years = event_to_years[ev_clean]
                    if len(possible_years) == 1:
                        resolved_year = list(possible_years)[0]
                        source = 'priority_1_root_folder'
                    else:
                        if dt_clean:
                            parts = dt_clean.split('-')
                            if len(parts) >= 1 and parts[0].isdigit():
                                y_ce = int(parts[0])
                                if y_ce > 1900:
                                    cand = str(y_ce + 543)
                                    if cand in possible_years:
                                        resolved_year = cand
                                        source = 'priority_1_root_folder'
                        if not resolved_year:
                            resolved_year = sorted(list(possible_years), reverse=True)[0]
                            source = 'priority_1_root_folder'

                # Priority 2: จาก Event Subfolder Name Regex
                if not resolved_year and ev_clean:
                    m_be = re.search(r'25[3-7]\d', ev_clean)
                    if m_be:
                        resolved_year = m_be.group(0)
                        source = 'priority_2_event_regex'
                    else:
                        m_short = re.search(r'(?:ปี|พ\.ศ\.|\s|^)(6[0-9])(?:\s|$|[^\d])', ev_clean)
                        if m_short:
                            resolved_year = "25" + m_short.group(1)
                            source = 'priority_2_event_regex'
                        else:
                            m_ce = re.search(r'20[1-3]\d', ev_clean)
                            if m_ce:
                                resolved_year = str(int(m_ce.group(0)) + 543)
                                source = 'priority_2_event_regex'

                # Priority 3: จาก File Name หรือ Photo Date
                if not resolved_year:
                    if fn_clean:
                        m_fn_be = re.search(r'25[3-7]\d', fn_clean)
                        if m_fn_be:
                            resolved_year = m_fn_be.group(0)
                            source = 'priority_3_date_filename'
                        else:
                            m_fn_ce = re.search(r'20[1-3]\d', fn_clean)
                            if m_fn_ce:
                                resolved_year = str(int(m_fn_ce.group(0)) + 543)
                                source = 'priority_3_date_filename'
                    if not resolved_year and dt_clean:
                        parts = dt_clean.split('-')
                        if len(parts) >= 1 and parts[0].isdigit():
                            y_ce = int(parts[0])
                            if y_ce > 1900:
                                resolved_year = str(y_ce + 543)
                                source = 'priority_3_date_filename'

                year_val = resolved_year or ""
                updates.append((year_val, pid))
                if resolved_year:
                    year_counts[resolved_year] = year_counts.get(resolved_year, 0) + 1
                    source_counts[source] += 1
                else:
                    source_counts['unresolved'] += 1

            logger.info(f"[MIGRATION v6.26] Updating academic_year for {len(updates)} photos in scanned_photos...")
            cursor.executemany(
                "UPDATE scanned_photos SET academic_year = ? WHERE photo_id = ?",
                updates
            )
            conn.commit()
            logger.info(f"[MIGRATION v6.26] Successfully backfilled academic_year for {len(updates)} photos.")
            return {
                "total_photos": len(photos),
                "year_counts": year_counts,
                "source_counts": source_counts
            }

    def reconcile_photo_dates(self):
        """
        ปรับปรุงข้อมูลวันที่รูปภาพ (photo_date) ใน scanned_photos ที่ขัดแย้งกับปีการศึกษาจริง (v6.45)
        แก้ไขปัญหาประวัติรูปภาพในอดีต (เช่น 2563, 2564, 2565) ที่ถูก Google Drive Upload Date เขียนทับเป็นปี 2026
        """
        import re
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM scanned_photos 
                WHERE photo_date LIKE '2026%' AND academic_year IN ('2563', '2564', '2565')
            """)
            if cursor.fetchone()[0] == 0:
                return 0

            cursor.execute("""
                SELECT photo_id, academic_year, event_name, file_name 
                FROM scanned_photos 
                WHERE photo_date LIKE '2026%' AND academic_year IN ('2563', '2564', '2565')
            """)
            rows = cursor.fetchall()
            if not rows:
                return 0

            thai_to_ar = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')
            month_map = {
                'ม.ค.': 1, 'มค': 1, 'ก.พ.': 2, 'กพ': 2, 'มี.ค.': 3, 'มีค': 3,
                'เม.ย.': 4, 'เมย': 4, 'พ.ค.': 5, 'พค': 5, 'มิ.ย.': 6, 'มิย': 6,
                'ก.ค.': 7, 'กค': 7, 'ส.ค.': 8, 'สค': 8, 'ก.ย.': 9, 'กย': 9,
                'ต.ค.': 10, 'ตค': 10, 'พ.ย.': 11, 'พย': 11, 'ธ.ค.': 12, 'ธค': 12
            }

            def resolve_single_date(ay, ev, fn):
                ay_int = int(ay)
                ce_base = ay_int - 543
                ev_clean = (ev or '').strip()
                fn_clean = (fn or '').strip()
                combined = f'{ev_clean} {fn_clean}'.translate(thai_to_ar)
                
                # 1. ตรวจสอบ LINE Album format: _YYMMDD_
                m_line = re.search(r'_(\d{2})(\d{2})(\d{2})_', combined)
                if m_line:
                    yy, mm, dd = int(m_line.group(1)), int(m_line.group(2)), int(m_line.group(3))
                    if 1 <= mm <= 12 and 1 <= dd <= 31:
                        ce_y = 2000 + yy if yy < 50 else (2500 + yy) - 543
                        return f'{ce_y:04d}-{mm:02d}-{dd:02d}'
                        
                # 2. ตรวจสอบรูปแบบตัวเลขวันที่ระบุชัดเจน DD-MM-YY หรือ DD-MM-YYYY
                m_dmy = re.search(r'(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})(?!\d)', combined)
                if m_dmy:
                    d, m, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        if y >= 2500: cy = y - 543
                        elif y >= 50: cy = (2500 + y) - 543
                        elif y >= 20: cy = 2000 + y
                        else: cy = ce_base
                        return f'{cy:04d}-{m:02d}-{d:02d}'
                        
                # 3. ตรวจสอบชื่อเดือนภาษาไทย เช่น 23 พย, 21 มีค
                for m_txt, m_num in month_map.items():
                    m_thai = re.search(r'(\d{1,2})\s*' + re.escape(m_txt), combined)
                    if m_thai:
                        d = int(m_thai.group(1))
                        if 1 <= d <= 31:
                            cy = ce_base if m_num >= 5 else ce_base + 1
                            return f'{cy:04d}-{m_num:02d}-{d:02d}'
                            
                # 4. ตรวจสอบคีย์เวิร์ดกิจกรรมยอดนิยมประจำโรงเรียน
                ev_l = ev_clean.lower()
                if '1-65' in ev_l:
                    return '2022-05-15'
                if any(k in ev_l for k in ['ปฐมนิเทศ', 'เปิดเทอม', 'เปิดภาคเรียน', 'มอบตัว', 'ต้นเทอม']):
                    return f'{ce_base:04d}-05-15'
                if any(k in ev_l for k in ['ไหว้ครู', 'สภานักเรียน', 'เลือกตั้ง']):
                    return f'{ce_base:04d}-06-15'
                if any(k in ev_l for k in ['เฉลิมพระชนม', 'ร.10', 'รัชกาลที่ 10', 'เยี่ยม รร']):
                    return f'{ce_base:04d}-07-28'
                if any(k in ev_l for k in ['วันคล้ายวันกำเนิด', 'กำเนิด รร', 'วันแม่', 'วิทยาศาสตร์']):
                    return f'{ce_base:04d}-08-12'
                if any(k in ev_l for k in ['เกษียณ', 'มุทิตาจิต']):
                    return f'{ce_base:04d}-09-30'
                if any(k in ev_l for k in ['วันปิยะ', 'ปิดเทอม', 'ออกพรรษา']):
                    return f'{ce_base:04d}-10-15'
                if any(k in ev_l for k in ['ลอยกระทง', 'วันเพ็ญ']):
                    return f'{ce_base:04d}-11-15'
                if any(k in ev_l for k in ['วันพ่อ', 'วันชาติ', 'กีฬาแห่งชาติ', 'ฟุตบอล', 'บอล']):
                    return f'{ce_base:04d}-12-10'
                if any(k in ev_l for k in ['ปีใหม่', 'คริสต์มาส', 'ส่งท้ายปี']):
                    return f'{ce_base:04d}-12-25'
                if any(k in ev_l for k in ['วันเด็ก', 'วันครู']):
                    return f'{ce_base+1:04d}-01-16'
                if any(k in ev_l for k in ['ตรุษจีน', 'ศรร 26-1']):
                    return f'{ce_base+1:04d}-01-26'
                if any(k in ev_l for k in ['onet', 'โอเน็ต']):
                    return f'{ce_base+1:04d}-02-12'
                if any(k in ev_l for k in ['ปัจฉิม', 'วันม่วงเหลือง', 'บัณฑิตน้อย', 'จบการศึกษา']):
                    return f'{ce_base+1:04d}-03-22'
                if any(k in ev_l for k in ['สอบเข้า', 'รับสมัคร', 'ปลายภาค']):
                    return f'{ce_base+1:04d}-03-15'
                if any(k in ev_l for k in ['ธรรมศึกษา']):
                    return f'{ce_base:04d}-11-20'
                if any(k in ev_l for k in ['เปิดเรียน2', 'เปิดเทอม2']):
                    return f'{ce_base:04d}-11-01'

                # 5. Fallback ในปีการศึกษานั้น
                return f'{ce_base:04d}-08-15'

            updates = []
            for pid, ay, ev, fn in rows:
                new_date = resolve_single_date(ay, ev, fn)
                updates.append((new_date, pid))

            cursor.executemany("UPDATE scanned_photos SET photo_date = ? WHERE photo_id = ?", updates)
            conn.commit()
            logger.info(f"[MIGRATION v6.45] Reconciled {len(updates)} photo_dates matching true academic years.")
            return len(updates)

    # --- ส่วนการจัดการข้อมูลครู (Staff Registry) ---
    
    def register_staff_member(self, name, department=""):
        """เพิ่มชื่อครูและคืนค่า ID (ตั้งค่า is_backfilled = 0 เพื่อให้ Task 3 ทำ Retroactive Match) พร้อมบันทึกสังกัด (v6.34)"""
        name_clean = (name or "").strip()
        dep_clean = clean_department_name(department) or "อื่นๆ"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # ตรวจสอบว่ามีครูชื่อนี้อยู่แล้วหรือไม่
            cursor.execute("SELECT id, department FROM staff_members WHERE name = ? AND (role = 'teacher' OR role IS NULL OR role = '')", (name_clean,))
            existing = cursor.fetchone()
            if existing:
                staff_id, curr_dep = existing[0], existing[1]
                if not curr_dep or (dep_clean and dep_clean != "อื่นๆ" and curr_dep != dep_clean):
                    cursor.execute("UPDATE staff_members SET department = ? WHERE id = ?", (dep_clean, staff_id))
                    conn.commit()
                    logger.info(f"Updated department for existing staff member: {name_clean} -> {dep_clean}")
                return staff_id

            try:
                cursor.execute("INSERT INTO staff_members (name, role, is_backfilled, department) VALUES (?, 'teacher', 0, ?)", (name_clean, dep_clean))
                conn.commit()
                logger.info(f"Registered new staff member: {name_clean} (Department: '{dep_clean}')")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM staff_members WHERE name = ?", (name_clean,))
                row = cursor.fetchone()
                staff_id = row[0]
                if dep_clean:
                    cursor.execute("UPDATE staff_members SET department = ? WHERE id = ?", (dep_clean, staff_id))
                    conn.commit()
                return staff_id

    def update_teacher_department(self, staff_id, department):
        """อัปเดตสังกัดของคุณครู (v6.34)"""
        dep_clean = clean_department_name(department)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE staff_members SET department = ? WHERE id = ?", (dep_clean, staff_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_staff_member_by_id(self, staff_id):
        """ดึงข้อมูลบุคลากรรายบุคคลแบบสมบูรณ์ตาม ID (v6.34)"""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, role, student_id, pin_code, personal_threshold,
                       is_backfilled, status, class_room, entry_year, graduation_year, department
                FROM staff_members
                WHERE id = ?
            """, (staff_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["department"] = clean_department_name(d.get("department", ""))
                return d
            return None

    def update_staff_member_full(self, staff_id, name=None, department=None, status=None,
                                 role=None, student_id=None, class_room=None,
                                 personal_threshold=None, graduation_year=None, entry_year=None,
                                 original_image_path=None, cropped_image_path=None):
        """
        อัปเดตข้อมูลบุคลากรแบบรอบด้านใน Transaction เดียว รองรับทั้งครูและนักเรียน (v6.34/v6.42)
        """
        fields = []
        params = []
        if name is not None:
            fields.append("name = ?")
            params.append(str(name).strip())
        if department is not None:
            fields.append("department = ?")
            params.append(clean_department_name(department))
        if status is not None:
            fields.append("status = ?")
            params.append(str(status).strip())
        if role is not None:
            fields.append("role = ?")
            params.append(str(role).strip())
        if student_id is not None:
            fields.append("student_id = ?")
            params.append(str(student_id).strip())
        if class_room is not None:
            fields.append("class_room = ?")
            params.append(str(class_room).strip())
        if personal_threshold is not None:
            try:
                pt = float(personal_threshold)
                fields.append("personal_threshold = ?")
                params.append(pt)
            except (ValueError, TypeError):
                pass
        if graduation_year is not None:
            fields.append("graduation_year = ?")
            params.append(str(graduation_year).strip())
        if entry_year is not None:
            fields.append("entry_year = ?")
            params.append(str(entry_year).strip())
        if original_image_path is not None:
            fields.append("original_image_path = ?")
            params.append(str(original_image_path).strip())
        if cropped_image_path is not None:
            fields.append("cropped_image_path = ?")
            params.append(str(cropped_image_path).strip())
            
        if not fields:
            return False
            
        params.append(staff_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE staff_members SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0


    def update_scanned_photo_record(self, photo_id, event_name=None, academic_year=None):
        """อัปเดตข้อมูลภาพที่สแกนแล้ว (event_name, academic_year) (v6.34)"""
        fields = []
        params = []
        if event_name is not None:
            fields.append("event_name = ?")
            params.append(str(event_name).strip())
        if academic_year is not None:
            fields.append("academic_year = ?")
            params.append(str(academic_year).strip())
        if not fields:
            return False
        params.append(photo_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE scanned_photos SET {', '.join(fields)} WHERE photo_id = ?", params)
            conn.commit()
            return cursor.rowcount > 0

    def check_embedding_url_exists(self, staff_id, source_url):
        """
        ตรวจสอบว่ามี embedding ที่มี source_url เดียวกันอยู่แล้วหรือไม่ (รองรับการตัดช่องว่าง และสกัด File ID)
        คืนค่า: True ถ้ามีอยู่แล้ว, False ถ้ายังไม่มี
        """
        if not source_url:
            return False
            
        clean_url = source_url.strip()
        file_id = None
        if '/file/d/' in clean_url:
            file_id = clean_url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in clean_url:
            file_id = clean_url.split('id=')[1].split('&')[0]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if file_id:
                cursor.execute("""
                    SELECT id FROM staff_embeddings 
                    WHERE staff_id = ? AND (
                        source_url = ? OR source_url = ? OR source_url LIKE ? OR image_path LIKE ?
                    )
                """, (staff_id, source_url, clean_url, f"%{file_id}%", f"%{file_id}%"))
            else:
                cursor.execute(
                    "SELECT id FROM staff_embeddings WHERE staff_id = ? AND (source_url = ? OR source_url = ?)",
                    (staff_id, source_url, clean_url)
                )
            return cursor.fetchone() is not None

    def add_staff_embedding(self, staff_id, image_path, embedding_vector, source_url=None):
        """
        บันทึกเวกเตอร์ใบหน้า (embedding_vector ต้องเป็น numpy array หรือ list ขนาด 512 มิติ)
        source_url: ลิงค์ที่มาของรูป (ถ้ามี) - ใช้สำหรับตรวจสอบรูปซ้ำใน Batch Import
        """
        if isinstance(embedding_vector, list):
            embedding_vector = np.array(embedding_vector, dtype=np.float32)

        # แปลง numpy array เป็น bytes
        embedding_blob = embedding_vector.astype(np.float32).tobytes()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO staff_embeddings (staff_id, image_path, embedding, source_url) VALUES (?, ?, ?, ?)",
                (staff_id, image_path, embedding_blob, source_url)
            )
            conn.commit()
            logger.debug(f"Saved embedding for staff_id {staff_id} from {os.path.basename(image_path)}")

    def get_all_staff_members(self):
        """ดึงข้อมูลรายชื่อครูทั้งหมดพร้อมจำนวนรูปภาพที่ลงทะเบียนไว้ และสังกัด (v6.34)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, COALESCE(s.department, '') as department, COUNT(e.id) as photo_count,
                       COALESCE(s.status, 'active') as status
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                GROUP BY s.id, s.name, s.department, s.status
                ORDER BY s.name ASC
            """)
            return [{
                "id": row[0],
                "name": row[1],
                "department": clean_department_name(row[2]),
                "photo_count": row[3],
                "status": row[4]
            } for row in cursor.fetchall()]

    def get_all_teachers(self):
        """ดึงรายชื่อครูทั้งหมด (role = 'teacher') พร้อมสังกัด สถานะ ภาพต้นฉบับ ภาพสแกน และรูปภาพอ้างอิงแรก (avatar_path) (v6.41/v6.42)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, COALESCE(s.department, '') as department, COUNT(e.id) as photo_count,
                       COALESCE(s.status, 'active') as status,
                       COALESCE(s.original_image_path, '') as original_image_path,
                       COALESCE(s.cropped_image_path, '') as cropped_image_path,
                       (SELECT image_path FROM staff_embeddings WHERE staff_id = s.id ORDER BY id ASC LIMIT 1) as legacy_crop_path
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                GROUP BY s.id, s.name, s.department, s.status, s.original_image_path, s.cropped_image_path
                ORDER BY s.name ASC
            """)
            teachers = []
            for row in cursor.fetchall():
                orig_img = row[5] or ""
                crop_img = row[6] or row[7] or ""
                # avatar_path: ให้ความสำคัญกับภาพต้นฉบับก่อนเสมอ หากมีไฟล์จริงในเครื่อง ถ้าไม่มีจึง fallback ไปภาพ crop
                avatar_path = orig_img if (orig_img and os.path.exists(orig_img)) else crop_img
                teachers.append({
                    "id": row[0],
                    "name": row[1],
                    "department": clean_department_name(row[2]),
                    "photo_count": row[3],
                    "status": row[4],
                    "original_image_path": orig_img,
                    "cropped_image_path": crop_img,
                    "avatar_path": avatar_path
                })
            return teachers


    def get_all_teachers_with_avatar_stats(self):
        """
        ดึงข้อมูลคุณครูทั้งหมดพร้อมพาธรูป Avatar และสถิติจำนวนรูปภาพกิจกรรมที่แมตช์ได้ (v6.36/v6.43)
        เรียงลำดับเริ่มต้นตามจำนวนรูปกิจกรรมที่แมตช์พบมากที่สุด (matched_count DESC)
        รองรับ Dual Photo Architecture (ภาพ Original ความละเอียดสูง และภาพ Cropped สแกน)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, COALESCE(s.department, '') as department,
                       COALESCE(s.status, 'active') as status,
                       COALESCE(s.original_image_path, '') as original_image_path,
                       COALESCE(s.cropped_image_path, '') as cropped_image_path,
                       (SELECT image_path FROM staff_embeddings WHERE staff_id = s.id ORDER BY id ASC LIMIT 1) as legacy_crop_path,
                       (SELECT COUNT(DISTINCT photo_id) FROM detected_faces WHERE staff_id = s.id) as matched_count,
                       (SELECT COUNT(*) FROM staff_embeddings WHERE staff_id = s.id) as ref_photos_count
                FROM staff_members s
                WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                GROUP BY s.id
                ORDER BY matched_count DESC, s.name ASC
            """)
            teachers = []
            for row in cursor.fetchall():
                orig_img = row[4] or ""
                crop_img = row[5] or row[6] or ""
                # ให้ความสำคัญกับภาพต้นฉบับก่อนเสมอ หากมีไฟล์จริงในเครื่อง ถ้าไม่มีจึง fallback ไปภาพ crop
                avatar_path = orig_img if (orig_img and os.path.exists(orig_img)) else crop_img
                teachers.append({
                    "id": row[0],
                    "name": row[1],
                    "department": clean_department_name(row[2]),
                    "status": row[3],
                    "original_image_path": orig_img,
                    "cropped_image_path": crop_img,
                    "avatar_path": avatar_path,
                    "matched_count": row[7] or 0,
                    "ref_photos_count": row[8] or 0
                })
            return teachers

    def get_all_students(self, status_filter=None, class_filter=None):
        """ดึงรายชื่อนักเรียนทั้งหมด (role = 'student') พร้อม student_id, status, class_room, grad_year (v6.29)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT s.id, s.name, s.student_id, COUNT(e.id) as photo_count,
                       COALESCE(s.status, 'active') as status,
                       COALESCE(s.class_room, '') as class_room,
                       COALESCE(s.graduation_year, '') as graduation_year,
                       COALESCE(s.entry_year, '') as entry_year
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                WHERE s.role = 'student'
            """
            params = []
            if status_filter and status_filter != 'all':
                if status_filter == 'active':
                    query += " AND (s.status = 'active' OR s.status IS NULL OR s.status = '')"
                else:
                    query += " AND s.status = ?"
                    params.append(status_filter)
            if class_filter and class_filter != 'all':
                query += " AND s.class_room = ?"
                params.append(class_filter)
            query += """
                GROUP BY s.id, s.name, s.student_id, s.status, s.class_room, s.graduation_year, s.entry_year
                ORDER BY s.class_room ASC, s.student_id ASC, s.name ASC
            """
            cursor.execute(query, params)
            return [{
                "id": row[0],
                "name": row[1],
                "student_id": row[2],
                "photo_count": row[3],
                "status": row[4],
                "class_room": row[5],
                "graduation_year": row[6],
                "entry_year": row[7]
            } for row in cursor.fetchall()]

    def check_student_id_exists(self, student_id):
        """ตรวจสอบว่ารหัสประจำตัวนักเรียนนี้ถูกใช้ไปแล้วหรือยัง"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM staff_members WHERE student_id = ? AND role = 'student'", (student_id,))
            return cursor.fetchone() is not None

    def find_student_by_code_and_name(self, student_id, name):
        """
        ค้นหานักเรียนจากรหัสและชื่อ
        คืนค่า: dict มีคีย์ 'id', 'name', 'student_id' ถ้าเจอ, None ถ้าไม่เจอ
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, student_id, COALESCE(status, 'active'), COALESCE(class_room, '') FROM staff_members WHERE student_id = ? AND role = 'student'",
                (student_id,)
            )
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "student_id": row[2], "status": row[3], "class_room": row[4]}
            return None

    def get_student_photo_count(self, staff_id):
        """ดึงจำนวนภาพที่ลงทะเบียนไว้ของนักเรียนคนหนึ่ง"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def register_member(self, name, role='teacher', student_id=None, pin_code=None, personal_threshold=None, status='active', class_room='', entry_year='', graduation_year=''):
        """ลงทะเบียนสมาชิกใหม่พร้อมระบุ role (teacher/student), student_id, pin_code, personal_threshold และข้อมูลวงจรชีวิต (v6.29)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if role == 'student' and student_id:
                    cursor.execute(
                        """INSERT INTO staff_members 
                           (name, role, student_id, pin_code, personal_threshold, status, class_room, entry_year, graduation_year) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, role, student_id, pin_code, personal_threshold if personal_threshold is not None else 0.50,
                         status or 'active', class_room or '', entry_year or '', graduation_year or '')
                    )
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (ID: {student_id}, Room: {class_room}, Status: {status})")
                    return cursor.lastrowid
                elif role == 'student':
                    cursor.execute(
                        """INSERT INTO staff_members 
                           (name, role, pin_code, personal_threshold, status, class_room, entry_year, graduation_year) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, role, pin_code, personal_threshold if personal_threshold is not None else 0.50,
                         status or 'active', class_room or '', entry_year or '', graduation_year or '')
                    )
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (WARNING: no student_id)")
                    return cursor.lastrowid
                else:
                    cursor.execute(
                        "INSERT INTO staff_members (name, role, personal_threshold, status) VALUES (?, ?, ?, ?)",
                        (name, role, personal_threshold if personal_threshold is not None else 0.50, status or 'active')
                    )
                    conn.commit()
                    logger.info(f"Registered new {role}: {name}")
                    return cursor.lastrowid
            except sqlite3.IntegrityError:
                # กรณีมีชื่อซ้ำหรือ student_id ซ้ำ ดึงไอดีเดิมส่งกลับไป
                if role == 'student' and student_id:
                    cursor.execute("SELECT id FROM staff_members WHERE student_id = ?", (student_id,))
                    row = cursor.fetchone()
                    if row:
                        updates = ["name = ?", "role = 'student'"]
                        up_params = [name]
                        if personal_threshold is not None:
                            updates.append("personal_threshold = ?")
                            up_params.append(personal_threshold)
                        if status:
                            updates.append("status = ?")
                            up_params.append(status)
                        if class_room:
                            updates.append("class_room = ?")
                            up_params.append(class_room)
                        up_params.append(row[0])
                        cursor.execute(f"UPDATE staff_members SET {', '.join(updates)} WHERE id = ?", up_params)
                        conn.commit()
                        logger.info(f"Student '{name}' updated existing record (ID: {row[0]}, Student ID: {student_id}).")
                        return row[0]
                
                cursor.execute("SELECT id FROM staff_members WHERE name = ? AND (role = ? OR role IS NULL OR role = '')", (name, role))
                row = cursor.fetchone()
                if row:
                    logger.info(f"{role.capitalize()} '{name}' already registered (ID: {row[0]}).")
                    return row[0]
                    
                if student_id:
                    cursor.execute("SELECT id FROM staff_members WHERE student_id = ?", (student_id,))
                    row = cursor.fetchone()
                    if row:
                        return row[0]

                return None

    def get_staff_id_by_student_id(self, student_id):
        """ดึง staff_id จาก student_id (รหัสนักเรียน)"""
        if not student_id:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM staff_members WHERE student_id = ? AND role = 'student'", (str(student_id).strip(),))
            row = cursor.fetchone()
            return row[0] if row else None

    def update_student_info(self, staff_id, new_name, new_student_id, status=None, class_room=None, graduation_year=None, entry_year=None):
        """อัปเดตชื่อและรหัสนักเรียน พร้อมข้อมูลวงจรชีวิต (v6.29)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # ตรวจสอบว่า student_id ซ้ำกับคนอื่นหรือไม่
                if new_student_id:
                    cursor.execute("SELECT id FROM staff_members WHERE student_id = ? AND id != ? AND role = 'student'", (str(new_student_id).strip(), staff_id))
                    if cursor.fetchone():
                        logger.warning(f"[DATABASE] Student ID {new_student_id} already exists for another student.")
                        return False, "รหัสประจำตัวนักเรียนนี้ถูกใช้ไปแล้วโดยนักเรียนคนอื่น"
                        
                fields = ["name = ?", "student_id = ?"]
                params = [new_name.strip(), str(new_student_id).strip() if new_student_id else None]

                if status is not None:
                    fields.append("status = ?")
                    params.append(status.strip())
                if class_room is not None:
                    fields.append("class_room = ?")
                    params.append(class_room.strip())
                if graduation_year is not None:
                    fields.append("graduation_year = ?")
                    params.append(str(graduation_year).strip())
                if entry_year is not None:
                    fields.append("entry_year = ?")
                    params.append(str(entry_year).strip())

                params.append(staff_id)
                query = f"UPDATE staff_members SET {', '.join(fields)} WHERE id = ?"
                cursor.execute(query, params)
                conn.commit()
                logger.info(f"[DATABASE] Updated student ID {staff_id} info: name='{new_name}', student_id='{new_student_id}', status='{status}', class='{class_room}'")
                return True, "อัปเดตข้อมูลสำเร็จ"
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error updating student info for ID {staff_id}: {e}")
                conn.rollback()
                return False, f"เกิดข้อผิดพลาดในฐานข้อมูล: {e}"

    def batch_update_student_status(self, student_ids, new_status, graduation_year=None):
        """อัปเดตสถานะนักเรียนแบบกลุ่ม (เช่น บันทึกจบการศึกษา) ใน 1 Transaction (v6.29)"""
        if not student_ids:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if graduation_year is not None:
                    cursor.executemany(
                        "UPDATE staff_members SET status = ?, graduation_year = ? WHERE id = ? AND role = 'student'",
                        [(new_status, str(graduation_year).strip(), sid) for sid in student_ids]
                    )
                else:
                    cursor.executemany(
                        "UPDATE staff_members SET status = ? WHERE id = ? AND role = 'student'",
                        [(new_status, sid) for sid in student_ids]
                    )
                affected = cursor.rowcount
                conn.commit()
                logger.info(f"[DATABASE] Batch updated {len(student_ids)} students to status='{new_status}' (Grad Year: {graduation_year})")
                return len(student_ids)
            except Exception as e:
                conn.rollback()
                logger.error(f"[DATABASE] Error in batch_update_student_status: {e}")
                raise e

    def batch_update_staff_status(self, staff_ids, new_status="inactive"):
        """อัปเดตสถานะของบุคลากร/ครูแบบกลุ่ม (เช่น ปรับเป็น inactive) ใน 1 Transaction (v6.37)"""
        if not staff_ids:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany(
                    "UPDATE staff_members SET status = ? WHERE id = ?",
                    [(new_status.strip(), sid) for sid in staff_ids]
                )
                affected = len(staff_ids)
                conn.commit()
                logger.info(f"[DATABASE] Batch updated {affected} staff members to status='{new_status}' (IDs: {staff_ids[:5]}...)")
                return affected
            except Exception as e:
                conn.rollback()
                logger.error(f"[DATABASE] Error in batch_update_staff_status: {e}")
                raise e

    def batch_update_staff_departments_and_statuses(self, updates_list):
        """
        อัปเดตสังกัด (department) และสถานะ (status) ของบุคลากรแบบกลุ่มใน 1 Transaction (v6.39)
        updates_list: [(department, status, staff_id), ...]
        """
        if not updates_list:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany(
                    "UPDATE staff_members SET department = ?, status = ? WHERE id = ?",
                    [(dept.strip(), status.strip(), sid) for dept, status, sid in updates_list]
                )
                affected = len(updates_list)
                conn.commit()
                logger.info(f"[DATABASE] Batch updated department and status for {affected} staff members (v6.39).")
                return affected
            except Exception as e:
                conn.rollback()
                logger.error(f"[DATABASE] Error in batch_update_staff_departments_and_statuses: {e}")
                raise e

    def assign_unassigned_teachers_to_other(self):
        """
        ปรับปรุงบุคลากรครูที่ไม่มีสังกัดกลุ่มสาระ (เป็นค่าว่าง หรือ NULL) ให้มีสังกัดเป็น 'อื่นๆ' (v6.40)
        คืนค่า: จำนวนแถวที่ได้รับการอัปเดต
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE staff_members 
                SET department = 'อื่นๆ' 
                WHERE (role = 'teacher' OR role IS NULL OR role = '') 
                  AND (department IS NULL OR TRIM(department) = '' OR department = 'ไม่ระบุ')
            """)
            affected = cursor.rowcount
            conn.commit()
            if affected > 0:
                logger.info(f"[DATABASE] Assigned {affected} unassigned teachers to department 'อื่นๆ' (v6.40).")
            return affected

    def batch_promote_students(self, source_class, target_class):
        """เลื่อนชั้นเรียนนักเรียนทั้งห้อง (เช่น ม.1/1 -> ม.2/1) เฉพาะนักเรียนที่กำลังศึกษา (v6.29)"""
        if not source_class or not target_class:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE staff_members 
                    SET class_room = ? 
                    WHERE role = 'student' 
                      AND class_room = ? 
                      AND (status = 'active' OR status IS NULL OR status = '')
                """, (target_class.strip(), source_class.strip()))
                affected = cursor.rowcount
                conn.commit()
                logger.info(f"[DATABASE] Promoted {affected} students from '{source_class}' to '{target_class}'")
                return affected
            except Exception as e:
                conn.rollback()
                logger.error(f"[DATABASE] Error promoting students: {e}")
                raise e

    def get_student_classrooms(self):
        """ดึงรายชื่อห้องเรียนทั้งหมดที่มีนักเรียนในฐานข้อมูล เรียงตามตัวอักษร (v6.29)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT class_room 
                FROM staff_members 
                WHERE role = 'student' AND class_room IS NOT NULL AND TRIM(class_room) != ''
                ORDER BY class_room ASC
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_student_lifecycle_stats(self):
        """ดึงข้อมูลสถิติภาพรวมวงจรชีวิตนักเรียน (v6.29)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(id) as total_students,
                    SUM(CASE WHEN status = 'active' OR status IS NULL OR status = '' THEN 1 ELSE 0 END) as active_count,
                    SUM(CASE WHEN status = 'graduated' THEN 1 ELSE 0 END) as graduated_count,
                    SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END) as inactive_count,
                    COUNT(DISTINCT CASE WHEN class_room IS NOT NULL AND TRIM(class_room) != '' THEN class_room END) as classroom_count
                FROM staff_members
                WHERE role = 'student'
            """)
            row = cursor.fetchone()
            return {
                "total_students": row[0] or 0,
                "active_count": row[1] or 0,
                "graduated_count": row[2] or 0,
                "inactive_count": row[3] or 0,
                "classroom_count": row[4] or 0
            }

    def delete_staff_member(self, staff_id):
        """ลบข้อมูลครูและลบความสัมพันธ์อื่น ๆ ทั้งหมด (Cascaded)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM staff_members WHERE id = ?", (staff_id,))
            conn.commit()
            logger.info(f"Deleted staff member ID: {staff_id}")

    def cleanup_orphan_students(self):
        """ลบข้อมูลนักเรียนที่ถูกลงทะเบียนแต่ไม่มีรูปภาพ (ไม่มี embedding) และไม่มีประวัติการแมตช์ เพื่อแก้ปัญหา Task 2 ลงทะเบียนผิดพลาด 700 คน"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # ค้นหานักเรียนที่ไม่มี record ใน staff_embeddings และไม่มี record ใน detected_faces
            cursor.execute("""
                DELETE FROM staff_members 
                WHERE role = 'student' 
                AND id NOT IN (SELECT staff_id FROM staff_embeddings)
                AND id NOT IN (SELECT staff_id FROM detected_faces)
            """)
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} orphan student records without photos.")
            return deleted_count

    def get_all_embeddings(self, active_only=True):
        """ดึงเวกเตอร์ทั้งหมดของครูและนักเรียนเพื่อใช้โหลดลงหน่วยความจำตอนเริ่มต้นโปรแกรม หรือตอนจับคู่ใบหน้า (v6.37)
        active_only: หากเป็น True จะดึงคุณครูทั้งหมด (ทั้ง active และ inactive เพื่อสืบค้นภาพกิจกรรมหอจดหมายเหตุ)
        และดึงเฉพาะนักเรียนที่มีสถานะ 'active' (ข้ามศิษย์เก่า/จบการศึกษา)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("""
                    SELECT e.staff_id, s.name, e.embedding, e.image_path, s.role, 
                           COALESCE(s.personal_threshold, 0.50), COALESCE(s.status, 'active'), COALESCE(s.class_room, '')
                    FROM staff_embeddings e
                    JOIN staff_members s ON e.staff_id = s.id
                    WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                       OR (s.role = 'student' AND (s.status = 'active' OR s.status IS NULL OR s.status = ''))
                """)
            else:
                cursor.execute("""
                    SELECT e.staff_id, s.name, e.embedding, e.image_path, s.role, 
                           COALESCE(s.personal_threshold, 0.50), COALESCE(s.status, 'active'), COALESCE(s.class_room, '')
                    FROM staff_embeddings e
                    JOIN staff_members s ON e.staff_id = s.id
                """)
            rows = cursor.fetchall()
            
            embeddings = []
            names = []
            staff_ids = []
            image_paths = []
            roles = []
            personal_thresholds = []
            statuses = []
            class_rooms = []
            
            for row in rows:
                staff_id, name, blob, img_path, role, thresh, status, c_room = row
                vec = np.frombuffer(blob, dtype=np.float32)
                embeddings.append(vec)
                names.append(name)
                staff_ids.append(staff_id)
                image_paths.append(img_path)
                roles.append(role if role else "teacher")
                personal_thresholds.append(float(thresh) if thresh is not None else 0.50)
                statuses.append(status if status else "active")
                class_rooms.append(c_room if c_room else "")
                
            return {
                "embeddings": np.array(embeddings) if embeddings else np.empty((0, 512), dtype=np.float32),
                "names": names,
                "staff_ids": staff_ids,
                "image_paths": image_paths,
                "roles": roles,
                "personal_thresholds": personal_thresholds,
                "statuses": statuses,
                "class_rooms": class_rooms
            }

    def get_personal_threshold(self, staff_id):
        """ดึงค่า Personal Threshold ของบุคคลจาก staff_id"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(personal_threshold, 0.50) FROM staff_members WHERE id = ?", (staff_id,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return float(row[0])
            return 0.50

    def update_personal_threshold(self, staff_id, threshold_value):
        """อัปเดตค่า Personal Threshold ของบุคคลในฐานข้อมูล"""
        return self.update_personal_thresholds_batch([staff_id], threshold_value)

    def update_personal_thresholds_batch(self, staff_ids, threshold_value):
        """อัปเดตค่า Personal Threshold ของบุคคลหลายคนพร้อมกันใน 1 Transaction (v5.40)"""
        if not staff_ids:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                val = float(threshold_value)
                cursor.executemany(
                    "UPDATE staff_members SET personal_threshold = ? WHERE id = ?",
                    [(val, sid) for sid in staff_ids]
                )
                conn.commit()
                logger.info(f"[DATABASE] Batch updated personal_threshold to {val:.2f} for {len(staff_ids)} members.")
                return True
            except Exception as e:
                logger.error(f"Error batch updating personal_threshold: {e}")
                return False

    # --- ส่วนการจัดการภาพสแกนกิจกรรม (Photo Matching DB) ---
    
    def is_photo_scanned(self, drive_file_id):
        """ตรวจสอบว่ารูปนี้ใน Google Drive ถูกสแกนหรือบันทึกเป็นไฟล์ RAW ไปแล้วหรือไม่ (v6.10)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT photo_id FROM scanned_photos WHERE drive_file_id = ?
                UNION
                SELECT photo_id FROM raw_camera_photos WHERE drive_file_id = ?
                LIMIT 1
            """, (drive_file_id, drive_file_id))
            return cursor.fetchone() is not None

    def is_raw_photo_recorded(self, drive_file_id):
        """ตรวจสอบว่าไฟล์นี้ถูกบันทึกในตาราง raw_camera_photos หรือไม่ (v6.10)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id FROM raw_camera_photos WHERE drive_file_id = ? LIMIT 1", (drive_file_id,))
            return cursor.fetchone() is not None

    def save_scanned_photo(self, photo_id, drive_file_id, event_name, drive_link, matches, photo_date="", file_name="", file_extension="", total_faces_detected=None):
        """
        บันทึกข้อมูลรูปภาพที่สแกนเสร็จแล้วและรายชื่อใบหน้าที่ตรวจพบ (v6.00 เพิ่ม file_name และ file_extension, v6.23 เพิ่ม total_faces_detected)
        matches: list ของ tuple (staff_id, confidence)
        """
        if not file_extension and file_name:
            file_extension = os.path.splitext(file_name)[1].lower()
        if total_faces_detected is None:
            total_faces = len(matches) if matches else 0
        else:
            total_faces = int(total_faces_detected)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # บันทึกรูปภาพ (ใช้ INSERT OR REPLACE เพื่อป้องกัน drive_file_id ซ้ำซ้อน)
                cursor.execute(
                    "INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, total_faces_detected) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, total_faces)
                )
                
                # บันทึกคนในรูป
                for staff_id, confidence in matches:
                    cursor.execute(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        (photo_id, staff_id, float(confidence))
                    )
                conn.commit()
                logger.info(f"Saved scanned photo {photo_id} ({file_name}) with {len(matches)} matches to SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving scanned photo {photo_id} to SQLite: {e}")
                conn.rollback()
                return False

    def save_scanned_photos_batch(self, batch_items):
        """
        บันทึกข้อมูลรูปภาพที่สแกนเสร็จแล้วแบบกลุ่ม (Batch) ใน Transaction เดียวด้วย executemany (v5.20 / v6.00 / v6.28 รองรับ academic_year)
        batch_items: list of dict [
            {
                "photo_id": ...,
                "drive_file_id": ...,
                "event_name": ...,
                "drive_link": ...,
                "matches": [...],
                "photo_date": ...,
                "file_name": ...,
                "file_extension": ...,
                "academic_year": ...,
                "faces": [...]
            }
        ]
        """
        if not batch_items:
            return True
            
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                photo_rows = []
                detected_face_rows = []
                cached_face_rows = []

                for item in batch_items:
                    pid = item["photo_id"]
                    fid = item["drive_file_id"]
                    event = item.get("event_name", "")
                    link = item.get("drive_link", f"https://drive.google.com/file/d/{fid}/view")
                    pdate = item.get("photo_date", "")
                    fname = item.get("file_name", "")
                    fext = item.get("file_extension", "")
                    if not fext and fname:
                        fext = os.path.splitext(fname)[1].lower()
                    matches = item.get("matches", [])
                    faces = item.get("faces") if "faces" in item else item.get("all_faces", [])
                    if "total_faces_detected" in item and item["total_faces_detected"] is not None:
                        total_faces = int(item["total_faces_detected"])
                    elif "total_faces" in item and item["total_faces"] is not None:
                        total_faces = int(item["total_faces"])
                    else:
                        total_faces = len(faces) if faces else (len(matches) if matches else 0)

                    acad_year = str(item.get("academic_year", "") or "").strip()
                    if not acad_year:
                        acad_year = self.extract_year_from_text(event) or self.extract_year_from_text(fname)
                        if not acad_year and pdate and "-" in str(pdate):
                            parts = str(pdate).split("-")
                            if parts[0].isdigit() and int(parts[0]) > 1900:
                                acad_year = str(int(parts[0]) + 543)

                    photo_rows.append((pid, fid, event, link, pdate, fname, fext, total_faces, acad_year))

                    for m in matches:
                        if isinstance(m, dict):
                            s_id = m.get("staff_id")
                            conf = m.get("confidence", 0.0)
                        else:
                            s_id, conf = m[0], m[1]
                        detected_face_rows.append((pid, s_id, float(conf)))

                    if not faces:
                        cached_face_rows.append((pid, -1, 0.0, 0.0, 0.0, 0.0, b""))
                    else:
                        for idx, f in enumerate(faces):
                            bbox = f["bbox"] if isinstance(f, dict) else f.bbox
                            emb_arr = f["embedding"] if isinstance(f, dict) else f.embedding
                            x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                            if isinstance(emb_arr, bytes):
                                emb_bytes = emb_arr
                            else:
                                emb_bytes = np.asarray(emb_arr, dtype=np.float32).tobytes()
                            cached_face_rows.append((pid, idx, x1, y1, x2, y2, emb_bytes))

                # 1. บันทึก scanned_photos แบบ Batch executemany
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO scanned_photos
                    (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, total_faces_detected, academic_year)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    photo_rows
                )

                # 2. บันทึก detected_faces แบบ Batch executemany
                if detected_face_rows:
                    cursor.executemany(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        detected_face_rows
                    )

                # 3. บันทึก scanned_photo_faces (Embedding cache) แบบ Batch executemany
                if cached_face_rows:
                    cursor.executemany(
                        """
                        INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        cached_face_rows
                    )

                conn.commit()
                logger.info(f"⚡ [BATCH DB] Successfully committed batch of {len(batch_items)} photos ({len(cached_face_rows)} face rows) to SQLite via executemany.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving batch photos to SQLite: {e}")
                conn.rollback()
                return False

    def mark_skipped_photo(self, photo_id, drive_file_id, event_name, reason="SKIPPED_UNREADABLE", file_name="", file_extension=""):
        """บันทึกประวัติไฟล์รูปภาพที่ไม่สามารถอ่านได้/เสียหาย/ไม่ใช่ไฟล์รูปภาพลง SQLite เพื่อป้องกันการติดลูปสแกนซ้ำ (v6.00)"""
        if not file_extension and file_name:
            file_extension = os.path.splitext(file_name)[1].lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (photo_id, drive_file_id, event_name, f"https://drive.google.com/file/d/{drive_file_id}/view", reason, file_name, file_extension)
                )
                conn.commit()
                logger.info(f"[DATABASE] Marked unreadable photo {photo_id} ({file_name}) as '{reason}' in SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error marking skipped photo {photo_id}: {e}")
                return False

    def save_raw_photos_batch(self, batch_items):
        """บันทึกข้อมูลไฟล์ภาพดิบจากกล้อง (RAW Camera Files) ลงตาราง raw_camera_photos แบบ Batch (v6.10)"""
        if not batch_items:
            return True
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                for item in batch_items:
                    pid = item["photo_id"]
                    fid = item["drive_file_id"]
                    event = item.get("event_name", "")
                    link = item.get("drive_link", f"https://drive.google.com/file/d/{fid}/view")
                    pdate = item.get("photo_date", "")
                    fname = item.get("file_name", "")
                    fext = item.get("file_extension", "")
                    if not fext and fname:
                        fext = os.path.splitext(fname)[1].lower()
                    brand = item.get("camera_brand", "")
                    if not brand and fext:
                        brand = RAW_EXTENSIONS_MAP.get(fext, "Unknown Camera RAW")

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO raw_camera_photos 
                        (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, camera_brand) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pid, fid, event, link, pdate, fname, fext, brand)
                    )
                conn.commit()
                logger.info(f"📷 [RAW DB] Successfully saved batch of {len(batch_items)} RAW camera files to SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving raw camera photos batch: {e}")
                conn.rollback()
                return False

    def get_dashboard_fast_stats(self, sort_dir="DESC"):
        """
        ดึงข้อมูลสถิติหน้า Dashboard อย่างรวดเร็วด้วย SQL COUNT(*) และ Correlated Covering Index (v6.28)
        ลดเวลาจาก ~1,190 ms เหลือ ~35 ms โดยผลลัพธ์ตรงกับวิธีเดิม 100%
        """
        s_dir = "ASC" if str(sort_dir).upper() == "ASC" else "DESC"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM staff_members WHERE role = 'teacher'")
            num_teachers = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM staff_members WHERE role = 'student'")
            num_students = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM scanned_photos")
            num_photos = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM detected_faces df JOIN staff_members s ON df.staff_id = s.id")
            num_matches = cursor.fetchone()[0] or 0

            cursor.execute(f"""
                SELECT sm.name, (SELECT COUNT(DISTINCT df.photo_id) FROM detected_faces df WHERE df.staff_id = sm.id) as photo_count
                FROM staff_members sm
                WHERE sm.role = 'teacher' OR sm.role IS NULL OR sm.role = ''
                ORDER BY photo_count {s_dir}, sm.name ASC
                LIMIT 50
            """)
            teacher_rows = cursor.fetchall()

            cursor.execute(f"""
                SELECT sm.name, (SELECT COUNT(DISTINCT df.photo_id) FROM detected_faces df WHERE df.staff_id = sm.id) as photo_count
                FROM staff_members sm
                WHERE sm.role = 'student'
                ORDER BY photo_count {s_dir}, sm.name ASC
                LIMIT 50
            """)
            student_rows = cursor.fetchall()

            return {
                "num_teachers": num_teachers,
                "num_students": num_students,
                "num_photos": num_photos,
                "num_matches": num_matches,
                "teacher_rows": teacher_rows,
                "student_rows": student_rows,
            }

    def get_all_sync_data(self):
        """ดึงข้อมูลทั้งหมดในฐานข้อมูลเพื่อพร้อมอัปเดตลง Google Sheets และ Google Drive JSON Index (v6.23 เพิ่ม face_count, v6.26 academic_year)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # ข้อมูลชีท photos (ดึง photo_date, total_faces_detected, และ academic_year มาด้วย)
            cursor.execute("SELECT photo_id, event_name, drive_link, photo_date, total_faces_detected, academic_year FROM scanned_photos")
            photos = cursor.fetchall()
            
            # ข้อมูลชีท faces (ดึงชื่อคนแทนไอดีเพื่อบันทึกลงชีท พร้อมดึงไอดีแถวการสแกนเป็น face_id)
            cursor.execute("""
                SELECT df.id, s.name, df.photo_id, s.role, s.student_id
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
            """)
            faces = cursor.fetchall()
            
            photo_entries = []
            for p in photos:
                ev_name = p[1] or ""
                p_date = p[3] if p[3] else ""
                academic_year = p[5] if len(p) > 5 and p[5] else ""
                year_val = academic_year.strip()
                if not year_val:
                    # Fallback Priority 2: Auto extract year from event name
                    m_year = re.search(r'25\d\d', ev_name)
                    year_val = m_year.group(0) if m_year else ""
                    if not year_val:
                        m_short = re.search(r'(?:ปี|พ\.ศ\.|\s|^)(6[0-9])(?:\s|$|[^\d])', ev_name)
                        if m_short:
                            year_val = "25" + m_short.group(1)
                    # Fallback Priority 3: จาก photo_date
                    if not year_val and p_date and len(p_date.split('-')) >= 1:
                        try:
                            y_ce = int(p_date.split('-')[0])
                            if y_ce > 1900:
                                year_val = str(y_ce + 543)
                        except Exception:
                            pass
                photo_entries.append({
                    "photo_id": p[0],
                    "event": ev_name,
                    "drive_link": p[2],
                    "date": p_date,
                    "year": year_val,
                    "face_count": int(p[4]) if len(p) > 4 and p[4] is not None else 0
                })

            return {
                "photos": photo_entries,
                "faces": [
                    {
                        "face_id": f[0],
                        "person": f[1],
                        "photo_id": f[2],
                        "role": f[3] if f[3] else "teacher",
                        "student_id": f[4] if f[4] else ""
                    }
                    for f in faces
                ]
            }

    def get_sync_data_sharded(self, active_years=None):
        """
        ดึงข้อมูลทั้งหมดในฐานข้อมูลและจัดเตรียมพาร์ทิชันสำหรับ Sharded Architecture (v6.30)
        - แยกข้อมูลนักเรียน: active_students (status != 'graduated') vs alumni_students (status == 'graduated')
        - จัดกลุ่มรูปภาพแยกตามปีการศึกษา: photo_index_YYYY.json และ photo_index_archive.json
        - สร้างข้อมูล photo_manifest.json
        - คงรูปแบบเดิมสำหรับ Dual-Write (Legacy Compatibility 100%)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # ดึงข้อมูล scanned_photos
            cursor.execute("SELECT photo_id, event_name, drive_link, photo_date, total_faces_detected, academic_year FROM scanned_photos")
            photos = cursor.fetchall()
            
            # ดึงข้อมูล faces พร้อมสถานะ status และ student_id
            cursor.execute("""
                SELECT df.id, s.name, df.photo_id, s.role, s.student_id, COALESCE(s.status, 'active') as status
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
            """)
            faces = cursor.fetchall()
            
            photo_entries = []
            photo_year_map = {}
            for p in photos:
                ev_name = p[1] or ""
                p_date = p[3] if p[3] else ""
                academic_year = p[5] if len(p) > 5 and p[5] else ""
                year_val = academic_year.strip()
                if not year_val:
                    m_year = re.search(r'25\d\d', ev_name)
                    year_val = m_year.group(0) if m_year else ""
                    if not year_val:
                        m_short = re.search(r'(?:ปี|พ\.ศ\.|\s|^)(6[0-9])(?:\s|$|[^\d])', ev_name)
                        if m_short:
                            year_val = "25" + m_short.group(1)
                    if not year_val and p_date and len(p_date.split('-')) >= 1:
                        try:
                            y_ce = int(p_date.split('-')[0])
                            if y_ce > 1900:
                                year_val = str(y_ce + 543)
                        except Exception:
                            pass
                entry = {
                    "photo_id": p[0],
                    "event": ev_name,
                    "drive_link": p[2],
                    "date": p_date,
                    "year": year_val,
                    "face_count": int(p[4]) if len(p) > 4 and p[4] is not None else 0
                }
                photo_entries.append(entry)
                photo_year_map[p[0]] = year_val

            # กำหนดรายชื่อปีที่จะแยกเป็นไฟล์ Shard เดี่ยว (สร้างไฟล์แยกเดี่ยวครบถ้วนทุกปีการศึกษา 2563-2569 และอนาคต)
            if not active_years:
                all_years = sorted(list({y for y in photo_year_map.values() if y and y.startswith('25') and len(y) == 4 and y.isdigit()}), reverse=True)
                active_years = all_years

            photos_by_shard = {y: {} for y in active_years}
            photos_by_shard["archive"] = {}
            shard_counts = {y: 0 for y in active_years}
            shard_counts["archive"] = 0

            for entry in photo_entries:
                pid = entry["photo_id"]
                y = entry["year"]
                shard_key = y if y in active_years else "archive"
                photos_by_shard[shard_key][pid] = entry
                shard_counts[shard_key] += 1

            # แยกกลุ่มนักเรียนและคุณครู (Sharded: Active Staff vs Former Staff - v6.38/v6.40)
            active_students = {}
            alumni_students = {}
            active_staff = {}
            former_staff = {}
            teachers = {}  # สำหรับ Dual-Write Compatibility

            # ตั้งต้นรายชื่อสมาชิกทุกคนจาก staff_members เพื่อความสมบูรณ์ 100% (Full Member Inclusion - v6.40)
            # สมาชิกที่ยังไม่มีรูปสแกนในระบบ จะมีค่าเป็นอาร์เรย์ว่าง [] เสมอ เพื่อให้ค้นหาชื่อพบได้ครบทุกคน
            cursor.execute("SELECT id, name, role, student_id, COALESCE(status, 'active') FROM staff_members ORDER BY name ASC")
            all_members = cursor.fetchall()
            for m in all_members:
                m_name = m[1]
                m_role = m[2] if m[2] else "teacher"
                m_sid = m[3] if m[3] else ""
                m_status = m[4] if m[4] else "active"

                if m_role == "student":
                    target_dict = alumni_students if m_status == "graduated" else active_students
                    if m_name not in target_dict:
                        target_dict[m_name] = {
                            "photos": [],
                            "years": [],
                            "student_id": m_sid
                        }
                else:
                    if m_status == "inactive":
                        if m_name not in former_staff:
                            former_staff[m_name] = []
                    else:
                        if m_name not in active_staff:
                            active_staff[m_name] = []
                        if m_name not in teachers:
                            teachers[m_name] = []

            for f in faces:
                person_name = f[1]
                pid = f[2]
                role = f[3] if f[3] else "teacher"
                student_id = f[4] if f[4] else ""
                status = f[5] if f[5] else "active"
                p_year = photo_year_map.get(pid, "")

                if role == "student":
                    target_dict = alumni_students if status == "graduated" else active_students
                    if person_name not in target_dict:
                        target_dict[person_name] = {
                            "photos": [],
                            "years": [],
                            "student_id": student_id
                        }
                    if pid not in target_dict[person_name]["photos"]:
                        target_dict[person_name]["photos"].append(pid)
                    if p_year and p_year not in target_dict[person_name]["years"]:
                        target_dict[person_name]["years"].append(p_year)
                else:
                    # คุณครู/บุคลากร: แยก active_staff (status != 'inactive') และ former_staff (status == 'inactive')
                    target_staff = former_staff if status == "inactive" else active_staff
                    if person_name not in target_staff:
                        target_staff[person_name] = []
                    if pid not in target_staff[person_name]:
                        target_staff[person_name].append(pid)

                    # สำหรับ Legacy teachers (Dual-Write Compatibility กับ person_index.json)
                    if status != "inactive":
                        if person_name not in teachers:
                            teachers[person_name] = []
                        if pid not in teachers[person_name]:
                            teachers[person_name].append(pid)

            # เรียงลำดับปีของนักเรียนแต่ละคนจากล่าสุดไปหาอดีต
            for s_dict in [active_students, alumni_students]:
                for k, v in s_dict.items():
                    v["years"] = sorted(v["years"], reverse=True)

            available_shards = list(active_years)
            year_file_map = {y: f"photo_index_{y}.json" for y in active_years}
            if shard_counts.get("archive", 0) > 0:
                available_shards.append("archive")
                year_file_map["archive"] = "photo_index_archive.json"

            manifest = {
                "version": "v6.59",
                "updated_at": datetime.now().isoformat(),
                "available_years": available_shards,
                "year_file_map": year_file_map,
                "year_counts": shard_counts,
                "total_photos": len(photo_entries),
                "staff_file": "staff_index.json",
                "former_staff_file": "former_staff_index.json",
                "staff_counts": {
                    "active": len(active_staff),
                    "former": len(former_staff)
                }
            }

            return {
                "active_students": active_students,
                "alumni_students": alumni_students,
                "active_staff": active_staff,
                "former_staff": former_staff,
                "teachers": teachers,
                "photos_by_shard": photos_by_shard,
                "manifest": manifest,
                "photos": photo_entries,
                "faces": [
                    {
                        "face_id": f[0],
                        "person": f[1],
                        "photo_id": f[2],
                        "role": f[3] if f[3] else "teacher",
                        "student_id": f[4] if f[4] else ""
                    }
                    for f in faces
                ]
            }

    def get_archive_crowdsource_data(self, academic_year="25xx", sync_manager=None):
        """
        ดึงข้อมูลภาพกิจกรรมในอดีต (2562-25xx) พร้อมพิกัดใบหน้าทั้งหมดในหน่วยเปอร์เซ็นต์
        สำหรับ Crowdsourcing Tagging บนเว็บ (v6.49):
        - ไม่มีข้อมูลชื่อหรือตำแหน่งของบุคคล (เพื่อให้ผู้ใช้บนเว็บระบุชื่อเอง)
        - แต่ละรูปภาพมีรายการใบหน้าพร้อม box_pct (สำหรับครอปทำ Avatar) และ center_pct (สำหรับ Hover วงกลม)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. ดึงรายการรูปภาพทั้งหมดในปีการศึกษาที่กำหนด (เช่น '25xx')
            cursor.execute("""
                SELECT photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, total_faces_detected,
                       COALESCE(image_width, 0), COALESCE(image_height, 0)
                FROM scanned_photos
                WHERE academic_year = ?
                ORDER BY photo_date DESC, photo_id ASC
            """, (academic_year,))
            photos = cursor.fetchall()
            
            if not photos:
                return {
                    "schema_version": 1,
                    "photos": {}
                }

            # 2. ตรวจสอบรูปภาพที่ยังไม่มีมิติภาพ (image_width <= 0 หรือ image_height <= 0)
            # และเติมเต็มจาก Drive API (Batch)
            missing_dim_fids = [p[1] for p in photos if p[7] <= 0 or p[8] <= 0]
            fetched_dims = {}
            if missing_dim_fids and sync_manager and hasattr(sync_manager, 'drive_service') and sync_manager.drive_service:
                try:
                    def _batch_cb(req_id, response, exception):
                        if not exception and response:
                            meta = response.get('imageMediaMetadata', {})
                            w = meta.get('width', 0)
                            h = meta.get('height', 0)
                            rot = meta.get('rotation', 0)
                            if rot in (1, 3):
                                w, h = h, w
                            if w > 0 and h > 0:
                                fetched_dims[req_id] = (w, h)
                    
                    chunk_size = 50
                    for i in range(0, len(missing_dim_fids), chunk_size):
                        chunk = missing_dim_fids[i:i + chunk_size]
                        batch = sync_manager.drive_service.new_batch_http_request(callback=_batch_cb)
                        for fid in chunk:
                            batch.add(sync_manager.drive_service.files().get(fileId=fid, fields='id,imageMediaMetadata'), request_id=fid)
                        batch.execute()

                    if fetched_dims:
                        update_rows = [(w, h, fid) for fid, (w, h) in fetched_dims.items()]
                        cursor.executemany("UPDATE scanned_photos SET image_width = ?, image_height = ? WHERE drive_file_id = ?", update_rows)
                        conn.commit()
                        logger.info(f"[DB] Backfilled image dimensions for {len(fetched_dims)} photos to SQLite.")
                except Exception as b_err:
                    logger.warning(f"[DB] Could not batch fetch dimensions from Drive: {b_err}")

            # 3. ดึงพิกัดใบหน้าทั้งหมดจาก scanned_photo_faces
            photo_ids = [p[0] for p in photos]
            placeholders = ",".join("?" for _ in photo_ids)
            cursor.execute(f"""
                SELECT photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM scanned_photo_faces
                WHERE photo_id IN ({placeholders}) AND face_index >= 0
                ORDER BY photo_id ASC, face_index ASC
            """, photo_ids)
            faces_raw = cursor.fetchall()

            faces_by_photo = {}
            for r in faces_raw:
                pid, f_idx, x1, y1, x2, y2 = r
                if pid not in faces_by_photo:
                    faces_by_photo[pid] = []
                faces_by_photo[pid].append((f_idx, float(x1), float(y1), float(x2), float(y2)))

            # 4. ประกอบข้อมูลในแต่ละรูปภาพ (Ultra-Minimal Schema v6.56)
            photo_dict = {}

            for p in photos:
                pid, fid, ev_name, d_link, p_date, fname, face_cnt, db_w, db_h = p
                pid_str = str(pid) if str(pid).startswith('P') else f"P{pid}"
                
                # ตรวจสอบขนาดภาพ
                dim = fetched_dims.get(fid)
                w = dim[0] if dim else db_w
                h = dim[1] if dim else db_h
                
                raw_faces = faces_by_photo.get(pid, [])
                
                # Fallback หาขนาดภาพถ้ายังเป็น 0
                if w <= 0 or h <= 0:
                    if raw_faces:
                        max_x = max(f[3] for f in raw_faces)
                        max_y = max(f[4] for f in raw_faces)
                        w = max(2000, int(max_x * 1.15))
                        h = max(1500, int(max_y * 1.15))
                    else:
                        w, h = 2880, 1920

                face_list = []
                for f_idx, x1, y1, x2, y2 in raw_faces:
                    left = max(0.0, min(float(w), float(x1)))
                    top = max(0.0, min(float(h), float(y1)))
                    right = max(0.0, min(float(w), float(x2)))
                    bottom = max(0.0, min(float(h), float(y2)))
                    bw = right - left
                    bh = bottom - top
                    if bw <= 0 or bh <= 0:
                        continue
                    
                    left_pct = round((left / w) * 100.0, 2)
                    top_pct = round((top / h) * 100.0, 2)
                    width_pct = round((bw / w) * 100.0, 2)
                    height_pct = round((bh / h) * 100.0, 2)

                    face_list.append({
                        "face_id": f"{pid_str}_F{int(f_idx) + 1:03d}",
                        "box_pct": {
                            "left": left_pct,
                            "top": top_pct,
                            "width": width_pct,
                            "height": height_pct
                        }
                    })

                photo_dict[pid_str] = {
                    "drive_file_id": fid,
                    "dimensions": {
                        "width": int(w),
                        "height": int(h)
                    },
                    "faces": face_list
                }

            return {
                "schema_version": 1,
                "photos": photo_dict
            }

    def clear_scan_history(self):
        """ล้างประวัติการสแกนรูปภาพกิจกรรมทั้งหมด (เก็บข้อมูลครูต้นแบบไว้)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scanned_photos")
            conn.commit()
            logger.info("Cleared all scan history from SQLite.")

    def delete_photo_scan_record(self, drive_file_id):
        """ลบข้อมูลการสแกนรูปภาพนี้ใน SQLite เพื่อเตรียมเขียนทับข้อมูลการตรวจพบใบหน้าแบบละเอียด (สแกนซ้ำ Re-scan)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # ค้นหา photo_id จาก drive_file_id ก่อน
                cursor.execute("SELECT photo_id FROM scanned_photos WHERE drive_file_id = ?", (drive_file_id,))
                row = cursor.fetchone()
                if row:
                    photo_id = row[0]
                    # ลบความสัมพันธ์ใบหน้าที่เคยสแกนในรูปนี้ใน detected_faces
                    cursor.execute("DELETE FROM detected_faces WHERE photo_id = ?", (photo_id,))
                    # ลบแถวข้อมูลรูปภาพใน scanned_photos
                    cursor.execute("DELETE FROM scanned_photos WHERE photo_id = ?", (photo_id,))
                    conn.commit()
                    logger.debug(f"[DATABASE] Deleted old SQLite match records for photo_id: {photo_id}")
                    return True
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error deleting scan record for drive file {drive_file_id}: {e}")
                conn.rollback()
        return False

    def get_photo_id_by_drive_id(self, drive_file_id):
        """ดึง photo_id จาก drive_file_id"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id FROM scanned_photos WHERE drive_file_id = ?", (drive_file_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_next_photo_serial(self):
        """ดึงเลขลำดับถัดไปของ photo_id แบบ Pxxxxx (เช่น P43682)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id FROM scanned_photos WHERE photo_id LIKE 'P%' ORDER BY CAST(SUBSTR(photo_id, 2) AS INTEGER) DESC LIMIT 1")
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    num_part = int(row[0][1:])
                    return num_part + 1
                except ValueError:
                    pass
            return 1

    def has_cached_faces(self, photo_id):
        """ตรวจสอบว่ารูปนี้มีแคชใบหน้าบันทึกไว้ในตารางหรือไม่"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM scanned_photo_faces WHERE photo_id = ? LIMIT 1", (photo_id,))
            return cursor.fetchone() is not None

    def save_photo_face_embeddings(self, photo_id, faces):
        """บันทึกแคชเวกเตอร์ใบหน้าทั้งหมดในรูปภาพกิจกรรม (รวมกรณีไม่พบใบหน้าด้วย)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if not faces:
                    # บันทึกข้อมูลจำลอง (Dummy) เพื่อระบุว่ารูปนี้สแกนแล้วแต่ไม่มีใบหน้า (0 faces)
                    cursor.execute(
                        """
                        INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (photo_id, -1, 0.0, 0.0, 0.0, 0.0, b"")
                    )
                else:
                    for idx, f in enumerate(faces):
                        bbox = f.bbox
                        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                        emb_bytes = f.embedding.astype(np.float32).tobytes()
                        cursor.execute(
                            """
                            INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (photo_id, idx, x1, y1, x2, y2, emb_bytes)
                        )
                conn.commit()
                logger.info(f"Saved {len(faces)} face embeddings to cache for photo_id: {photo_id}")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving face embeddings cache for photo_id {photo_id}: {e}")
                conn.rollback()
                return False

    def get_photo_face_embeddings(self, photo_id):
        """ดึงเวกเตอร์ใบหน้าและกรอบใบหน้าทั้งหมดของรูปที่เซฟในแคชกลับมา (ไม่ดึง Dummy แถว -1)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding
                FROM scanned_photo_faces
                WHERE photo_id = ? AND face_index >= 0
                ORDER BY face_index ASC
                """,
                (photo_id,)
            )
            rows = cursor.fetchall()
            cached_faces = []
            for r in rows:
                bbox = np.array([r[0], r[1], r[2], r[3]], dtype=np.float32)
                emb = np.frombuffer(r[4], dtype=np.float32)
                cached_faces.append(CachedFace(bbox, emb))
            return cached_faces

    def delete_photo_matches(self, photo_id):
        """ลบผลลัพธ์การจับคู่ใบหน้าเฉพาะรูปนี้ใน detected_faces (เก็บประวัติแคชและรูปถ่ายไว้)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM detected_faces WHERE photo_id = ?", (photo_id,))
                conn.commit()
                logger.debug(f"[DATABASE] Deleted old detected matches for photo_id: {photo_id}")
                return True
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error deleting matches for photo_id {photo_id}: {e}")
                conn.rollback()
                return False

    def save_detected_faces(self, photo_id, matches):
        """บันทึกความเชื่อมโยงใบหน้าใหม่ (matches: list ของ tuple (staff_id, confidence))"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                for staff_id, confidence in matches:
                    cursor.execute(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        (photo_id, staff_id, float(confidence))
                    )
                conn.commit()
                # logger.debug(f"Saved {len(matches)} matches to detected_faces for photo_id: {photo_id}")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving detected faces for photo_id {photo_id}: {e}")
                conn.rollback()
                return False

    def delete_photo_matches_selective(self, photo_id, staff_ids):
        """ลบผลการจับคู่เฉพาะของครูบางคนในรูปนี้ (staff_ids เป็น list หรือ tuple ของ ID ครู)"""
        if not staff_ids:
            return True
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in staff_ids)
                cursor.execute(
                    f"DELETE FROM detected_faces WHERE photo_id = ? AND staff_id IN ({placeholders})",
                    [photo_id] + list(staff_ids)
                )
                conn.commit()
                logger.debug(f"[DATABASE] Deleted selective matches for photo_id: {photo_id}, staff_ids: {staff_ids}")
                return True
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error deleting selective matches for photo_id {photo_id}: {e}")
                conn.rollback()
                return False

    def get_batch_photo_face_embeddings(self, drive_file_ids):
        """ดึงเวกเตอร์ใบหน้าแคชทั้งหมดในโฟลเดอร์รวดเดียวใน 1 Query (drive_file_ids: list ของ Drive File ID)"""
        if not drive_file_ids:
            return {}
        result = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in drive_file_ids)
                query = f"""
                    SELECT p.photo_id, p.drive_file_id, p.event_name, pf.embedding
                    FROM scanned_photos p
                    JOIN scanned_photo_faces pf ON p.photo_id = pf.photo_id
                    WHERE p.drive_file_id IN ({placeholders})
                """
                cursor.execute(query, list(drive_file_ids))
                rows = cursor.fetchall()
                for pid, fid, event_name, emb_blob in rows:
                    if pid not in result:
                        result[pid] = {
                            "drive_file_id": fid,
                            "event_name": event_name,
                            "embeddings": []
                        }
                    if emb_blob:
                        try:
                            emb = np.frombuffer(emb_blob, dtype=np.float32)
                            result[pid]["embeddings"].append(emb)
                        except Exception as e:
                            logger.error(f"[DATABASE] Error decoding face embedding blob for photo {pid}: {e}")
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error in get_batch_photo_face_embeddings: {e}")
        return result

    def safe_float(self, val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, bytes):
            try:
                import struct
                if len(val) == 4:
                    return float(struct.unpack('<f', val)[0])
                elif len(val) == 8:
                    return float(struct.unpack('<d', val)[0])
            except Exception:
                pass
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    def batch_save_detected_faces(self, photo_matches_dict):
        """บันทึกความเชื่อมโยงใบหน้าแบบ Batch ทั้งโฟลเดอร์ใน 1 Transaction (photo_matches_dict: {photo_id: [(staff_id, confidence), ...]})"""
        if not photo_matches_dict:
            return True
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                photo_ids = list(photo_matches_dict.keys())
                placeholders = ",".join("?" for _ in photo_ids)
                cursor.execute(f"DELETE FROM detected_faces WHERE photo_id IN ({placeholders})", photo_ids)

                insert_rows = []
                for pid, matches in photo_matches_dict.items():
                    for staff_id, confidence in matches:
                        insert_rows.append((pid, staff_id, float(confidence)))

                if insert_rows:
                    cursor.executemany(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        insert_rows
                    )
                conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error in batch_save_detected_faces: {e}")
                conn.rollback()
                return False

    def get_matched_photos_for_staff(self, staff_id):
        """ดึงประวัติรูปภาพกิจกรรมทั้งหมดที่สแกนพบบุคคลนี้ (staff_id) เรียงจากวันที่ใหม่ล่าสุดไปเก่าสุด"""
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                query = """
                    SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.photo_date, p.academic_year, MAX(df.confidence) as max_conf
                    FROM detected_faces df
                    JOIN scanned_photos p ON df.photo_id = p.photo_id
                    WHERE df.staff_id = ?
                    GROUP BY p.photo_id
                    ORDER BY p.photo_date DESC, p.photo_id DESC
                """
                cursor.execute(query, (staff_id,))
                rows = cursor.fetchall()
                for pid, fid, event, link, pdate, a_year, conf in rows:
                    results.append({
                        "photo_id": pid,
                        "drive_file_id": fid,
                        "event_name": event or "กิจกรรมทั่วไป",
                        "drive_link": link or f"https://drive.google.com/file/d/{fid}/view",
                        "photo_date": pdate or "ไม่ระบุวันที่",
                        "academic_year": a_year or "",
                        "confidence": self.safe_float(conf)
                    })
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error in get_matched_photos_for_staff for staff_id {staff_id}: {e}")
        return results

    def get_unbackfilled_students(self):
        """ดึงรายการ staff_id ของนักเรียนที่เพิ่งเพิ่มใหม่ หรืออัปเดตรูปใหม่ (is_backfilled = 0)"""
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id, name, role, student_id FROM staff_members WHERE is_backfilled = 0 AND role = 'student'")
                for row in cursor.fetchall():
                    results.append({"staff_id": row[0], "name": row[1], "role": row[2], "student_id": row[3]})
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error getting unbackfilled students: {e}")
        return results

    def get_unbackfilled_teachers(self):
        """ดึงรายการ staff_id ของคุณครูที่เพิ่งเพิ่มใหม่ หรืออัปเดตรูปใหม่ (is_backfilled = 0 และ role = 'teacher')"""
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT id, name, role, student_id 
                    FROM staff_members 
                    WHERE is_backfilled = 0 AND (role = 'teacher' OR role IS NULL OR role = '')
                """)
                for row in cursor.fetchall():
                    results.append({"staff_id": row[0], "name": row[1], "role": row[2] if row[2] else "teacher", "student_id": row[3]})
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error getting unbackfilled teachers: {e}")
        return results

    def mark_students_backfilled(self, staff_ids):
        """อัปเดตสถานะ is_backfilled = 1 หลังจากแมตช์ย้อนหลังสำเร็จ"""
        if not staff_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in staff_ids)
                cursor.execute(f"UPDATE staff_members SET is_backfilled = 1 WHERE id IN ({placeholders})", staff_ids)
                conn.commit()
                logger.info(f"Marked {len(staff_ids)} students as backfilled.")
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error marking students backfilled: {e}")

    def mark_teachers_backfilled(self, staff_ids):
        """อัปเดตสถานะ is_backfilled = 1 หลังจากแมตช์ย้อนหลังของคุณครูสำเร็จ"""
        if not staff_ids:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in staff_ids)
                cursor.execute(f"UPDATE staff_members SET is_backfilled = 1 WHERE id IN ({placeholders})", staff_ids)
                conn.commit()
                logger.info(f"Marked {len(staff_ids)} teachers as backfilled.")
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error marking teachers backfilled: {e}")

    def clear_staff_embeddings(self, staff_id):
        """ลบเวกเตอร์ใบหน้าทั้งหมดของ staff_id นี้ (เพื่อเตรียมรับรูปใหม่)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
                conn.commit()
                logger.debug(f"Cleared embeddings for staff_id: {staff_id}")
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error clearing embeddings for {staff_id}: {e}")

    def set_staff_backfill_status(self, staff_id, status=0):
        """เซตค่า is_backfilled ของ staff_id นี้"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE staff_members SET is_backfilled = ? WHERE id = ?", (status, staff_id))
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error setting backfill status for {staff_id}: {e}")

    def get_scanned_event_names(self):
        """ดึงรายชื่อ event_name ทั้งหมดที่เคยสแกนไปแล้ว (เพื่อใช้อ้างอิงแสดงแถบสีเขียวบน GUI)"""
        events = set()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT DISTINCT event_name FROM scanned_photos")
                for row in cursor.fetchall():
                    if row[0]:
                        events.add(row[0])
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error getting scanned event names: {e}")
        return events

    def purge_zero_face_scanned_photos(self):
        """
        ลบรายการรูปภาพใน scanned_photos ที่ไม่มีใบหน้าตรวจพบ (0 Faces)
        เพื่อให้ระบบสแกนอัตโนมัติ (Task 1) นำภาพกลับมาถอดรหัสใหม่ด้วย Multi-Format Decoder (รองรับ Apple HEIC) (v5.90 / v6.28 Indexed)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT photo_id, event_name
                    FROM scanned_photos p
                    WHERE COALESCE(p.total_faces_detected, 0) = 0
                """)
                rows = cursor.fetchall()
                if not rows:
                    logger.info("[DATABASE] ไม่มีรูปภาพ 0 Faces ที่ต้องล้าง")
                    return []

                photo_ids = [r[0] for r in rows]
                events = list(set(r[1] for r in rows if r[1]))
                
                cursor.execute("""
                    DELETE FROM scanned_photos
                    WHERE COALESCE(total_faces_detected, 0) = 0
                """)
                conn.commit()
                logger.info(f"[DATABASE] ✅ ล้างรูปภาพ 0 Faces สำเร็จ {len(photo_ids):,} รูป จาก {len(events)} กิจกรรม เพื่อเตรียมสแกนใหม่ด้วย Multi-Format HEIC Decoder")
                return events
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error purging 0-face photos: {e}")
                return []

    # =========================================================================
    # ระบบสถิติและจัดกลุ่มใบหน้าบุคคลนิรนาม (v6.20 Unknown Faces Analytics)
    # =========================================================================
    def get_unmatched_face_embeddings(self):
        """
        ดึงเวกเตอร์ใบหน้าทั้งหมดจาก scanned_photo_faces ที่ยังไม่เคยถูกจับคู่ใน detected_faces
        คืนค่า: ลิสต์ของดิกชันนารี [{photo_id, face_index, embedding, photo_date, event_name, bbox}]
        """
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT pf.photo_id, pf.face_index, pf.bbox_x1, pf.bbox_y1, pf.bbox_x2, pf.bbox_y2, pf.embedding,
                       p.photo_date, p.event_name
                FROM scanned_photo_faces pf
                JOIN scanned_photos p ON pf.photo_id = p.photo_id
                WHERE pf.face_index >= 0
                  AND NOT EXISTS (
                      SELECT 1 FROM detected_faces df 
                      WHERE df.photo_id = pf.photo_id
                  )
            """
            cursor.execute(query)
            for row in cursor.fetchall():
                pid, f_idx, x1, y1, x2, y2, emb_blob, p_date, event = row
                if emb_blob:
                    results.append({
                        "photo_id": pid,
                        "face_index": f_idx,
                        "bbox": [x1, y1, x2, y2],
                        "embedding": emb_blob,
                        "photo_date": p_date or "",
                        "event_name": event or ""
                    })
        return results

    def save_unknown_clusters_batch(self, clusters_data, members_data, year_stats_data):
        """บันทึกผลการจัดกลุ่มสถิติบุคคลนิรนามแบบ Batch ใน 1 Transaction (ล้างของเก่าก่อนบันทึกใหม่)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM unknown_cluster_year_stats")
                cursor.execute("DELETE FROM unknown_cluster_members")
                cursor.execute("DELETE FROM unknown_clusters")

                # 1. บันทึก unknown_clusters
                if clusters_data:
                    c_rows = [
                        (c["cluster_id"], c["photo_count"], c["event_count"], c.get("rep_photo_id", ""),
                         c.get("rep_face_index", 0), json.dumps(c.get("rep_bbox", [])),
                         c.get("first_seen_year", ""), c.get("last_seen_year", ""), c.get("active_years", ""))
                        for c in clusters_data
                    ]
                    cursor.executemany("""
                        INSERT INTO unknown_clusters 
                        (cluster_id, photo_count, event_count, rep_photo_id, rep_face_index, rep_bbox, first_seen_year, last_seen_year, active_years)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, c_rows)

                # 2. บันทึก unknown_cluster_members
                if members_data:
                    m_rows = [
                        (m["cluster_id"], m["photo_id"], m["face_index"], m["year"], m.get("event_name", ""), m.get("confidence", 0.0))
                        for m in members_data
                    ]
                    cursor.executemany("""
                        INSERT INTO unknown_cluster_members
                        (cluster_id, photo_id, face_index, year, event_name, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, m_rows)

                # 3. บันทึก unknown_cluster_year_stats
                if year_stats_data:
                    y_rows = [
                        (y["cluster_id"], y["year"], y["photo_count"], y.get("rep_photo_id", ""), y.get("rep_face_index", 0))
                        for y in year_stats_data
                    ]
                    cursor.executemany("""
                        INSERT INTO unknown_cluster_year_stats
                        (cluster_id, year, photo_count, rep_photo_id, rep_face_index)
                        VALUES (?, ?, ?, ?, ?)
                    """, y_rows)

                conn.commit()
                logger.info(f"[DATABASE] Saved {len(clusters_data)} unknown clusters, {len(members_data)} members, {len(year_stats_data)} year stats.")
                return True
            except Exception as e:
                logger.error(f"[DATABASE] Error saving unknown clusters batch: {e}", exc_info=True)
                conn.rollback()
                return False

    def get_unknown_clusters_summary(self, selected_year="all", min_photos=1):
        """ดึงรายการจัดอันดับบุคคลนิรนามตามเงื่อนไขปีและจำนวนรูปขั้นต่ำ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if selected_year == "all":
                query = """
                    SELECT cluster_id, photo_count, event_count, rep_photo_id, rep_face_index, 
                           rep_bbox, first_seen_year, last_seen_year, active_years
                    FROM unknown_clusters
                    WHERE photo_count >= ?
                    ORDER BY photo_count DESC
                """
                cursor.execute(query, (min_photos,))
            else:
                query = """
                    SELECT c.cluster_id, y.photo_count as year_photos, c.photo_count as total_photos,
                           c.event_count, y.rep_photo_id, y.rep_face_index, c.rep_bbox,
                           c.first_seen_year, c.last_seen_year, c.active_years
                    FROM unknown_cluster_year_stats y
                    JOIN unknown_clusters c ON y.cluster_id = c.cluster_id
                    WHERE y.year = ? AND y.photo_count >= ?
                    ORDER BY y.photo_count DESC
                """
                cursor.execute(query, (selected_year, min_photos))
            return cursor.fetchall()

    def get_unknown_cluster_yearly_breakdown(self, cluster_id):
        """ดึงสถิติจำนวนรูปแยกตามปี พ.ศ. เรียงจากปัจจุบันไปหาอดีต"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT year, photo_count, rep_photo_id, rep_face_index
                FROM unknown_cluster_year_stats
                WHERE cluster_id = ?
                ORDER BY CAST(year AS INTEGER) DESC
            """, (cluster_id,))
            return cursor.fetchall()

    def get_unknown_cluster_member_photos(self, cluster_id, filter_year=None):
        """ดึงรูปถ่ายกิจกรรมทั้งหมดที่มีบุคคลนิรนามนี้ปรากฏตัว"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if filter_year and filter_year != "all":
                query = """
                    SELECT m.photo_id, m.face_index, m.year, m.event_name, p.drive_link, p.photo_date, pf.bbox_x1, pf.bbox_y1, pf.bbox_x2, pf.bbox_y2
                    FROM unknown_cluster_members m
                    LEFT JOIN scanned_photos p ON m.photo_id = p.photo_id
                    LEFT JOIN scanned_photo_faces pf ON m.photo_id = pf.photo_id AND m.face_index = pf.face_index
                    WHERE m.cluster_id = ? AND m.year = ?
                    ORDER BY p.photo_date DESC, m.photo_id DESC
                """
                cursor.execute(query, (cluster_id, filter_year))
            else:
                query = """
                    SELECT m.photo_id, m.face_index, m.year, m.event_name, p.drive_link, p.photo_date, pf.bbox_x1, pf.bbox_y1, pf.bbox_x2, pf.bbox_y2
                    FROM unknown_cluster_members m
                    LEFT JOIN scanned_photos p ON m.photo_id = p.photo_id
                    LEFT JOIN scanned_photo_faces pf ON m.photo_id = pf.photo_id AND m.face_index = pf.face_index
                    WHERE m.cluster_id = ?
                    ORDER BY p.photo_date DESC, m.photo_id DESC
                """
                cursor.execute(query, (cluster_id,))
            return cursor.fetchall()

    def get_unknown_available_years(self):
        """ดึงรายชื่อปี พ.ศ. ทั้งหมดที่มีข้อมูลใน unknown_cluster_year_stats เรียงจากปัจจุบันไปหาอดีต"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT year FROM unknown_cluster_year_stats ORDER BY CAST(year AS INTEGER) DESC")
            return [row[0] for row in cursor.fetchall() if row[0] and row[0] != "ไม่ระบุปี"]

    # =========================================================================
    # 8. ระบบจัดการโฟลเดอร์หลักประจำปีการศึกษา (v6.27 Root Year Folders Management)
    # =========================================================================
    @staticmethod
    def extract_year_from_text(text):
        """สกัดเลขปี พ.ศ. 4 หลักจากข้อความ (หากเป็น ค.ศ. จะบวก 543 ให้อัตโนมัติ)"""
        if not text:
            return ""
        text_str = str(text)
        m_be = re.search(r'(?<!\d)(25[5-8]\d)(?!\d)', text_str)
        if m_be:
            return m_be.group(1)
        m_ce = re.search(r'(?<!\d)(20[1-4]\d)(?!\d)', text_str)
        if m_ce:
            return str(int(m_ce.group(1)) + 543)
        return ""

    def create_root_year_folders_table(self):
        """สร้างตาราง root_year_folders และนำเข้าข้อมูลเริ่มต้นจาก config/year_folders.json อัตโนมัติหากตารางว่าง (v6.27)"""
        default_seed_folders = [
            {"name": "ภาพกิจกรรม 2569", "id": "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ", "academic_year": "2569", "is_active": 1},
            {"name": "ภาพกิจกรรม 2568", "id": "1YYkDLsalb0jVM0K876lcejLoiggoJ18N", "academic_year": "2568", "is_active": 1},
            {"name": "ภาพกิจกรรม 2567", "id": "1ocR4srmu1tA1nYgJOhoM9I0KDVMmbRGF", "academic_year": "2567", "is_active": 1},
            {"name": "ภาพกิจกรรม 2566", "id": "1ZMhLENv8u-onIhVzwBTxCzjJVQVCriVd", "academic_year": "2566", "is_active": 1},
            {"name": "ภาพกิจกรรม 2565", "id": "1cN-3d_mz_9CAbAwLOFKil22bBr0xgasL", "academic_year": "2565", "is_active": 1},
            {"name": "ภาพกิจกรรม 2563", "id": "1uE8wHS5MNxscTIif9TmRLoxd5ptK16_t", "academic_year": "2563", "is_active": 1},
        ]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS root_year_folders (
                folder_id TEXT PRIMARY KEY,
                folder_name TEXT NOT NULL,
                academic_year TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ryf_year ON root_year_folders(academic_year DESC, sort_order ASC)")
            except Exception as e:
                logger.warning(f"Could not create idx_ryf_year index: {e}")

            cursor.execute("SELECT COUNT(*) FROM root_year_folders")
            existing_cnt = cursor.fetchone()[0]

            if existing_cnt == 0:
                seed_items = []
                # ลองโหลดจากไฟล์ JSON ปัจจุบันก่อน
                for json_candidate in [self.year_folders_json_path, self._default_year_folders_json_path]:
                    if json_candidate and os.path.exists(json_candidate):
                        try:
                            with open(json_candidate, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                if isinstance(data, list) and len(data) > 0:
                                    seed_items = data
                                    break
                        except Exception as e:
                            logger.warning(f"Failed to read seed JSON {json_candidate}: {e}")

                if not seed_items:
                    seed_items = default_seed_folders

                for idx, item in enumerate(seed_items):
                    f_id = str(item.get("id") or item.get("folder_id") or "").strip()
                    f_name = str(item.get("name") or item.get("folder_name") or "").strip()
                    if not f_id or not f_name:
                        continue
                    f_year = str(item.get("academic_year") or "").strip()
                    if not f_year:
                        f_year = self.extract_year_from_text(f_name)
                    f_active = 1 if item.get("is_active", 1) else 0
                    f_order = int(item.get("sort_order", idx + 1))
                    cursor.execute("""
                        INSERT OR IGNORE INTO root_year_folders
                        (folder_id, folder_name, academic_year, is_active, sort_order)
                        VALUES (?, ?, ?, ?, ?)
                    """, (f_id, f_name, f_year, f_active, f_order))
                conn.commit()
                logger.info(f"Seeded {len(seed_items)} root year folders into SQLite root_year_folders table.")

    def get_root_year_folders(self, active_only=False, include_photo_counts=False):
        """
        ดึงรายการโฟลเดอร์หลักประจำปีการศึกษาจากตาราง root_year_folders (v6.27)
        คืนค่าเป็น List ของ Dict ที่มีทั้งคีย์ id/folder_id และ name/folder_name เพื่อความเข้ากันได้ 100%
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("""
                    SELECT folder_id, folder_name, academic_year, is_active, sort_order, created_at
                    FROM root_year_folders
                    WHERE is_active = 1
                    ORDER BY CAST(CASE WHEN academic_year GLOB '[0-9][0-9][0-9][0-9]' THEN academic_year ELSE '0' END AS INTEGER) DESC,
                             sort_order ASC,
                             folder_name DESC
                """)
            else:
                cursor.execute("""
                    SELECT folder_id, folder_name, academic_year, is_active, sort_order, created_at
                    FROM root_year_folders
                    ORDER BY CAST(CASE WHEN academic_year GLOB '[0-9][0-9][0-9][0-9]' THEN academic_year ELSE '0' END AS INTEGER) DESC,
                             sort_order ASC,
                             folder_name DESC
                """)
            rows = cursor.fetchall()

            year_counts = {}
            if include_photo_counts:
                try:
                    cursor.execute("SELECT academic_year, COUNT(*) FROM scanned_photos GROUP BY academic_year")
                    for y_val, cnt in cursor.fetchall():
                        if y_val:
                            year_counts[str(y_val).strip()] = int(cnt)
                except Exception as e:
                    logger.warning(f"Failed to query photo counts by academic_year: {e}")

            results = []
            for r in rows:
                f_id, f_name, f_year, f_active, f_order, f_created = r
                f_year_str = str(f_year or "").strip()
                if not f_year_str:
                    f_year_str = self.extract_year_from_text(f_name)
                results.append({
                    "id": f_id,
                    "folder_id": f_id,
                    "name": f_name,
                    "folder_name": f_name,
                    "academic_year": f_year_str,
                    "is_active": int(f_active) if f_active is not None else 1,
                    "sort_order": int(f_order) if f_order is not None else 0,
                    "created_at": f_created,
                    "photo_count": year_counts.get(f_year_str, 0) if include_photo_counts else 0
                })
            return results

    def _sync_root_folders_to_json(self):
        """บันทึกข้อมูลโฟลเดอร์หลักจาก SQLite ลงไฟล์ config/year_folders.json อัตโนมัติ (v6.27)"""
        try:
            folders = self.get_root_year_folders(active_only=False, include_photo_counts=False)
            json_payload = []
            for item in folders:
                json_payload.append({
                    "name": item["name"],
                    "id": item["id"],
                    "academic_year": item["academic_year"],
                    "is_active": item["is_active"]
                })
            if self.year_folders_json_path:
                os.makedirs(os.path.dirname(os.path.abspath(self.year_folders_json_path)), exist_ok=True)
                with open(self.year_folders_json_path, "w", encoding="utf-8") as f:
                    json.dump(json_payload, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to sync root_year_folders to JSON: {e}")
            return False

    def upsert_root_year_folder(self, folder_id, folder_name, academic_year="", is_active=1, sort_order=0):
        """เพิ่มหรืออัปเดตโฟลเดอร์หลักประจำปีการศึกษาใน SQLite และซิงค์ลง year_folders.json อัตโนมัติ (v6.27)"""
        f_id = str(folder_id or "").strip()
        f_name = str(folder_name or "").strip()
        if not f_id or not f_name:
            raise ValueError("กรุณาระบุทั้ง Folder ID และชื่อโฟลเดอร์")

        f_year = str(academic_year or "").strip()
        if not f_year:
            f_year = self.extract_year_from_text(f_name)
        elif len(f_year) == 4 and f_year.isdigit() and 2000 <= int(f_year) <= 2045:
            f_year = str(int(f_year) + 543)

        f_active = 1 if is_active else 0
        f_order = int(sort_order or 0)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO root_year_folders (folder_id, folder_name, academic_year, is_active, sort_order)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(folder_id) DO UPDATE SET
                    folder_name = excluded.folder_name,
                    academic_year = excluded.academic_year,
                    is_active = excluded.is_active,
                    sort_order = CASE WHEN excluded.sort_order > 0 THEN excluded.sort_order ELSE root_year_folders.sort_order END
            """, (f_id, f_name, f_year, f_active, f_order))
            conn.commit()

        self._sync_root_folders_to_json()
        logger.info(f"[ROOT_FOLDERS] Upserted root folder: {f_name} (ID={f_id}, Year={f_year}, Active={f_active})")
        return True

    def toggle_root_year_folder_active(self, folder_id, is_active):
        """เปิด/ปิดสถานะการสแกนของโฟลเดอร์หลักประจำปีการศึกษา (v6.27)"""
        f_id = str(folder_id or "").strip()
        f_active = 1 if is_active else 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE root_year_folders SET is_active = ? WHERE folder_id = ?", (f_active, f_id))
            updated = cursor.rowcount > 0
            conn.commit()
        if updated:
            self._sync_root_folders_to_json()
        return updated

    def delete_root_year_folder(self, folder_id):
        """ลบโฟลเดอร์หลักประจำปีการศึกษาออกจากตาราง root_year_folders และซิงค์ลง JSON (v6.27)"""
        f_id = str(folder_id or "").strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM root_year_folders WHERE folder_id = ?", (f_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
        if deleted:
            self._sync_root_folders_to_json()
            logger.info(f"[ROOT_FOLDERS] Deleted root folder ID={f_id}")
        return deleted
