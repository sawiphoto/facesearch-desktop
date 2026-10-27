import os
import sys
import tkinter as tk
from tkinter import ttk

class SplashScreen:
    """
    หน้าต่าง Splash Screen น้ำหนักเบาพิเศษ (Pure Tkinter)
    เปิดได้ทันทีใน <0.15 วินาที พร้อมแถบ Progress Bar (0% - 100%)
    และป้ายข้อความแสดงสถานะการโหลดแบบเรียลไทม์ (v6.67)
    """
    def __init__(self, title="GOOGLE PHOTOS FACE FINDER", version="v6.67"):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.overrideredirect(True)  # ไร้กรอบขอบหน้าต่างแบบโมเดิร์น
        self.root.attributes("-topmost", True)  # อยู่บนสุดเสมอขณะโหลด
        
        # ขนาดและการจัดกึ่งกลางหน้าจอ
        width = 520
        height = 270
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, int((screen_width - width) / 2))
        y = max(0, int((screen_height - height) / 2))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        # ธีมสี Dark Navy (#1A252F / #243342 / #3498DB)
        self.bg_color = "#121212"
        self.card_color = "#1E1F22"
        self.accent_color = "#8AB4F8"
        self.text_title_color = "#8AB4F8"
        self.text_sub_color = "#C4C7C5"
        
        self.root.configure(bg=self.bg_color)
        
        # กรอบด้านใน (Card container พร้อมขอบบางๆ)
        self.card = tk.Frame(self.root, bg=self.card_color, highlightbackground="#3C4043", highlightthickness=2)
        self.card.pack(fill="both", expand=True, padx=4, pady=4)
        
        # โลโก้ / หัวข้อ
        self.lbl_title = tk.Label(
            self.card,
            text=f"✨ {title}",
            font=("Segoe UI", 17, "bold"),
            fg=self.text_title_color,
            bg=self.card_color
        )
        self.lbl_title.pack(pady=(22, 2))
        
        # ป้ายเวอร์ชัน
        self.lbl_version = tk.Label(
            self.card,
            text=f"Version {version} • GPU AI Accelerated",
            font=("Segoe UI", 10, "bold"),
            fg="#81C995",
            bg=self.card_color
        )
        self.lbl_version.pack(pady=(0, 4))
        
        # คำอธิบายย่อย
        self.lbl_subtitle = tk.Label(
            self.card,
            text="ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากรโรงเรียน",
            font=("Segoe UI", 10),
            fg=self.text_sub_color,
            bg=self.card_color
        )
        self.lbl_subtitle.pack(pady=(0, 18))
        
        # แถบ Progress Bar พร้อม Frame ครอบ
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Splash.Horizontal.TProgressbar",
            troughcolor="#121212",
            background="#1A73E8",
            bordercolor="#3C4043",
            lightcolor="#8AB4F8",
            darkcolor="#1765CC"
        )
        
        self.pb = ttk.Progressbar(
            self.card,
            style="Splash.Horizontal.TProgressbar",
            orient="horizontal",
            length=440,
            mode="determinate"
        )
        self.pb.pack(pady=(0, 8))
        
        # แถวสถานะล่าง: ข้อความฝั่งซ้าย + ตัวเลขเปอร์เซ็นต์ฝั่งขวา
        status_frame = tk.Frame(self.card, bg=self.card_color)
        status_frame.pack(fill="x", padx=40, pady=(0, 15))
        
        self.lbl_status = tk.Label(
            status_frame,
            text="กำลังเริ่มต้นระบบและตรวจสอบสภาพแวดล้อม...",
            font=("Segoe UI", 9),
            fg="#E8EAED",
            bg=self.card_color,
            anchor="w"
        )
        self.lbl_status.pack(side="left", fill="x", expand=True)
        
        self.lbl_percent = tk.Label(
            status_frame,
            text="0%",
            font=("Segoe UI", 9, "bold"),
            fg=self.accent_color,
            bg=self.card_color,
            anchor="e"
        )
        self.lbl_percent.pack(side="right")
        
        # อัปเดตทันทีเพื่อให้หน้าต่างปรากฏ
        self.root.update()

    def update_progress(self, percent: int, text: str = ""):
        """อัปเดตเปอร์เซ็นต์ (0-100) และข้อความสถานะ"""
        try:
            if not self.root.winfo_exists():
                return
            pct = max(0, min(100, int(percent)))
            self.pb["value"] = pct
            self.lbl_percent.config(text=f"{pct}%")
            if text:
                self.lbl_status.config(text=text)
            self.root.update()
        except Exception:
            pass

    def close(self):
        """ปิดหน้าต่าง Splash Screen"""
        try:
            if self.root and self.root.winfo_exists():
                self.root.destroy()
        except Exception:
            pass
