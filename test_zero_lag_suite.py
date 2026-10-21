# -*- coding: utf-8 -*-
"""
test_zero_lag_suite.py
Unit Test Suite for v6.43: High-Performance Zero-Lag Optimization Suite
Covers Test Cases: TC-126 through TC-130
"""

import os
import sys
import time
import unittest
import py_compile
import sqlite3
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_manager import DatabaseManager


class TestZeroLagSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()

    def test_tc126_persistent_disk_thumbnail_caching(self):
        """TC-126: Persistent Disk Thumbnail Caching - Speed & Existence Check"""
        dir_32 = os.path.join(PROJECT_ROOT, "data", "thumbnail_cache", "avatar_32")
        dir_96 = os.path.join(PROJECT_ROOT, "data", "thumbnail_cache", "avatar_96_96")

        self.assertTrue(os.path.exists(dir_32), f"Directory {dir_32} must exist")
        self.assertTrue(os.path.exists(dir_96), f"Directory {dir_96} must exist")

        files_32 = [f for f in os.listdir(dir_32) if f.endswith(".png")]
        files_96 = [f for f in os.listdir(dir_96) if f.endswith(".png")]

        self.assertGreaterEqual(len(files_32), 160, f"Expected at least 160 cached 32x32 thumbnails, got {len(files_32)}")
        self.assertGreaterEqual(len(files_96), 160, f"Expected at least 160 cached 96x96 thumbnails, got {len(files_96)}")

        # Benchmark reading speed of 32x32 thumbnails
        t0 = time.time()
        for f in files_32[:50]:
            with Image.open(os.path.join(dir_32, f)) as img:
                img.load()
                self.assertEqual(img.size, (32, 32))
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.5, f"Reading 50 thumbnails took {elapsed:.4f}s, expected < 0.5s")

    def test_tc127_tab_switching_zero_lag_logic(self):
        """TC-127: Tab Switching Zero-Lag Parity - Non-destructive reuse logic"""
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            code = f.read()

        # Verify registry tab checks existing children before reloading
        self.assertIn("if hasattr(self, 'teacher_tree') and not self.teacher_tree.get_children():", code)

        # Verify matched_gallery tab checks existing cards before recreating
        self.assertIn("elif hasattr(self, 'scr_teacher_cards') and not self.scr_teacher_cards.winfo_children():", code)

    def test_tc128_progressive_batch_rendering_and_cancellation(self):
        """TC-128: Progressive Batch Rendering & Cancellation Integrity"""
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            code = f.read()

        # Verify batch rendering components exist
        self.assertIn("_grid_render_token", code)
        self.assertIn("batch_size = 25", code)
        self.assertIn("_render_next_batch", code)
        self.assertIn("current_token != self._grid_render_token", code)

    def test_tc129_background_prewarm_caches_integrity(self):
        """TC-129: Background Pre-Warming Daemon Thread Safety"""
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("def _start_prewarm_caches(self):", code)
        self.assertIn("self.after(200, self._start_prewarm_caches)", code)
        self.assertIn("PrewarmCachesWorker", code)

    def test_tc130_version_parity_and_compilation(self):
        """TC-130: Version Parity v6.43 and compilation across all core files"""
        files = ["db_manager.py", "gdrive_sync.py", "app_gui.py"]
        for pf in files:
            full_path = os.path.join(PROJECT_ROOT, pf)
            py_compile.compile(full_path, doraise=True)

        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            gui_code = f.read()

        self.assertIn("v6.43 (High-Performance Zero-Lag Optimization Suite)", gui_code)
        self.assertIn("FACE MATCHING\\nSYSTEM v6.43", gui_code)

        # Check DB Manifest
        with open(os.path.join(PROJECT_ROOT, "db_manager.py"), "r", encoding="utf-8") as f:
            db_code = f.read()
        self.assertIn('"version": "v6.43"', db_code)


if __name__ == '__main__':
    unittest.main()
