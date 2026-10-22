import os
import sys
import logging

def setup_directories():
    """สร้างไดเรกทอรีพื้นฐานที่จำเป็นสำหรับโครงสร้างโปรเจกต์"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    
    # 1. โฟลเดอร์เก็บ credentials
    os.makedirs(os.path.join(project_root, "config"), exist_ok=True)
    # 2. โฟลเดอร์เก็บข้อมูล SQLite & Settings
    os.makedirs(os.path.join(project_root, "data"), exist_ok=True)
    # 3. โฟลเดอร์เก็บโมเดล AI
    os.makedirs(os.path.join(project_root, "models"), exist_ok=True)

if __name__ == "__main__":
    project_root = os.path.dirname(os.path.abspath(__file__))

    # ตั้งค่า handlers ให้รองรับทั้ง python.exe (Console) และ pythonw.exe (Windowless - sys.stdout is None)
    handlers = []
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    log_file = os.path.join(project_root, "app_execution.log")
    handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=handlers
    )
    
    # ดำเนินการสร้างไดเรกทอรีที่จำเป็น
    setup_directories()
    
    # เรียกใช้โปรแกรม GUI หลัก
    try:
        from app_gui import FaceSearchApp
        app = FaceSearchApp()
        app.mainloop()
    except Exception as e:
        logging.error(f"Failed to start GUI application: {e}", exc_info=True)
        if sys.stdin is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            try:
                input("\nPress Enter to exit...")
            except Exception:
                pass
        else:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("เกิดข้อผิดพลาดในการเริ่มโปรแกรม", f"ไม่สามารถเปิดโปรแกรมได้:\n{e}\n\nกรุณาตรวจสอบ app_execution.log")
                root.destroy()
            except Exception:
                pass
