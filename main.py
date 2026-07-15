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
    # ตั้งค่า logging ระดับคอนโซลพื้นฐานตอนเริ่มต้น
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
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
        input("\nPress Enter to exit...")
