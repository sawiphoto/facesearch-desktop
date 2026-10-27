import os
import sys
import logging

logger = logging.getLogger("FaceSearchApp")

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_APP_REG_NAME = "SchoolFaceFinderTray"


def get_default_autostart_command() -> str:
    """
    สร้างคำสั่งมาตรฐานสำหรับเปิดโปรแกรมแบบไร้หน้าต่างดำและซ่อนลง System Tray ทันทีเมื่อเปิดเครื่อง (--tray)
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    exe_launcher = os.path.join(project_root, "SchoolFaceFinder.exe")
    if os.path.exists(exe_launcher):
        return f'"{exe_launcher}" --tray'
    main_script = os.path.join(project_root, "main.py")

    venv_pythonw = os.path.join(project_root, "venv", "Scripts", "pythonw.exe")
    if os.path.exists(venv_pythonw):
        exe_path = venv_pythonw
    else:
        exe_path = sys.executable
        if exe_path.lower().endswith("python.exe"):
            candidate_w = exe_path[:-10] + "pythonw.exe"
            if os.path.exists(candidate_w):
                exe_path = candidate_w

    return f'"{exe_path}" "{main_script}" --tray'


def is_autostart_enabled(app_name: str = DEFAULT_APP_REG_NAME) -> bool:
    """ตรวจสอบว่าได้ลงทะเบียนเปิดโปรแกรมอัตโนมัติพร้อม Windows ไว้หรือไม่"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, app_name)
            return bool(val and str(val).strip())
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug(f"[AUTOSTART] Error checking registry key '{app_name}': {e}")
        return False


def enable_autostart(app_name: str = DEFAULT_APP_REG_NAME, command: str = None) -> bool:
    """เปิดใช้งานการรันโปรแกรมอัตโนมัติเมื่อเปิด Windows (บันทึกลง HKCU\\...\\Run)"""
    if sys.platform != "win32":
        return False
    cmd = command or get_default_autostart_command()
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
        logger.info(f"[AUTOSTART] ✅ เปิดใช้งาน Start with Windows สำเร็จ ({app_name} -> {cmd})")
        return True
    except Exception as e:
        logger.error(f"[AUTOSTART] ❌ ไม่สามารถตั้งค่า Start with Windows ได้: {e}")
        return False


def disable_autostart(app_name: str = DEFAULT_APP_REG_NAME) -> bool:
    """ปิดใช้งานการรันโปรแกรมอัตโนมัติเมื่อเปิด Windows"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, app_name)
                logger.info(f"[AUTOSTART] 🗑️ ยกเลิก Start with Windows เรียบร้อยแล้ว ({app_name})")
            except FileNotFoundError:
                pass
        return True
    except Exception as e:
        logger.error(f"[AUTOSTART] ❌ ไม่สามารถลบค่า Start with Windows ได้: {e}")
        return False


def set_autostart(enable: bool, app_name: str = DEFAULT_APP_REG_NAME, command: str = None) -> bool:
    """สลับสถานะการเปิดโปรแกรมอัตโนมัติพร้อม Windows ตามค่า boolean"""
    if enable:
        return enable_autostart(app_name=app_name, command=command)
    return disable_autostart(app_name=app_name)
