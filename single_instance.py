import os
import sys
import time
import logging
import ctypes
from ctypes import wintypes

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
DEFAULT_MUTEX_NAME = "Local\\FaceSearchApp_SingleInstance_Mutex_2026"
PID_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.pid")
TRAY_WAKEUP_SIGNAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tray_wakeup.signal")


def send_tray_wakeup_signal():
    """ส่งสัญญาณปลุกหน้าต่างโปรแกรมที่ซ่อนอยู่ในถาด System Tray ให้เด้งขึ้นมาแสดงผล (v6.69)"""
    try:
        os.makedirs(os.path.dirname(TRAY_WAKEUP_SIGNAL_PATH), exist_ok=True)
        with open(TRAY_WAKEUP_SIGNAL_PATH, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return False


def check_and_consume_tray_wakeup_signal() -> bool:
    """ตรวจสอบและรับสัญญาณปลุกหน้าต่างจาก System Tray (คืนค่า True หากมีคำสั่งปลุก)"""
    try:
        if os.path.exists(TRAY_WAKEUP_SIGNAL_PATH):
            os.remove(TRAY_WAKEUP_SIGNAL_PATH)
            return True
    except Exception:
        pass
    return False

# Win32 Constants
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(wintypes.ULONG)),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', wintypes.LONG),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_char * 260)
    ]

def write_pid_file(pid=None):
    """บันทึก PID ปัจจุบันลงในไฟล์ data/app.pid"""
    try:
        os.makedirs(os.path.dirname(PID_FILE_PATH), exist_ok=True)
        current_pid = pid or os.getpid()
        with open(PID_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(str(current_pid))
    except Exception as e:
        logger.debug(f"Could not write PID file: {e}")

def read_pid_file():
    """อ่าน PID จากไฟล์ data/app.pid"""
    try:
        if os.path.exists(PID_FILE_PATH):
            with open(PID_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.isdigit():
                    return int(content)
    except Exception:
        pass
    return None

def cleanup_pid_file():
    """ลบไฟล์ data/app.pid เมื่อโปรแกรมปิดตัวลง"""
    try:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
    except Exception:
        pass

def is_process_alive(pid: int) -> bool:
    """ตรวจสอบว่า Process ID ยังมีชีวิตอยู่หรือไม่"""
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE = 259
    except Exception:
        pass
    return False

def terminate_process_by_pid(pid: int) -> bool:
    """ยุติการทำงานของ Process ตาม PID ทันที (Native Win32 TerminateProcess)"""
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if handle:
            ret = kernel32.TerminateProcess(handle, 1)
            kernel32.WaitForSingleObject(handle, 1000)
            kernel32.CloseHandle(handle)
            logger.info(f"[SINGLE_INSTANCE] 🛑 ยุติการทำงานของโปรเซสตกค้าง PID {pid} สำเร็จ")
            return bool(ret)
    except Exception as e:
        logger.error(f"[SINGLE_INSTANCE] เกิดข้อผิดพลาดในการ Terminate PID {pid}: {e}")
    return False

def find_active_gui_windows(title_keywords=("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร", "FACE MATCHING"), include_tray_hidden=True):
    """ค้นหา Handle ของหน้าต่าง GUI ที่กำลังเปิดใช้งาน (รวมถึงกรณีซ่อนอยู่ในถาด System Tray) และไม่ค้าง"""
    found_hwnds = []
    try:
        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        
        def foreach_window(hwnd, lParam):
            if include_tray_hidden or user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    for kw in title_keywords:
                        if kw.lower() in title.lower():
                            try:
                                if not user32.IsHungAppWindow(hwnd):
                                    found_hwnds.append(hwnd)
                            except Exception:
                                found_hwnds.append(hwnd)
                            break
            return True

        EnumWindows(EnumWindowsProc(foreach_window), 0)
    except Exception:
        pass
    return found_hwnds

def bring_existing_window_to_front(title_keywords=("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร", "FACE MATCHING")) -> bool:
    """ค้นหาหน้าต่างเดิมที่เปิดอยู่และนำขึ้นมาแสดงข้างหน้าสุด (คืนค่า True หากพบหน้าต่าง)"""
    found_hwnds = find_active_gui_windows(title_keywords)
    if not found_hwnds:
        return False
    try:
        user32 = ctypes.windll.user32
        for hwnd in found_hwnds:
            user32.ShowWindow(hwnd, 9)  # 9 = SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return bool(found_hwnds)

def kill_stale_project_processes():
    """ค้นหาและสั่งปิด Process ซอมบี้ของโปรเจกต์ที่ค้างอยู่โดยไม่มีหน้าต่าง GUI"""
    current_pid = os.getpid()
    project_dir = os.path.dirname(os.path.abspath(__file__)).lower()
    
    # 1. ตรวจสอบจาก data/app.pid ก่อน
    old_pid = read_pid_file()
    if old_pid and old_pid != current_pid and is_process_alive(old_pid):
        logger.warning(f"[SINGLE_INSTANCE] ⚠️ ตรวจพบ PID จาก app.pid ค้างอยู่: {old_pid} -> ทำการ Terminate")
        terminate_process_by_pid(old_pid)

    # 2. สแกนหา pythonw.exe (Windowless Python ของแอป) ที่รันจากโฟลเดอร์โปรเจกต์นี้
    try:
        kernel32 = ctypes.windll.kernel32
        hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if hSnapshot and hSnapshot != -1:
            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if kernel32.Process32First(hSnapshot, ctypes.byref(pe)):
                while True:
                    pid = pe.th32ProcessID
                    exe_name = pe.szExeFile.decode('ansi', errors='ignore').lower()
                    if pid != current_pid and exe_name == 'pythonw.exe':
                        # ตรวจสอบ Path ของ Executable
                        hProc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                        if hProc:
                            buff = ctypes.create_unicode_buffer(1024)
                            size = wintypes.DWORD(1024)
                            if kernel32.QueryFullProcessImageNameW(hProc, 0, buff, ctypes.byref(size)):
                                full_path = buff.value.lower()
                                if project_dir in full_path or "venv" in full_path:
                                    logger.warning(f"[SINGLE_INSTANCE] ⚠️ ตรวจพบโปรเซสซอมบี้ในโปรเจกต์: PID {pid} ({full_path}) -> สั่ง Terminate")
                                    kernel32.CloseHandle(hProc)
                                    terminate_process_by_pid(pid)
                                    hProc = None
                            if hProc:
                                kernel32.CloseHandle(hProc)
                    if not kernel32.Process32Next(hSnapshot, ctypes.byref(pe)):
                        break
            kernel32.CloseHandle(hSnapshot)
    except Exception as e:
        logger.error(f"[SINGLE_INSTANCE] Error scanning stale processes: {e}")

def acquire_mutex(mutex_name=DEFAULT_MUTEX_NAME, auto_heal=True):
    """
    จอง Named Mutex สำหรับ Windows OS พร้อมระบบ Self-Healing (v6.55)
    - หากมีโปรแกรม instance อื่นเปิดและมีหน้าต่างใช้งานอยู่จริง: คืนค่า None
    - หากพบ Mutex แต่ไม่มีหน้าต่างโปรแกรมใดๆ (Stale/Zombie Lock): ทำการเคลียร์โปรเซสซอมบี้และกู้คืน Mutex ให้ทันที
    """
    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        
        if last_error == ERROR_ALREADY_EXISTS:
            if mutex:
                kernel32.CloseHandle(mutex)
                mutex = None

            # ตรวจสอบว่ามีหน้าต่างโปรแกรมที่ตอบสนองอยู่จริงหรือไม่
            active_windows = find_active_gui_windows()
            if active_windows:
                # มีหน้าต่างอยู่จริง (หรือซ่อนอยู่ใน System Tray) -> ส่งสัญญาณปลุกและนำขึ้นมาข้างหน้า
                logger.info("[SINGLE_INSTANCE] พบโปรแกรมเดิมกำลังทำงานอยู่ (GUI/System Tray) ส่งสัญญาณปลุกหน้าต่างขึ้นมาแสดงข้างหน้า")
                send_tray_wakeup_signal()
                bring_existing_window_to_front()
                return None

            # ถ้าไม่มีหน้าต่างโปรแกรมเลย แต่ Mutex ยังติดอยู่ = STALE / ZOMBIE LOCK!
            if auto_heal:
                logger.warning("[SINGLE_INSTANCE] 🚨 ตรวจพบ Stale Mutex โดยไม่มีหน้าต่าง GUI ตอบสนอง! เริ่มระบบ Self-Healing กู้คืนอัตโนมัติ...")
                kill_stale_project_processes()
                time.sleep(0.15)  # รอ Windows kernel ปลดปล่อย Mutex handle
                cleanup_pid_file()

                # ลองจองใหม่อีกครั้ง
                new_mutex = kernel32.CreateMutexW(None, False, mutex_name)
                new_error = kernel32.GetLastError()
                if new_error == 0:
                    logger.info("[SINGLE_INSTANCE] ✅ กู้คืน Stale Mutex สำเร็จ! อนุญาตให้โปรแกรมเปิดใช้งานได้ทันที")
                    write_pid_file()
                    return new_mutex
                else:
                    if new_mutex:
                        kernel32.CloseHandle(new_mutex)
                    return None
            return None

        # จอง Mutex สำเร็จในครั้งแรก
        write_pid_file()
        return mutex
    except Exception as err:
        logger.error(f"[SINGLE_INSTANCE] acquire_mutex error: {err}")
        return True

def release_mutex(mutex):
    """ปลดปล่อย Mutex และลบไฟล์ PID เมื่อปิดโปรแกรม"""
    cleanup_pid_file()
    try:
        if mutex and mutex is not True:
            ctypes.windll.kernel32.CloseHandle(mutex)
    except Exception:
        pass
