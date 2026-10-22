import unittest
import os
import py_compile
from unittest.mock import MagicMock
import app_gui
import scheduler_task
from db_manager import DatabaseManager

class TestSequentialSyncAndStopSuite(unittest.TestCase):
    """
    Test Suite for v6.47: Sequential Task-1 Sync & Responsive Instant-Stop Suite
    TC-143 to TC-146
    """

    def test_tc143_task1_sequential_sync_integrity(self):
        """TC-143: ตรวจสอบว่าจบ Task 1 มีการซิงค์ JSON 1 ครั้งก่อนขึ้น Task 2 และไม่ล็อกตัวแปร Stop"""
        with open("scheduler_task.py", "r", encoding="utf-8") as f:
            code = f.read()

        # ตรวจสอบลำดับใน run_scheduled_tasks
        sched_part = code.split("def run_scheduled_tasks(self):")[1].split("def _sync_all_json_to_drive")[0]
        
        pos_t1 = sched_part.find("self._task_1_scan_new_photos_fast()")
        pos_t1_sync = sched_part.find("กำลังซิงค์ไฟล์ JSON ดัชนีขึ้น Google Drive ครั้งที่ 1 ก่อนเริ่ม Task 2")
        pos_t2 = sched_part.find("self._task_2_sync_new_students_bulk()")
        pos_t3 = sched_part.find("self._task_3_sync_new_teachers_bulk()")
        pos_final_sync = sched_part.find("Final Consistency Sync v6.47")

        self.assertTrue(pos_t1 > 0, "Task 1 must exist")
        self.assertTrue(pos_t1_sync > pos_t1, "Task 1 sync must occur after Task 1")
        self.assertTrue(pos_t2 > pos_t1_sync, "Task 2 must occur after Task 1 sync")
        self.assertTrue(pos_t3 > pos_t2, "Task 3 must occur after Task 2")
        self.assertTrue(pos_final_sync > pos_t3, "Final Consistency Sync must occur after Task 3")

        # ตรวจสอบว่าในการซิงค์หลัง Task 1 ไม่ได้เซ็ต _stopped_json_synced = True
        t1_sync_block = sched_part[pos_t1_sync:pos_t2]
        self.assertNotIn("_stopped_json_synced = True", t1_sync_block, "Task 1 normal sync must NOT set _stopped_json_synced = True")

        print("\n[TC-143 PASSED] Task 1 sequential sync runs right after Task 1 and does not lock out stop sync.")

    def test_tc144_instant_stop_responsiveness(self):
        """TC-144: ตรวจสอบจุด Return ทันทีเมื่อผู้ใช้กด Stop ใน Task 1, Task 2, และ Task 3"""
        with open("scheduler_task.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Task 1 check
        t1_part = code.split("def _task_1_scan_new_photos_fast(self):")[1].split("def _task_2_sync_new_students_bulk")[0]
        self.assertIn("self._safe_sync_json_on_stop()\n                    return", t1_part, "Task 1 must return immediately after safe sync on stop")

        # Task 2 check
        t2_part = code.split("def _task_2_sync_new_students_bulk(self):")[1].split("def _task_3_sync_new_teachers_bulk")[0]
        self.assertIn("if self.stop_requested:\n            return", t2_part, "Task 2 must check stop_requested at start")
        self.assertIn("ข้ามขั้นตอน Backfill นักเรียน", t2_part, "Task 2 must skip backfill if stopped")

        # Task 3 check
        t3_part = code.split("def _task_3_sync_new_teachers_bulk(self):")[1]
        self.assertIn("if self.stop_requested:\n            return", t3_part, "Task 3 must check stop_requested at start")
        self.assertIn("ข้ามขั้นตอน Backfill คุณครู", t3_part, "Task 3 must skip backfill if stopped")

        print("\n[TC-144 PASSED] Instant-Stop points correctly return immediately across Task 1, 2, and 3.")

    def test_tc145_stop_triggered_immediate_google_drive_sync(self):
        """TC-145: จำลองการกด Stop และตรวจสอบว่า _safe_sync_json_on_stop เรียก _sync_all_json_to_drive ทันที"""
        scheduler = scheduler_task.SchedulerTask(
            app_gui=None, db_manager=MagicMock(), sync_manager=MagicMock(), face_analyzer=MagicMock()
        )
        scheduler._sync_all_json_to_drive = MagicMock()
        
        # ตั้งค่าว่าถูกหยุด
        scheduler.stop_requested = True
        scheduler._stopped_json_synced = False

        # เรียก _safe_sync_json_on_stop ครั้งที่ 1
        scheduler._safe_sync_json_on_stop()
        self.assertEqual(scheduler._sync_all_json_to_drive.call_count, 1, "Drive sync must be called immediately on stop")
        self.assertTrue(scheduler._stopped_json_synced, "_stopped_json_synced flag must be set to True after stop sync")

        # เรียก _safe_sync_json_on_stop ซ้ำ (เพื่อทดสอบว่าไม่ sync ซ้ำซ้อนในรอบเดียวกัน)
        scheduler._safe_sync_json_on_stop()
        self.assertEqual(scheduler._sync_all_json_to_drive.call_count, 1, "Must prevent double sync in the same stop session")

        print("\n[TC-145 PASSED] Stop-triggered sync executes Drive upload immediately and safely.")

    def test_tc146_version_parity_v647_and_compilation(self):
        """TC-146: ตรวจสอบความถูกต้องของเลขเวอร์ชัน v6.47 ทั่วระบบและการคอมไพล์"""
        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()
        self.assertIn("v6.47 (Sequential Task-1 Sync & Responsive Instant-Stop Suite)", gui_code)
        self.assertIn("SYSTEM v6.47", gui_code)

        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertIn('"version": "v6.47"', db_code)

        # py_compile verification
        py_compile.compile("app_gui.py", doraise=True)
        py_compile.compile("scheduler_task.py", doraise=True)
        py_compile.compile("db_manager.py", doraise=True)

        print("\n[TC-146 PASSED] All modules compile cleanly with 0 errors and Version v6.47 parity is confirmed.")

if __name__ == "__main__":
    unittest.main()
