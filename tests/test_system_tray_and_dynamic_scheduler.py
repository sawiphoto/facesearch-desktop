import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scheduler_task import calculate_schedule_slots, get_next_run_info, INTERVAL_OPTIONS_MAP
from autostart_manager import (
    enable_autostart,
    disable_autostart,
    is_autostart_enabled,
    get_default_autostart_command,
)
from system_tray import create_google_photos_tray_icon, SystemTrayManager


class TestSystemTrayAndDynamicScheduler(unittest.TestCase):
    def test_01_calculate_schedule_slots_30m_to_24h(self):
        """ทดสอบการคำนวณรอบเวลาอัตโนมัติตั้งแต่คาบเวลา 30 นาที จนถึง 24 ชั่วโมง"""
        # 1. เริ่ม 05:00 ทุกๆ 6 ชั่วโมง (360 นาที) -> 05:00, 11:00, 17:00, 23:00
        slots_6h = calculate_schedule_slots("05:00", 360)
        self.assertEqual(slots_6h, ["05:00", "11:00", "17:00", "23:00"])

        # 2. เริ่ม 08:00 ทุกๆ 2 ชั่วโมง (120 นาที) -> 12 รอบ/วัน
        slots_2h = calculate_schedule_slots("08:00", 120)
        self.assertEqual(len(slots_2h), 12)
        self.assertEqual(slots_2h[:4], ["08:00", "10:00", "12:00", "14:00"])
        self.assertIn("00:00", slots_2h)
        self.assertIn("06:00", slots_2h)

        # 3. เริ่ม 07:30 ทุกๆ 30 นาที -> 48 รอบ/วัน
        slots_30m = calculate_schedule_slots("07:30", 30)
        self.assertEqual(len(slots_30m), 48)
        self.assertEqual(slots_30m[:3], ["07:30", "08:00", "08:30"])

        # 4. เริ่ม 09:00 ทุกๆ 24 ชั่วโมง (1440 นาที) -> 1 รอบ/วัน
        slots_24h = calculate_schedule_slots("09:00", 1440)
        self.assertEqual(slots_24h, ["09:00"])

    def test_02_get_next_run_info_same_day_and_tomorrow_rollover(self):
        """ทดสอบการคำนวณเวลารอบถัดไปทั้งภายในวันเดียวกันและข้ามเที่ยงคืนไปวันพรุ่งนี้"""
        slots = ["05:00", "11:00", "17:00", "23:00"]

        # เวลา 09:40 -> รอบถัดไปคือวันนี้ 11:00 (อีก 1 ชม. 20 นาที = 80 นาที)
        now_morning = datetime(2026, 10, 27, 9, 40, 0)
        info_1 = get_next_run_info(slots, enabled=True, now_dt=now_morning)
        self.assertEqual(info_1["next_time_str"], "11:00")
        self.assertFalse(info_1["is_tomorrow"])
        self.assertEqual(info_1["remaining_minutes"], 80)
        self.assertIn("วันนี้ เวลา 11:00 น.", info_1["display_text"])

        # เวลา 23:30 -> รอบถัดไปคือพรุ่งนี้ 05:00 (อีก 5 ชม. 30 นาที = 330 นาที)
        now_night = datetime(2026, 10, 27, 23, 30, 0)
        info_2 = get_next_run_info(slots, enabled=True, now_dt=now_night)
        self.assertEqual(info_2["next_time_str"], "05:00")
        self.assertTrue(info_2["is_tomorrow"])
        self.assertEqual(info_2["remaining_minutes"], 330)
        self.assertIn("พรุ่งนี้ เวลา 05:00 น.", info_2["display_text"])

        # กรณีปิดตารางเวลา
        info_off = get_next_run_info(slots, enabled=False, now_dt=now_morning)
        self.assertEqual(info_off["next_time_str"], "-")
        self.assertIn("ปิด", info_off["display_text"])

    def test_03_windows_autostart_registry_lifecycle(self):
        """ทดสอบการลงทะเบียนและยกเลิก Start with Windows ใน Registry โดยไม่กระทบคีย์หลัก"""
        test_reg_name = "SchoolFaceFinder_UnitTest_v664"
        cmd = get_default_autostart_command()
        self.assertIn("--tray", cmd)

        try:
            ok_enable = enable_autostart(app_name=test_reg_name, command=cmd)
            self.assertTrue(ok_enable)
            self.assertTrue(is_autostart_enabled(app_name=test_reg_name))

            ok_disable = disable_autostart(app_name=test_reg_name)
            self.assertTrue(ok_disable)
            self.assertFalse(is_autostart_enabled(app_name=test_reg_name))
        finally:
            disable_autostart(app_name=test_reg_name)

    def test_04_system_tray_icon_and_gui_schedule_integration(self):
        """ทดสอบการสร้างไอคอน System Tray และการซิงค์ตารางเวลาไดนามิกบนหน้าต่าง GUI"""
        icon_img = create_google_photos_tray_icon(64)
        self.assertEqual(icon_img.size, (64, 64))
        self.assertEqual(icon_img.mode, "RGBA")

        from app_gui import FaceSearchApp
        mock_analyzer = MagicMock()
        mock_analyzer.initialized = True

        app = FaceSearchApp(analyzer=mock_analyzer, enable_tray=False, start_in_tray=False, save_on_destroy=False)
        try:
            # ตรวจสอบค่าเริ่มต้นตารางเวลา (05:00 ทุก 6 ชม. -> 4 รอบ)
            app.combo_sched_anchor.set("05:00")
            app.combo_sched_interval.set("ทุกๆ 6 ชั่วโมง (4 รอบ/วัน - แนะนำ)")
            app.sw_schedule_enabled.select()
            app.on_schedule_option_change()
            self.assertEqual(app.scheduler.schedule_slots, ["05:00", "11:00", "17:00", "23:00"])

            # ทดสอบเปลี่ยนเป็น เริ่ม 06:00 ทุกๆ 3 ชั่วโมง -> 8 รอบ/วัน
            app.combo_sched_anchor.set("06:00")
            app.combo_sched_interval.set("ทุกๆ 3 ชั่วโมง (8 รอบ/วัน)")
            app.on_schedule_option_change()
            self.assertEqual(
                app.scheduler.schedule_slots,
                ["06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "00:00", "03:00"]
            )
            self.assertIn("06:00, 09:00, 12:00", app.lbl_sched_slots_preview.cget("text"))

            # ทดสอบย่อหน้าต่างลง System Tray และดึงหน้าต่างกลับขึ้นมา (Double-Click Simulation)
            app.hide_to_tray()
            self.assertEqual(app.state(), "withdrawn")
            app.show_from_tray()
            self.assertEqual(app.state(), "normal")

            # ทดสอบปลุกหน้าต่างที่ซ่อนอยู่ในถาด System Tray ผ่านสัญญาณ Tray Wakeup Signal (เมื่อกดเปิด Shortcut บน Desktop ซ้ำ)
            from single_instance import send_tray_wakeup_signal
            app.hide_to_tray()
            self.assertEqual(app.state(), "withdrawn")
            self.assertTrue(send_tray_wakeup_signal())
            app.check_log_queue()
            self.assertEqual(app.state(), "normal")
        finally:
            app.face_search_worker_gen += 1
            app.destroy()

    def test_05_exe_launcher_and_icon_artifacts(self):
        """ตรวจสอบว่าไฟล์ SchoolFaceFinder.exe และ app_icon.ico ถูกสร้างครบถ้วนสมบูรณ์"""
        exe_file = os.path.join(project_root, "SchoolFaceFinder.exe")
        ico_file = os.path.join(project_root, "app_icon.ico")
        self.assertTrue(os.path.exists(exe_file), "SchoolFaceFinder.exe ต้องมีอยู่ในโฟลเดอร์โปรเจกต์")
        self.assertGreater(os.path.getsize(exe_file), 4096)
        self.assertTrue(os.path.exists(ico_file), "app_icon.ico ต้องมีอยู่ในโฟลเดอร์โปรเจกต์")
        self.assertGreater(os.path.getsize(ico_file), 1024)
        self.assertIn("SchoolFaceFinder.exe", get_default_autostart_command())

    def test_06_desktop_toast_notification_and_permanent_autostart_v666(self):
        """ทดสอบการแสดงป๊อปอัปแจ้งเตือนมุมขวาล่าง Desktop (Start/Finish) และการเปิด Auto-Start ถาวรหลังรีสตาร์ท (v6.66)"""
        # 1. ยืนยันว่า Windows Auto-Start ถูกเปิดใช้งานจริงใน Registry สำหรับการเปิด/ปิดคอมหรือ Restart ทุกครั้ง
        self.assertTrue(is_autostart_enabled(), "Windows Auto-Start ต้องถูกเปิดใช้งานใน Registry เป็นค่าเริ่มต้น")
        self.assertIn("--tray", get_default_autostart_command())

        from app_gui import FaceSearchApp
        mock_analyzer = MagicMock()
        mock_analyzer.initialized = True

        app = FaceSearchApp(analyzer=mock_analyzer, enable_tray=False, start_in_tray=False, save_on_destroy=False)
        try:
            # 2. ย่อหน้าต่างลงถาด System Tray แล้วทดสอบแสดงแจ้งเตือนเริ่มทำงาน (status_type='start')
            app.hide_to_tray()
            self.assertEqual(app.state(), "withdrawn")

            toast_start = app.show_desktop_toast(
                "🚀 เริ่มทำงานอัตโนมัติ (รอบเวลา 11:00 น.)",
                "กำลังรัน Task 1 (สแกนภาพใหม่) ➔ Task 2 (นักเรียน) ➔ Task 3 (บุคลากรครู)",
                status_type="start",
                duration_ms=5000
            )
            self.assertIsNotNone(toast_start)
            self.assertTrue(toast_start.winfo_exists())
            self.assertEqual(toast_start._toast_status_type, "start")
            self.assertIn("เริ่มทำงานอัตโนมัติ", toast_start._toast_title)

            # ตรวจสอบพิกัดมุมขวาล่างของหน้าจอ (Bottom-Right Corner)
            screen_w = app.winfo_screenwidth()
            screen_h = app.winfo_screenheight()
            expected_x = max(10, screen_w - 390 - 16)
            expected_y = max(10, screen_h - 116 - 56)
            self.assertEqual(toast_start._toast_geometry, f"390x116+{expected_x}+{expected_y}")

            # 3. ทดสอบแสดงแจ้งเตือนเมื่อเสร็จสิ้นรอบการทำงาน (status_type='success') และตรวจสอบว่าอันเก่าถูกแทนที่ทันที
            toast_done = app.show_desktop_toast(
                "✅ ทำงานอัตโนมัติเสร็จสมบูรณ์! (11:04 น.)",
                "สแกนภาพ 25 รูป | พบใบหน้า 42 หน้า (ใช้เวลา 4m 12s)\nรอบถัดไป: วันนี้ 17:00 น.",
                status_type="success",
                duration_ms=5000
            )
            self.assertIsNotNone(toast_done)
            self.assertTrue(toast_done.winfo_exists())
            self.assertFalse(toast_start.winfo_exists(), "Toast อันก่อนหน้าต้องถูกปิดอัตโนมัติเพื่อไม่ให้ซ้อนทับกัน")
            self.assertEqual(toast_done._toast_status_type, "success")
            self.assertIn("ทำงานอัตโนมัติเสร็จสมบูรณ์", toast_done._toast_title)

            # 4. ทดสอบการเรียกผ่าน SchedulerTask._notify_desktop()
            app.scheduler._notify_desktop(
                "🚀 ทดสอบแจ้งเตือนจาก Scheduler",
                "ข้อความจากเธรดตารางเวลาอัตโนมัติ",
                status_type="info",
                duration_ms=3000
            )
            app.update()
            self.assertIsNotNone(app._active_desktop_toast)
            self.assertIn("Scheduler", app._active_desktop_toast._toast_title)
        finally:
            app.face_search_worker_gen += 1
            app.destroy()

    def test_07_run_scheduled_tasks_and_task2_task3_execution_paths_v667(self):
        """TC-172: ทดสอบ Execution Paths ของ SchedulerTask ป้องกัน UnboundLocalError datetime (v6.67)"""
        from scheduler_task import SchedulerTask

        mock_db = MagicMock()
        mock_sync = MagicMock()
        mock_sync.connected = True
        mock_analyzer = MagicMock()
        mock_analyzer.initialized = True
        mock_gui = MagicMock()

        notified_calls = []
        def fake_notify(title, message, status_type="info", duration_ms=8000):
            notified_calls.append((title, message, status_type, duration_ms))

        scheduler = SchedulerTask(mock_db, mock_sync, mock_analyzer, mock_gui)
        scheduler._notify_desktop = fake_notify

        # 1. ทดสอบ _run_task_2_only: ต้องไม่มี UnboundLocalError และมีแจ้งเตือน start + finish
        notified_calls.clear()
        scheduler._ensure_analyzer = MagicMock()
        scheduler._task_2_sync_new_students_bulk = MagicMock()
        scheduler._sync_all_json_to_drive = MagicMock()
        scheduler._safe_sync_json_on_stop = MagicMock()

        scheduler._run_task_2_only()
        self.assertFalse(scheduler.is_running)
        self.assertEqual(len(notified_calls), 2)
        self.assertEqual(notified_calls[0][2], "start")
        self.assertEqual(notified_calls[1][2], "success")

        # 2. ทดสอบ _run_task_3_only: ต้องไม่มี UnboundLocalError และมีแจ้งเตือน start + finish
        notified_calls.clear()
        scheduler._task_3_sync_new_teachers_bulk = MagicMock()
        scheduler._run_task_3_only()
        self.assertFalse(scheduler.is_running)
        self.assertEqual(len(notified_calls), 2)
        self.assertEqual(notified_calls[0][2], "start")
        self.assertEqual(notified_calls[1][2], "success")

        # 3. ทดสอบ run_scheduled_tasks: ต้องไม่มี UnboundLocalError และมีแจ้งเตือน start + finish
        notified_calls.clear()
        scheduler._task_1_scan_new_photos_fast = MagicMock()
        scheduler.run_scheduled_tasks()
        self.assertFalse(scheduler.is_running)
        self.assertEqual(len(notified_calls), 2)
        self.assertEqual(notified_calls[0][2], "start")
        self.assertEqual(notified_calls[1][2], "success")
        self.assertIn("เสร็จสมบูรณ์", notified_calls[1][0])

        # 4. ทดสอบกรณีเกิด Exception ใน run_scheduled_tasks: ต้องจับข้อผิดพลาดและยังคงแจ้งเตือน finish ใน finally ได้
        notified_calls.clear()
        scheduler._task_1_scan_new_photos_fast = MagicMock(side_effect=RuntimeError("Simulated network drop"))
        scheduler.run_scheduled_tasks()
        self.assertFalse(scheduler.is_running)
        self.assertEqual(len(notified_calls), 2)
        self.assertEqual(notified_calls[0][2], "start")
        self.assertIn("เสร็จสมบูรณ์", notified_calls[1][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
