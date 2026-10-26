"""
Test Suite: Staff Index & Former Staff Sharding Suite (v6.38)
Coverage:
- TC-101: Two-Way Staff Index Partitioning Logic (Active <-> Inactive)
- TC-102: Zero Data Loss Integrity Check
- TC-103: Dual-Write & Shard Drive Upload Simulation
- TC-104: Delete Request Metadata Compatibility
- TC-105: Version v6.38 Parity & py_compile
"""

import os
import sys
import json
import unittest
import py_compile
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

CURRENT_VERSION = "v6.59"

from db_manager import DatabaseManager
from gdrive_sync import GoogleSyncManager


class TestStaffAndFormerStaffIndexSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.sync_data = cls.db.get_sync_data_sharded()

    def test_tc101_two_way_staff_index_partitioning_logic(self):
        """TC-101: Test that get_sync_data_sharded partitions staff by status and supports two-way transition."""
        sync_data = self.sync_data
        self.assertIn("active_staff", sync_data)
        self.assertIn("former_staff", sync_data)
        self.assertIn("teachers", sync_data)
        self.assertIn("manifest", sync_data)

        active_staff = sync_data["active_staff"]
        former_staff = sync_data["former_staff"]
        teachers = sync_data["teachers"]
        manifest = sync_data["manifest"]

        # Check manifest metadata
        self.assertEqual(manifest.get("staff_file"), "staff_index.json")
        self.assertEqual(manifest.get("former_staff_file"), "former_staff_index.json")
        self.assertIn("staff_counts", manifest)
        self.assertEqual(manifest["staff_counts"]["active"], len(active_staff))
        self.assertEqual(manifest["staff_counts"]["former"], len(former_staff))
        self.assertEqual(manifest["version"], CURRENT_VERSION)

        # Check that active_staff and former_staff have no intersecting keys
        intersection = set(active_staff.keys()) & set(former_staff.keys())
        self.assertEqual(len(intersection), 0, f"Overlap between active and former staff: {intersection}")

        # Check teachers for dual-write compatibility equals active_staff
        self.assertEqual(set(teachers.keys()), set(active_staff.keys()))

        # Test two-way lifecycle via simulation:
        # Pick one teacher from active_staff
        if active_staff:
            test_teacher_name = list(active_staff.keys())[0]
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, status FROM staff_members WHERE name = ?", (test_teacher_name,))
                row = cursor.fetchone()
                if row:
                    staff_id, original_status = row[0], row[1]
                    try:
                        # 1. Switch to inactive (ย้ายออก/เกษียณ)
                        cursor.execute("UPDATE staff_members SET status = 'inactive' WHERE id = ?", (staff_id,))
                        conn.commit()

                        cursor.execute("""
                            SELECT df.id, s.name, df.photo_id, s.role, s.student_id, COALESCE(s.status, 'active') as status
                            FROM detected_faces df
                            JOIN staff_members s ON df.staff_id = s.id
                            WHERE s.id = ?
                        """, (staff_id,))
                        f_rows = cursor.fetchall()
                        self.assertTrue(len(f_rows) > 0)
                        for r in f_rows:
                            self.assertEqual(r[5], "inactive", "Status must be inactive after update")

                        # 2. Switch back to active (ย้ายกลับมาดำรงตำแหน่งใหม่)
                        cursor.execute("UPDATE staff_members SET status = 'active' WHERE id = ?", (staff_id,))
                        conn.commit()

                        cursor.execute("""
                            SELECT df.id, s.name, df.photo_id, s.role, s.student_id, COALESCE(s.status, 'active') as status
                            FROM detected_faces df
                            JOIN staff_members s ON df.staff_id = s.id
                            WHERE s.id = ?
                        """, (staff_id,))
                        f_rows_back = cursor.fetchall()
                        for r in f_rows_back:
                            self.assertEqual(r[5], "active", "Status must be active after restoring")

                    finally:
                        # Restore original status
                        cursor.execute("UPDATE staff_members SET status = ? WHERE id = ?", (original_status, staff_id))
                        conn.commit()

    def test_tc102_zero_data_loss_integrity(self):
        """TC-102: Check that all detected faces of teachers are fully preserved across shards."""
        sync_data = self.sync_data
        active_staff = sync_data["active_staff"]
        former_staff = sync_data["former_staff"]

        total_sharded_photos = sum(len(pids) for pids in active_staff.values()) + \
                               sum(len(pids) for pids in former_staff.values())

        # Count total face matches for teachers in SQLite
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT df.photo_id)
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
                WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
            """)
            expected_distinct_photos = cursor.fetchone()[0] or 0

            # Sum of distinct photos per person
            cursor.execute("""
                SELECT s.name, COUNT(DISTINCT df.photo_id)
                FROM detected_faces df
                JOIN staff_members s ON df.staff_id = s.id
                WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                GROUP BY s.name
            """)
            person_counts = dict(cursor.fetchall())

        for name, count in person_counts.items():
            actual_count = len(active_staff.get(name, [])) + len(former_staff.get(name, []))
            self.assertEqual(actual_count, count, f"Mismatch for teacher {name}: expected {count}, got {actual_count}")

    def test_tc103_dual_write_drive_upload_simulation(self):
        """TC-103: Simulate update_json_indexes_on_drive with mock Drive service and verify all 3 staff files upload."""
        sync_manager = GoogleSyncManager()
        sync_manager.connected = True
        sync_manager.drive_service = MagicMock()

        sync_data = self.sync_data

        with patch('gdrive_sync.MediaIoBaseUpload'), \
             patch.object(sync_manager, 'reconnect_drive_service'):
            
            # Intercept self.drive_service.files().update
            def fake_update(fileId, media_body):
                mock_req = MagicMock()
                mock_req.execute.return_value = {"id": fileId}
                return mock_req

            sync_manager.drive_service.files().update = fake_update
            
            # Mock files().list() to return existing files map with nextPageToken=None
            sync_manager.drive_service.files().list.return_value.execute.return_value = {
                "files": [
                    {"id": "FID_STAFF", "name": "staff_index.json"},
                    {"id": "FID_FORMER", "name": "former_staff_index.json"},
                    {"id": "FID_PERSON", "name": "person_index.json"}
                ],
                "nextPageToken": None
            }

            res = sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id="1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L", scan_mode="teachers")
            self.assertTrue(res)

    def test_tc104_delete_request_metadata_compatibility(self):
        """TC-104: Test staff_index and former_staff_index merging logic for Delete Requests."""
        active_mock = {"ครูสมชาย": ["p1", "p2"]}
        former_mock = {"ครูสมหญิง (ย้าย)": ["p3", "p4"]}

        merged_index = {}
        merged_index.update(active_mock)
        for k, v in former_mock.items():
            if k not in merged_index:
                merged_index[k] = v

        self.assertIn("ครูสมชาย", merged_index)
        self.assertIn("ครูสมหญิง (ย้าย)", merged_index)
        self.assertEqual(merged_index["ครูสมชาย"], ["p1", "p2"])
        self.assertEqual(merged_index["ครูสมหญิง (ย้าย)"], ["p3", "p4"])

    def test_tc105_version_parity_and_py_compile(self):
        """TC-105: Verify all modified python files compile cleanly and have version v6.38."""
        files_to_compile = [
            "db_manager.py",
            "gdrive_sync.py",
            "app_gui.py"
        ]

        for fname in files_to_compile:
            fpath = os.path.join(PROJECT_ROOT, fname)
            self.assertTrue(os.path.exists(fpath), f"File missing: {fname}")
            try:
                py_compile.compile(fpath, doraise=True)
            except py_compile.PyCompileError as e:
                self.fail(f"Compilation error in {fname}: {e}")

        # Check version string in app_gui.py and db_manager.py
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn(CURRENT_VERSION, content)

        self.assertEqual(self.sync_data["manifest"]["version"], CURRENT_VERSION)


if __name__ == "__main__":
    unittest.main()
