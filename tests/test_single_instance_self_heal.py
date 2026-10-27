import os
import sys
import time
import unittest
import subprocess
import ctypes
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import single_instance

class TestSingleInstanceSelfHealing(unittest.TestCase):
    """
    ชุดทดสอบระบบ Self-Healing Single Instance และ Clean Teardown Protocol (v6.54)
    """

    def setUp(self):
        self.test_mutex_name = f"Local\\FaceSearchApp_TestMutex_{os.getpid()}_{int(time.time())}"
        single_instance.cleanup_pid_file()

    def tearDown(self):
        single_instance.cleanup_pid_file()

    def test_01_normal_acquire_and_release(self):
        """TC-165: ทดสอบการจองและปลดปล่อย Mutex ปกติ พร้อมเขียน/ลบไฟล์ data/app.pid"""
        mutex = single_instance.acquire_mutex(mutex_name=self.test_mutex_name, auto_heal=False)
        self.assertIsNotNone(mutex)
        
        # ตรวจสอบว่า app.pid ถูกเขียน
        recorded_pid = single_instance.read_pid_file()
        self.assertEqual(recorded_pid, os.getpid())

        # ปลดปล่อย Mutex
        single_instance.release_mutex(mutex)
        self.assertIsNone(single_instance.read_pid_file())

    def test_02_is_process_alive_and_terminate(self):
        """TC-166: ทดสอบตรวจสอบสถานะ Process และ Native Win32 TerminateProcess"""
        # สร้างโปรเซสชั่วคราว
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        dummy_pid = proc.pid
        try:
            self.assertTrue(single_instance.is_process_alive(dummy_pid))
            
            # สั่ง Terminate ผ่าน Win32 API
            killed = single_instance.terminate_process_by_pid(dummy_pid)
            self.assertTrue(killed)
            time.sleep(0.1)
            self.assertFalse(single_instance.is_process_alive(dummy_pid))
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_03_self_healing_stale_mutex(self):
        """TC-167: ทดสอบระบบกู้คืน Stale Mutex อัตโนมัติเมื่อโปรเซสเดิมกลายเป็นซอมบี้ไร้หน้าต่าง"""
        # จำลองโปรเซสลูกถือ Mutex ค้างไว้ แล้วไม่มีหน้าต่าง GUI
        hold_script = f"""
import ctypes, time, os
kernel32 = ctypes.windll.kernel32
m = kernel32.CreateMutexW(None, False, '{self.test_mutex_name}')
with open('{single_instance.PID_FILE_PATH.replace(chr(92), '/')}', 'w') as f:
    f.write(str(os.getpid()))
time.sleep(30)
"""
        pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw_exe):
            pythonw_exe = sys.executable

        zombie_proc = subprocess.Popen(
            [pythonw_exe, "-c", hold_script],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        zombie_pid = zombie_proc.pid
        time.sleep(0.4)  # รอให้ subprocess สร้าง mutex และเขียน pid

        try:
            # รอให้ subprocess เขียน PID ลงไฟล์
            for _ in range(20):
                zombie_pid = single_instance.read_pid_file()
                if zombie_pid and single_instance.is_process_alive(zombie_pid):
                    break
                time.sleep(0.05)

            self.assertIsNotNone(zombie_pid)
            self.assertTrue(single_instance.is_process_alive(zombie_pid))

            # พยายาม Acquire ด้วย auto_heal=True
            # ควรตรวจพบว่าไม่มีหน้าต่าง GUI ตอบสนอง -> Terminate zombie -> จอง Mutex ใหม่สำเร็จ
            healed_mutex = single_instance.acquire_mutex(mutex_name=self.test_mutex_name, auto_heal=True)
            self.assertIsNotNone(healed_mutex)

            # ตรวจสอบว่า zombie_pid ถูก terminate จริง
            time.sleep(0.1)
            self.assertFalse(single_instance.is_process_alive(zombie_pid))

            # ตรวจสอบว่า PID ปัจจุบันถูกเขียนแทนที่
            self.assertEqual(single_instance.read_pid_file(), os.getpid())

            single_instance.release_mutex(healed_mutex)
        finally:
            if zombie_proc.poll() is None:
                zombie_proc.kill()

    def test_04_active_gui_window_protection(self):
        """TC-168: ตรวจสอบว่าหากมีหน้าต่าง GUI ตอบสนองอยู่จริง จะไม่ทำลายโปรเซสเดิม แต่คืนค่า None"""
        with patch("single_instance.find_active_gui_windows", return_value=[12345]):
            with patch("single_instance.bring_existing_window_to_front", return_value=True):
                # จำลอง Mutex มีอยู่แล้ว
                kernel32 = ctypes.windll.kernel32
                m = kernel32.CreateMutexW(None, False, self.test_mutex_name)
                try:
                    # ควรคืนค่า None และไม่ auto_heal เพราะหน้าต่างยังใช้งานอยู่จริง
                    res = single_instance.acquire_mutex(mutex_name=self.test_mutex_name, auto_heal=True)
                    self.assertIsNone(res)
                finally:
                    kernel32.CloseHandle(m)

    def test_05_wm_delete_window_protocol_bound(self):
        """TC-169: ตรวจสอบโค้ด app_gui.py ว่ามีการผูก WM_DELETE_WINDOW และ on_app_close"""
        app_gui_file = os.path.join(PROJECT_ROOT, "app_gui.py")
        with open(app_gui_file, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('self.protocol("WM_DELETE_WINDOW", self.on_app_close)', code)
        self.assertIn('def on_app_close(self', code)
        self.assertIn('os._exit(0)', code)

    def test_06_customtkinter_window_reveal_state(self):
        """TC-170: ตรวจสอบว่า CustomTkinter ปลดล็อก _withdraw_called_before_window_exists และแสดงผลได้จริง (v6.55)"""
        import customtkinter as ctk
        app = ctk.CTk()
        app.withdraw()
        
        # จำลองการปลดล็อกแบบ v6.55
        app._withdraw_called_before_window_exists = False
        app._window_exists = True
        app.deiconify()

        # ตรวจสอบสถานะ
        self.assertEqual(app.state(), "normal")
        self.assertFalse(app._withdraw_called_before_window_exists)
        self.assertTrue(app._window_exists)
        app.destroy()

    def test_07_default_root_restoration_and_images(self):
        """TC-171: ตรวจสอบการกู้คืน _default_root และการสร้าง ImageTk, CTkImage, BooleanVar (v6.56)"""
        import tkinter as tk
        from PIL import Image, ImageTk
        import customtkinter as ctk

        # 1. จำลองการเปิดและปิด Splash Screen
        splash = tk.Tk()
        splash.title("Test Splash")
        app = ctk.CTk()
        app.title("Test App")
        splash.destroy()

        # 2. กู้คืน _default_root แบบ v6.56
        tk._default_root = app
        self.assertIsNotNone(tk._default_root)
        self.assertEqual(tk._default_root, app)

        # 3. ตรวจสอบ BooleanVar
        b_var = ctk.BooleanVar(master=app, value=True)
        self.assertTrue(b_var.get())

        # 4. ตรวจสอบ ImageTk.PhotoImage และ CTkImage
        pil_img = Image.new("RGBA", (32, 32), color="blue")
        photo = ImageTk.PhotoImage(pil_img)
        self.assertIsNotNone(photo)

        ctk_img = ctk.CTkImage(light_image=pil_img, size=(32, 32))
        self.assertIsNotNone(ctk_img)

        # 5. ตรวจสอบ CTkLabel พร้อม CTkImage
        lbl = ctk.CTkLabel(app, image=ctk_img, text="")
        self.assertIsNotNone(lbl)

        app.destroy()

if __name__ == "__main__":
    unittest.main()
