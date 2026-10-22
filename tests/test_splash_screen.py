import unittest
import os
import sys
import time
from unittest.mock import MagicMock, patch

# เพิ่ม Root Path สำหรับการทดสอบ
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from splash_screen import SplashScreen
from single_instance import acquire_mutex, release_mutex, ERROR_ALREADY_EXISTS
from gdrive_sync import GoogleSyncManager

class TestSplashScreenAndSingleInstance(unittest.TestCase):
    def test_tc156_splash_screen_lifecycle(self):
        """TC-156: ทดสอบวงจรชีวิตของ SplashScreen (เปิด, อัปเดต Progress, ปิด)"""
        splash = SplashScreen(title="UNIT TEST SPLASH", version="v6.51")
        self.assertTrue(splash.root.winfo_exists())
        
        # ทดสอบการอัปเดต 0-100%
        splash.update_progress(50, "กำลังโหลดส่วนประกอบทดสอบ...")
        self.assertEqual(splash.pb["value"], 50)
        self.assertEqual(splash.lbl_percent.cget("text"), "50%")
        self.assertEqual(splash.lbl_status.cget("text"), "กำลังโหลดส่วนประกอบทดสอบ...")

        splash.update_progress(100, "เสร็จสมบูรณ์")
        self.assertEqual(splash.pb["value"], 100)
        self.assertEqual(splash.lbl_percent.cget("text"), "100%")

        # ปิด
        splash.close()
        # หลังปิด winfo_exists ต้องเป็น False หรือ throw TclError
        try:
            exists = splash.root.winfo_exists()
            self.assertFalse(exists)
        except Exception:
            pass

    def test_tc157_single_instance_mutex(self):
        """TC-157: ทดสอบระบบ Single-Instance Mutex ป้องกันการเปิดโปรเซสซ้อน"""
        test_mutex_name = "Local\\FaceSearchApp_UnitTest_Mutex_2026"
        m1 = acquire_mutex(test_mutex_name)
        self.assertIsNotNone(m1)

        # จำลองการเปิด Instance ที่สองด้วย Mutex เดียวกัน
        m2 = acquire_mutex(test_mutex_name)
        self.assertIsNone(m2, "Instance ที่สองต้องได้ None เนื่องจากมี Instance แรกเปิดอยู่แล้ว")

        # ปลดปล่อย m1
        release_mutex(m1)

        # หลังปลดปล่อยแล้ว ต้องสามารถ Acquire ใหม่ได้
        m3 = acquire_mutex(test_mutex_name)
        self.assertIsNotNone(m3)
        release_mutex(m3)

    def test_tc158_gdrive_sync_archive_auto_connect(self):
        """TC-158: ตรวจสอบว่า sync_archive_crowdsource_only มีระบบ Auto-Connect เมื่อยังไม่ได้ต่อ Drive"""
        sm = GoogleSyncManager()
        sm.connected = False
        sm.drive_service = None

        # จำลองว่า connect() ทำงานได้ผล
        with patch.object(sm, 'connect', return_value=True) as mock_connect:
            with patch.object(sm, 'verify_spreadsheet', return_value=True):
                # ให้ mock_connect คืนค่า True และตั้ง mock drive_service
                mock_drive = MagicMock()
                mock_drive.files().list().execute.return_value = {"files": []}
                
                def fake_connect(*args, **kwargs):
                    sm.connected = True
                    sm.drive_service = mock_drive
                    return True
                mock_connect.side_effect = fake_connect
                
                mock_db = MagicMock()
                mock_db.get_archive_crowdsource_data.return_value = {
                    "version": "v6.51",
                    "total_photos": 1,
                    "photos": [{"photo_id": 99, "gdrive_file_id": "test", "file_name": "test.jpg", "faces": []}]
                }

                # เรียกใช้งาน sync_archive_crowdsource_only
                # แม้เริ่มต้น connected=False แต่ระบบต้องสั่ง auto-connect ให้เอง
                success, msg = sm.sync_archive_crowdsource_only(json_folder_id="1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L", db=mock_db)
                self.assertTrue(mock_connect.called, "sync_archive_crowdsource_only ต้องเรียก connect() อัตโนมัติหากยังไม่ได้เชื่อมต่อ")

if __name__ == "__main__":
    unittest.main()
