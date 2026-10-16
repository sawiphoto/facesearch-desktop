import sqlite3
import re
import os
import json
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

class CachedFace:
    def __init__(self, bbox, embedding):
        self.bbox = bbox
        self.embedding = embedding

class DatabaseManager:
    def __init__(self, db_path=None):
        if db_path is None:
            db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "faces_db.db")
        
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
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

            # Migration: เพิ่ม Indexes เพื่อความเร็วสูงในการสืบค้นฐานข้อมูล (v5.70 Blazing Fast Indexes)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_spf_photo_id ON scanned_photo_faces(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_event_name ON scanned_photos(event_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_drive_file_id ON scanned_photos(drive_file_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_staff_id ON detected_faces(staff_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_photo_id ON detected_faces(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_photo_id ON scanned_photos(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_date ON scanned_photos(photo_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_role ON staff_members(role)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_name ON staff_members(name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sm_student_id ON staff_members(student_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_se_staff_id ON staff_embeddings(staff_id)")
                logger.info("Migration v5.70: created performance indexes for instant search.")
            except Exception as e:
                logger.warning(f"Could not create performance indexes: {e}")

            # Migration: ทำความสะอาดขยะประวัติการตรวจจับใบหน้าที่ไม่มีรูปจริงแล้ว (v4.21 Cleanup)
            try:
                cursor.execute("DELETE FROM detected_faces WHERE photo_id NOT IN (SELECT photo_id FROM scanned_photos)")
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

            # 7. ตารางระบบสถิติและจัดกลุ่มใบหน้าบุคคลนิรนาม (v6.20 Unknown VIP & Yearly Analytics)
            conn.commit()
        
        self.create_unknown_tables()
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_photo_id ON unknown_cluster_members(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucm_year ON unknown_cluster_members(year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_cluster_id ON unknown_cluster_year_stats(cluster_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_year ON unknown_cluster_year_stats(year)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_ucys_photo_count ON unknown_cluster_year_stats(year, photo_count DESC)")
                conn.commit()
                logger.info("Executed database migration v6.20: created unknown_clusters, unknown_cluster_members, and unknown_cluster_year_stats tables and indexes.")
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

    # --- ส่วนการจัดการข้อมูลครู (Staff Registry) ---
    
    def register_staff_member(self, name):
        """เพิ่มชื่อครูและคืนค่า ID (ตั้งค่า is_backfilled = 0 เพื่อให้ Task 3 ทำ Retroactive Match)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO staff_members (name, role, is_backfilled) VALUES (?, 'teacher', 0)", (name,))
                conn.commit()
                logger.info(f"Registered new staff member: {name}")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM staff_members WHERE name = ?", (name,))
                row = cursor.fetchone()
                return row[0]

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
        """ดึงข้อมูลรายชื่อครูทั้งหมดพร้อมจำนวนรูปภาพที่ลงทะเบียนไว้"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, COUNT(e.id) as photo_count
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                GROUP BY s.id, s.name
                ORDER BY s.name ASC
            """)
            return [{"id": row[0], "name": row[1], "photo_count": row[2]} for row in cursor.fetchall()]

    def get_all_teachers(self):
        """ดึงรายชื่อครูทั้งหมด (role = 'teacher')"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, COUNT(e.id) as photo_count
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                WHERE s.role = 'teacher'
                GROUP BY s.id, s.name
                ORDER BY s.name ASC
            """)
            return [{"id": row[0], "name": row[1], "photo_count": row[2]} for row in cursor.fetchall()]

    def get_all_students(self):
        """ดึงรายชื่อนักเรียนทั้งหมด (role = 'student') พร้อม student_id"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.name, s.student_id, COUNT(e.id) as photo_count
                FROM staff_members s
                LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                WHERE s.role = 'student'
                GROUP BY s.id, s.name, s.student_id
                ORDER BY s.name ASC
            """)
            return [{"id": row[0], "name": row[1], "student_id": row[2], "photo_count": row[3]} for row in cursor.fetchall()]

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
                "SELECT id, name, student_id FROM staff_members WHERE student_id = ? AND role = 'student'",
                (student_id,)
            )
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "student_id": row[2]}
            return None

    def get_student_photo_count(self, staff_id):
        """ดึงจำนวนภาพที่ลงทะเบียนไว้ของนักเรียนคนหนึ่ง"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def register_member(self, name, role='teacher', student_id=None, pin_code=None, personal_threshold=None):
        """ลงทะเบียนสมาชิกใหม่พร้อมระบุ role (teacher/student), student_id, pin_code และ personal_threshold"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if role == 'student' and student_id:
                    cursor.execute(
                        "INSERT INTO staff_members (name, role, student_id, pin_code, personal_threshold) VALUES (?, ?, ?, ?, ?)",
                        (name, role, student_id, pin_code, personal_threshold if personal_threshold is not None else 0.50)
                    )
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (ID: {student_id}, Thresh: {personal_threshold or 0.50})")
                    return cursor.lastrowid
                elif role == 'student':
                    cursor.execute(
                        "INSERT INTO staff_members (name, role, pin_code, personal_threshold) VALUES (?, ?, ?, ?)",
                        (name, role, pin_code, personal_threshold if personal_threshold is not None else 0.50)
                    )
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (WARNING: no student_id)")
                    return cursor.lastrowid
                else:
                    cursor.execute(
                        "INSERT INTO staff_members (name, role, personal_threshold) VALUES (?, ?, ?)",
                        (name, role, personal_threshold if personal_threshold is not None else 0.50)
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
                        if personal_threshold is not None:
                            cursor.execute("UPDATE staff_members SET name = ?, role = 'student', personal_threshold = ? WHERE id = ?", (name, personal_threshold, row[0]))
                        else:
                            cursor.execute("UPDATE staff_members SET name = ?, role = 'student' WHERE id = ?", (name, row[0]))
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

    def update_student_info(self, staff_id, new_name, new_student_id):
        """อัปเดตชื่อและรหัสนักเรียน (v5.30)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # ตรวจสอบว่า student_id ซ้ำกับคนอื่นหรือไม่
                if new_student_id:
                    cursor.execute("SELECT id FROM staff_members WHERE student_id = ? AND id != ? AND role = 'student'", (str(new_student_id).strip(), staff_id))
                    if cursor.fetchone():
                        logger.warning(f"[DATABASE] Student ID {new_student_id} already exists for another student.")
                        return False, "รหัสประจำตัวนักเรียนนี้ถูกใช้ไปแล้วโดยนักเรียนคนอื่น"
                        
                cursor.execute("UPDATE staff_members SET name = ?, student_id = ? WHERE id = ?", (new_name.strip(), str(new_student_id).strip() if new_student_id else None, staff_id))
                conn.commit()
                logger.info(f"[DATABASE] Updated student ID {staff_id} info: name='{new_name}', student_id='{new_student_id}'")
                return True, "อัปเดตข้อมูลสำเร็จ"
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error updating student info for ID {staff_id}: {e}")
                conn.rollback()
                return False, f"เกิดข้อผิดพลาดในฐานข้อมูล: {e}"

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

    def get_all_embeddings(self):
        """ดึงเวกเตอร์ทั้งหมดของครูเพื่อใช้โหลดลงหน่วยความจำตอนเริ่มต้นโปรแกรม"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.staff_id, s.name, e.embedding, e.image_path, s.role, COALESCE(s.personal_threshold, 0.50)
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
            
            for row in rows:
                staff_id, name, blob, img_path, role, thresh = row
                # แปลง bytes กลับเป็น numpy array
                vec = np.frombuffer(blob, dtype=np.float32)
                embeddings.append(vec)
                names.append(name)
                staff_ids.append(staff_id)
                image_paths.append(img_path)
                roles.append(role if role else "teacher")
                personal_thresholds.append(float(thresh) if thresh is not None else 0.50)
                
            return {
                "embeddings": np.array(embeddings) if embeddings else np.empty((0, 512), dtype=np.float32),
                "names": names,
                "staff_ids": staff_ids,
                "image_paths": image_paths,
                "roles": roles,
                "personal_thresholds": personal_thresholds
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
        บันทึกข้อมูลรูปภาพที่สแกนเสร็จแล้วแบบกลุ่ม (Batch) ใน Transaction เดียว (v5.20 / v6.00 รองรับ file_name และ file_extension)
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
                "faces": [...]
            }
        ]
        """
        if not batch_items:
            return True
            
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                for item in batch_items:
                    pid = item["photo_id"]
                    fid = item["drive_file_id"]
                    event = item["event_name"]
                    link = item["drive_link"]
                    pdate = item.get("photo_date", "")
                    fname = item.get("file_name", "")
                    fext = item.get("file_extension", "")
                    if not fext and fname:
                        fext = os.path.splitext(fname)[1].lower()
                    matches = item.get("matches", [])
                    faces = item.get("faces", [])
                    total_faces = len(faces) if faces else (len(matches) if matches else 0)
                    
                    # 1. บันทึก scanned_photos
                    cursor.execute(
                        "INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, total_faces_detected) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (pid, fid, event, link, pdate, fname, fext, total_faces)
                    )
                    
                    # 2. บันทึก detected_faces
                    for staff_id, confidence in matches:
                        cursor.execute(
                            "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                            (pid, staff_id, float(confidence))
                        )
                        
                    # 3. บันทึก scanned_photo_faces (Embedding cache)
                    if not faces:
                        cursor.execute(
                            """
                            INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (pid, -1, 0.0, 0.0, 0.0, 0.0, b"")
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
                                (pid, idx, x1, y1, x2, y2, emb_bytes)
                            )
                            
                conn.commit()
                logger.info(f"⚡ [BATCH DB] Successfully committed batch of {len(batch_items)} photos to SQLite.")
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
                    SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.photo_date, MAX(df.confidence) as max_conf
                    FROM detected_faces df
                    JOIN scanned_photos p ON df.photo_id = p.photo_id
                    WHERE df.staff_id = ?
                    GROUP BY p.photo_id
                    ORDER BY p.photo_date DESC, p.photo_id DESC
                """
                cursor.execute(query, (staff_id,))
                rows = cursor.fetchall()
                for pid, fid, event, link, pdate, conf in rows:
                    results.append({
                        "photo_id": pid,
                        "drive_file_id": fid,
                        "event_name": event or "กิจกรรมทั่วไป",
                        "drive_link": link or f"https://drive.google.com/file/d/{fid}/view",
                        "photo_date": pdate or "ไม่ระบุวันที่",
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
        เพื่อให้ระบบสแกนอัตโนมัติ (Task 1) นำภาพกลับมาถอดรหัสใหม่ด้วย Multi-Format Decoder (รองรับ Apple HEIC) (v5.90)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT photo_id, event_name
                    FROM scanned_photos p
                    WHERE (SELECT COUNT(*) FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id) = 0
                """)
                rows = cursor.fetchall()
                if not rows:
                    logger.info("[DATABASE] ไม่มีรูปภาพ 0 Faces ที่ต้องล้าง")
                    return []

                photo_ids = [r[0] for r in rows]
                events = list(set(r[1] for r in rows if r[1]))
                
                cursor.execute("""
                    DELETE FROM scanned_photos
                    WHERE photo_id IN (
                        SELECT p.photo_id
                        FROM scanned_photos p
                        WHERE (SELECT COUNT(*) FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id) = 0
                    )
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

