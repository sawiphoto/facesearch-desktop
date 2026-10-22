import os
import sys
import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183

def acquire_mutex(mutex_name="Local\\FaceSearchApp_SingleInstance_Mutex_2026"):
    """
    จอง Named Mutex สำหรับ Windows OS
    คืนค่า handle ถ้าสำเร็จ หรือคืนค่า None หากมีโปรแกรม instance อื่นทำงานอยู่แล้ว
    """
    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            if mutex:
                kernel32.CloseHandle(mutex)
            return None
        return mutex
    except Exception:
        # Fallback หากสภาพแวดล้อมไม่รองรับ ctypes (เช่น non-Windows)
        return True

def release_mutex(mutex):
    """ปลดปล่อย Mutex เมื่อปิดโปรแกรม"""
    try:
        if mutex and mutex is not True:
            ctypes.windll.kernel32.CloseHandle(mutex)
    except Exception:
        pass

def bring_existing_window_to_front(title_keywords=("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร", "FACE MATCHING")):
    """ค้นหาหน้าต่างเดิมที่เปิดอยู่และนำขึ้นมาแสดงข้างหน้าสุด (Foreground)"""
    try:
        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        
        found_hwnds = []
        def foreach_window(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    for kw in title_keywords:
                        if kw.lower() in title.lower():
                            found_hwnds.append(hwnd)
                            break
            return True
            
        EnumWindows(EnumWindowsProc(foreach_window), 0)
        for hwnd in found_hwnds:
            user32.ShowWindow(hwnd, 9)  # 9 = SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
