import os
import sys
import time
import logging
import threading

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
    try:
        os.chdir(project_root)
    except Exception:
        pass

    start_in_tray = ("--tray" in sys.argv) or ("--minimized" in sys.argv)

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

    # 1. ป้องกันการเปิดโปรแกรมซ้ำซ้อน และระบบกู้คืนโปรเซสซอมบี้อัตโนมัติ (Self-Healing Single Instance v6.55)
    from single_instance import acquire_mutex, release_mutex, bring_existing_window_to_front, cleanup_pid_file, send_tray_wakeup_signal
    app_mutex = acquire_mutex(auto_heal=True)
    if app_mutex is None:
        logging.warning("⚠️ มีโปรแกรม FaceSearchApp กำลังทำงานอยู่แล้ว ทำการปลุกจาก System Tray / สลับไปหน้าต่างเดิม")
        send_tray_wakeup_signal()
        bring_existing_window_to_front()
        sys.exit(0)

    # 2. เปิดหน้าต่าง Splash Screen ทันที (<0.15s) ยกเว้นกรณีเปิดแบบซ่อนลงถาด System Tray (--tray)
    splash = None
    if not start_in_tray:
        from splash_screen import SplashScreen
        splash = SplashScreen(version="v6.66")
        splash.update_progress(10, "กำลังตรวจสอบไดเรกทอรีและสภาพแวดล้อมระบบ...")

    # ดำเนินการสร้างไดเรกทอรีที่จำเป็น
    setup_directories()
    if splash:
        splash.update_progress(20, "กำลังเชื่อมต่อฐานข้อมูล SQLite และการตั้งค่า...")

    # 3. โหลด AI InsightFace & Components ใน Worker Thread แบบ Pre-warming
    worker_state = {
        "analyzer": None,
        "error": None,
        "done": False,
        "progress": 30,
        "status": "กำลังเตรียมโมเดล AI InsightFace & AntelopeV2..."
    }

    def _init_worker():
        try:
            worker_state["progress"] = 40
            worker_state["status"] = "กำลังโหลดเอนจิน AI InsightFace (Detection & Recognition)..."
            from face_analyzer import FaceAnalyzer
            analyzer = FaceAnalyzer(use_gpu=True)
            worker_state["progress"] = 60
            worker_state["status"] = "กำลังโหลดโมเดล AntelopeV2 (ONNX) และทดสอบ CUDA Acceleration..."
            analyzer.initialize()
            worker_state["analyzer"] = analyzer

            worker_state["progress"] = 85
            worker_state["status"] = "กำลังเตรียมส่วนติดต่อผู้ใช้ (CustomTkinter UI)..."
            import app_gui

            worker_state["progress"] = 96
            worker_state["status"] = "พร้อมเข้าสู่โปรแกรม..."
        except Exception as err:
            worker_state["error"] = err
        finally:
            worker_state["done"] = True

    init_thread = threading.Thread(target=_init_worker, daemon=True)
    init_thread.start()

    # ลูปอัปเดตหน้าต่าง Splash Screen ขณะโหลดโมเดลในพื้นหลัง
    while not worker_state["done"]:
        if splash:
            splash.update_progress(worker_state["progress"], worker_state["status"])
        time.sleep(0.05)

    if worker_state["error"]:
        if splash:
            splash.close()
        logging.error(f"Failed to start GUI application during model pre-warm: {worker_state['error']}", exc_info=True)
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("เกิดข้อผิดพลาดในการเริ่มโปรแกรม", f"ไม่สามารถโหลดโมเดล AI ได้:\n{worker_state['error']}\n\nกรุณาตรวจสอบ app_execution.log")
        root.destroy()
        release_mutex(app_mutex)
        sys.exit(1)

    # 4. เรียกใช้โปรแกรม GUI หลัก พร้อมส่ง Analyzer และ Splash Screen เข้าไป
    # FaceSearchApp จะสร้างวิดเจ็ตในพื้นหลัง (Hidden) พร้อมอัปเดต Splash จนถึง 100%
    # แล้วสลับแสดงหน้าต่างหลักและปิด Splash Screen พร้อมกันทันทีในระดับมิลลิวินาที (Zero-Gap Seamless Transition v6.52)
    try:
        from app_gui import FaceSearchApp
        app = FaceSearchApp(analyzer=worker_state["analyzer"], splash=splash, app_mutex=app_mutex, enable_tray=True, start_in_tray=start_in_tray)
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
    finally:
        from single_instance import release_mutex, cleanup_pid_file
        cleanup_pid_file()
        release_mutex(app_mutex)
        import os
        os._exit(0)
