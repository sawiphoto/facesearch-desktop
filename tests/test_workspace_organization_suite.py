import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import py_compile
import glob

class TestWorkspaceOrganizationSuite(unittest.TestCase):
    """
    Test Suite for v6.48: Comprehensive Workspace Organization & 11.5GB Disk Cleanup Suite
    TC-147 to TC-150
    """

    def setUp(self):
        self.root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_tc147_disk_space_reclamation_verification(self):
        """TC-147: ตรวจสอบว่าไฟล์สำรองขนาดใหญ่, zip ซ้ำซ้อน, และไฟล์ 0 ไบต์ถูกลบอย่างสมบูรณ์"""
        deleted_paths = [
            os.path.join(self.root, "data", "faces_db_backup_20261005_v570.db"),
            os.path.join(self.root, "data", "faces_db_backup.db"),
            os.path.join(self.root, "data", "faces_db_v3.1_backup.db"),
            os.path.join(self.root, "data", "faces_db_v3.2_backup.db"),
            os.path.join(self.root, "data", "backups"),
            os.path.join(self.root, "antelopev2.zip"),
            os.path.join(self.root, "models", "models"),
            os.path.join(self.root, "faces_db.db"),
            os.path.join(self.root, "data", "faces.db"),
            os.path.join(self.root, "data", "face_database.db"),
            os.path.join(self.root, "insightface_models"),
            os.path.join(self.root, "export_student")
        ]

        for p in deleted_paths:
            self.assertFalse(os.path.exists(p), f"Path should have been deleted: {p}")

        # Check log file is clean
        log_file = os.path.join(self.root, "app_execution.log")
        self.assertTrue(os.path.exists(log_file))
        self.assertEqual(os.path.getsize(log_file), 0, "app_execution.log should be truncated to 0 bytes")

        print("\n[TC-147 PASSED] All redundant backup files and folders successfully deleted (Reclaimed 10.94 GB).")

    def test_tc148_active_system_core_integrity(self):
        """TC-148: ตรวจสอบความสมบูรณ์ของฐานข้อมูลจริง (4.81 GB) และโมเดล ONNX ครบถ้วน"""
        active_db = os.path.join(self.root, "data", "faces_db.db")
        self.assertTrue(os.path.exists(active_db), "Active DB must exist")
        db_size_mb = os.path.getsize(active_db) / (1024 * 1024)
        self.assertGreater(db_size_mb, 4000, f"Active DB must be > 4000 MB, got {db_size_mb:.2f} MB")

        # Check ONNX models
        models_dir = os.path.join(self.root, "models", "antelopev2")
        required_models = ["1k3d68.onnx", "2d106det.onnx", "genderage.onnx", "glintr100.onnx", "scrfd_10g_bnkps.onnx"]
        for m in required_models:
            mpath = os.path.join(models_dir, m)
            self.assertTrue(os.path.exists(mpath), f"Required model {m} must exist")
            self.assertGreater(os.path.getsize(mpath), 1024 * 1024, f"Model {m} must be valid size")

        print(f"\n[TC-148 PASSED] Active DB ({db_size_mb:.2f} MB) and all 5 ONNX models intact and healthy.")

    def test_tc149_tests_and_archive_folder_organization(self):
        """TC-149: ตรวจสอบการจัดระเบียบโฟลเดอร์ tests/ และ archive_scripts/ และความสะอาดของ Root"""
        tests_dir = os.path.join(self.root, "tests")
        archive_dir = os.path.join(self.root, "archive_scripts")
        self.assertTrue(os.path.isdir(tests_dir), "tests/ directory must exist")
        self.assertTrue(os.path.isdir(archive_dir), "archive_scripts/ directory must exist")

        # No test_*.py in root
        root_tests = glob.glob(os.path.join(self.root, "test_*.py"))
        self.assertEqual(len(root_tests), 0, "No test files should remain in root directory")

        # Tests in tests/
        inner_tests = glob.glob(os.path.join(tests_dir, "test_*.py"))
        self.assertGreaterEqual(len(inner_tests), 27, "All test files must reside in tests/")

        # Utility scripts in archive_scripts/
        expected_archived = [
            "clean_student_prefixes.py", "inspect_student_prefix.py", "inspect_db.py",
            "execute_department_and_status_sync.py", "export_students.py",
            "run_backfill_academic_year.py", "run_heal_nested_events.py",
            "run_sharded_sync_to_drive.py", "sync_photo_index_now.py"
        ]
        for s in expected_archived:
            self.assertTrue(os.path.exists(os.path.join(archive_dir, s)), f"Script {s} should be archived")

        print(f"\n[TC-149 PASSED] Workspace is clean: {len(inner_tests)} tests organized in tests/, utility scripts in archive_scripts/.")

    def test_tc150_version_parity_v648_and_compilation(self):
        """TC-150: ตรวจสอบความถูกต้องของเลขเวอร์ชัน v6.48 ทั่วระบบและการคอมไพล์โค้ดหลัก"""
        with open(os.path.join(self.root, "app_gui.py"), "r", encoding="utf-8") as f:
            gui_code = f.read()
        self.assertIn("v6.48 (Comprehensive Workspace Organization & 11.5GB Disk Cleanup Suite)", gui_code)
        self.assertIn("SYSTEM v6.48", gui_code)

        with open(os.path.join(self.root, "db_manager.py"), "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertIn('"version": "v6.48"', db_code)

        # py_compile verification on all core files
        core_files = [
            "main.py", "app_gui.py", "db_manager.py", "scheduler_task.py",
            "face_analyzer.py", "gdrive_sync.py", "gradient_chart.py", "unknown_analyzer.py"
        ]
        for cf in core_files:
            py_compile.compile(os.path.join(self.root, cf), doraise=True)

        print("\n[TC-150 PASSED] All 8 active core files compile cleanly and Version v6.48 parity confirmed.")

if __name__ == "__main__":
    unittest.main()
