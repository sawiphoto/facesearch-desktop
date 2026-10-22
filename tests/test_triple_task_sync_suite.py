import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import unittest
import os
import py_compile
import inspect
from db_manager import DatabaseManager
import app_gui
import scheduler_task

class TestTripleTaskSyncSuite(unittest.TestCase):
    """
    Test Suite for v6.46: Unified Triple-Task Google Drive JSON Sync Suite
    TC-139 to TC-142
    """

    def test_tc139_retroactive_match_scan_mode_parity(self):
        """TC-139: ตรวจสอบความถูกต้องของพารามิเตอร์ scan_mode ใน process_retroactive_match_headless"""
        sig = inspect.signature(app_gui.FaceSearchApp.process_retroactive_match_headless)
        params = list(sig.parameters.keys())
        self.assertIn("scan_mode", params, "process_retroactive_match_headless must accept scan_mode")
        self.assertEqual(sig.parameters["scan_mode"].default, "all", "default scan_mode must be 'all'")

        # ตรวจสอบ source code ใน app_gui.py
        with open("app_gui.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('scan_mode=scan_mode', code, "update_json_indexes_on_drive must receive scan_mode=scan_mode")
        self.assertIn('"1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L"', code, "Fallback folder must be 1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L")
        print("\n[TC-139 PASSED] process_retroactive_match_headless correctly uses scan_mode='all' and true folder ID.")

    def test_tc140_task2_and_task3_manual_sync_resilience(self):
        """TC-140: ตรวจสอบการเรียก _sync_all_json_to_drive ใน _run_task_2_only และ _run_task_3_only"""
        with open("scheduler_task.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Check _run_task_2_only
        self.assertIn("def _run_task_2_only(self):", code)
        task2_part = code.split("def _run_task_2_only(self):")[1].split("def ")[0]
        self.assertIn("self._sync_all_json_to_drive()", task2_part, "_run_task_2_only must call _sync_all_json_to_drive()")

        # Check _run_task_3_only
        self.assertIn("def _run_task_3_only(self):", code)
        task3_part = code.split("def _run_task_3_only(self):")[1].split("def ")[0]
        self.assertIn("self._sync_all_json_to_drive()", task3_part, "_run_task_3_only must call _sync_all_json_to_drive()")

        print("\n[TC-140 PASSED] Manual Task 2 and Task 3 runs both guarantee Drive JSON sync resilience.")

    def test_tc141_scheduled_tasks_final_consistency_sync(self):
        """TC-141: ตรวจสอบ Final Consistency Sync ใน run_scheduled_tasks และการส่ง scan_mode='all' ทุกจุด"""
        with open("scheduler_task.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Check run_scheduled_tasks has final sync
        sched_part = code.split("def run_scheduled_tasks(self):")[1].split("def _sync_all_json_to_drive")[0]
        self.assertIn("Final Consistency Sync", sched_part, "run_scheduled_tasks must have Final Consistency Sync block")
        self.assertIn("self._sync_all_json_to_drive()", sched_part)

        # Check _sync_all_json_to_drive fallback folder ID
        sync_method = code.split("def _sync_all_json_to_drive(self):")[1].split("def ")[0]
        self.assertIn("1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L", sync_method, "Fallback folder must be 1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L")

        # Check all process_retroactive_match_headless calls pass scan_mode="all"
        call_count = code.count('self.app_gui.process_retroactive_match_headless(matched_faces_to_process, scan_mode="all")')
        self.assertEqual(call_count, 3, f"Expected 3 occurrences of scan_mode='all', found {call_count}")

        print("\n[TC-141 PASSED] Full scheduled tasks loop includes final sync, and all 3 retroactive calls pass scan_mode='all'.")

    def test_tc142_student_data_integrity_and_version_parity(self):
        """TC-142: ตรวจสอบข้อมูล จตุรพร พูลสวัสดิ์ (23371) มี 14 รูป และตรวจ Version Parity v6.46 ทั่วระบบ"""
        db = DatabaseManager()
        sharded_data = db.get_sync_data_sharded()
        active_students = sharded_data.get("active_students", {})

        # Find Jaturaporn in active_students
        self.assertIn("จตุรพร พูลสวัสดิ์", active_students, "Student จตุรพร พูลสวัสดิ์ must exist in active_students")
        student_obj = active_students["จตุรพร พูลสวัสดิ์"]
        self.assertEqual(student_obj.get("student_id"), "23371")
        self.assertEqual(len(student_obj.get("photos", [])), 14, f"Student 23371 must have exactly 14 photos, got {len(student_obj.get('photos', []))}")

        # Check Version Parity v6.46+ / v6.47
        with open("app_gui.py", "r", encoding="utf-8") as f:
            gui_code = f.read()
        self.assertIn("v6.47", gui_code)
        self.assertIn("SYSTEM v6.47", gui_code)

        with open("db_manager.py", "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertIn('"version": "v6.47"', db_code)

        # py_compile verification
        py_compile.compile("app_gui.py", doraise=True)
        py_compile.compile("scheduler_task.py", doraise=True)
        py_compile.compile("db_manager.py", doraise=True)

        print("\n[TC-142 PASSED] Student 23371 data integrity verified (14 photos) & Version v6.46 parity confirmed across all modules.")

if __name__ == "__main__":
    unittest.main()
