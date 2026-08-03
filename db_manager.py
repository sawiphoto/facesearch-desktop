import sqlite3
import os
import numpy as np
import logging

logger = logging.getLogger("FaceSearchApp")

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

            # Migration: เพิ่ม Indexes เพื่อความเร็วสูง (v4.14)
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_staff_id ON detected_faces(staff_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_df_photo_id ON detected_faces(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_photo_id ON scanned_photos(photo_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sp_date ON scanned_photos(photo_date)")
                logger.info("Migration: created performance indexes for detected_faces & scanned_photos.")
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

            conn.commit()
        logger.info("SQLite database initialized successfully.")

    # --- ส่วนการจัดการข้อมูลครู (Staff Registry) ---
    
    def register_staff_member(self, name):
        """เพิ่มชื่อครูและคืนค่า ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO staff_members (name) VALUES (?)", (name,))
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
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                val = float(threshold_value)
                cursor.execute("UPDATE staff_members SET personal_threshold = ? WHERE id = ?", (val, staff_id))
                conn.commit()
                logger.info(f"Updated personal_threshold for staff_id {staff_id} to {val:.2f}")
                return True
            except Exception as e:
                logger.error(f"Error updating personal_threshold for staff_id {staff_id}: {e}")
                return False

    # --- ส่วนการจัดการภาพสแกนกิจกรรม (Photo Matching DB) ---
    
    def is_photo_scanned(self, drive_file_id):
        """ตรวจสอบว่ารูปนี้ใน Google Drive ถูกสแกนไปแล้วหรือไม่"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id FROM scanned_photos WHERE drive_file_id = ?", (drive_file_id,))
            return cursor.fetchone() is not None

    def save_scanned_photo(self, photo_id, drive_file_id, event_name, drive_link, matches, photo_date=""):
        """
        บันทึกข้อมูลรูปภาพที่สแกนเสร็จแล้วและรายชื่อใบหน้าที่ตรวจพบ
        matches: list ของ tuple (staff_id, confidence)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # บันทึกรูปภาพ (ใช้ INSERT OR REPLACE เพื่อป้องกัน drive_file_id ซ้ำซ้อน)
                cursor.execute(
                    "INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date) VALUES (?, ?, ?, ?, ?)",
                    (photo_id, drive_file_id, event_name, drive_link, photo_date)
                )
                
                # บันทึกคนในรูป
                for staff_id, confidence in matches:
                    cursor.execute(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        (photo_id, staff_id, float(confidence))
                    )
                conn.commit()
                logger.info(f"Saved scanned photo {photo_id} with {len(matches)} matches to SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving scanned photo {photo_id} to SQLite: {e}")
                conn.rollback()
                return False

    def mark_skipped_photo(self, photo_id, drive_file_id, event_name, reason="SKIPPED_UNREADABLE"):
        """บันทึกประวัติไฟล์รูปภาพที่ไม่สามารถอ่านได้/เสียหาย/ไม่ใช่ไฟล์รูปภาพลง SQLite เพื่อป้องกันการติดลูปสแกนซ้ำ"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date) VALUES (?, ?, ?, ?, ?)",
                    (photo_id, drive_file_id, event_name, f"https://drive.google.com/file/d/{drive_file_id}/view", reason)
                )
                conn.commit()
                logger.info(f"[DATABASE] Marked unreadable photo {photo_id} as '{reason}' in SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error marking skipped photo {photo_id}: {e}")
                return False

    def get_all_sync_data(self):
        """ดึงข้อมูลทั้งหมดในฐานข้อมูลเพื่อพร้อมอัปเดตลง Google Sheets"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # ข้อมูลชีท photos (ดึง photo_date มาด้วย)
            cursor.execute("SELECT photo_id, event_name, drive_link, photo_date FROM scanned_photos")
            photos = cursor.fetchall()
            
            # ข้อมูลชีท faces (ดึงชื่อคนแทนไอดีเพื่อบันทึกลงชีท พร้อมดึงไอดีแถวการสแกนเป็น face_id)
            cursor.execute("""
                SELECT df.id, s.name, df.photo_id, s.role, s.student_id
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
            """)
            faces = cursor.fetchall()
            
            return {
                "photos": [{"photo_id": p[0], "event": p[1], "drive_link": p[2], "date": p[3] if p[3] else ""} for p in photos],
                "faces": [{"face_id": f[0], "person": f[1], "photo_id": f[2], "role": f[3] if f[3] else "teacher", "student_id": f[4] if f[4] else ""} for f in faces]
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
        """ดึงรายการ staff_id ของนักเรียน/ครูที่เพิ่งเพิ่มใหม่ หรืออัปเดตรูปใหม่ (is_backfilled = 0)"""
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id, name, role, student_id FROM staff_members WHERE is_backfilled = 0")
                for row in cursor.fetchall():
                    results.append({"staff_id": row[0], "name": row[1], "role": row[2], "student_id": row[3]})
            except sqlite3.Error as e:
                logger.error(f"[DATABASE] Error getting unbackfilled students: {e}")
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
