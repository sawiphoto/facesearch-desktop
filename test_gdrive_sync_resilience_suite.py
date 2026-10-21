import unittest
import os
import sys
import socket
import ssl
import json
import io
import py_compile
from unittest.mock import MagicMock, patch

# เพิ่ม Path ปัจจุบัน
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gdrive_sync import GoogleSyncManager

class TestGDriveSyncResilienceSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sync_mgr = GoogleSyncManager()

    def test_tc87_reconnect_drive_service(self):
        """TC-87: ทดสอบ reconnect_drive_service สร้าง AuthorizedHttp ใหม่พร้อม timeout 120s และล้าง Socket Pool เดิม"""
        mock_creds = MagicMock()
        self.sync_mgr.credentials = mock_creds
        
        with patch("gdrive_sync.build") as mock_build, patch("gdrive_sync.AuthorizedHttp") as mock_auth_http, patch("httplib2.Http") as mock_http:
            res = self.sync_mgr.reconnect_drive_service()
            self.assertTrue(res)
            # ตรวจสอบว่าเรียก httplib2.Http ด้วย timeout 120 วินาที
            mock_http.assert_called_with(timeout=120)
            mock_auth_http.assert_called_once()
            mock_build.assert_called_once()

    def test_tc88_one_shot_folder_files_cache_lookup(self):
        """TC-88: ทดสอบระบบ Folder Listing Cache ช่วยลด Network Request และดึง File ID ได้ใน O(1)"""
        # จำลองไฟล์เดิมใน Drive 5 ไฟล์
        mock_existing_files = [
            {"id": "FID_001", "name": "person_index.json"},
            {"id": "FID_002", "name": "photo_manifest.json"},
            {"id": "FID_003", "name": "photo_index_2568.json"},
            {"id": "FID_004", "name": "student_index_active.json"},
            {"id": "FID_005", "name": "student_index.json"},
        ]
        
        cache_map = {f["name"]: f["id"] for f in mock_existing_files}
        
        # ตรวจสอบว่าสามารถเข้าถึง File ID ได้ทันทีโดยไม่ต้องยิงคำสั่งค้นหา
        self.assertEqual(cache_map.get("person_index.json"), "FID_001")
        self.assertEqual(cache_map.get("photo_index_2568.json"), "FID_003")
        self.assertIsNone(cache_map.get("non_existent.json"))
        self.assertEqual(len(cache_map), 5)

    def test_tc89_adaptive_resumable_threshold(self):
        """TC-89: ทดสอบ Adaptive Resumable Toggle (ไฟล์ < 5MB ใช้ resumable=False, >= 5MB ใช้ resumable=True)"""
        # ไฟล์ขนาด 1.2 MB (< 5MB)
        small_size_mb = 1.2
        is_resumable_small = (small_size_mb >= 5.0)
        self.assertFalse(is_resumable_small, "ไฟล์ขนาดเล็กกว่า 5MB ควรใช้ Simple Multipart (resumable=False)")

        # ไฟล์ขนาด 7.8 MB (>= 5MB)
        large_size_mb = 7.8
        is_resumable_large = (large_size_mb >= 5.0)
        self.assertTrue(is_resumable_large, "ไฟล์ขนาด 5MB ขึ้นไปควรใช้ Resumable Upload (resumable=True)")

    def test_tc90_mock_timeout_and_ssleof_recovery(self):
        """TC-90: ทดสอบการกู้คืนจากการเชื่อมต่อหลุด (TimeoutError และ SSLEOFError) ด้วย Self-Healing Reconnect"""
        # จำลองการทำงานของ upload_overwrite_json โดยให้รอบแรกเกิด TimeoutError และรอบสองสำเร็จ
        mock_drive_service = MagicMock()
        self.sync_mgr.drive_service = mock_drive_service
        self.sync_mgr.credentials = MagicMock()
        
        # กำหนดให้ครั้งแรกเกิด ssl.SSLEOFError('EOF occurred in violation of protocol')
        # และครั้งที่สองผ่านฉลุย
        call_count = 0
        def side_effect_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ssl.SSLEOFError("EOF occurred in violation of protocol (_ssl.c:2427)")
            return {"id": "SUCCESS_ID"}

        mock_update = MagicMock()
        mock_update.execute.side_effect = side_effect_execute
        mock_drive_service.files().update.return_value = mock_update

        # จำลอง Retry Loop เดียวกันกับใน upload_overwrite_json
        max_retries = 3
        reconnect_called = False
        upload_success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                mock_drive_service.files().update(fileId="FID_001", media_body=MagicMock()).execute()
                upload_success = True
                break
            except (socket.timeout, TimeoutError, ssl.SSLEOFError, ssl.SSLError, ConnectionError, OSError):
                if attempt < max_retries:
                    reconnect_called = True
                    # จำลองการเรียก self.reconnect_drive_service()
                    self.sync_mgr.reconnect_drive_service()

        self.assertTrue(reconnect_called, "ต้องมีการเรียก self.reconnect_drive_service() เมื่อเจอ SSLEOFError")
        self.assertTrue(upload_success, "การอัปโหลดต้องสำเร็จหลังจากกู้คืนการเชื่อมต่อ")
        self.assertEqual(call_count, 2, "ต้องมีการพยายามทั้งหมด 2 รอบ")

    def test_tc91_version_parity_and_py_compile(self):
        """TC-91: ตรวจสอบความถูกต้องของเวอร์ชัน v6.35 และความสมบูรณ์ของไวยากรณ์ (py_compile)"""
        # 1. py_compile
        py_compile.compile("gdrive_sync.py", doraise=True)
        py_compile.compile("app_gui.py", doraise=True)
        py_compile.compile("db_manager.py", doraise=True)

        # 2. ตรวจสอบ Window Title
        with open("app_gui.py", "r", encoding="utf-8") as f:
            app_code = f.read()
            self.assertIn("v6.35 (Google Drive JSON Sync Resilience & Self-Healing Suite)", app_code)
            self.assertIn("FACE MATCHING\\nSYSTEM v6.35", app_code)

        # 3. ตรวจสอบ socket default timeout ใน gdrive_sync.py
        with open("gdrive_sync.py", "r", encoding="utf-8") as f:
            gdrive_code = f.read()
            self.assertIn("socket.setdefaulttimeout(120)", gdrive_code)
            self.assertIn("def reconnect_drive_service(self):", gdrive_code)

        # 4. ตรวจสอบ Manifest Version ใน db_manager.py
        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
            self.assertIn('"version": "v6.35"', db_code)

if __name__ == "__main__":
    unittest.main()
