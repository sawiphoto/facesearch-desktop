import logging
import threading
from PIL import Image, ImageDraw

logger = logging.getLogger("FaceSearchApp")


def create_google_photos_tray_icon(size: int = 64) -> Image.Image:
    """
    สร้างไอคอนสไตล์ Google Photos (4 สี: แดง, เหลือง, เขียว, ฟ้า) สำหรับแสดงใน Windows System Tray
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # พื้นหลังสี่เหลี่ยมขอบมนสีเข้มสไตล์ Material Dark
    pad = 2
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=max(8, size // 5),
        fill=(30, 31, 34, 255),
        outline=(60, 64, 67, 255),
        width=2
    )

    cx, cy = size // 2, size // 2
    r = int(size * 0.28)

    # 4 กลีบสี Google Photos (บน=แดง, ขวา=เหลือง, ล่าง=เขียว, ซ้าย=ฟ้า)
    # บน (Google Red #EA4335)
    draw.pieslice([cx - r, cy - r - 6, cx + r, cy + r - 6], start=200, end=340, fill=(234, 67, 53, 255))
    # ขวา (Google Yellow #FBBC04)
    draw.pieslice([cx - r + 6, cy - r, cx + r + 6, cy + r], start=290, end=70, fill=(251, 188, 4, 255))
    # ล่าง (Google Green #34A853)
    draw.pieslice([cx - r, cy - r + 6, cx + r, cy + r + 6], start=20, end=160, fill=(52, 168, 83, 255))
    # ซ้าย (Google Blue #4285F4)
    draw.pieslice([cx - r - 6, cy - r, cx + r - 6, cy + r], start=110, end=250, fill=(66, 133, 244, 255))

    # วงกลมเลนส์ตรงกลางสีขาวนวล
    inner_r = max(4, size // 9)
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(255, 255, 255, 255)
    )
    return img


class SystemTrayManager:
    """
    ตัวจัดการไอคอนในถาดระบบ Windows (System Tray / Show Hidden Icons) (v6.66)
    - รองรับการดับเบิลคลิกเพื่อเปิดหน้าต่างโปรแกรมหลักขึ้นมาใช้งานทันที
    - รองรับเมนูคลิกขวาสำหรับสั่งรัน Task 1, 2, 3 ทันที, หยุดงาน, เปิดหน้าตั้งค่า, หรือปิดโปรแกรมสมบูรณ์
    """
    def __init__(self, app_gui):
        self.app_gui = app_gui
        self.icon = None
        self.tray_thread = None
        self.is_running = False
        self._notified_minimize_once = False

    def start(self) -> bool:
        """เริ่มแสดงไอคอนใน System Tray บน Background Daemon Thread"""
        if self.is_running:
            return True
        try:
            import pystray
            from pystray import MenuItem as item, Menu

            icon_image = create_google_photos_tray_icon(64)

            menu = Menu(
                item("📸 เปิดหน้าต่างโปรแกรม (Open Window)", self._on_open_window, default=True),
                item("▶️ สั่งรัน Task 1, 2, 3 ตอนนี้ทันที (Run Now)", self._on_run_tasks_now),
                item("🛑 หยุดการทำงานชั่วคราว (Stop Running Task)", self._on_stop_tasks),
                Menu.SEPARATOR,
                item("⚙️ ตั้งค่าตารางเวลา (Schedule Settings)", self._on_open_settings),
                Menu.SEPARATOR,
                item("❌ ออกจากโปรแกรมโดยสมบูรณ์ (Exit)", self._on_exit_app),
            )

            self.icon = pystray.Icon(
                "SchoolFaceFinder",
                icon_image,
                "School Face Finder v6.66 (กำลังทำงานเบื้องหลัง)",
                menu
            )

            self.is_running = True
            self.tray_thread = threading.Thread(
                target=self._run_icon_loop,
                name="SystemTrayThread",
                daemon=True
            )
            self.tray_thread.start()
            logger.info("[TRAY] 🔔 เริ่มทำงานไอคอนใน System Tray (Show Hidden Icons) เรียบร้อยแล้ว")
            return True
        except Exception as e:
            self.is_running = False
            logger.error(f"[TRAY] ❌ ไม่สามารถเริ่ม System Tray ได้: {e}", exc_info=True)
            return False

    def _run_icon_loop(self):
        try:
            if self.icon:
                self.icon.run()
        except Exception as e:
            logger.debug(f"[TRAY] System tray loop ended: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """หยุดและนำไอคอนออกจาก System Tray อย่างสะอาด"""
        self.is_running = False
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    def update_tooltip(self, tooltip_text: str):
        """อัปเดตข้อความเมื่อเอาเมาส์ชี้ที่ไอคอนใน System Tray"""
        try:
            if self.icon and self.is_running:
                self.icon.title = str(tooltip_text)[:120]
        except Exception:
            pass

    def notify(self, title: str, message: str):
        """แสดงการแจ้งเตือนของ Windows จากถาด System Tray"""
        try:
            if self.icon and self.is_running:
                self.icon.notify(str(message), str(title))
        except Exception as e:
            logger.debug(f"[TRAY] Notification skipped: {e}")

    def _on_open_window(self, icon=None, item=None):
        if self.app_gui:
            try:
                self.app_gui.after(0, self.app_gui.show_from_tray)
            except Exception:
                pass

    def _on_run_tasks_now(self, icon=None, item=None):
        if self.app_gui and hasattr(self.app_gui, "scheduler") and self.app_gui.scheduler:
            try:
                logger.info("[TRAY] ▶️ ผู้ใช้สั่งรัน Task 1, 2, 3 ทันทีผ่านไอคอน System Tray")
                self.app_gui.after(0, self.app_gui.scheduler.run_scheduled_tasks_manual)
            except Exception:
                pass

    def _on_stop_tasks(self, icon=None, item=None):
        if self.app_gui and hasattr(self.app_gui, "scheduler") and self.app_gui.scheduler:
            try:
                logger.info("[TRAY] 🛑 ผู้ใช้สั่งหยุดงานชั่วคราวผ่านไอคอน System Tray")
                self.app_gui.after(0, self.app_gui.scheduler.request_stop)
            except Exception:
                pass

    def _on_open_settings(self, icon=None, item=None):
        if self.app_gui:
            try:
                def _show_and_select_settings():
                    self.app_gui.show_from_tray()
                    self.app_gui.select_menu("settings")
                self.app_gui.after(0, _show_and_select_settings)
            except Exception:
                pass

    def _on_exit_app(self, icon=None, item=None):
        logger.info("[TRAY] ❌ ผู้ใช้เลือกออกจากโปรแกรมโดยสมบูรณ์ผ่าน System Tray")
        self.stop()
        if self.app_gui:
            try:
                self.app_gui.after(0, lambda: self.app_gui.on_app_close(force_exit=True))
            except Exception:
                import os
                os._exit(0)
