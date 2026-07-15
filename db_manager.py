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
                student_id TEXT
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

    def add_staff_embedding(self, staff_id, image_path, embedding_vector):
        """บันทึกเวกเตอร์ใบหน้า (embedding_vector ต้องเป็น numpy array หรือ list ขนาด 512 มิติ)"""
        if isinstance(embedding_vector, list):
            embedding_vector = np.array(embedding_vector, dtype=np.float32)
        
        # แปลง numpy array เป็น bytes
        embedding_blob = embedding_vector.astype(np.float32).tobytes()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO staff_embeddings (staff_id, image_path, embedding) VALUES (?, ?, ?)",
                (staff_id, image_path, embedding_blob)
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

    def register_member(self, name, role='teacher', student_id=None):
        """ลงทะเบียนสมาชิกใหม่พร้อมระบุ role (teacher/student) และ student_id (สำหรับนักเรียน)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if role == 'student' and student_id:
                    # นักเรียน: ใช้ student_id เป็น unique identifier
                    cursor.execute("INSERT INTO staff_members (name, role, student_id) VALUES (?, ?, ?)", (name, role, student_id))
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (ID: {student_id})")
                    return cursor.lastrowid
                elif role == 'student':
                    # นักเรียนแต่ไม่มี student_id - ใช้ unique constraint บน name+role
                    cursor.execute("INSERT INTO staff_members (name, role) VALUES (?, ?)", (name, role))
                    conn.commit()
                    logger.info(f"Registered new {role}: {name} (WARNING: no student_id)")
                    return cursor.lastrowid
                else:
                    # ครู: ใช้ unique constraint บน name+role
                    cursor.execute("INSERT INTO staff_members (name, role) VALUES (?, ?)", (name, role))
                    conn.commit()
                    logger.info(f"Registered new {role}: {name}")
                    return cursor.lastrowid
            except sqlite3.IntegrityError as e:
                # ลองดึงจาก student_id ก่อน (สำหรับนักเรียน)
                if student_id:
                    cursor.execute("SELECT id FROM staff_members WHERE student_id = ?", (student_id,))
                    row = cursor.fetchone()
                    if row:
                        return row[0]
                # ถ้าไม่มี ลองดึงจาก name+role
                cursor.execute("SELECT id FROM staff_members WHERE name = ? AND role = ?", (name, role))
                row = cursor.fetchone()
                return row[0] if row else None

    def delete_staff_member(self, staff_id):
        """ลบข้อมูลครูและลบความสัมพันธ์อื่น ๆ ทั้งหมด (Cascaded)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM staff_members WHERE id = ?", (staff_id,))
            conn.commit()
            logger.info(f"Deleted staff member ID: {staff_id}")

    def get_all_embeddings(self):
        """ดึงเวกเตอร์ทั้งหมดของครูเพื่อใช้โหลดลงหน่วยความจำตอนเริ่มต้นโปรแกรม"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.staff_id, s.name, e.embedding, e.image_path
                FROM staff_embeddings e
                JOIN staff_members s ON e.staff_id = s.id
            """)
            rows = cursor.fetchall()
            
            embeddings = []
            names = []
            staff_ids = []
            image_paths = []
            
            for row in rows:
                staff_id, name, blob, img_path = row
                # แปลง bytes กลับเป็น numpy array
                vec = np.frombuffer(blob, dtype=np.float32)
                embeddings.append(vec)
                names.append(name)
                staff_ids.append(staff_id)
                image_paths.append(img_path)
                
            return {
                "embeddings": np.array(embeddings) if embeddings else np.empty((0, 512), dtype=np.float32),
                "names": names,
                "staff_ids": staff_ids,
                "image_paths": image_paths
            }

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
                # บันทึกรูปภาพ
                cursor.execute(
                    "INSERT INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date) VALUES (?, ?, ?, ?, ?)",
                    (photo_id, drive_file_id, event_name, drive_link, photo_date)
                )
                
                # บันทึกคนในรูป
                for staff_id, confidence in matches:
                    cursor.execute(
                        "INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)",
                        (photo_id, staff_id, confidence)
                    )
                conn.commit()
                logger.info(f"Saved scanned photo {photo_id} with {len(matches)} matches to SQLite.")
                return True
            except sqlite3.Error as e:
                logger.error(f"Error saving scanned photo {photo_id} to SQLite: {e}")
                conn.rollback()
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
                SELECT df.id, s.name, df.photo_id
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
            """)
            faces = cursor.fetchall()
            
            return {
                "photos": [{"photo_id": p[0], "event": p[1], "drive_link": p[2], "date": p[3] if p[3] else ""} for p in photos],
                "faces": [{"face_id": f[0], "person": f[1], "photo_id": f[2]} for f in faces]
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
                        (photo_id, staff_id, confidence)
                    )
                conn.commit()
                logger.debug(f"Saved {len(matches)} matches to detected_faces for photo_id: {photo_id}")
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

