import os
import sys
import re
import queue
import logging
import threading
import time
import json
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image
import numpy as np
import cv2
import webbrowser
import requests

# นำเข้าโมดูลหลังบ้านที่เราพัฒนาไว้
from db_manager import DatabaseManager, RAW_EXTENSIONS_MAP, get_camera_brand_from_filename, SW_DEPARTMENTS, clean_department_name
from face_analyzer import FaceAnalyzer, get_antelopev2_dir, get_project_root, decode_image_bytes, read_image_file
from gdrive_sync import GoogleSyncManager, is_generic_folder_name
from scheduler_task import SchedulerTask
from gradient_chart import GradientBarChart, get_gradient_color
import unknown_analyzer

# ==================== (v6.33) ระบบแยกวิเคราะห์ชื่อไฟล์คุณครูอัจฉริยะ (Smart Teacher Filename Parser) ====================
THAI_PREFIXES = [
    r'ว่าที่\s*ร้อยตรี\s*หญิง',
    r'ว่าที่\s*ร้อยตรี',
    r'ว่าที่\s*ร\.ต\.หญิง',
    r'ว่าที่\s*ร\.ต\.',
    r'นางสาว',
    r'น\.ส\.',
    r'นาย',
    r'นาง',
    r'ดร\.',
    r'ผศ\.ดร\.',
    r'รศ\.ดร\.',
    r'ศ\.ดร\.',
    r'ผศ\.',
    r'รศ\.',
    r'ศ\.',
    r'อาจารย์',
    r'อ\.',
    r'คุณครู',
    r'ครู',
    r'Mr\.',
    r'Mrs\.',
    r'Miss',
    r'Ms\.',
]

def parse_teacher_filename(filename):
    """
    แยกวิเคราะห์ชื่อไฟล์ครูออกเป็น (main_name, department, photo_index)
    ตัวอย่าง:
      'นายสมชาย ใจดี วิทยาศาสตร์  1.jpg' -> ('นายสมชาย ใจดี', 'วิทยาศาสตร์', 1)
      'นายสมชาย ใจดี วิทยาศาสตร์  2.jpg' -> ('นายสมชาย ใจดี', 'วิทยาศาสตร์', 2)
      'นางสาวสมหญิง สดใส คณิตศาสตร์ (2).png' -> ('นางสาวสมหญิง สดใส', 'คณิตศาสตร์', 2)
      'นายวิชาญ การงาน ภาษาไทย.jpg' -> ('นายวิชาญ การงาน', 'ภาษาไทย', 1)
      'นายสมศักดิ์ รักดี 1.jpg' -> ('นายสมศักดิ์ รักดี', '', 1)
    """
    base_name = os.path.splitext(os.path.basename(filename))[0].strip()
    photo_index = 1
    idx_match = re.search(r'[\s_\-\(\[\{]+(\d+)[\s\)\]\}]*$', base_name)
    if idx_match:
        try:
            photo_index = int(idx_match.group(1))
            base_name = base_name[:idx_match.start()].strip()
        except Exception:
            photo_index = 1
            
    clean_text = re.sub(r'\s+', ' ', base_name).strip()
    if not clean_text:
        return ("", "", photo_index)
        
    prefix_matched = None
    had_space = False
    remaining_after_prefix = clean_text
    
    for prefix_pat in THAI_PREFIXES:
        match = re.match(r'^(' + prefix_pat + r')(\s*)(.*)$', clean_text, re.IGNORECASE)
        if match:
            prefix_matched = match.group(1).strip()
            had_space = bool(match.group(2))
            remaining_after_prefix = match.group(3).strip()
            break
            
    if prefix_matched:
        tokens = [t for t in remaining_after_prefix.split(' ') if t]
        no_space_prefixes = ('นาย', 'นาง', 'นางสาว', 'น.ส.', 'ครู', 'คุณครู', 'ดร.')
        join_char = "" if (prefix_matched in no_space_prefixes and not had_space) else " "
        
        if len(tokens) == 0:
            main_name = prefix_matched
            department = ""
        elif len(tokens) == 1:
            main_name = f"{prefix_matched}{join_char}{tokens[0]}".strip()
            department = ""
        elif len(tokens) == 2:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = ""
        else:
            main_name = f"{prefix_matched}{join_char}{tokens[0]} {tokens[1]}".strip()
            department = " ".join(tokens[2:]).strip()
    else:
        tokens = [t for t in clean_text.split(' ') if t]
        if len(tokens) == 1:
            main_name = tokens[0]
            department = ""
        elif len(tokens) == 2:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = ""
        else:
            main_name = f"{tokens[0]} {tokens[1]}"
            department = " ".join(tokens[2:]).strip()
            
    return (main_name.strip(), clean_department_name(department), photo_index)


# ตั้งค่าการบันทึก Log หลัก
logger = logging.getLogger("FaceSearchApp")
logger.setLevel(logging.DEBUG)

# สร้าง Log Handler ส่งไปยัง GUI Queue
class GUIQueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        log_entry = self.format(record)
        self.log_queue.put(log_entry)

class GoogleDrivePicker(ctk.CTkToplevel):
    def __init__(self, parent, mode="folder", callback=None):
        super().__init__(parent)
        self.mode = mode
        self.callback = callback
        self.parent = parent
        self.sync_manager = parent.sync_manager
        
        if mode == "folder":
            self.title("เลือกโฟลเดอร์ Google Drive")
        elif mode == "delete_req_json":
            self.title("เลือกไฟล์ JSON คำขอลบรูปภาพ")
        else:
            self.title("เลือกไฟล์ Google Sheets")
            
        self.geometry("550x480")
        self.resizable(False, False)
        
        # ทำให้เป็น Modal dialog (ต้องรอการปิด)
        self.transient(parent)
        self.grab_set()
        
        # คุมประวัติการเข้าโฟลเดอร์ (Folder Stack เพื่อการย้อนกลับ)
        # เก็บเป็นลิสต์ของทูเพิล (folder_id, folder_name)
        self.folder_stack = [('root', 'Root (ไดรฟ์หลัก)')]
        
        # แถบแสดงตำแหน่งปัจจุบัน (Breadcrumb) และปุ่มขึ้นระดับ
        self.path_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.path_frame.pack(fill="x", padx=20, pady=(15, 2))
        
        self.lbl_path = ctk.CTkLabel(
            self.path_frame, text="ตำแหน่ง: Root (ไดรฟ์หลัก)", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#6CA6CD", anchor="w"
        )
        self.lbl_path.pack(side="left", fill="x", expand=True)
        
        self.btn_up = ctk.CTkButton(
            self.path_frame, text="⬆️ ขึ้น 1 ระดับ", width=90, height=22, 
            font=ctk.CTkFont(size=11), fg_color="#1F3A60", hover_color="#20334F",
            command=self.navigate_up
        )
        self.btn_up.pack(side="right")
        
        # แถบค้นหาในไดเรกทอรีปัจจุบัน
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=5)
        
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="🔍 กรองชื่อในตำแหน่งนี้...")
        self.search_entry.pack(fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.filter_list)
        
        # รายการข้อมูล
        list_frame = ctk.CTkFrame(self, fg_color="#101B2B")
        list_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # หากเป็นโหมดโฟลเดอร์ ให้สามารถกดเลือกได้หลายอันพร้อมกัน (Multi-select)
        select_mode = tk.MULTIPLE if self.mode == "folder" else tk.BROWSE
        self.listbox = tk.Listbox(
            list_frame, 
            bg="#0A111A", 
            fg="#2ECC71", 
            selectbackground="#1F3A60", 
            selectforeground="white",
            selectmode=select_mode,
            font=("Consolas", 10),
            borderwidth=0,
            highlightthickness=0
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.listbox.bind("<Double-Button-1>", self.on_double_click) # ดับเบิ้ลคลิกเข้าโฟลเดอร์
        
        from tkinter import ttk
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y", pady=5)
        self.listbox.config(yscrollcommand=scrollbar.set)
        
        # ปุ่มกดด้านล่าง
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)
        
        btn_cancel = ctk.CTkButton(btn_frame, text="ยกเลิก", width=90, fg_color="#C0392B", hover_color="#962D22", command=self.destroy)
        btn_cancel.pack(side="left")
        
        self.btn_ok = ctk.CTkButton(
            btn_frame, text="ตกลงเลือก", width=95, 
            fg_color="#2ECC71", hover_color="#27AE60", text_color="black", 
            font=ctk.CTkFont(weight="bold"), command=self.on_select
        )
        self.btn_ok.pack(side="right")
        
        # ข้อความกำลังโหลด
        self.loading_label = ctk.CTkLabel(self, text="กำลังเชื่อมต่อและดึงข้อมูลจาก Google Drive...", font=ctk.CTkFont(size=13), text_color="#A2B5CD")
        self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
        
        # โหลดเบื้องหลัง
        self.items = []
        self.filtered_items = []
        
        threading.Thread(target=self.load_data, daemon=True).start()

    def load_data(self):
        # เชื่อมต่อ API
        if not self.sync_manager.connected:
            if not self.sync_manager.connect():
                self.parent.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเชื่อมต่อ Google API ได้ กรุณาตรวจสอบไฟล์ credentials ของท่าน"))
                self.parent.after(0, self.destroy)
                return
                
        try:
            current_folder_id = self.folder_stack[-1][0]
            
            # ตรวจสอบเงื่อนไขตำแหน่ง: หากอยู่ที่หน้าแรก (Root) ให้ดึงทั้งโฟลเดอร์ใน Drive ของบอท และโฟลเดอร์ที่ผู้อื่นแชร์มาให้
            if current_folder_id == 'root':
                parent_condition = "('root' in parents or sharedWithMe = true)"
            else:
                parent_condition = f"'{current_folder_id}' in parents"
            
            # ดึงข้อมูลลูกที่สังกัดโฟลเดอร์นี้
            if self.mode == "folder":
                # โหมดโฟลเดอร์: ดึงเฉพาะโฟลเดอร์ย่อย
                query = f"{parent_condition} and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            elif self.mode == "delete_req_json":
                # โหมดคำขอลบ: ดึงทั้งโฟลเดอร์ย่อย และไฟล์ JSON (.json หรือ mimeType json)
                query = f"{parent_condition} and (mimeType = 'application/vnd.google-apps.folder' or mimeType = 'application/json' or name contains '.json') and trashed = false"
            else:
                # โหมดชีท: ดึงทั้งโฟลเดอร์ย่อย (เผื่อกดเข้าต่อ) และไฟล์ Google Sheets
                query = f"{parent_condition} and (mimeType = 'application/vnd.google-apps.folder' or mimeType = 'application/vnd.google-apps.spreadsheet') and trashed = false"
                
            logger.info(f"Picker: Browsing current folder ID '{current_folder_id}' -> Query: {query}")
            results = self.sync_manager.drive_service.files().list(
                q=query, fields="files(id, name, mimeType)", pageSize=150
            ).execute()
            
            self.items = results.get("files", [])
            # จัดเรียงประเภท: โฟลเดอร์อยู่บนสุด ตามด้วยชื่อไฟล์ตามลำดับอักษร
            self.items.sort(key=lambda x: (0 if x["mimeType"] == "application/vnd.google-apps.folder" else 1, x["name"].lower()))
            
            logger.info(f"Picker: Loaded {len(self.items)} contents in folder.")
            self.parent.after(0, self.display_items)
        except Exception as e:
            logger.error(f"Picker Error: {e}", exc_info=True)
            self.parent.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถดึงข้อมูลจาก Google ได้: {e}"))
            self.parent.after(0, self.destroy)

    def display_items(self):
        self.loading_label.place_forget()
        self.filtered_items = self.items.copy()
        self.update_listbox()

    def update_listbox(self):
        self.listbox.delete(0, tk.END)
        # ดึงประวัติโฟลเดอร์ที่ทำการ Matching สำเร็จแล้ว
        matched_folders = getattr(self.parent, "get_matched_folders", lambda: {})()
        
        # ดึงประวัติชื่อ event_name จากฐานข้อมูลด้วย (เพื่อความชัวร์ว่าโฟลเดอร์เคยสแกนแล้ว 100%)
        db_events = set()
        if hasattr(self.parent, 'db_manager'):
            db_events = self.parent.db_manager.get_scanned_event_names()

        for idx, item in enumerate(self.filtered_items):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                prefix = "📂 [Folder] "
                is_matched = (item["id"] in matched_folders) or (item["name"] in db_events)
                self.listbox.insert(tk.END, prefix + item["name"])
                # ถ้าเคยสแกนแล้ว ใช้สีเขียว (#2ECC71) ถ้ายังไม่เคยสแกนใช้สีแดง (#E74C3C)
                self.listbox.itemconfig(idx, fg="#2ECC71" if is_matched else "#E74C3C")
            elif item["mimeType"] == "application/vnd.google-apps.spreadsheet":
                prefix = "📊 [Sheet] "
                self.listbox.insert(tk.END, prefix + item["name"])
                self.listbox.itemconfig(idx, fg="#F39C12") # สีส้มสำหรับสเปรดชีต
            else:
                prefix = "📄 [JSON] "
                self.listbox.insert(tk.END, prefix + item["name"])
                self.listbox.itemconfig(idx, fg="#3498DB") # สีฟ้าสำหรับไฟล์คำขอลบ JSON

    def filter_list(self, event=None):
        query = self.search_entry.get().strip().lower()
        if not query:
            self.filtered_items = self.items.copy()
        else:
            self.filtered_items = [
                item for item in self.items if query in item["name"].lower()
            ]
        self.update_listbox()

    def update_path_label(self):
        path_str = " / ".join([folder[1] for folder in self.folder_stack])
        if len(path_str) > 60:
            path_str = "..." + path_str[-57:]
        self.lbl_path.configure(text=f"ตำแหน่ง: {path_str}")

    def navigate_up(self):
        """ขึ้นโฟลเดอร์ข้างบน 1 ระดับ"""
        if len(self.folder_stack) > 1:
            self.folder_stack.pop()
            self.search_entry.delete(0, tk.END)
            self.update_path_label()
            
            # รีเฟรชรายการ
            self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
            self.listbox.delete(0, tk.END)
            threading.Thread(target=self.load_data, daemon=True).start()

    def on_double_click(self, event):
        """ดับเบิ้ลคลิกที่แถวรายการ"""
        try:
            sel_idx = self.listbox.curselection()
            if not sel_idx:
                return
            picked_item = self.filtered_items[sel_idx[0]]
            
            # ถ้าดับเบิ้ลคลิกที่โฟลเดอร์ ให้ดึงข้อมูลภายในโฟลเดอร์ย่อยนั้นขึ้นมาแสดงผล
            if picked_item["mimeType"] == "application/vnd.google-apps.folder":
                self.folder_stack.append((picked_item["id"], picked_item["name"]))
                self.search_entry.delete(0, tk.END)
                self.update_path_label()
                
                self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
                self.listbox.delete(0, tk.END)
                threading.Thread(target=self.load_data, daemon=True).start()
        except Exception as e:
            logger.error(f"Error on double click folder: {e}")

    def on_select(self):
        try:
            sel_indices = self.listbox.curselection()
            
            # หากไม่ได้กดเลือกแถวใดในลิสต์บ็อกซ์
            if not sel_indices:
                # ถ้าอยู่ในโหมดโฟลเดอร์ ให้ตกลงเลือกโฟลเดอร์ปัจจุบันที่กำลังเปิดนำทางอยู่ (ตัวเดียว)
                if self.mode == "folder":
                    curr_id, curr_name = self.folder_stack[-1]
                    if curr_id == 'root':
                        messagebox.showwarning("แจ้งเตือน", "กรุณาเข้าไปในโฟลเดอร์เป้าหมายก่อน (ไม่สามารถเลือกไดเรกทอรีหลัก Root ได้)")
                        return
                    if self.callback:
                        self.callback(self.mode, curr_id, curr_name)
                    self.destroy()
                else:
                    messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกไฟล์ Google Sheets จากรายการ")
                return
                
            # หากอยู่ในโหมดโฟลเดอร์ และมีการเลือกรายการในลิสต์บ็อกซ์ (รองรับเลือกหลายรายการ)
            if self.mode == "folder":
                selected_ids = []
                selected_names = []
                for idx in sel_indices:
                    picked_item = self.filtered_items[idx]
                    if picked_item["mimeType"] == "application/vnd.google-apps.folder":
                        selected_ids.append(picked_item["id"])
                        selected_names.append(picked_item["name"])
                        
                if not selected_ids:
                    messagebox.showwarning("คำเตือน", "กรุณาเลือกโฟลเดอร์กิจกรรมจากรายการ")
                    return
                    
                # รวมรายการทั้งหมดคั่นด้วยคอมมา
                ids_str = ", ".join(selected_ids)
                names_str = ", ".join(selected_names)
                if self.callback:
                    self.callback("folder", ids_str, names_str)
                self.destroy()
            else:
                # โหมดไฟล์อื่น (Sheet หรือ JSON) ซึ่งเลือกได้เพียง 1 ไฟล์
                picked_item = self.filtered_items[sel_indices[0]]
                
                if self.mode == "delete_req_json" and (picked_item["mimeType"] == "application/json" or picked_item["name"].lower().endswith(".json")):
                    if self.callback:
                        self.callback("delete_req_json", picked_item["id"], picked_item["name"])
                    self.destroy()
                elif picked_item["mimeType"] == "application/vnd.google-apps.spreadsheet":
                    if self.callback:
                        self.callback("sheet", picked_item["id"], picked_item["name"])
                    self.destroy()
                else:
                    # กรณีเลือกโฟลเดอร์แต่เป็นโหมดแผ่นงาน (sheets) หรือเลือกไฟล์ในเงื่อนไขอื่น
                    messagebox.showinfo(
                        "แนะนำ", 
                        "ดับเบิ้ลคลิกที่โฟลเดอร์นี้เพื่อเข้าดูไฟล์เป้าหมายด้านใน หรือกด 'ยกเลิก' เพื่อออก"
                    )
        except Exception as e:
            logger.error(f"Error selecting in picker: {e}")

class SheetsImportDialog(ctk.CTkToplevel):
    def __init__(self, parent, callback=None):
        super().__init__(parent)
        self.callback = callback
        self.parent = parent
        self.sync_manager = parent.sync_manager

        self.title("นำเข้านักเรียนจาก Google Sheets")
        self.geometry("550x600")
        self.resizable(False, False)

        # เก็บ Sheet ID ที่เลือก
        self.selected_sheet_id = None
        self.selected_sheet_name = None

        # โหลดค่าล่าสุดจาก settings (ถ้ามี)
        self.last_sheet_id = parent.settings.get("last_import_sheet_id", "")
        self.last_sheet_name = parent.settings.get("last_import_sheet_name", "")

        # โหลดค่า column ล่าสุด
        self.last_col_id = parent.settings.get("last_import_col_id", "A")
        self.last_col_name = parent.settings.get("last_import_col_name", "B")
        self.last_col_class = parent.settings.get("last_import_col_class", "- ไม่ระบุ -")
        self.last_col_img1 = parent.settings.get("last_import_col_img1", "D")
        self.last_col_img2 = parent.settings.get("last_import_col_img2", "E")
        self.last_col_img3 = parent.settings.get("last_import_col_img3", "F")

        # ทำให้เป็น Modal dialog
        self.transient(parent)
        self.grab_set()

        # ฟอร์มหลัก
        main_frame = ctk.CTkFrame(self, fg_color="#101B2B")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # หัวข้อ
        ctk.CTkLabel(main_frame, text="ตั้งค่าการนำเข้าจาก Google Sheets",
                   font=ctk.CTkFont(size=16, weight="bold"), text_color="white").pack(pady=(0, 15))

        # Sheet Selection
        sheet_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        sheet_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(sheet_frame, text="Google Sheet:", width=100, anchor="w",
                   text_color="#A2B5CD").pack(side="left")

        # ปุ่ม Browse Sheet
        self.btn_browse = ctk.CTkButton(sheet_frame, text="🔍 เลือก Sheet...",
                                        fg_color="#3498DB", hover_color="#2980B9",
                                        command=self.browse_sheets, width=120)
        self.btn_browse.pack(side="right", padx=(5, 0))

        # Label แสดง Sheet ที่เลือก
        self.lbl_selected_sheet = ctk.CTkLabel(sheet_frame, text=self.last_sheet_name if self.last_sheet_name else "ยังไม่ได้เลือก",
                                               text_color="#F39C12", anchor="w")
        self.lbl_selected_sheet.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # โหลดค่าล่าสุด (ถ้ามี)
        if self.last_sheet_id:
            self.selected_sheet_id = self.last_sheet_id
            self.selected_sheet_name = self.last_sheet_name

        # คอลัมน์รหัสประจำตัว
        col1_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col1_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col1_frame, text="คอลัมน์รหัสประจำตัว:", width=130, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_id = ctk.CTkOptionMenu(col1_frame, values=["A", "B", "C", "D", "E", "F", "G", "H"])
        self.col_id.set(self.last_col_id)
        self.col_id.pack(side="left", padx=(5, 0))
        ctk.CTkLabel(col1_frame, text="(บังคับ)", text_color="#27AE60",
                   font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 0))

        # คอลัมน์ชื่อ-นามสกุล
        col2_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col2_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col2_frame, text="คอลัมน์ชื่อ-นามสกุล:", width=130, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_name = ctk.CTkOptionMenu(col2_frame, values=["A", "B", "C", "D", "E", "F", "G", "H"])
        self.col_name.set(self.last_col_name)
        self.col_name.pack(side="left", padx=(5, 0))
        ctk.CTkLabel(col2_frame, text="(บังคับ)", text_color="#27AE60",
                   font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 0))

        # คอลัมน์ระดับชั้น/ห้องเรียน (เสริม - v6.29)
        col_class_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col_class_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col_class_frame, text="คอลัมน์ห้องเรียน (ถ้ามี):", width=130, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_class = ctk.CTkOptionMenu(col_class_frame, values=["- ไม่ระบุ -", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
        self.col_class.set(self.last_col_class)
        self.col_class.pack(side="left", padx=(5, 0))
        ctk.CTkLabel(col_class_frame, text="(เลือกหรือไม่ก็ได้)", text_color="#F39C12",
                   font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 0))

        # คอลัมน์ภาพที่ 1
        col3_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col3_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col3_frame, text="คอลัมน์ภาพที่ 1 (บังคับ):", width=140, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_img1 = ctk.CTkOptionMenu(col3_frame, values=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
        self.col_img1.set(self.last_col_img1)
        self.col_img1.pack(side="left", padx=(5, 0))

        # คอลัมน์ภาพที่ 2
        col4_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col4_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col4_frame, text="คอลัมน์ภาพที่ 2 (เสริม):", width=140, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_img2 = ctk.CTkOptionMenu(col4_frame, values=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
        self.col_img2.set(self.last_col_img2)
        self.col_img2.pack(side="left", padx=(5, 0))
        
        # คอลัมน์ภาพที่ 3
        col5_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col5_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col5_frame, text="คอลัมน์ภาพที่ 3 (เสริม):", width=140, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_img3 = ctk.CTkOptionMenu(col5_frame, values=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
        self.col_img3.set(self.last_col_img3)
        self.col_img3.pack(side="left", padx=(5, 0))

        # คำอธิบาย
        desc_label = ctk.CTkLabel(main_frame,
                                  text="• 1 คน = 1 แถว (รหัส + ชื่อ)\n"
                                      "• ภาพที่ 1: บังคับต้องมี\n"
                                      "• ภาพที่ 2 และ 3: ใส่เสริมหรือไม่ก็ได้",
                                  text_color="#6CA6CD", font=ctk.CTkFont(size=11),
                                  justify="left")
        desc_label.pack(pady=(5, 10), anchor="w")

        # ปุ่มด้านล่าง
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(btn_frame, text="ยกเลิก", width=100, fg_color="#C0392B",
                     hover_color="#962D22", command=self.destroy).pack(side="right", padx=(5, 0))

        self.btn_start = ctk.CTkButton(btn_frame, text="เริ่มนำเข้า", width=120,
                                        fg_color="#27AE60", hover_color="#229954",
                                        command=self.on_start)
        self.btn_start.pack(side="right")

    def browse_sheets(self):
        """เปิด dialog เลือก Spreadsheet จาก Google Drive พร้อม Folder Hierarchy"""
        # สร้าง dialog ย่อยสำหรับเลือก Sheet
        dialog = ctk.CTkToplevel(self)
        dialog.title("เลือก Google Sheet")
        dialog.geometry("600x500")
        dialog.transient(self)
        dialog.grab_set()

        # Frame หลัก
        main_frame = ctk.CTkFrame(dialog, fg_color="#101B2B")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # หัวข้อ + ปุ่มขึ้นระดับ
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(header_frame, text="รายการ Google Sheets (คลิกโฟลเดอร์เพื่อขยาย)",
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="white").pack(side="left")

        ctk.CTkButton(header_frame, text="⬆️ ขึ้นระดับ", width=100, fg_color="#1F3A60",
                     hover_color="#20334F", command=lambda: self.navigate_up(tree)).pack(side="right")

        # Treeview แสดงรายการแบบ hierarchy
        import tkinter as tk
        from tkinter import ttk

        tree_frame = ctk.CTkFrame(main_frame, fg_color="#0A111A")
        tree_frame.pack(fill="both", expand=True, pady=(5, 10))

        # สร้าง Treeview ด้วย style ที่กำหนดเอง
        tree = ttk.Treeview(tree_frame, selectmode="browse", show="tree")
        tree.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollbar แนวตั้ง
        tree_scroll = ctk.CTkScrollbar(main_frame, command=tree.yview)
        tree_scroll.pack(side="right", fill="y", padx=(0, 5))
        tree.configure(yscrollcommand=tree_scroll.set)

        # กำหนดสีและ style สำหรับ Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#0A111A",
                        foreground="#2ECC71",
                        fieldbackground="#0A111A",
                        borderwidth=0,
                        font=("Consolas", 10))
        style.configure("Treeview.Heading",
                        background="#1C2D42",
                        foreground="#6CA6CD",
                        borderwidth=0,
                        font=("Consolas", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", "#1F3A60")],
                  foreground=[("selected", "white")])

        # ปุ่มด้านล่าง
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        def on_select():
            selection = tree.selection()
            if not selection:
                return
            item = selection[0]
            item_data = tree.item(item)

            # ตรวจสอบว่าเป็น Sheet หรือ Folder
            item_tags = item_data.get("tags", [])
            if "sheet" in item_tags:
                sheet_id = item_tags[1] if len(item_tags) > 1 else None
                sheet_name = item_data.get("text", "")
                if sheet_id:
                    self.selected_sheet_id = sheet_id
                    self.selected_sheet_name = sheet_name
                    self.lbl_selected_sheet.configure(text=sheet_name, text_color="#27AE60")
                    dialog.destroy()

        ctk.CTkButton(btn_frame, text="เลือก", fg_color="#27AE60", hover_color="#229954",
                     command=on_select, width=80).pack(side="right", padx=(5, 0))
        ctk.CTkButton(btn_frame, text="ปิด", fg_color="#C0392B", hover_color="#962D22",
                     command=dialog.destroy, width=80).pack(side="right")

        # โหลดรายการ Sheets แบบ async พร้อม folder hierarchy
        def load_sheets():
            try:
                if not self.sync_manager.connected:
                    self.sync_manager.connect()

                # ดึงข้อมูลทั้งหมดจาก Drive
                items = self.sync_manager.list_spreadsheets_with_folders()

                # อัปเดต UI ใน main thread
                def update_ui():
                    # ล้างข้อมูลเก่า
                    for item in tree.get_children():
                        tree.delete(item)

                    if not items or "sheets" not in items:
                        tree.insert("", "end", text="ไม่พบ Google Sheets ใน Drive", tags=("error",))
                        return

                    # แสดงรายการ
                    self._build_tree(tree, items, self.last_sheet_id)

                self.after(0, update_ui)
            except Exception as e:
                self.after(0, lambda: tree.insert("", "end", text=f"Error: {e}", tags=("error",)))

        threading.Thread(target=load_sheets, daemon=True).start()

    def _build_tree(self, tree, items, last_sheet_id):
        """สร้างโครงสร้าง tree จากข้อมูล Drive"""
        # สร้าง dict ของ folders
        folders = {f["id"]: f for f in items.get("folders", [])}
        sheet_to_folder = {s["id"]: s.get("parents", [""])[0] if s.get("parents") else "" for s in items.get("sheets", [])}

        # เพิ่ม root node (My Drive)
        root_id = tree.insert("", "end", text="☁ My Drive", tags=("folder", "root"))

        # สร้าง hierarchy
        folder_items = {}  # folder_id -> tree item_id
        processed_folders = set()

        def add_folder_to_tree(folder_id, parent_item):
            if folder_id in processed_folders or folder_id not in folders:
                return
            processed_folders.add(folder_id)

            folder = folders[folder_id]
            folder_name = folder.get("name", "Unnamed Folder")
            folder_item = tree.insert(parent_item, "end", text=f"📁 {folder_name}", tags=("folder", folder_id))
            folder_items[folder_id] = folder_item

            # เพิ่ม subfolders แบบ recursive
            for sub_id, sub_folder in folders.items():
                if sub_id != folder_id and sub_folder.get("parents") == [folder_id]:
                    add_folder_to_tree(sub_id, folder_item)

        # เริ่มจาก folders ที่อยู่ใน root
        for folder_id, folder in folders.items():
            parents = folder.get("parents", [])
            if not parents or parents[0] == "" or parents[0] == "root":
                add_folder_to_tree(folder_id, root_id)

        # เพิ่ม sheets ไปยัง folder ที่ถูกต้อง
        for sheet in items.get("sheets", []):
            sheet_id = sheet["id"]
            sheet_name = sheet["name"]
            parents = sheet.get("parents", [])

            # หา parent folder
            if parents and parents[0] in folder_items:
                parent_item = folder_items[parents[0]]
            else:
                parent_item = root_id

            # เพิ่ม sheet เป็น leaf node
            sheet_item = tree.insert(parent_item, "end", text=f"📊 {sheet_name}",
                                       tags=("sheet", sheet_id))

            # เลือก sheet ล่าสุด (ถ้ามี)
            if last_sheet_id and sheet_id == last_sheet_id:
                tree.see(sheet_item)
                tree.selection_set(sheet_item)
                # ขยาย folder ที่มี sheet ล่าสุด
                self._expand_parents(tree, sheet_item)

    def _expand_parents(self, tree, item):
        """ขยาย folder ลูกโขทั้งหมดจนถึง root"""
        parent = tree.parent(item)
        while parent:
            tree.item(parent, open=True)
            parent = tree.parent(parent)

    def navigate_up(self, tree):
        """ขึ้นระดับ folder"""
        selection = tree.selection()
        if not selection:
            return
        item = selection[0]
        parent = tree.parent(item)
        if parent:
            tree.selection_set(parent)
            tree.see(parent)

    def on_start(self):
        if not self.selected_sheet_id:
            messagebox.showwarning("คำเตือน", "กรุณาเลือก Google Sheet ก่อน")
            return

        settings = {
            "sheet_id": self.selected_sheet_id,
            "sheet_name": self.selected_sheet_name,
            "col_id": self.col_id.get(),
            "col_name": self.col_name.get(),
            "col_class": self.col_class.get() if hasattr(self, 'col_class') else "- ไม่ระบุ -",
            "col_img1": self.col_img1.get(),
            "col_img2": self.col_img2.get(),
            "col_img3": self.col_img3.get()
        }

        # บันทึกค่าล่าสุด
        self.parent.settings["last_import_sheet_id"] = self.selected_sheet_id
        self.parent.settings["last_import_sheet_name"] = self.selected_sheet_name
        self.parent.settings["last_import_col_id"] = self.col_id.get()
        self.parent.settings["last_import_col_name"] = self.col_name.get()
        if hasattr(self, 'col_class'):
            self.parent.settings["last_import_col_class"] = self.col_class.get()
        self.parent.settings["last_import_col_img1"] = self.col_img1.get()
        self.parent.settings["last_import_col_img2"] = self.col_img2.get()
        self.parent.settings["last_import_col_img3"] = self.col_img3.get()
        self.parent.save_settings()

        self.destroy()
        if self.callback:
            self.callback(settings)


class StudentLifecycleDialog(ctk.CTkToplevel):
    """หน้าต่างเครื่องมือบริหารวงจรชีวิตนักเรียน (เลื่อนชั้น / บันทึกจบการศึกษา) (v6.29)"""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.db = parent.db

        self.title("🎓 จัดการวงจรชีวิตนักเรียน (เลื่อนชั้น / บันทึกจบการศึกษา)")
        self.geometry("640x560")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 320
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 280
        self.geometry(f"+{x}+{y}")

        main_frame = ctk.CTkFrame(self, fg_color="#101B2B")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(main_frame, text="🎓 ระบบบริหารวงจรชีวิตนักเรียนตามปีการศึกษา (v6.29)",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color="#5CACEE").pack(pady=(5, 10))

        # Stats banner
        self.stats_frame = ctk.CTkFrame(main_frame, fg_color="#1C2D42")
        self.stats_frame.pack(fill="x", padx=10, pady=(0, 15))
        self.lbl_stats = ctk.CTkLabel(self.stats_frame, text="", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A2B5CD")
        self.lbl_stats.pack(padx=10, pady=8)
        self.refresh_stats()

        # Tabview for 2 primary modes: Graduate vs Promote
        tabview = ctk.CTkTabview(main_frame, fg_color="#162232")
        tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        tab_grad = tabview.add("🎓 บันทึกจบการศึกษา")
        tab_promote = tabview.add("🚀 เลื่อนชั้นเรียน (Promote)")

        # ----- TAB 1: บันทึกจบการศึกษา -----
        ctk.CTkLabel(tab_grad, text="ระบุห้องเรียนที่สำเร็จการศึกษา (เช่น ม.3/1 หรือ ม.6/1):", font=ctk.CTkFont(size=14, weight="bold"), text_color="white").pack(anchor="w", padx=15, pady=(10, 5))

        rooms = self.db.get_student_classrooms() or ["- ยังไม่มีห้องเรียน -"]
        
        grad_room_frame = ctk.CTkFrame(tab_grad, fg_color="transparent")
        grad_room_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(grad_room_frame, text="ห้องเรียนที่จบ:", width=130, anchor="w", text_color="#A2B5CD", font=ctk.CTkFont(size=13)).pack(side="left")
        self.combo_grad_room = ctk.CTkOptionMenu(grad_room_frame, values=rooms, width=190)
        self.combo_grad_room.pack(side="left", padx=5)

        grad_yr_frame = ctk.CTkFrame(tab_grad, fg_color="transparent")
        grad_yr_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(grad_yr_frame, text="ปีการศึกษาที่จบ:", width=130, anchor="w", text_color="#A2B5CD", font=ctk.CTkFont(size=13)).pack(side="left")
        self.entry_grad_academic_year = ctk.CTkEntry(grad_yr_frame, placeholder_text="เช่น 2568", width=190)
        self.entry_grad_academic_year.pack(side="left", padx=5)

        ctk.CTkLabel(tab_grad, 
                     text="💡 ข้อแนะนำสำหรับงานจบการศึกษา:\n"
                          "• นักเรียนในห้องที่เลือกจะถูกเปลี่ยนสถานะเป็น 'graduated' (จบการศึกษา)\n"
                          "• ประวัติภาพถ่ายทั้งหมดในอดีต (detected_faces) จะไม่สูญหาย และค้นหาผ่านเว็บได้ 100%\n"
                          "• การสแกนรูปภาพกิจกรรมใหม่หลังจากนี้ จะไม่นำใบหน้านักเรียนที่จบแล้วมาจับคู่ (Zero False Positive)",
                     font=ctk.CTkFont(size=12), text_color="#6CA6CD", justify="left").pack(anchor="w", padx=15, pady=12)

        btn_exec_grad = ctk.CTkButton(
            tab_grad, text="🎓 ยืนยันบันทึกจบการศึกษาทั้งห้องเรียน",
            fg_color="#E67E22", hover_color="#D35400", height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.execute_batch_graduate
        )
        btn_exec_grad.pack(fill="x", padx=15, pady=(5, 10))

        # ----- TAB 2: เลื่อนชั้นเรียน -----
        ctk.CTkLabel(tab_promote, text="ระบุห้องเรียนเดิม และห้องเรียนใหม่ที่ต้องการเลื่อนชั้น:", font=ctk.CTkFont(size=14, weight="bold"), text_color="white").pack(anchor="w", padx=15, pady=(10, 5))

        p_src_frame = ctk.CTkFrame(tab_promote, fg_color="transparent")
        p_src_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(p_src_frame, text="ห้องเรียนเดิม:", width=130, anchor="w", text_color="#A2B5CD", font=ctk.CTkFont(size=13)).pack(side="left")
        self.combo_promote_src = ctk.CTkOptionMenu(p_src_frame, values=rooms, width=190)
        self.combo_promote_src.pack(side="left", padx=5)

        p_dst_frame = ctk.CTkFrame(tab_promote, fg_color="transparent")
        p_dst_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(p_dst_frame, text="เลื่อนไปห้องใหม่:", width=130, anchor="w", text_color="#A2B5CD", font=ctk.CTkFont(size=13)).pack(side="left")
        self.entry_promote_dst = ctk.CTkEntry(p_dst_frame, placeholder_text="เช่น ม.2/1 หรือ ม.5/2", width=190)
        self.entry_promote_dst.pack(side="left", padx=5)

        ctk.CTkLabel(tab_promote, 
                     text="💡 ข้อแนะนำสำหรับการเลื่อนชั้น:\n"
                          "• ระบบจะปรับปรุงห้องเรียนของนักเรียนที่กำลังศึกษา (active) ในห้องเดิมทุกคน\n"
                          "• ประวัติภาพถ่ายและเวกเตอร์ใบหน้าเดิมทั้งหมดจะยังคงอยู่ครบถ้วน\n"
                          "• ดำเนินการเสร็จสิ้นในคลิกเดียวด้วยความเร็วระดับมิลลิวินาที",
                     font=ctk.CTkFont(size=12), text_color="#6CA6CD", justify="left").pack(anchor="w", padx=15, pady=12)

        btn_exec_promote = ctk.CTkButton(
            tab_promote, text="🚀 ยืนยันดำเนินการเลื่อนชั้นเรียน",
            fg_color="#27AE60", hover_color="#229954", height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.execute_batch_promote
        )
        btn_exec_promote.pack(fill="x", padx=15, pady=(5, 10))

        # Close button at bottom
        ctk.CTkButton(main_frame, text="ปิดหน้าต่าง", width=100, fg_color="#7F8C8D", hover_color="#95A5A6", command=self.destroy).pack(side="right", padx=10, pady=(0, 5))

    def refresh_stats(self):
        stats = self.db.get_student_lifecycle_stats()
        stats_text = f"📊 สถิติปัจจุบัน: กำลังศึกษา {stats['active_count']} คน | จบการศึกษา {stats['graduated_count']} คน | รวมทั้งหมด {stats['total_students']} คน ({stats['classroom_count']} ห้องเรียน)"
        self.lbl_stats.configure(text=stats_text)

    def execute_batch_graduate(self):
        room = self.combo_grad_room.get()
        grad_year = self.entry_grad_academic_year.get().strip()
        if not room or room == "- ยังไม่มีห้องเรียน -":
            messagebox.showwarning("คำเตือน", "กรุณาเลือกห้องเรียนที่ต้องการบันทึกจบการศึกษา", parent=self)
            return
        if not grad_year:
            messagebox.showwarning("คำเตือน", "กรุณาระบุปีการศึกษาที่จบ (เช่น 2568)", parent=self)
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM staff_members WHERE role = 'student' AND class_room = ? AND (status = 'active' OR status IS NULL OR status = '')", (room,))
            stds = cursor.fetchall()

        if not stds:
            messagebox.showinfo("ไม่พบนักเรียน", f"ไม่พบนักเรียนที่มีสถานะกำลังศึกษาในห้อง '{room}'", parent=self)
            return

        confirm = messagebox.askyesno(
            "ยืนยันการบันทึกจบการศึกษา",
            f"คุณต้องการบันทึกจบการศึกษานักเรียนห้อง '{room}' จำนวน {len(stds)} คน\nปีการศึกษาที่จบ: {grad_year} ใช่หรือไม่?",
            parent=self
        )
        if not confirm:
            return

        try:
            ids = [s[0] for s in stds]
            updated_count = self.db.batch_update_student_status(ids, 'graduated', grad_year)
            self.refresh_stats()
            self.parent.load_student_list(refresh_db=True)
            messagebox.showinfo("สำเร็จ", f"บันทึกจบการศึกษานักเรียนห้อง '{room}' สำเร็จแล้วจำนวน {updated_count} คน", parent=self)
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถบันทึกจบการศึกษาได้: {e}", parent=self)

    def execute_batch_promote(self):
        src_room = self.combo_promote_src.get()
        dst_room = self.entry_promote_dst.get().strip()
        if not src_room or src_room == "- ยังไม่มีห้องเรียน -":
            messagebox.showwarning("คำเตือน", "กรุณาเลือกห้องเรียนเดิม", parent=self)
            return
        if not dst_room:
            messagebox.showwarning("คำเตือน", "กรุณาระบุห้องเรียนใหม่ที่จะเลื่อนไป", parent=self)
            return
        if src_room == dst_room:
            messagebox.showwarning("คำเตือน", "ห้องเรียนใหม่ต้องไม่ตรงกับห้องเรียนเดิม", parent=self)
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM staff_members WHERE role = 'student' AND class_room = ? AND (status = 'active' OR status IS NULL OR status = '')", (src_room,))
            cnt = cursor.fetchone()[0]

        if cnt == 0:
            messagebox.showinfo("ไม่พบนักเรียน", f"ไม่พบนักเรียนที่กำลังศึกษาในห้อง '{src_room}'", parent=self)
            return

        confirm = messagebox.askyesno(
            "ยืนยันการเลื่อนชั้น",
            f"คุณต้องการเลื่อนชั้นนักเรียนห้อง '{src_room}' (จำนวน {cnt} คน)\nไปยังห้องใหม่ '{dst_room}' ใช่หรือไม่?",
            parent=self
        )
        if not confirm:
            return

        try:
            promoted_cnt = self.db.batch_promote_students(src_room, dst_room)
            self.refresh_stats()
            new_rooms = self.db.get_student_classrooms() or ["- ยังไม่มีห้องเรียน -"]
            self.combo_grad_room.configure(values=new_rooms)
            self.combo_promote_src.configure(values=new_rooms)
            self.parent.load_student_list(refresh_db=True)
            messagebox.showinfo("สำเร็จ", f"เลื่อนชั้นนักเรียนจากห้อง '{src_room}' ไปยัง '{dst_room}' สำเร็จ {promoted_cnt} คน", parent=self)
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถเลื่อนชั้นได้: {e}", parent=self)

class FaceSearchApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- การตั้งค่าธีมและหน้าต่างโปรแกรม (Navy Blue Theme) ---
        ctk.set_appearance_mode("dark")
        # เราใช้ธีมสีน้ำเงินพื้นฐานของ CTk เป็นฐาน และตกแต่งด้วยสี Navy เฉพาะตัว
        ctk.set_default_color_theme("blue")
        
        self.title("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v6.34 (Teacher Interactive Table & Universal SQLite DB Editor Suite)")
        self.geometry("1400x880")
        self.minsize(1250, 760)

        # --- ส่วนประกอบฐานข้อมูลและหลังบ้าน ---
        self.db = DatabaseManager()
        self.sync_manager = GoogleSyncManager()
        from face_analyzer import FaceAnalyzer
        self.analyzer = FaceAnalyzer(use_gpu=True)
        self.analyzer.initialize()
        
        # ThreadPoolExecutor ควบคุมคิวโหลดภาพพรีวิวไม่ให้ค้าง (สูงสุด 4 เธรด)
        from concurrent.futures import ThreadPoolExecutor
        self.thumb_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ThumbWorker")
        self.http_session = requests.Session()
        self.http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # คิวจัดการ Log เพื่อป้องกันหน้าจอค้าง
        self.log_queue = queue.Queue()
        self.console_log_history = []  # v6.11: เก็บประวัติ Log (msg, tag) เพื่อใช้สลับตัวกรอง All / Warning / Error
        self.console_filter_mode = "all"  # v6.11: โหมดตัวกรองปัจจุบัน ('all', 'warning', 'error')
        queue_handler = GUIQueueHandler(self.log_queue)
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', '%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)

        # เพิ่ม File Handler และ Console Handler สำรอง
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_execution.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # เก็บสถานะการทำงานสแกน
        self.scan_thread = None
        self.is_scanning = False
        self.is_paused = False
        self.floating_preview_win = None  # v5.50: หน้าต่างพรีวิวผลลอยตัว (Floating Window)
        self.lbl_float_preview = None
        self.txt_float_summary = None
        self.selected_staff_ids_for_scan = []  # รายชื่อ ID ครูที่เลือกสำหรับสแกนแบบเจาะจง (Selective Matching)
        self.selected_teacher_ids = []  # v1.7.4 รายชื่อ ID ครูที่เลือกสแกนเฉพาะเจาะจง
        self.selected_student_ids = []  # v1.7.4 รายชื่อ ID นักเรียนที่เลือกสแกนเฉพาะเจาะจง
        self.dashboard_sort_desc = True  # True = เรียงมากไปน้อย, False = เรียงน้อยไปมาก
        self.db_current_page = 1
        self.db_page_size = 200
        self.db_sort_col = "photo_id"  # v6.00: คอลัมน์ที่กำลังจัดเรียงในตาราง SQLite
        self.db_sort_desc = True       # v6.00: ทิศทางการจัดเรียง (True = DESC, False = ASC)
        self._db_search_timer = None  # v5.70: Timer สำหรับ Search Debounce ป้องกัน UI Freezing
        self._db_cached_count_key = None  # v6.28: แคชคีย์สำหรับการเปลี่ยนหน้า Pagination โดยไม่ต้องรัน COUNT(*) ซ้ำ
        self._db_cached_total_rows = None
        self._staff_search_timer = None   # v6.28: Timer Debounce 250ms สำหรับค้นหาครู
        self._student_search_timer = None # v6.28: Timer Debounce 250ms สำหรับค้นหานักเรียน
        self._matched_search_timer = None # v6.28: Timer Debounce 250ms สำหรับค้นหาแกลเลอรี
        self._cached_teachers_list = None
        self._cached_students_list = None
        self._last_loaded_matched_person = None

        # Settings cache
        self.settings = {}

        # v6.20 / v6.28: State variables for Unknown Faces Analytics + Pagination
        self.selected_unknown_cluster_id = None
        self.selected_unknown_cluster_data = None
        self.unknown_clusters_cache = []
        self.unknown_filtered_rows = []
        self.unknown_page = 1
        self.unknown_page_size = 250
        self._unknown_search_timer = None
        self.unknown_gallery_filter_year = None
        self._unknown_face_preview_img = None  # Reference to prevent GC

        # --- Scheduler Task ---
        self.scheduler = SchedulerTask(self.db, self.sync_manager, self.analyzer, self)

        # --- จัดทำเลย์เอาต์หลัก ---
        # แบ่งซ้าย (Sidebar Menu) และขวา (Content Pane)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)  # แบ่งครึ่ง 1:1 เพื่อขยายโซนด้านล่างเป็นครึ่งจอหลัก!
        self.grid_rowconfigure(1, weight=1)

        self.create_sidebar()
        self.create_content_areas()
        self.create_global_console()

        # แสดงหน้า Dashboard เป็นหน้าแรก
        self.select_menu("dashboard")
        
        # เริ่มการตรวจคิวข้อความ Log
        self.check_log_queue()
        
        # โหลดการตั้งค่าเก่า (ถ้ามี)
        self.load_settings()

    # --- ส่วนเมนูด้านซ้าย (Sidebar) ---
    def create_sidebar(self):
        # พื้นหลัง Sidebar สี Navy ครามเข้ม (Span 2 แถวเพื่อครอบคลุมไปถึง Console ด้านล่าง)
        self.sidebar_frame = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color="#101B2B")
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        # โลโก้หรือหัวข้อโปรแกรม
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="FACE MATCHING\nSYSTEM v6.34",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#6CA6CD"
        )
        self.logo_label.grid(row=0, column=0, padx=15, pady=25)

        # ฟอนต์ขนาด 1.5 เท่า สำหรับเมนู
        menu_font = ctk.CTkFont(size=14, weight="normal")
        schedule_font = ctk.CTkFont(size=14, weight="bold")

        # ปุ่มเมนูต่างๆ
        self.btn_dashboard = ctk.CTkButton(
            self.sidebar_frame, text="📊 Dashboard", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("dashboard")
        )
        self.btn_dashboard.grid(row=1, column=0, padx=12, pady=5, sticky="ew")

        self.btn_registry = ctk.CTkButton(
            self.sidebar_frame, text="👨‍🏫 ลงทะเบียนครู", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("registry")
        )
        self.btn_registry.grid(row=2, column=0, padx=12, pady=5, sticky="ew")

        self.btn_student_registry = ctk.CTkButton(
            self.sidebar_frame, text="🎒 ลงทะเบียนนักเรียน", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("student_registry")
        )
        self.btn_student_registry.grid(row=3, column=0, padx=12, pady=5, sticky="ew")

        self.btn_scan = ctk.CTkButton(
            self.sidebar_frame, text="🔍 สแกนรูปภาพกิจกรรม", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("scan")
        )
        self.btn_scan.grid(row=4, column=0, padx=12, pady=5, sticky="ew")

        self.btn_database = ctk.CTkButton(
            self.sidebar_frame, text="🗄️ ดูฐานข้อมูล SQLite", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("database")
        )
        self.btn_database.grid(row=5, column=0, padx=12, pady=5, sticky="ew")

        self.btn_matched_gallery = ctk.CTkButton(
            self.sidebar_frame, text="🖼️ ภาพกิจกรรมที่แมตช์แล้ว", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("matched_gallery")
        )
        self.btn_matched_gallery.grid(row=6, column=0, padx=12, pady=5, sticky="ew")

        self.btn_unknown_analytics = ctk.CTkButton(
            self.sidebar_frame, text="👥 สถิติบุคคลนิรนาม (Unknowns)", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("unknown_analytics")
        )
        self.btn_unknown_analytics.grid(row=7, column=0, padx=12, pady=5, sticky="ew")

        self.btn_settings = ctk.CTkButton(
            self.sidebar_frame, text="⚙️ ตั้งค่าระบบ", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("settings")
        )
        self.btn_settings.grid(row=8, column=0, padx=12, pady=5, sticky="ew")

        self.btn_delete_req = ctk.CTkButton(
            self.sidebar_frame, text="🗑️ คำขอลบภาพ (Requests)", height=36, font=menu_font,
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("delete_req")
        )
        self.btn_delete_req.grid(row=9, column=0, padx=12, pady=5, sticky="ew")

        self.btn_start_schedule = ctk.CTkButton(
            self.sidebar_frame, text="▶️ 1. สแกนภาพเพิ่มมาใหม่", height=38, font=schedule_font,
            fg_color="#8E44AD", text_color="white", hover_color="#9B59B6",
            anchor="w", command=lambda: self.scheduler.run_scheduled_tasks_manual()
        )
        self.btn_start_schedule.grid(row=10, column=0, padx=12, pady=(12, 4), sticky="ew")

        self.btn_start_task2 = ctk.CTkButton(
            self.sidebar_frame, text="▶️ 2. Sync New Student", height=38, font=schedule_font,
            fg_color="#D35400", text_color="white", hover_color="#E67E22",
            anchor="w", command=lambda: self.scheduler.run_task_2_manual()
        )
        self.btn_start_task2.grid(row=11, column=0, padx=12, pady=4, sticky="ew")

        self.btn_start_task3 = ctk.CTkButton(
            self.sidebar_frame, text="▶️ 3. Sync New Teacher", height=38, font=schedule_font,
            fg_color="#16A085", text_color="white", hover_color="#1ABC9C",
            anchor="w", command=lambda: self.scheduler.run_task_3_manual()
        )
        self.btn_start_task3.grid(row=12, column=0, padx=12, pady=4, sticky="ew")

        self.btn_stop_schedule = ctk.CTkButton(
            self.sidebar_frame, text="🛑 Stop Schedule Task", height=38, font=schedule_font,
            fg_color="#E74C3C", text_color="white", hover_color="#C0392B",
            anchor="w", command=lambda: self.scheduler.request_stop()
        )
        self.btn_stop_schedule.grid(row=13, column=0, padx=12, pady=(4, 12), sticky="ew")

        # เครดิตด้านล่าง
        self.credit_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Admin Console\n© 2026 School Face Finder",
            font=ctk.CTkFont(size=11),
            text_color="#4F6580"
        )
        self.credit_label.grid(row=14, column=0, pady=15, sticky="s")
        self.sidebar_frame.grid_rowconfigure(14, weight=1)

    def select_menu(self, menu_name):
        # รีเซ็ตสีปุ่มทั้งหมด
        self.btn_dashboard.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_registry.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_student_registry.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_scan.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_database.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_matched_gallery.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_unknown_analytics.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_settings.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_delete_req.configure(fg_color="transparent", text_color="#A2B5CD")

        # ซ่อนเฟรมเนื้อหาทั้งหมด
        self.frame_dashboard.grid_forget()
        self.frame_registry.grid_forget()
        self.frame_student_registry.grid_forget()
        self.frame_scan.grid_forget()
        self.frame_database.grid_forget()
        self.frame_matched_gallery.grid_forget()
        self.frame_unknown_analytics.grid_forget()
        self.frame_settings.grid_forget()
        self.frame_delete_req.grid_forget()

        # แสดงเฟรมและเปลี่ยนสีปุ่มที่เลือก (วางที่แถว 0 เสมอเพื่อให้เหลือก้นจอเป็น Console)
        if menu_name == "dashboard":
            self.btn_dashboard.configure(fg_color="#1F3A60", text_color="white")
            self.frame_dashboard.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            self.refresh_dashboard_stats()
        elif menu_name == "registry":
            self.btn_registry.configure(fg_color="#1F3A60", text_color="white")
            self.frame_registry.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            self.load_staff_list()
        elif menu_name == "student_registry":
            self.btn_student_registry.configure(fg_color="#1F3A60", text_color="white")
            self.frame_student_registry.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            self.load_student_list()
        elif menu_name == "scan":
            self.btn_scan.configure(fg_color="#1F3A60", text_color="white")
            self.frame_scan.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
        elif menu_name == "database":
            self.btn_database.configure(fg_color="#1F3A60", text_color="white")
            self.frame_database.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            self.load_db_table_data()
        elif menu_name == "matched_gallery":
            self.btn_matched_gallery.configure(fg_color="#1F3A60", text_color="white")
            self.frame_matched_gallery.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            if hasattr(self, 'on_matched_role_change'):
                # โหลดข้อมูล async เพื่อไม่ให้ GUI ฟรีซค้างขณะเปิดเมนู (v4.14)
                self.after(50, lambda: self.on_matched_role_change(self.combo_matched_role.get()))
        elif menu_name == "unknown_analytics":
            self.btn_unknown_analytics.configure(fg_color="#1F3A60", text_color="white")
            self.frame_unknown_analytics.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            self.load_unknown_clusters_list()
        elif menu_name == "settings":
            self.btn_settings.configure(fg_color="#1F3A60", text_color="white")
            self.frame_settings.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
            if hasattr(self, 'refresh_root_folders_table'):
                self.refresh_root_folders_table()
        elif menu_name == "delete_req":
            self.btn_delete_req.configure(fg_color="#1F3A60", text_color="white")
            self.frame_delete_req.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")

    # --- โครงสร้างเฟรมเนื้อหาขวา (Content Pane) ---
    def create_content_areas(self):
        # 1. เฟรมหน้า Dashboard
        self.frame_dashboard = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_dashboard_ui()

        # 2. เฟรมหน้าลงทะเบียนครู
        self.frame_registry = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_registry_ui()

        # 3. เฟรมหน้าลงทะเบียนนักเรียน
        self.frame_student_registry = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_student_registry_ui()

        # 4. เฟรมหน้าสแกนรูปกิจกรรม
        self.frame_scan = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_scan_ui()

        # 5. เฟรมหน้าดูฐานข้อมูล
        self.frame_database = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_database_ui()

        # 6. เฟรมหน้าภาพกิจกรรมที่แมตช์แล้ว (v3.2)
        self.frame_matched_gallery = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_matched_gallery_ui()

        # 7. เฟรมหน้าสถิติบุคคลนิรนาม (Unknowns Analytics v6.20)
        self.frame_unknown_analytics = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_unknown_analytics_ui()

        # 8. เฟรมหน้าตั้งค่าระบบ
        self.frame_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_settings_ui()

        # 9. เฟรมหน้าคำขอลบภาพ (Delete Requests)
        self.frame_delete_req = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_delete_req_ui()

    # ==================== (1) หน้า Dashboard ====================
    def setup_dashboard_ui(self):
        self.frame_dashboard.grid_columnconfigure(0, weight=1)
        self.frame_dashboard.grid_columnconfigure((1, 2), weight=2)
        self.frame_dashboard.grid_rowconfigure(2, weight=1)

        # หัวข้อ
        lbl_title = ctk.CTkLabel(
            self.frame_dashboard, text="ภาพรวมของระบบ (Dashboard)", 
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))

        # การ์ดแสดงสถิติต่างๆ
        self.stats_container = ctk.CTkFrame(self.frame_dashboard, fg_color="transparent")
        self.stats_container.grid(row=1, column=0, columnspan=3, sticky="new", pady=(0, 20))
        self.stats_container.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # การ์ด 1: จำนวนครู
        self.card_teachers = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=145)
        self.card_teachers.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self.card_teachers.grid_propagate(False)
        self.lbl_stat_teachers = ctk.CTkLabel(self.card_teachers, text="0", font=ctk.CTkFont(size=42, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_teachers.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_teachers, text="ครูที่ลงทะเบียน (คน)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 2: จำนวนนักเรียน
        self.card_students = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=145)
        self.card_students.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
        self.card_students.grid_propagate(False)
        self.lbl_stat_students = ctk.CTkLabel(self.card_students, text="0", font=ctk.CTkFont(size=42, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_students.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_students, text="นักเรียนที่ลงทะเบียน (คน)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 3: จำนวนภาพกิจกรรมที่สแกนแล้ว
        self.card_photos = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=145)
        self.card_photos.grid(row=0, column=2, padx=8, pady=8, sticky="nsew")
        self.card_photos.grid_propagate(False)
        self.lbl_stat_photos = ctk.CTkLabel(self.card_photos, text="0", font=ctk.CTkFont(size=42, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_photos.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_photos, text="ภาพกิจกรรมที่สแกน (รูป)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 4: จำนวนใบหน้าที่ตรวจพบ
        self.card_matches = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=145)
        self.card_matches.grid(row=0, column=3, padx=8, pady=8, sticky="nsew")
        self.card_matches.grid_propagate(False)
        self.lbl_stat_matches = ctk.CTkLabel(self.card_matches, text="0", font=ctk.CTkFont(size=42, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_matches.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_matches, text="การตรวจพบ (ครั้ง)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # 2.1 กล่องตรวจสอบโมเดลและไลบรารี (ฝั่งซ้ายของแถว 2)
        self.status_box = ctk.CTkFrame(self.frame_dashboard, fg_color="#101B2B")
        self.status_box.grid(row=2, column=0, padx=(0, 10), pady=10, sticky="nsew")
        
        lbl_status_title = ctk.CTkLabel(self.status_box, text="สถานะไลบรารีและโมเดล AI", font=ctk.CTkFont(size=16, weight="bold"), text_color="#6CA6CD")
        lbl_status_title.pack(anchor="w", padx=20, pady=(15, 5))

        self.lbl_model_status = ctk.CTkLabel(self.status_box, text="กำลังตรวจสอบโมเดล...", text_color="#A2B5CD", font=ctk.CTkFont(size=14))
        self.lbl_model_status.pack(anchor="w", padx=20, pady=5)
        
        self.lbl_db_status = ctk.CTkLabel(self.status_box, text="ตรวจสอบฐานข้อมูล: เชื่อมต่อแล้ว (SQLite)", text_color="#A2B5CD", font=ctk.CTkFont(size=14))
        self.lbl_db_status.pack(anchor="w", padx=20, pady=(5, 10))

        # ส่วนซิงค์ข้อมูล Google Sheets แบบ Manual
        lbl_sync_title = ctk.CTkLabel(self.status_box, text="การซิงค์ข้อมูลคลาวด์", font=ctk.CTkFont(size=16, weight="bold"), text_color="#6CA6CD")
        lbl_sync_title.pack(anchor="w", padx=20, pady=(10, 5))
        
        self.btn_manual_sync = ctk.CTkButton(
            self.status_box, 
            text="📤 ซิงค์ข้อมูลขึ้น Google Sheets", 
            fg_color="#27AE60", hover_color="#229954", text_color="white",
            height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.run_manual_sync
        )
        self.btn_manual_sync.pack(anchor="w", padx=20, pady=(5, 15))

        # 2.2 กล่องสถิติจำนวนภาพของคุณครู (ฝั่งขวาซีกซ้าย แถว 2 คอลัมน์ 1)
        self.teacher_faces_box = ctk.CTkFrame(self.frame_dashboard, fg_color="#101B2B")
        self.teacher_faces_box.grid(row=2, column=1, padx=5, pady=10, sticky="nsew")
        
        teacher_title_frame = ctk.CTkFrame(self.teacher_faces_box, fg_color="transparent")
        teacher_title_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        self.lbl_teacher_title = ctk.CTkLabel(
            teacher_title_frame, 
            text="สถิติคุณครู (จากมากไปน้อย 🔽)", 
            font=ctk.CTkFont(size=14, weight="bold"), 
            text_color="#2ECC71"
        )
        self.lbl_teacher_title.pack(side="left", anchor="w")
        
        self.btn_teacher_sort = ctk.CTkButton(
            teacher_title_frame, 
            text="สลับ 🔼", 
            width=65, height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.toggle_dashboard_sort
        )
        self.btn_teacher_sort.pack(side="right", anchor="e")
        
        self.scr_teacher_faces = ctk.CTkScrollableFrame(self.teacher_faces_box, fg_color="transparent", height=150)
        self.scr_teacher_faces.pack(fill="both", expand=True, padx=10, pady=(0, 15))

        # 2.3 กล่องสถิติจำนวนภาพของนักเรียน (ฝั่งขวาซีกขวา แถว 2 คอลัมน์ 2)
        self.student_faces_box = ctk.CTkFrame(self.frame_dashboard, fg_color="#101B2B")
        self.student_faces_box.grid(row=2, column=2, padx=(5, 0), pady=10, sticky="nsew")
        
        student_title_frame = ctk.CTkFrame(self.student_faces_box, fg_color="transparent")
        student_title_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        self.lbl_student_title = ctk.CTkLabel(
            student_title_frame, 
            text="สถิตินักเรียน (จากมากไปน้อย 🔽)", 
            font=ctk.CTkFont(size=14, weight="bold"), 
            text_color="#F39C12"
        )
        self.lbl_student_title.pack(side="left", anchor="w")
        
        self.btn_student_sort = ctk.CTkButton(
            student_title_frame, 
            text="สลับ 🔼", 
            width=65, height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.toggle_dashboard_sort
        )
        self.btn_student_sort.pack(side="right", anchor="e")
        
        self.scr_student_faces = ctk.CTkScrollableFrame(self.student_faces_box, fg_color="transparent", height=150)
        self.scr_student_faces.pack(fill="both", expand=True, padx=10, pady=(0, 15))

    def toggle_dashboard_sort(self):
        self.dashboard_sort_desc = not getattr(self, 'dashboard_sort_desc', True)
        if self.dashboard_sort_desc:
            self.lbl_teacher_title.configure(text="สถิติคุณครู (จากมากไปน้อย 🔽)")
            self.btn_teacher_sort.configure(text="สลับ 🔼")
            self.lbl_student_title.configure(text="สถิตินักเรียน (จากมากไปน้อย 🔽)")
            self.btn_student_sort.configure(text="สลับ 🔼")
        else:
            self.lbl_teacher_title.configure(text="สถิติคุณครู (จากน้อยไปมาก 🔼)")
            self.btn_teacher_sort.configure(text="สลับ 🔽")
            self.lbl_student_title.configure(text="สถิตินักเรียน (จากน้อยไปมาก 🔼)")
            self.btn_student_sort.configure(text="สลับ 🔽")
        self.refresh_dashboard_stats()

    def refresh_dashboard_stats(self):
        try:
            sort_dir = "DESC" if self.dashboard_sort_desc else "ASC"
            stats = self.db.get_dashboard_fast_stats(sort_dir=sort_dir)

            self.lbl_stat_teachers.configure(text=str(stats["num_teachers"]))
            self.lbl_stat_students.configure(text=str(stats["num_students"]))
            self.lbl_stat_photos.configure(text=str(stats["num_photos"]))
            self.lbl_stat_matches.configure(text=str(stats["num_matches"]))
            
            # ตรวจโมเดล
            model_dir = get_antelopev2_dir()
            required_files = ["scrfd_10g_bnkps.onnx", "glintr100.onnx"]
            model_exists = all(os.path.exists(os.path.join(model_dir, f)) for f in required_files)
            
            if model_exists:
                self.lbl_model_status.configure(text="โมเดล InsightFace (antelopev2): พร้อมในเครื่อง", text_color="#2ECC71")
            else:
                self.lbl_model_status.configure(text="โมเดล InsightFace: ยังไม่มีไฟล์ในเครื่อง", text_color="#E67E22")
                
            teacher_rows = stats["teacher_rows"]
            student_rows = stats["student_rows"]
            
            if not hasattr(self, "_dash_font_bold"):
                self._dash_font_bold = ctk.CTkFont(size=13, weight="bold")
                self._dash_font_norm = ctk.CTkFont(size=13, weight="normal")

            # ฟังก์ชันวาดแถวข้อมูลสถิติแบบ Widget Pooling / Reuse (v6.28 ไม่ทำลายและสร้างใหม่ซ้ำ 300 วิดเจ็ต)
            def draw_rows(rows, scroll_frame):
                all_counts = [r[1] for r in rows]
                max_count = max(all_counts) if all_counts else 0
                if max_count == 0:
                    max_count = 1
                
                pool = getattr(scroll_frame, "_row_pool", None)
                if pool is None or any(not item["frame"].winfo_exists() for item in pool):
                    for widget in scroll_frame.winfo_children():
                        widget.destroy()
                    pool = []
                    scroll_frame._row_pool = pool

                def _on_mousewheel(event, sf=scroll_frame):
                    try:
                        sf._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                    except Exception:
                        pass

                for idx, r in enumerate(rows):
                    name = r[0]
                    count = r[1]
                    ratio = count / max_count
                    
                    # ไล่เฉดสีจากเขียวเข้ม (#27AE60) ไปหาแดงเข้ม (#C0392B)
                    r_val = int(192 + (39 - 192) * ratio)
                    g_val = int(57 + (174 - 57) * ratio)
                    b_val = int(43 + (96 - 43) * ratio)
                    color_hex = f"#{r_val:02x}{g_val:02x}{b_val:02x}"
                    rank_str = f"{idx+1}."
                    name_font = self._dash_font_bold if ratio > 0.5 else self._dash_font_norm

                    if idx < len(pool):
                        entry = pool[idx]
                        if not entry["visible"]:
                            entry["frame"].pack(fill="x", pady=2)
                            entry["visible"] = True
                        entry["lbl_rank"].configure(text=rank_str, text_color=color_hex)
                        entry["lbl_name"].configure(text=name, text_color=color_hex, font=name_font)
                        entry["lbl_count"].configure(text=f"{count} รูป", text_color=color_hex)
                    else:
                        row_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
                        row_frame.pack(fill="x", pady=2)
                        
                        lbl_rank = ctk.CTkLabel(row_frame, text=rank_str, width=28, anchor="w", font=self._dash_font_bold, text_color=color_hex)
                        lbl_rank.pack(side="left")
                        
                        lbl_name = ctk.CTkLabel(row_frame, text=name, anchor="w", text_color=color_hex, font=name_font)
                        lbl_name.pack(side="left", fill="x", expand=True)
                        
                        lbl_count = ctk.CTkLabel(row_frame, text=f"{count} รูป", width=60, anchor="e", text_color=color_hex, font=self._dash_font_bold)
                        lbl_count.pack(side="right")
                        
                        row_frame.bind("<MouseWheel>", _on_mousewheel)
                        lbl_rank.bind("<MouseWheel>", _on_mousewheel)
                        lbl_name.bind("<MouseWheel>", _on_mousewheel)
                        lbl_count.bind("<MouseWheel>", _on_mousewheel)
                        pool.append({
                            "frame": row_frame,
                            "lbl_rank": lbl_rank,
                            "lbl_name": lbl_name,
                            "lbl_count": lbl_count,
                            "visible": True
                        })

                for idx in range(len(rows), len(pool)):
                    if pool[idx]["visible"]:
                        pool[idx]["frame"].pack_forget()
                        pool[idx]["visible"] = False

            draw_rows(teacher_rows, self.scr_teacher_faces)
            draw_rows(student_rows, self.scr_student_faces)
            
        except Exception as e:
            logger.error(f"Error loading dashboard stats: {e}")

    def run_manual_sync(self):
        # ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต/Google Drive
        if not self.sync_manager.connected:
            cred_path = self.entry_cred_path.get().strip()
            if not os.path.exists(cred_path):
                messagebox.showerror("ข้อผิดพลาด", "ไม่พบไฟล์ Service Account JSON กรุณาตั้งค่าในหน้าตั้งค่าระบบก่อน")
                return
            self.sync_manager.credentials_path = cred_path
            success = self.sync_manager.connect()
            if not success:
                messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเชื่อมต่อ Google API ได้ (กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือไฟล์ Service Account)")
                return

        # ปิดปุ่มชั่วคราวเพื่อป้องกันการกดซ้ำ
        self.btn_manual_sync.configure(state="disabled", text="กำลังซิงค์ข้อมูล...")

        def do_sync():
            try:
                logger.info("[GSHEETS] Manual Sync Started: Syncing all SQLite data to Google Sheets & Drive JSON...")
                sync_data = self.db.get_all_sync_data()
                
                # ซิงค์ไป Google Sheets
                self.sync_manager.sync_to_google_sheet(sync_data)
                
                # บันทึก Excel สำรองในเครื่อง
                self.sync_manager.save_local_excel_mirror(sync_data)
                
                # อัปเดตไฟล์ JSON บน Google Drive
                json_folder_id = self.entry_json_folder_id.get().strip()
                if json_folder_id:
                    self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
                    logger.info("[GSHEETS] Manual Sync: Google Sheets & Drive JSON Sync Completed.")
                else:
                    logger.warning("[GSHEETS] Manual Sync: Google Sheets Sync Completed (Drive JSON Skipped - no Folder ID).")

                # แจ้งความสำเร็จทาง GUI
                self.after(0, lambda: messagebox.showinfo("ซิงค์สำเร็จ", "ซิงค์ข้อมูลทั้งหมดไปยัง Google Sheets, Excel Backup และ JSON บน Drive สำเร็จเรียบร้อย!"))
            except Exception as e:
                logger.error(f"[GSHEETS] Manual Sync Error: {e}")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการซิงค์ข้อมูล: {e}"))
            finally:
                # เปิดปุ่มให้ใช้งานได้อีกครั้ง
                self.after(0, lambda: self.btn_manual_sync.configure(state="normal", text="📤 ซิงค์ข้อมูลขึ้น Google Sheets"))

        threading.Thread(target=do_sync, daemon=True).start()

    # ==================== (2) หน้าลงทะเบียนครู (Staff Registry) ====================
    def setup_registry_ui(self):
        self.frame_registry.grid_columnconfigure(0, weight=2)
        self.frame_registry.grid_columnconfigure(1, weight=3)
        self.frame_registry.grid_rowconfigure(1, weight=1)

        # หัวข้อหน้า
        lbl_title = ctk.CTkLabel(
            self.frame_registry, text="ลงทะเบียนใบหน้าคุณครู", 
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        # ซีกซ้าย: รายชื่อครูที่ลงทะเบียนไว้
        self.list_frame = ctk.CTkFrame(self.frame_registry, fg_color="#101B2B")
        self.list_frame.grid(row=1, column=0, padx=(0, 10), sticky="nsew")
        self.list_frame.grid_rowconfigure(3, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.list_frame, text="รายชื่อคุณครูที่บันทึกแล้ว", font=ctk.CTkFont(size=16, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, padx=15, pady=12, sticky="w")
        
        # ช่องค้นหาคุณครู
        search_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        search_frame.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_staff_search = ctk.CTkEntry(search_frame, placeholder_text="🔍 ค้นหา (ID, ชื่อ, สังกัด)...", height=36, font=ctk.CTkFont(size=14))
        self.entry_staff_search.grid(row=0, column=0, sticky="ew")
        self.entry_staff_search.bind("<KeyRelease>", lambda event: self.filter_staff_list())
        
        btn_clear_staff_search = ctk.CTkButton(search_frame, text="✕", width=34, height=36, font=ctk.CTkFont(size=14, weight="bold"), fg_color="transparent", hover_color="#20334F", text_color="#A2B5CD", command=self.clear_staff_search)
        btn_clear_staff_search.grid(row=0, column=1, padx=(5, 0))

        # ตัวกรองสังกัด (Department Filter Dropdown v6.34)
        filter_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        filter_frame.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")
        filter_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(filter_frame, text="สังกัด:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A2B5CD").grid(row=0, column=0, padx=(0, 5), sticky="w")
        
        dept_filter_options = ["ทั้งหมด (ทุกสังกัด)"] + [d for d in SW_DEPARTMENTS if d != "อื่นๆ (ระบุเอง)"]
        self.option_teacher_dept_filter = ctk.CTkOptionMenu(
            filter_frame,
            values=dept_filter_options,
            height=32,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            dropdown_fg_color="#101B2B",
            dropdown_hover_color="#1F3A60",
            dropdown_text_color="white",
            command=lambda val: self.filter_staff_list(immediate=True)
        )
        self.option_teacher_dept_filter.grid(row=0, column=1, sticky="ew")
        
        # ตาราง Treeview แสดงรายชื่อคุณครูแบบมีคอลัมน์และคลิกเรียงลำดับได้ (v6.34)
        tree_container = ctk.CTkFrame(self.list_frame, fg_color="#1C2D42")
        tree_container.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="nsew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        cols = ("id", "name", "department", "photos")
        self.teacher_tree = ttk.Treeview(tree_container, columns=cols, show="headings", selectmode="browse")
        self.teacher_tree.grid(row=0, column=0, sticky="nsew")

        self.teacher_sort_col = "id"
        self.teacher_sort_desc = False

        self.teacher_tree.column("id", width=55, anchor="center")
        self.teacher_tree.column("name", width=175, anchor="w")
        self.teacher_tree.column("department", width=130, anchor="w")
        self.teacher_tree.column("photos", width=55, anchor="center")

        self.teacher_tree.heading("id", text="ID ▲", command=lambda: self.sort_teacher_table("id"))
        self.teacher_tree.heading("name", text="ชื่อ-นามสกุล", command=lambda: self.sort_teacher_table("name"))
        self.teacher_tree.heading("department", text="สังกัด", command=lambda: self.sort_teacher_table("department"))
        self.teacher_tree.heading("photos", text="รูป", command=lambda: self.sort_teacher_table("photos"))

        teacher_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.teacher_tree.yview)
        teacher_scrollbar.grid(row=0, column=1, sticky="ns")
        self.teacher_tree.configure(yscrollcommand=teacher_scrollbar.set)

        self.teacher_tree.bind("<<TreeviewSelect>>", self.on_teacher_tree_select)
        
        self.selected_staff_id = None
        self.selected_staff_name = None
        self.staff_buttons = {}
        self.selected_thumb_path = None
        self.selected_thumb_widget = None

        # ซีกขวา: ฟอร์มจัดการเพิ่มคน อัปโหลดรูป และลบ
        self.form_frame = ctk.CTkFrame(self.frame_registry, fg_color="#1C2D42")
        self.form_frame.grid(row=1, column=1, padx=(10, 0), sticky="nsew")
        self.form_frame.grid_columnconfigure(0, weight=1)

        # เพิ่มครูคนใหม่
        ctk.CTkLabel(self.form_frame, text="1. เพิ่มรายชื่อครูใหม่", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))
        
        add_input_frame = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        add_input_frame.pack(fill="x", padx=20, pady=2)
        
        self.entry_staff_name = ctk.CTkEntry(add_input_frame, placeholder_text="กรอกชื่อคุณครู (เช่น ครูสมชาย ใจดี หรือ นายสมชาย ใจดี วิทยาศาสตร์)", height=36, font=ctk.CTkFont(size=14))
        self.entry_staff_name.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        btn_add_staff = ctk.CTkButton(add_input_frame, text="เพิ่มชื่อ", width=95, height=36, font=ctk.CTkFont(size=14, weight="bold"), command=self.add_staff_name)
        btn_add_staff.pack(side="right")

        add_input_frame2 = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        add_input_frame2.pack(fill="x", padx=20, pady=(2, 6))

        ctk.CTkLabel(add_input_frame2, text="สังกัด:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=(0, 5))

        dept_options_add = ["(เลือกสังกัด)"] + SW_DEPARTMENTS
        self.option_staff_dept_add = ctk.CTkOptionMenu(
            add_input_frame2,
            values=dept_options_add,
            height=32,
            width=180,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            dropdown_fg_color="#101B2B",
            dropdown_hover_color="#1F3A60",
            dropdown_text_color="white",
            command=self.on_dept_add_option_selected
        )
        self.option_staff_dept_add.pack(side="left", padx=(0, 5))

        self.entry_staff_department = ctk.CTkEntry(add_input_frame2, placeholder_text="หรือระบุสังกัดเอง...", height=32, font=ctk.CTkFont(size=13))
        self.entry_staff_department.pack(side="left", fill="x", expand=True)

        # ปุ่มนำเข้ายกโฟลเดอร์อัตโนมัติ
        btn_batch_import = ctk.CTkButton(
            self.form_frame, text="📁 นำเข้าคุณครูยกโฟลเดอร์อัตโนมัติ (Batch Import)", 
            fg_color="#1F3A60", hover_color="#20334F", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.batch_import_teachers
        )
        btn_batch_import.pack(fill="x", padx=20, pady=(4, 12))

        # จัดการภาพใบหน้าคุณครูที่เลือก
        ctk.CTkLabel(self.form_frame, text="2. จัดการภาพใบหน้าต้นแบบ", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(15, 5))
        
        self.lbl_selected_info = ctk.CTkLabel(self.form_frame, text="กรุณาเลือกคุณครูจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ", font=ctk.CTkFont(size=14), text_color="#A2B5CD")
        self.lbl_selected_info.pack(anchor="w", padx=20, pady=5)

        # ปุ่มอัปโหลดรูปต้นแบบเพิ่ม
        self.btn_upload_photo = ctk.CTkButton(
            self.form_frame, text="อัปโหลดรูปใบหน้าต้นแบบเพิ่ม (จากคอมพิวเตอร์)", 
            state="disabled", fg_color="#1F3A60", hover_color="#20334F", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.upload_staff_photos
        )
        self.btn_upload_photo.pack(fill="x", padx=20, pady=10)

        # แสดงจำนวนรูปที่ลงทะเบียน
        self.lbl_photo_count_detail = ctk.CTkLabel(self.form_frame, text="", font=ctk.CTkFont(size=14), text_color="white")
        self.lbl_photo_count_detail.pack(anchor="w", padx=20, pady=5)

        # พื้นที่แสดงรูปภาพใบหน้าครูต้นแบบ
        self.thumbs_frame = ctk.CTkFrame(self.form_frame, fg_color="#101B2B", height=200)
        self.thumbs_frame.pack(fill="x", expand=False, padx=20, pady=(5, 10))
        self.thumbs_frame.pack_propagate(False)
        
        ctk.CTkLabel(self.thumbs_frame, text="ภาพใบหน้าที่เรียนรู้แล้ว (ตารางภาพ):", font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD").pack(anchor="w", padx=10, pady=(6, 2))
        
        self.thumbs_scrollable = ctk.CTkScrollableFrame(self.thumbs_frame, orientation="vertical", fg_color="transparent", height=155)
        self.thumbs_scrollable.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ปุ่มลบรูปที่เลือก
        self.btn_delete_photo = ctk.CTkButton(
            self.form_frame, text="❌ ลบรูปภาพที่เลือก", height=36, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_photo
        )
        self.btn_delete_photo.pack(fill="x", padx=20, pady=(5, 10))

        # 3. การดำเนินการอื่น ๆ (แก้ไข และ ลบ)
        ctk.CTkLabel(self.form_frame, text="3. การดำเนินการอื่น ๆ", font=ctk.CTkFont(size=16, weight="bold"), text_color="#E74C3C").pack(anchor="w", padx=20, pady=(15, 5))
        
        staff_actions_frame = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        staff_actions_frame.pack(fill="x", padx=20, pady=10)
        staff_actions_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_edit_staff = ctk.CTkButton(
            staff_actions_frame, text="✏️ แก้ไขข้อมูลคุณครู", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#F39C12", hover_color="#D68910", text_color="#101B2B", command=self.edit_selected_staff
        )
        self.btn_edit_staff.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.btn_delete_staff = ctk.CTkButton(
            staff_actions_frame, text="🗑️ ลบรายชื่อคุณครู", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_staff
        )
        self.btn_delete_staff.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    # ==================== (3) หน้าลงทะเบียนนักเรียน (Student Registry) ====================
    def setup_student_registry_ui(self):
        self.frame_student_registry.grid_columnconfigure(0, weight=2)
        self.frame_student_registry.grid_columnconfigure(1, weight=3)
        self.frame_student_registry.grid_rowconfigure(1, weight=1)

        # หัวข้อหน้า
        lbl_title = ctk.CTkLabel(
            self.frame_student_registry, text="ลงทะเบียนใบหน้านักเรียน",
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 20))

        # ปุ่มเปิดหน้าต่างบริหารวงจรชีวิตนักเรียน (เลื่อนชั้น / บันทึกจบการศึกษา) (v6.29)
        btn_lifecycle_header = ctk.CTkButton(
            self.frame_student_registry,
            text="🎓 จัดการเลื่อนชั้น / บันทึกจบการศึกษา",
            height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#8E44AD",
            hover_color="#7D3C98",
            command=self.open_student_lifecycle_dialog
        )
        btn_lifecycle_header.grid(row=0, column=1, sticky="e", pady=(0, 20))

        # ซีกซ้าย: รายชื่อนักเรียนที่ลงทะเบียนไว้
        self.student_list_frame = ctk.CTkFrame(self.frame_student_registry, fg_color="#101B2B")
        self.student_list_frame.grid(row=1, column=0, padx=(0, 10), sticky="nsew")
        self.student_list_frame.grid_rowconfigure(3, weight=1)
        self.student_list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.student_list_frame, text="รายชื่อนักเรียนที่บันทึกแล้ว", font=ctk.CTkFont(size=16, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, padx=15, pady=(12, 6), sticky="w")

        # ช่องค้นหานักเรียน
        student_search_frame = ctk.CTkFrame(self.student_list_frame, fg_color="transparent")
        student_search_frame.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")
        student_search_frame.grid_columnconfigure(0, weight=1)

        self.entry_student_search = ctk.CTkEntry(student_search_frame, placeholder_text="🔍 ค้นหารหัส, ชื่อ หรือห้อง...", height=36, font=ctk.CTkFont(size=14))
        self.entry_student_search.grid(row=0, column=0, sticky="ew")
        self.entry_student_search.bind("<KeyRelease>", lambda event: self.filter_student_list())

        btn_clear_student_search = ctk.CTkButton(student_search_frame, text="✕", width=34, height=36, font=ctk.CTkFont(size=14, weight="bold"), fg_color="transparent", hover_color="#20334F", text_color="#A2B5CD", command=self.clear_student_search)
        btn_clear_student_search.grid(row=0, column=1, padx=(5, 0))

        # แถบตัวกรองสถานะ และห้องเรียน (v6.29 Student Lifecycle Filter Bar)
        student_filter_frame = ctk.CTkFrame(self.student_list_frame, fg_color="transparent")
        student_filter_frame.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")
        student_filter_frame.grid_columnconfigure(0, weight=1)

        self.student_status_segmented = ctk.CTkSegmentedButton(
            student_filter_frame,
            values=["กำลังศึกษา", "จบแล้ว", "ทั้งหมด"],
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color="#1F3A60",
            selected_hover_color="#20334F",
            command=lambda v: self.filter_student_list(immediate=True)
        )
        self.student_status_segmented.set("กำลังศึกษา")
        self.student_status_segmented.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.option_student_classroom = ctk.CTkOptionMenu(
            student_filter_frame,
            values=["ห้อง: ทั้งหมด"],
            width=130,
            height=30,
            font=ctk.CTkFont(size=12),
            command=lambda v: self.filter_student_list(immediate=True)
        )
        self.option_student_classroom.set("ห้อง: ทั้งหมด")
        self.option_student_classroom.pack(side="right")

        # Listbox แสดงรายชื่อ
        self.student_list_scrollable = ctk.CTkScrollableFrame(self.student_list_frame, fg_color="transparent")
        self.student_list_scrollable.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="nsew")

        self.selected_student_id = None
        self.selected_student_name = None
        self.student_buttons = {}
        self.selected_student_thumb_path = None
        self.selected_student_thumb_widget = None

        # ซีกขวา: ฟอร์มจัดการเพิ่มคน อัปโหลดรูป และลบ
        self.student_form_frame = ctk.CTkFrame(self.frame_student_registry, fg_color="#1C2D42")
        self.student_form_frame.grid(row=1, column=1, padx=(10, 0), sticky="nsew")
        self.student_form_frame.grid_columnconfigure(0, weight=1)

        # เพิ่มนักเรียนคนใหม่
        ctk.CTkLabel(self.student_form_frame, text="1. เพิ่มรายชื่อนักเรียนใหม่", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))

        # ฟิลด์รหัสประจำตัว
        id_input_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        id_input_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(id_input_frame, text="รหัสประจำตัว:", font=ctk.CTkFont(size=14), text_color="#A2B5CD", width=120, anchor="w").pack(side="left")
        self.entry_student_id = ctk.CTkEntry(id_input_frame, placeholder_text="เช่น 66001", height=36, font=ctk.CTkFont(size=14))
        self.entry_student_id.pack(side="left", fill="x", expand=True, padx=(5, 10))

        # ฟิลด์ชื่อ-นามสกุล
        name_input_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        name_input_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(name_input_frame, text="ชื่อ-นามสกุล:", font=ctk.CTkFont(size=14), text_color="#A2B5CD", width=120, anchor="w").pack(side="left")
        self.entry_student_name = ctk.CTkEntry(name_input_frame, placeholder_text="กรอกชื่อนักเรียน (เช่น นายรักเรียน มัธยม1)", height=36, font=ctk.CTkFont(size=14))
        self.entry_student_name.pack(side="left", fill="x", expand=True, padx=(5, 10))

        # ฟิลด์ระดับชั้น/ห้องเรียน (v6.29)
        class_input_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        class_input_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(class_input_frame, text="ระดับชั้น/ห้อง:", font=ctk.CTkFont(size=14), text_color="#A2B5CD", width=120, anchor="w").pack(side="left")
        self.entry_student_classroom = ctk.CTkEntry(class_input_frame, placeholder_text="เช่น ม.1/1, ม.4/2 (ใส่หรือไม่ก็ได้)", height=36, font=ctk.CTkFont(size=14))
        self.entry_student_classroom.pack(side="left", fill="x", expand=True, padx=(5, 10))

        btn_add_student = ctk.CTkButton(class_input_frame, text="เพิ่มชื่อ", width=95, height=36, font=ctk.CTkFont(size=14, weight="bold"), command=self.add_student_name)
        btn_add_student.pack(side="right")

        # ปุ่มนำเข้าจาก Google Sheets
        btn_import_from_sheets = ctk.CTkButton(
            self.student_form_frame, text="📊 นำเข้านักเรียนจาก Google Sheets (Batch Import)",
            fg_color="#27AE60", hover_color="#229954", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.open_sheets_import_dialog
        )
        btn_import_from_sheets.pack(fill="x", padx=20, pady=(4, 8))

        # จัดการภาพใบหน้านักเรียนที่เลือก
        ctk.CTkLabel(self.student_form_frame, text="2. จัดการภาพใบหน้าต้นแบบ", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(15, 5))

        self.lbl_student_selected_info = ctk.CTkLabel(self.student_form_frame, text="กรุณาเลือกนักเรียนจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ", font=ctk.CTkFont(size=14), text_color="#A2B5CD")
        self.lbl_student_selected_info.pack(anchor="w", padx=20, pady=5)

        # ปุ่มอัปโหลดรูปต้นแบบเพิ่ม
        self.btn_upload_student_photo = ctk.CTkButton(
            self.student_form_frame, text="อัปโหลดรูปใบหน้าต้นแบบเพิ่ม (จากคอมพิวเตอร์)",
            state="disabled", fg_color="#1F3A60", hover_color="#20334F", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.upload_student_photos
        )
        self.btn_upload_student_photo.pack(fill="x", padx=20, pady=10)

        # แสดงจำนวนรูปที่ลงทะเบียน
        self.lbl_student_photo_count_detail = ctk.CTkLabel(self.student_form_frame, text="", font=ctk.CTkFont(size=14), text_color="white")
        self.lbl_student_photo_count_detail.pack(anchor="w", padx=20, pady=5)

        # ปุ่มลบรูปที่เลือก (ย้ายมาก่อน thumbs_frame เพื่อให้แสดงได้เสมอ)
        self.btn_delete_student_photo = ctk.CTkButton(
            self.student_form_frame, text="❌ ลบรูปภาพที่เลือก", height=36, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_student_photo
        )
        self.btn_delete_student_photo.pack(fill="x", padx=20, pady=(5, 10))

        # พื้นที่แสดงรูปภาพใบหน้านักเรียนต้นแบบ
        self.student_thumbs_frame = ctk.CTkFrame(self.student_form_frame, fg_color="#101B2B", height=200)
        self.student_thumbs_frame.pack(fill="x", expand=False, padx=20, pady=(5, 10))
        self.student_thumbs_frame.pack_propagate(False)

        ctk.CTkLabel(self.student_thumbs_frame, text="ภาพใบหน้าที่เรียนรู้แล้ว (ตารางภาพ):", font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD").pack(anchor="w", padx=10, pady=(6, 2))

        self.student_thumbs_scrollable = ctk.CTkScrollableFrame(self.student_thumbs_frame, orientation="vertical", fg_color="transparent", height=155)
        self.student_thumbs_scrollable.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # 3. การดำเนินการอื่น ๆ (แก้ไข และ ลบ)
        ctk.CTkLabel(self.student_form_frame, text="3. การดำเนินการอื่น ๆ", font=ctk.CTkFont(size=16, weight="bold"), text_color="#E74C3C").pack(anchor="w", padx=20, pady=(15, 5))
        
        student_actions_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        student_actions_frame.pack(fill="x", padx=20, pady=5)
        student_actions_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_edit_student = ctk.CTkButton(
            student_actions_frame, text="✏️ แก้ไขข้อมูลนักเรียน", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#F39C12", hover_color="#D68910", text_color="#101B2B", command=self.edit_selected_student
        )
        self.btn_edit_student.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.btn_delete_student = ctk.CTkButton(
            student_actions_frame, text="❌ ลบรายชื่อนักเรียน", height=38, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_student
        )
        self.btn_delete_student.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def load_student_list(self, refresh_db=True):
        # ลบวิดเจ็ตใน Scrollable Frame เก่าออก
        for widget in self.student_list_scrollable.winfo_children():
            widget.destroy()

        self.student_buttons = {}
        self.selected_student_id = None
        self.selected_student_name = None
        self.selected_student_code = None
        self.selected_student_classroom = ""
        self.selected_student_status = "active"
        self.selected_student_grad_year = ""
        self.btn_upload_student_photo.configure(state="disabled")
        if hasattr(self, 'btn_edit_student'):
            self.btn_edit_student.configure(state="disabled")
        self.btn_delete_student.configure(state="disabled")
        self.lbl_student_selected_info.configure(text="กรุณาเลือกนักเรียนจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ")
        self.lbl_student_photo_count_detail.configure(text="")

        search_term = ""
        if hasattr(self, 'entry_student_search'):
            search_term = self.entry_student_search.get().strip().lower()

        status_val = self.student_status_segmented.get() if hasattr(self, 'student_status_segmented') else "กำลังศึกษา"
        class_val = self.option_student_classroom.get() if hasattr(self, 'option_student_classroom') else "ห้อง: ทั้งหมด"

        if refresh_db or getattr(self, '_cached_students_list', None) is None:
            self._cached_students_list = self.db.get_all_students(status_filter='all')
            if hasattr(self, 'option_student_classroom'):
                current_rooms = self.db.get_student_classrooms()
                room_values = ["ห้อง: ทั้งหมด"] + current_rooms
                self.option_student_classroom.configure(values=room_values)

        students = self._cached_students_list
        rendered_count = 0
        for idx, s in enumerate(students):
            st_status = s.get('status', 'active')
            if status_val == "กำลังศึกษา" and st_status != 'active':
                continue
            elif status_val == "จบแล้ว" and st_status != 'graduated':
                continue

            st_room = s.get('class_room', '')
            if class_val and class_val != "ห้อง: ทั้งหมด":
                if st_room != class_val:
                    continue

            if search_term:
                name_match = search_term in s['name'].lower()
                id_match = s['student_id'] and (search_term in s['student_id'].lower())
                room_match = st_room and (search_term in st_room.lower())
                if not (name_match or id_match or room_match):
                    continue
            
            if rendered_count >= 100:
                lbl_more = ctk.CTkLabel(self.student_list_scrollable, text="... แสดงเฉพาะ 100 รายการแรก (กรุณาค้นหาเพิ่มเติม) ...", text_color="#A2B5CD", font=ctk.CTkFont(size=13, slant="italic"))
                lbl_more.pack(pady=5)
                break
            
            rendered_count += 1

            row_frame = ctk.CTkFrame(self.student_list_scrollable, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)

            status_tag = ""
            if st_status == 'graduated':
                grad_yr = f" จบปี {s['graduation_year']}" if s.get('graduation_year') else " จบแล้ว"
                status_tag = f" • 🎓{grad_yr}"
            elif st_status == 'inactive':
                status_tag = " • ⚪ ลาออก"

            room_str = f" ({st_room})" if st_room else ""
            btn_text = f"{s['name']} [{s['student_id']}]{room_str}{status_tag} ({s['photo_count']} รูป)"

            btn = ctk.CTkButton(
                row_frame,
                text=btn_text,
                anchor="w",
                height=34,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                text_color="#A2B5CD" if st_status == 'active' else "#85929E",
                hover_color="#1F3A60",
                command=lambda sid=s['id'], sname=s['name'], scode=s['student_id'], scnt=s['photo_count'], sroom=st_room, sstat=st_status, sgy=s.get('graduation_year', ''): self.select_student_item(sid, sname, scode, scnt, sroom, sstat, sgy)
            )
            btn.pack(side="left", fill="x", expand=True)
            self.student_buttons[s['id']] = btn

            btn_delete_x = ctk.CTkButton(
                row_frame,
                text="❌",
                width=30, height=30,
                fg_color="transparent",
                hover_color="#E74C3C",
                text_color="#E74C3C",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda sid=s['id'], sname=s['name']: self.delete_selected_student_by_id(sid, sname)
            )
            btn_delete_x.pack(side="right", padx=(5, 2))


    def filter_student_list(self, event=None, immediate=False):
        if getattr(self, "_student_search_timer", None) is not None:
            try:
                self.after_cancel(self._student_search_timer)
            except Exception:
                pass
            self._student_search_timer = None
        if immediate:
            self.load_student_list(refresh_db=False)
        else:
            self._student_search_timer = self.after(250, lambda: self.load_student_list(refresh_db=False))

    def clear_student_search(self):
        if getattr(self, "_student_search_timer", None) is not None:
            try:
                self.after_cancel(self._student_search_timer)
            except Exception:
                pass
            self._student_search_timer = None
        if hasattr(self, 'entry_student_search'):
            self.entry_student_search.delete(0, "end")
            self.load_student_list(refresh_db=False)

    def select_student_item(self, student_id, student_name, student_code, photo_count, classroom='', status='active', grad_year=''):
        self.selected_student_id = student_id
        self.selected_student_name = student_name
        self.selected_student_code = student_code
        self.selected_student_classroom = classroom
        self.selected_student_status = status
        self.selected_student_grad_year = grad_year
        self.selected_student_thumb_paths = set()

        # ไฮไลต์ปุ่มที่ถูกเลือก
        for sid, btn in self.student_buttons.items():
            if sid == student_id:
                btn.configure(fg_color="#1F3A60", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#A2B5CD")

        status_display = "🟢 กำลังศึกษา" if status == 'active' else (f"🎓 จบการศึกษา ({grad_year})" if status == 'graduated' else "⚪ ลาออก/พักการเรียน")
        room_display = f"ห้อง: {classroom}" if classroom else "ห้อง: ไม่ระบุ"
        self.lbl_student_selected_info.configure(text=f"นักเรียนที่เลือก: {student_name} (รหัส: {student_code}) • {room_display} • {status_display}")
        self.lbl_student_photo_count_detail.configure(text=f"รูปภาพที่ลงทะเบียนแล้วในระบบ: {photo_count} รูป")

        self.btn_upload_student_photo.configure(state="normal")
        if hasattr(self, 'btn_edit_student'):
            self.btn_edit_student.configure(state="normal")
        self.btn_delete_student.configure(state="normal")
        self.btn_delete_student_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

        # ดึงภาพย่อมาแสดงผล
        self.show_student_thumbnails(student_id)

    def add_student_name(self):
        name = self.entry_student_name.get().strip()
        student_code = self.entry_student_id.get().strip()
        classroom = self.entry_student_classroom.get().strip() if hasattr(self, 'entry_student_classroom') else ""

        if not name:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อนักเรียน")
            return

        if not student_code:
            messagebox.showwarning("คำเตือน", "กรุณากรอกรหัสประจำตัวนักเรียน")
            return

        # ตรวจสอบว่ารหัสประจำตัวซ้ำหรือไม่
        if self.db.check_student_id_exists(student_code):
            messagebox.showerror("ข้อผิดพลาด", f"รหัสประจำตัว {student_code} ถูกใช้ไปแล้ว")
            return

        student_id = self.db.register_member(name, role='student', student_id=student_code, class_room=classroom, status='active')
        if student_id:
            logger.info(f"Registered new student '{name}' (ID: {student_code}, Room: {classroom}) successfully.")
            self.entry_student_name.delete(0, "end")
            self.entry_student_id.delete(0, "end")
            if hasattr(self, 'entry_student_classroom'):
                self.entry_student_classroom.delete(0, "end")
            self.load_student_list(refresh_db=True)
        else:
            messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเพิ่มรายชื่อได้")

    def upload_student_photos(self):
        if self.selected_student_id is None:
            return

        file_paths = filedialog.askopenfilenames(
            title=f"เลือกรูปภาพใบหน้าของ {self.selected_student_name}",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.webp")]
        )
        if not file_paths:
            return

        # เริ่มทำงานสแกนรูปเพื่อหาเวกเตอร์ใน Thread ย่อยเพื่อไม่ให้ GUI ค้าง
        def process_upload():
            logger.info(f"Processing {len(file_paths)} registration photos for student: {self.selected_student_name}")

            # โหลดตัวตรวจจับใบหน้า
            analyzer = FaceAnalyzer(use_gpu=False)
            if not analyzer.initialize():
                logger.error("Failed to initialize FaceAnalyzer.")
                return

            success_count = 0
            for path in file_paths:
                try:
                    logger.info(f"Extracting embedding from: {os.path.basename(path)}")
                    faces = analyzer.detect_and_extract_faces(path)

                    if len(faces) == 0:
                        logger.warning(f"No face detected in file: {os.path.basename(path)}. Skipping.")
                        continue
                    elif len(faces) > 1:
                        logger.warning(f"Multiple faces ({len(faces)}) detected in file: {os.path.basename(path)}. Using the largest face.")
                        largest_face = max(faces, key=lambda f: (f["bbox"][2]-f["bbox"][0]) * (f["bbox"][3]-f["bbox"][1]))
                        student_face_path = self.save_cropped_student_face(self.selected_student_id, self.selected_student_code, path, largest_face["bbox"], success_count)
                        self.db.add_staff_embedding(self.selected_student_id, student_face_path, largest_face["embedding"])
                    else:
                        student_face_path = self.save_cropped_student_face(self.selected_student_id, self.selected_student_code, path, faces[0]["bbox"], success_count)
                        self.db.add_staff_embedding(self.selected_student_id, student_face_path, faces[0]["embedding"])

                    success_count += 1
                except Exception as e:
                    logger.error(f"Error processing {os.path.basename(path)}: {e}")

            logger.info(f"Registered {success_count} / {len(file_paths)} face templates for student {self.selected_student_name}")

            # รีเฟรชรายชื่อและรูปภาพย่อยในหน่วยความจำ
            self.after(0, self.load_student_list)
            self.after(0, lambda: self.show_student_thumbnails(self.selected_student_id))
            self.after(0, lambda: messagebox.showinfo(
                "ลงทะเบียนสำเร็จ",
                f"ลงทะเบียนใบหน้าของนักเรียน {self.selected_student_name} สำเร็จ {success_count} รูป"
            ))

    def edit_selected_student(self):
        """แก้ไขชื่อ รหัสประจำตัว ห้องเรียน และสถานะนักเรียน (v6.29)"""
        if self.selected_student_id is None:
            return

        student_id = self.selected_student_id
        old_name = self.selected_student_name or ""
        old_code = self.selected_student_code or ""
        old_classroom = getattr(self, 'selected_student_classroom', '') or ""
        old_status = getattr(self, 'selected_student_status', 'active') or "active"
        old_grad_year = getattr(self, 'selected_student_grad_year', '') or ""

        # สร้างหน้าต่าง Popup Dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("แก้ไขข้อมูลนักเรียน")
        dialog.geometry("480x420")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # จัดกึ่งกลางหน้าจอหลัก
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 240
        y = self.winfo_y() + (self.winfo_height() // 2) - 210
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text="✏️ แก้ไขข้อมูลนักเรียน (v6.29)", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(pady=(15, 10))

        # รหัสประจำตัว
        frame_id = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_id.pack(fill="x", padx=25, pady=4)
        ctk.CTkLabel(frame_id, text="รหัสประจำตัว:", font=ctk.CTkFont(size=13), text_color="#A2B5CD", width=110, anchor="w").pack(side="left")
        entry_code = ctk.CTkEntry(frame_id, height=34, font=ctk.CTkFont(size=13))
        entry_code.pack(side="left", fill="x", expand=True)
        entry_code.insert(0, old_code)

        # ชื่อ-นามสกุล
        frame_name = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_name.pack(fill="x", padx=25, pady=4)
        ctk.CTkLabel(frame_name, text="ชื่อ-นามสกุล:", font=ctk.CTkFont(size=13), text_color="#A2B5CD", width=110, anchor="w").pack(side="left")
        entry_name = ctk.CTkEntry(frame_name, height=34, font=ctk.CTkFont(size=13))
        entry_name.pack(side="left", fill="x", expand=True)
        entry_name.insert(0, old_name)

        # ระดับชั้น / ห้องเรียน
        frame_class = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_class.pack(fill="x", padx=25, pady=4)
        ctk.CTkLabel(frame_class, text="ห้องเรียน:", font=ctk.CTkFont(size=13), text_color="#A2B5CD", width=110, anchor="w").pack(side="left")
        entry_classroom = ctk.CTkEntry(frame_class, height=34, font=ctk.CTkFont(size=13))
        entry_classroom.pack(side="left", fill="x", expand=True)
        entry_classroom.insert(0, old_classroom)

        # สถานะการศึกษา
        frame_status = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_status.pack(fill="x", padx=25, pady=4)
        ctk.CTkLabel(frame_status, text="สถานะ:", font=ctk.CTkFont(size=13), text_color="#A2B5CD", width=110, anchor="w").pack(side="left")
        status_map = {"active": "กำลังศึกษา (active)", "graduated": "จบการศึกษาแล้ว (graduated)", "inactive": "ลาออก/พักการเรียน (inactive)"}
        reverse_status_map = {v: k for k, v in status_map.items()}
        combo_status = ctk.CTkOptionMenu(frame_status, values=list(status_map.values()), height=34)
        combo_status.pack(side="left", fill="x", expand=True)
        combo_status.set(status_map.get(old_status, "กำลังศึกษา (active)"))

        # ปีการศึกษาที่จบ
        frame_grad = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_grad.pack(fill="x", padx=25, pady=4)
        ctk.CTkLabel(frame_grad, text="ปีที่จบ:", font=ctk.CTkFont(size=13), text_color="#A2B5CD", width=110, anchor="w").pack(side="left")
        entry_grad = ctk.CTkEntry(frame_grad, height=34, font=ctk.CTkFont(size=13))
        entry_grad.pack(side="left", fill="x", expand=True)
        entry_grad.insert(0, old_grad_year)

        def save_edit():
            new_name = entry_name.get().strip()
            new_code = entry_code.get().strip()
            new_classroom = entry_classroom.get().strip()
            new_status_key = reverse_status_map.get(combo_status.get(), "active")
            new_grad = entry_grad.get().strip()

            if not new_name:
                messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อ-นามสกุล", parent=dialog)
                return

            if not new_code:
                messagebox.showwarning("คำเตือน", "กรุณากรอกรหัสประจำตัวนักเรียน", parent=dialog)
                return

            success, msg = self.db.update_student_info(
                student_id, new_name, new_code, 
                status=new_status_key, class_room=new_classroom, graduation_year=new_grad
            )
            if success:
                logger.info(f"[SYSTEM] Student ID {student_id} updated to '{new_name}' (Code: {new_code}, Room: {new_classroom}, Status: {new_status_key})")
                dialog.destroy()
                
                # รีเฟรชข้อมูลในหน่วยความจำและหน้าจอ
                self.selected_student_name = new_name
                self.selected_student_code = new_code
                self.selected_student_classroom = new_classroom
                self.selected_student_status = new_status_key
                self.selected_student_grad_year = new_grad
                self.load_student_list(refresh_db=True)
                self.select_student_item(student_id, new_name, new_code, len(self.selected_student_thumb_paths or []), new_classroom, new_status_key, new_grad)
                
                # ซิงค์ไฟล์ JSON ดัชนีขึ้น Google Drive อัตโนมัติ
                def sync_drive():
                    try:
                        sync_data = self.db.get_all_sync_data()
                        json_folder_id = self.get_json_folder_id()
                        if json_folder_id:
                            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="students")
                            logger.info("[GDRIVE JSON] Updated JSON indexes after editing student.")
                    except Exception as err:
                        logger.error(f"[GDRIVE JSON] Error updating Drive JSON indexes after edit: {err}")

                threading.Thread(target=sync_drive, daemon=True).start()
                messagebox.showinfo("สำเร็จ", f"แก้ไขข้อมูลของ '{new_name}' สำเร็จเรียบร้อยแล้ว")
            else:
                messagebox.showerror("ข้อผิดพลาด", msg, parent=dialog)

        # ปุ่มบันทึก / ยกเลิก
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=25, pady=(15, 10))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        btn_cancel = ctk.CTkButton(btn_frame, text="ยกเลิก", height=36, fg_color="#7F8C8D", hover_color="#95A5A6", command=dialog.destroy)
        btn_cancel.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        btn_save = ctk.CTkButton(btn_frame, text="💾 บันทึกการแก้ไข", height=36, fg_color="#27AE60", hover_color="#229954", font=ctk.CTkFont(weight="bold"), command=save_edit)
        btn_save.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def delete_selected_student(self):
        if self.selected_student_id is None:
            return
        self.delete_selected_student_by_id(self.selected_student_id, self.selected_student_name)

    def delete_selected_student_by_id(self, student_id, student_name):
        confirm = messagebox.askyesno(
            "ยืนยันการลบนักเรียน",
            f"คุณต้องการลบรายชื่อและประวัติการตรวจพบทั้งหมดของ '{student_name}' ใช่หรือไม่?\n"
            f"การกระทำนี้จะล้างข้อมูลใน SQLite, Google Sheets และอัปเดตไฟล์ JSON บน Drive ทันที"
        )
        if not confirm:
            return

        def process_delete():
            try:
                logger.info(f"[SYSTEM] Starting deletion process for student: {student_name} (ID: {student_id})...")

                # 1. ลบจาก SQLite Local Database
                self.db.delete_staff_member(student_id)
                logger.info(f"[DATABASE] Removed student '{student_name}' and related embedding records from SQLite.")

                # ล้างประวัติใน student_sync_temp.json เพื่อให้ Task 2 ซิงค์ใหม่หากมีชื่อใน Sheet
                try:
                    from face_analyzer import get_project_root
                    temp_file = os.path.join(get_project_root(), "data", "student_sync_temp.json")
                    if os.path.exists(temp_file):
                        with open(temp_file, 'r', encoding='utf-8') as f:
                            t_data = json.load(f)
                        # ค้นหา student_id (รหัสนักเรียน) และลบออก
                        keys_to_del = [k for k, v in t_data.items() if v.get('name') == student_name]
                        for k in keys_to_del:
                            t_data.pop(k, None)
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(t_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"[CACHE] Removed '{student_name}' from student_sync_temp.json")
                except Exception as c_err:
                    logger.warning(f"[CACHE] Could not clean temp json: {c_err}")

                # 2. เชื่อมต่อ Google Sheets และอัปเดต Sheets + Excel + Drive JSON
                sheet_id = self.entry_sheets_id.get().strip()
                json_folder_id = self.entry_json_folder_id.get().strip()

                if sheet_id:
                    if self.sync_manager.connect(sheet_id):
                        sync_data = self.db.get_all_sync_data()

                        # อัปเดต Sheets (faces + photos)
                        logger.info("[GSHEETS] Syncing updated data to Google Sheets after student deletion...")
                        self.sync_manager.sync_to_google_sheet(sync_data)

                        # อัปเดต Local Excel
                        self.sync_manager.save_local_excel_mirror(sync_data)

                        # อัปเดตไฟล์ดัชนี JSON 2 ไฟล์หลัก บน Google Drive
                        if json_folder_id:
                            logger.info("[GDRIVE] Updating person_index.json & photo_index.json on Google Drive...")
                            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id)
                    else:
                        logger.error("[GSHEETS] Failed to connect to Google Sheets during deletion sync.")

                logger.info(f"[SYSTEM] Student deletion completed: {student_name}")

                # รีเฟรชหน้าจอ
                self.after(0, self.load_student_list)
                self.after(0, lambda: messagebox.showinfo("ลบสำเร็จ", f"ลบรายชื่อนักเรียน '{student_name}' และข้อมูลทั้งหมดเรียบร้อย"))
            except Exception as e:
                logger.error(f"Error deleting student: {e}")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการลบ: {e}"))

        threading.Thread(target=process_delete, daemon=True).start()

    def save_cropped_student_face(self, student_id, student_code, original_path, bbox, count, orig_filename=None):
        """ตัดและบันทึกใบหน้านักเรียนที่ตรวจพบ เป็นไฟล์ .jpg ลงโฟลเดอร์ registered_students"""
        try:
            img = read_image_file(original_path)
            if img is None:
                logger.warning(f"Could not read image: {original_path}")
                return original_path

            h, w = img.shape[:2]
            x1, y1, x2, y2 = bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            # ขยาย bounding box เล็กน้อย
            pad_x = int(0.15 * (x2 - x1))
            pad_y = int(0.15 * (y2 - y1))
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(w, x2 + pad_x)
            y2 = min(h, y2 + pad_y)

            cropped = img[y1:y2, x1:x2]

            student_face_dir = os.path.join(get_project_root(), "data", "registered_students")
            os.makedirs(student_face_dir, exist_ok=True)

            # ดึงชื่อไฟล์ดั้งเดิมมาฝังท้าย
            if orig_filename:
                orig_name = os.path.splitext(os.path.basename(orig_filename))[0]
            else:
                orig_name = os.path.splitext(os.path.basename(original_path))[0]
            orig_name_clean = "".join(c for c in orig_name if c.isalnum() or c in ('-', '_'))

            # ใช้ student_code (รหัสประจำตัว) แทน database id ใน naming
            student_filename = f"student_{student_code}_{int(time.time())}_{count}_{orig_name_clean}.jpg"
            student_path = os.path.join(student_face_dir, student_filename)

            # เขียนไฟล์ภาพ
            success, img_encoded = cv2.imencode('.jpg', cropped)
            if success:
                img_encoded.tofile(student_path)
                return student_path
        except Exception as e:
            logger.error(f"Error cropping and saving student face: {e}")
        return original_path # fallback

    def show_student_thumbnails(self, student_id):
        """แสดงรูปภาพย่อยของนักเรียนที่เลือกในรูปแบบตารางกริด (Grid) พร้อมระบบล้างขยะอัตโนมัติ"""
        self.selected_student_thumb_paths = set()
        if hasattr(self, 'btn_delete_student_photo'):
            self.btn_delete_student_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

        # ล้างข้อมูลเก่า
        for widget in self.student_thumbs_scrollable.winfo_children():
            widget.destroy()

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (student_id,))
        rows = cursor.fetchall()
        conn.close()

        # ลบ DB Record ขยะที่ไม่มีไฟล์จริงบนดิสก์ให้อัตโนมัติ (Auto-Clean Orphan DB Records)
        orphan_paths = [row[0] for row in rows if not os.path.exists(row[0])]
        if orphan_paths:
            try:
                conn = self.db.get_connection()
                cursor = conn.cursor()
                for p in orphan_paths:
                    cursor.execute("DELETE FROM staff_embeddings WHERE staff_id = ? AND image_path = ?", (student_id, p))
                conn.commit()
                conn.close()
                logger.info(f"Auto-cleaned {len(orphan_paths)} orphan DB face records for student ID {student_id}")
            except Exception as e:
                logger.error(f"Error auto-cleaning student orphan records: {e}")

        rows = [row for row in rows if os.path.exists(row[0])]
        logger.info(f"Student Registry: Loaded {len(rows)} templates thumbnails for student ID {student_id}")

        if not rows:
            lbl_empty = ctk.CTkLabel(self.student_thumbs_scrollable, text="ไม่มีรูปภาพใบหน้าในฐานข้อมูล", text_color="#A2B5CD", font=ctk.CTkFont(size=11))
            lbl_empty.pack(pady=15)
            return

        # กำหนดคอลัมน์กริดตาราง
        cols = 4
        for col_idx in range(cols):
            self.student_thumbs_scrollable.grid_columnconfigure(col_idx, weight=1)

        for idx, row in enumerate(rows):
            path = row[0]
            r_idx = idx // cols
            c_idx = idx % cols

            if os.path.exists(path):
                try:
                    pil_img = Image.open(path).convert("RGB")
                    pil_img = pil_img.resize((70, 70), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=pil_img, size=(70, 70))

                    frame_border = ctk.CTkFrame(self.student_thumbs_scrollable, width=80, height=80, fg_color="transparent", border_width=0)
                    frame_border.grid(row=r_idx, column=c_idx, padx=5, pady=5)
                    frame_border.grid_propagate(False)

                    lbl_thumb = ctk.CTkLabel(frame_border, image=ctk_img, text="")
                    lbl_thumb.pack(padx=2, pady=2, expand=True, fill="both")

                    lbl_thumb.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_student_thumbnail(p, w))
                    frame_border.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_student_thumbnail(p, w))
                except Exception as e:
                    logger.error(f"Error reading student image: {e}")
                    self.show_student_fallback_thumbnail(r_idx, c_idx, path)
            else:
                self.show_student_fallback_thumbnail(r_idx, c_idx, path)

    def show_student_fallback_thumbnail(self, r_idx, c_idx, path):
        frame_border = ctk.CTkFrame(self.student_thumbs_scrollable, width=80, height=80, fg_color="transparent", border_width=0)
        frame_border.grid(row=r_idx, column=c_idx, padx=5, pady=5)
        frame_border.grid_propagate(False)

        lbl_fallback = ctk.CTkLabel(
            frame_border, text="X",
            fg_color="#1C2D42", text_color="#E74C3C",
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=6
        )
        lbl_fallback.pack(padx=2, pady=2, expand=True, fill="both")
        
        lbl_fallback.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_student_thumbnail(p, w))
        frame_border.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_student_thumbnail(p, w))

    def select_student_thumbnail(self, path, widget):
        """เลือก/ยกเลิกการเลือกรูปภาพย่อยของนักเรียน (Multi-Select)"""
        if not hasattr(self, 'selected_student_thumb_paths'):
            self.selected_student_thumb_paths = set()

        if path in self.selected_student_thumb_paths:
            self.selected_student_thumb_paths.remove(path)
            try:
                widget.configure(fg_color="transparent", border_width=0, border_color="transparent")
            except Exception:
                pass
        else:
            self.selected_student_thumb_paths.add(path)
            try:
                widget.configure(fg_color="transparent", border_width=3, border_color="#FF5252")
            except Exception:
                pass

        count = len(self.selected_student_thumb_paths)
        if hasattr(self, 'btn_delete_student_photo'):
            if count > 0:
                self.btn_delete_student_photo.configure(state="normal", text=f"❌ ลบรูปภาพที่เลือก ({count} รูป)")
            else:
                self.btn_delete_student_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

    def delete_selected_student_photo(self):
        """ลบรูปภาพใบหน้านักเรียนที่เลือกทั้งหมด (Bulk Delete)"""
        if not hasattr(self, 'selected_student_thumb_paths') or not self.selected_student_thumb_paths or not self.selected_student_id:
            return

        count = len(self.selected_student_thumb_paths)
        confirm = messagebox.askyesno(
            "ยืนยันการลบรูปภาพ",
            f"คุณต้องการลบรูปภาพใบหน้าที่เลือกจำนวน {count} รูปภาพ ใช่หรือไม่?"
        )
        if not confirm:
            return

        try:
            paths_to_delete = list(self.selected_student_thumb_paths)
            conn = self.db.get_connection()
            cursor = conn.cursor()
            for p in paths_to_delete:
                cursor.execute("DELETE FROM staff_embeddings WHERE image_path = ? AND staff_id = ?",
                              (p, self.selected_student_id))
            conn.commit()
            conn.close()

            deleted_files = 0
            for p in paths_to_delete:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        deleted_files += 1
                    except Exception as fe:
                        logger.error(f"Failed to delete file {p}: {fe}")

            logger.info(f"Deleted {count} student photos from DB ({deleted_files} files from disk)")

            self.selected_student_thumb_paths = set()
            if hasattr(self, 'btn_delete_student_photo'):
                self.btn_delete_student_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

            self.show_student_thumbnails(self.selected_student_id)
            self.load_student_list()

            messagebox.showinfo("ลบสำเร็จ", f"ลบรูปภาพใบหน้าจำนวน {count} รูป เรียบร้อยแล้ว")
        except Exception as e:
            logger.error(f"Error deleting student photo: {e}")
            messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการลบรูป: {e}")

    def open_student_lifecycle_dialog(self):
        """เปิด Dialog จัดการวงจรชีวิตนักเรียน (เลื่อนชั้น / บันทึกจบการศึกษา) (v6.29)"""
        StudentLifecycleDialog(self)

    def open_sheets_import_dialog(self):
        """เปิด Dialog ตั้งค่าการนำเข้าจาก Google Sheets"""
        SheetsImportDialog(self, callback=self.batch_import_from_sheets)

    def batch_import_from_sheets(self, settings):
        """นำเข้านักเรียนจาก Google Sheets พร้อมตรวจสอบข้อมูลเดิมและการผูกห้องเรียน (v6.29)"""
        def process_import():
            try:
                sheet_id = settings["sheet_id"]

                # เชื่อมต่อ Google Sheets
                if not self.sync_manager.connected:
                    if not self.sync_manager.connect():
                        self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเชื่อมต่อ Google API ได้"))
                        return

                # อ่านข้อมูลจาก Sheets
                sheet_data = self.sync_manager.read_sheet_data(sheet_id)
                if not sheet_data or len(sheet_data) < 2:
                    self.after(0, lambda: messagebox.showwarning("ไม่พบข้อมูล", "Sheet ไม่มีข้อมูลหรือมีเฉพาะหัวคอลัมน์"))
                    return

                # แปลงตัวอักษรคอลัมน์เป็นตัวเลข (0-based)
                col_map = {
                    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7,
                    "I": 8, "J": 9, "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15
                }
                col_id = col_map.get(settings["col_id"], 0)
                col_name = col_map.get(settings["col_name"], 1)
                col_class_char = settings.get("col_class")
                col_class = col_map.get(col_class_char, None) if col_class_char and col_class_char != "- ไม่ระบุ -" else None
                col_img1 = col_map.get(settings["col_img1"], 3)
                col_img2 = col_map.get(settings["col_img2"], 4)
                col_img3 = col_map.get(settings["col_img3"], 5)

                # ข้ามแถวหัวคอลัมน์
                data_rows = sheet_data[1:]

                # จัดกลุ่มข้อมูลตาม รหัส + ชื่อ + รวบรวม URL ภาพทั้งหมด
                student_dict = {}
                for row in data_rows:
                    if len(row) <= max(col_id, col_name):
                        continue

                    student_code = row[col_id].strip() if col_id < len(row) else ""
                    student_name = row[col_name].strip() if col_name < len(row) else ""
                    student_classroom = row[col_class].strip() if col_class is not None and col_class < len(row) else ""

                    if not student_code or not student_name:
                        continue

                    # รวบรวม URL ภาพใบหน้าตรงสูงสุด 2 ภาพสำหรับนักเรียน (v3.4 Dual-Frontal Standard)
                    photo_urls = []
                    for col_idx in [col_img1, col_img2]:
                        url = row[col_idx].strip() if col_idx < len(row) else ""
                        if url and url != "-":
                            photo_urls.append((chr(65 + col_idx), url))

                    if not photo_urls:
                        continue

                    key = (student_code, student_name)
                    if key not in student_dict:
                        student_dict[key] = {"photos": photo_urls, "classroom": student_classroom}
                    elif student_classroom and not student_dict[key].get("classroom"):
                        student_dict[key]["classroom"] = student_classroom

                logger.info(f"Found {len(student_dict)} students from sheet")

                # เริ่มต้น Face Analyzer
                analyzer = FaceAnalyzer(use_gpu=False)
                if not analyzer.initialize():
                    self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเริ่มต้น FaceAnalyzer ได้"))
                    return

                # เก็บผลลัพธ์
                registered_list = []   # บันทึกใหม่
                updated_list = []      # เพิ่มภาพเติม
                failed_list = []       # ล้มเหลว
                skipped_list = []      # ข้ามรูปซ้ำ

                for (student_code, student_name), data in student_dict.items():
                    try:
                        # ตรวจสอบว่ามีข้อมูลอยู่แล้วหรือไม่
                        existing = self.db.find_student_by_code_and_name(student_code, student_name)
                        st_classroom = data.get("classroom", "")

                        if existing is None:
                            # กรณีที่ 1: ไม่มีข้อมูล → บันทึกใหม่พร้อมห้องเรียนและสถานะ active
                            student_id = self.db.register_member(student_name, role='student', student_id=student_code, class_room=st_classroom, status='active')
                            is_new = True
                            logger.info(f"New student: {student_name} (ID: {student_code}, Room: {st_classroom}, DB ID: {student_id})")
                        else:
                            # กรณีที่ 2-3: มีข้อมูลอยู่แล้ว → ใช้ ID เดิมและอัปเดตสถานะเป็น active พร้อมห้องใหม่
                            student_id = existing["id"]
                            is_new = False
                            if st_classroom:
                                self.db.update_student_info(student_id, student_name, student_code, status='active', class_room=st_classroom)
                            else:
                                self.db.update_student_info(student_id, student_name, student_code, status='active')
                            logger.info(f"Existing student: {student_name} (ID: {student_code}, Room: {st_classroom}, DB ID: {student_id})")

                        if not student_id:
                            logger.error(f"Cannot resolve DB student_id for {student_name} (Student Code: {student_code})")
                            failed_list.append(f"{student_code} - {student_name} (DB ID Error)")
                            continue

                        # นับจำนวนภาพเก่า
                        old_photo_count = self.db.get_student_photo_count(student_id)

                        # ประมวลผลภาพทั้งหมด
                        success_count = 0
                        skipped_count = 0
                        for col_char, raw_url in data["photos"]:
                            url = raw_url.strip() if raw_url else ""
                            if not url:
                                continue
                            try:
                                # เช็คว่าลิงค์นี้บันทึกไปแล้วหรือยัง (v1.7.2 Fix 2)
                                if self.db.check_embedding_url_exists(student_id, url):
                                    logger.info(f"Skipped duplicate URL from column {col_char} for {student_name}")
                                    skipped_count += 1
                                    skipped_list.append(f"{student_code} - {student_name} (คอลัมน์ {col_char})")
                                    continue

                                # ดาวน์โหลดรูปจาก Drive URL
                                temp_dir = os.path.join(get_project_root(), "data", "temp")
                                os.makedirs(temp_dir, exist_ok=True)
                                temp_path = os.path.join(temp_dir, f"temp_{student_code}_{col_char}.jpg")

                                image_bytes = self.sync_manager.download_image_from_url(url)
                                if not image_bytes:
                                    logger.warning(f"Failed to download image from column {col_char} for {student_name}")
                                    continue

                                # บันทึก bytes เป็นไฟล์ชั่วคราว
                                with open(temp_path, 'wb') as f:
                                    f.write(image_bytes)

                                # ตรวจจับใบหน้า
                                faces = analyzer.detect_and_extract_faces(temp_path)

                                if len(faces) == 0:
                                    logger.warning(f"No face detected in column {col_char} for {student_name}")
                                    continue
                                elif len(faces) > 1:
                                    logger.warning(f"Multiple faces ({len(faces)}) in column {col_char} for {student_name} - using largest")
                                    face = max(faces, key=lambda f: (f["bbox"][2]-f["bbox"][0]) * (f["bbox"][3]-f["bbox"][1]))
                                else:
                                    face = faces[0]

                                # บันทึกใบหน้า พร้อม source_url (v1.7.2 Fix 2)
                                face_path = self.save_cropped_student_face(student_id, student_code, temp_path, face["bbox"], success_count)
                                self.db.add_staff_embedding(student_id, face_path, face["embedding"], source_url=url)
                                success_count += 1
                                logger.info(f"Registered face from column {col_char} for {student_name}")

                                # ลบไฟล์ชั่วคราว
                                try:
                                    os.remove(temp_path)
                                except:
                                    pass

                            except Exception as e:
                                logger.error(f"Error processing column {col_char} for {student_name}: {e}")

                        if success_count > 0:
                            if is_new:
                                registered_list.append(f"{student_code} - {student_name} (+{success_count} รูป)")
                            else:
                                updated_list.append(f"{student_code} - {student_name} ({old_photo_count}→{old_photo_count + success_count} รูป)")
                        elif skipped_count == len(data["photos"]):
                            # กรณีทุกรูปซ้ำหมด
                            failed_list.append(f"{student_code} - {student_name} (รูปทั้งหมดซ้ำ)")
                        else:
                            failed_list.append(f"{student_code} - {student_name} (ไม่พบใบหน้า)")

                    except Exception as e:
                        logger.error(f"Error processing student {student_name}: {e}")
                        failed_list.append(f"{student_code} - {student_name} (Error: {e})")

                logger.info(f"Batch import completed: {len(registered_list)} new, {len(updated_list)} updated, {len(failed_list)} failed, {len(skipped_list)} skipped")

                # รีเฟรชและแจ้งผล
                self.after(0, self.load_student_list)
                self.after(0, lambda: self.show_import_summary(registered_list, updated_list, failed_list, skipped_list))

            except Exception as e:
                logger.error(f"Batch import from sheets failed: {e}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาด: {e}"))

        threading.Thread(target=process_import, daemon=True).start()

    def show_import_summary(self, registered_list, updated_list, failed_list, skipped_list=None):
        """แสดง Popup สรุปผลการนำเข้านักเรียน"""
        if skipped_list is None:
            skipped_list = []

        dialog = ctk.CTkToplevel(self)
        dialog.title("สรุปผลการนำเข้านักเรียน")
        dialog.geometry("600x500")
        dialog.transient(self)
        dialog.grab_set()

        # Frame หลัก
        main_frame = ctk.CTkFrame(dialog, fg_color="#101B2B")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # หัวข้อ
        ctk.CTkLabel(main_frame, text="สรุปผลการนำเข้านักเรียนจาก Google Sheets",
                   font=ctk.CTkFont(size=16, weight="bold"), text_color="white").pack(pady=(0, 15))

        # สถิติ
        stats_frame = ctk.CTkFrame(main_frame, fg_color="#1C2D42")
        stats_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(stats_frame, text=f"✅ บันทึกใหม่: {len(registered_list)} คน",
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="#27AE60").pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(stats_frame, text=f"📝 เพิ่มภาพเติม: {len(updated_list)} คน",
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="#F39C12").pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(stats_frame, text=f"❌ ล้มเหลว: {len(failed_list)} คน",
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="#E74C3C").pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(stats_frame, text=f"⏭️ ข้ามรูปซ้ำ: {len(skipped_list)} รูป",
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="#95A5A6").pack(side="left", padx=20, pady=10)

        # รายละเอียด (Scrollable)
        detail_frame = ctk.CTkFrame(main_frame, fg_color="#0A111A")
        detail_frame.pack(fill="both", expand=True)

        import tkinter as tk
        detail_text = tk.Text(detail_frame, bg="#0A111A", fg="#2ECC71",
                              font=("Consolas", 10), borderwidth=0, highlightthickness=0,
                              wrap="word", state="disabled")
        detail_text.pack(fill="both", expand=True, padx=5, pady=5)

        scrollbar = ctk.CTkScrollbar(detail_frame, command=detail_text.yview)
        scrollbar.pack(side="right", fill="y")
        detail_text.configure(yscrollcommand=scrollbar.set)

        # เติมข้อมูล
        detail_text.config(state="normal")
        if registered_list:
            detail_text.insert("end", "═══ บันทึกใหม่ ═══\n", "header")
            detail_text.tag_configure("header", foreground="#27AE60", font=("Consolas", 10, "bold"))
            for item in registered_list:
                detail_text.insert("end", f"• {item}\n")
            detail_text.insert("end", "\n")

        if updated_list:
            detail_text.insert("end", "═══ เพิ่มภาพเติม ═══\n", "header2")
            detail_text.tag_configure("header2", foreground="#F39C12", font=("Consolas", 10, "bold"))
            for item in updated_list:
                detail_text.insert("end", f"• {item}\n")
            detail_text.insert("end", "\n")

        if skipped_list:
            detail_text.insert("end", "═══ ข้ามรูปซ้ำ ═══\n", "header4")
            detail_text.tag_configure("header4", foreground="#95A5A6", font=("Consolas", 10, "bold"))
            for item in skipped_list:
                detail_text.insert("end", f"• {item}\n")
            detail_text.insert("end", "\n")

        if failed_list:
            detail_text.insert("end", "═══ ล้มเหลว ═══\n", "header3")
            detail_text.tag_configure("header3", foreground="#E74C3C", font=("Consolas", 10, "bold"))
            for item in failed_list:
                detail_text.insert("end", f"• {item}\n")

        detail_text.config(state="disabled")

        # ปุ่มปิด
        ctk.CTkButton(main_frame, text="ปิด", width=100, fg_color="#3498DB",
                     hover_color="#2980B9", command=dialog.destroy).pack(pady=(15, 0))

    def show_scan_report_popup(self, report_data, saved_path):
        """
        แสดง Popup สรุปผลรายงานรอบการสแกนภาพถ่าย (Scan Session Summary Report v6.24)
        ประกอบด้วย 4 KPI Cards, รายชื่อโฟลเดอร์, Top 10 บุคคลที่พบมากสุด, รายการภาพที่มีปัญหา และรายงานฉบับเต็ม
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("📊 สรุปผลรอบการสแกนภาพถ่าย (Scan Session Summary Report) v6.24")
        dialog.geometry("960x720")
        dialog.minsize(880, 620)
        dialog.transient(self)
        dialog.after(100, lambda: dialog.focus())

        # Main background container
        main_frame = ctk.CTkFrame(dialog, fg_color="#0A111A")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # 1. Header Frame
        header_frame = ctk.CTkFrame(main_frame, fg_color="#101B2B", corner_radius=8)
        header_frame.pack(fill="x", padx=10, pady=(10, 10))

        title_lbl = ctk.CTkLabel(
            header_frame, 
            text="📊 สรุปผลรอบการสแกนภาพถ่ายกิจกรรม (Scan Session Report)",
            font=ctk.CTkFont(size=18, weight="bold"), 
            text_color="#6CA6CD"
        )
        title_lbl.pack(anchor="w", padx=15, pady=(10, 4))

        sub_info = f"ช่วงเวลา: {report_data.get('start_time_str', '-')} ถึง {report_data.get('end_time_str', '-')}  |  ใช้เวลา: {report_data.get('duration_str', '-')}"
        sub_lbl = ctk.CTkLabel(
            header_frame, 
            text=sub_info,
            font=ctk.CTkFont(size=12), 
            text_color="#AAB7B8"
        )
        sub_lbl.pack(anchor="w", padx=15, pady=(0, 8))

        badges_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        badges_frame.pack(fill="x", padx=15, pady=(0, 10))

        # Status badge
        is_stopped = report_data.get("stopped_by_user", False)
        status_text = "🛑 หยุดทำงานตามคำร้องขอ (Stop Requested)" if is_stopped else "✅ สแกนเสร็จสิ้นสมบูรณ์ (Completed)"
        status_color = "#C0392B" if is_stopped else "#27AE60"
        ctk.CTkLabel(
            badges_frame, text=status_text,
            fg_color=status_color, text_color="white", corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"), padx=10, pady=3
        ).pack(side="left", padx=(0, 10))

        # Drive JSON badge
        is_synced = report_data.get("json_sync_completed", True)
        sync_text = "✅ อัปเดต Drive JSON สำเร็จ" if is_synced else "⚠️ ยังไม่ได้อัปเดต Drive JSON"
        sync_color = "#2980B9" if is_synced else "#E67E22"
        ctk.CTkLabel(
            badges_frame, text=sync_text,
            fg_color=sync_color, text_color="white", corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"), padx=10, pady=3
        ).pack(side="left", padx=(0, 10))

        # Saved Path badge
        if saved_path:
            filename = os.path.basename(saved_path)
            ctk.CTkLabel(
                badges_frame, text=f"💾 เซฟแล้ว: {filename}",
                fg_color="#1F3A60", text_color="#E0E6ED", corner_radius=6,
                font=ctk.CTkFont(size=11), padx=10, pady=3
            ).pack(side="left")

        # 2. KPI Cards Frame (4 Cards)
        kpi_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        kpi_frame.pack(fill="x", padx=10, pady=(0, 10))
        for col in range(4):
            kpi_frame.grid_columnconfigure(col, weight=1)

        kpis = [
            ("📁 โฟลเดอร์ที่สแกน", f"{report_data.get('total_folders', 0):,} โฟลเดอร์", "#3498DB", "#17263C"),
            ("📸 ภาพประมวลผลทั้งหมด", f"{report_data.get('total_all_images', 0):,} ภาพ\n(AI: {report_data.get('total_ai_photos', 0):,} | RAW: {report_data.get('total_raw_photos', 0):,} | ข้าม: {report_data.get('total_skipped_photos', 0):,})", "#2ECC71", "#17263C"),
            ("👤 ใบหน้าที่ตรวจพบ", f"{report_data.get('total_faces_detected', 0):,} ใบหน้า", "#F1C40F", "#17263C"),
            ("🎯 แมตช์บุคคลสะสม", f"{report_data.get('total_matched_appearances', 0):,} ครั้ง", "#E67E22", "#17263C")
        ]

        for idx, (title, value, accent_color, bg_card) in enumerate(kpis):
            card = ctk.CTkFrame(kpi_frame, fg_color=bg_card, corner_radius=8, border_width=1, border_color="#20334F")
            card.grid(row=0, column=idx, padx=4, sticky="nsew")
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=accent_color).pack(padx=8, pady=(8, 2))
            ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=13, weight="bold"), text_color="white", justify="center").pack(padx=8, pady=(0, 8))

        # 3. Tabview Frame
        tabview = ctk.CTkTabview(main_frame, fg_color="#101B2B", segmented_button_selected_color="#1F3A60")
        tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tab_folders = tabview.add(f"📁 รายชื่อโฟลเดอร์ ({report_data.get('total_folders', 0)})")
        tab_top10 = tabview.add("🏆 Top 10 บุคคลที่พบมากสุด")
        tab_issues = tabview.add(f"⚠️ ภาพที่มีปัญหา/ข้าม ({len(report_data.get('skipped_files', []))})")
        tab_markdown = tabview.add("📝 สรุปรายงานเต็ม (Markdown)")

        # Populate Tab 1: Folders Breakdown
        scr_folders = ctk.CTkScrollableFrame(tab_folders, fg_color="#0A111A")
        scr_folders.pack(fill="both", expand=True, padx=5, pady=5)
        
        folders_dict = report_data.get("folders_breakdown", {})
        if folders_dict:
            # Table Header
            hdr_f = ctk.CTkFrame(scr_folders, fg_color="#1F3A60", corner_radius=4)
            hdr_f.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(hdr_f, text="ลำดับ", width=40, font=ctk.CTkFont(size=11, weight="bold"), text_color="white").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="ชื่อโฟลเดอร์ / กิจกรรม", font=ctk.CTkFont(size=11, weight="bold"), text_color="white", anchor="w").pack(side="left", fill="x", expand=True, padx=4)
            ctk.CTkLabel(hdr_f, text="ปีการศึกษา", width=70, font=ctk.CTkFont(size=11, weight="bold"), text_color="white").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="AI สแกน", width=65, font=ctk.CTkFont(size=11, weight="bold"), text_color="#2ECC71").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="RAW", width=55, font=ctk.CTkFont(size=11, weight="bold"), text_color="#3498DB").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="ข้าม/ปัญหา", width=65, font=ctk.CTkFont(size=11, weight="bold"), text_color="#E74C3C").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="รวม", width=55, font=ctk.CTkFont(size=11, weight="bold"), text_color="white").pack(side="left", padx=4)
            ctk.CTkLabel(hdr_f, text="สถานะ", width=120, font=ctk.CTkFont(size=11, weight="bold"), text_color="white").pack(side="left", padx=4)

            for f_idx, (f_name, f_info) in enumerate(folders_dict.items(), start=1):
                row_f = ctk.CTkFrame(scr_folders, fg_color="#142236" if f_idx % 2 == 0 else "#101B2B", corner_radius=4)
                row_f.pack(fill="x", pady=2)
                tot = f_info.get("ai_count", 0) + f_info.get("raw_count", 0) + f_info.get("skipped_count", 0)
                status_f = f_info.get("status", "-")
                status_color = "#2ECC71" if "เสร็จสมบูรณ์" in status_f else "#F39C12"

                ctk.CTkLabel(row_f, text=str(f_idx), width=40, font=ctk.CTkFont(size=11)).pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=f_name, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", fill="x", expand=True, padx=4)
                ctk.CTkLabel(row_f, text=str(f_info.get("year", "-")), width=70, font=ctk.CTkFont(size=11), text_color="#95A5A6").pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=str(f_info.get("ai_count", 0)), width=65, font=ctk.CTkFont(size=11), text_color="#2ECC71").pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=str(f_info.get("raw_count", 0)), width=55, font=ctk.CTkFont(size=11), text_color="#3498DB").pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=str(f_info.get("skipped_count", 0)), width=65, font=ctk.CTkFont(size=11), text_color="#E74C3C").pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=str(tot), width=55, font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=4)
                ctk.CTkLabel(row_f, text=status_f, width=120, font=ctk.CTkFont(size=11, weight="bold"), text_color=status_color).pack(side="left", padx=4)
        else:
            ctk.CTkLabel(scr_folders, text="ℹ️ ไม่พบข้อมูลโฟลเดอร์ที่มีการสแกนในรอบนี้", font=ctk.CTkFont(size=13), text_color="#7F8C8D").pack(pady=40)

        # Populate Tab 2: Top 10 People
        scr_top10 = ctk.CTkScrollableFrame(tab_top10, fg_color="#0A111A")
        scr_top10.pack(fill="both", expand=True, padx=5, pady=5)
        top10_list = report_data.get("top_10_people", [])
        if top10_list:
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            for idx, p in enumerate(top10_list):
                row_p = ctk.CTkFrame(scr_top10, fg_color="#142236" if idx % 2 == 0 else "#101B2B", corner_radius=6)
                row_p.pack(fill="x", pady=3, padx=10)
                medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
                ctk.CTkLabel(row_p, text=medal, width=45, font=ctk.CTkFont(size=16)).pack(side="left", padx=10, pady=8)
                ctk.CTkLabel(row_p, text=p.get("name", "Unknown"), font=ctk.CTkFont(size=13, weight="bold"), text_color="white", anchor="w").pack(side="left", fill="x", expand=True, padx=5)
                ctk.CTkLabel(row_p, text=f"ปรากฏ {p.get('count', 0):,} ภาพ", font=ctk.CTkFont(size=12, weight="bold"), text_color="#2ECC71").pack(side="right", padx=15)
        else:
            ctk.CTkLabel(scr_top10, text="ℹ️ ไม่พบบุคคลที่จับคู่ได้ในรอบการสแกนนี้", font=ctk.CTkFont(size=13), text_color="#7F8C8D").pack(pady=40)

        # Populate Tab 3: Skipped / Error files
        scr_issues = ctk.CTkScrollableFrame(tab_issues, fg_color="#0A111A")
        scr_issues.pack(fill="both", expand=True, padx=5, pady=5)
        skipped_list = report_data.get("skipped_files", [])
        if skipped_list:
            for idx, item in enumerate(skipped_list, start=1):
                row_iss = ctk.CTkFrame(scr_issues, fg_color="#1C1824", corner_radius=6, border_width=1, border_color="#C0392B")
                row_iss.pack(fill="x", pady=4, padx=5)
                top_line = ctk.CTkFrame(row_iss, fg_color="transparent")
                top_line.pack(fill="x", padx=10, pady=(6, 2))
                ctk.CTkLabel(top_line, text=f"#{idx} [{item.get('folder', '-')}]", font=ctk.CTkFont(size=11, weight="bold"), text_color="#E74C3C").pack(side="left")
                ctk.CTkLabel(top_line, text=item.get("file_name", "-"), font=ctk.CTkFont(size=11, weight="bold"), text_color="white").pack(side="left", padx=10)
                
                drive_lnk = item.get("drive_link", "")
                if drive_lnk:
                    ctk.CTkButton(
                        top_line, text="🔗 ดูบน Drive", width=90, height=22, font=ctk.CTkFont(size=10),
                        fg_color="#1F3A60", hover_color="#20334F",
                        command=lambda u=drive_lnk: webbrowser.open(u)
                    ).pack(side="right")

                reason_lbl = ctk.CTkLabel(
                    row_iss, text=f"สาเหตุ: {item.get('reason', '-')}",
                    font=ctk.CTkFont(size=11), text_color="#E08277", anchor="w"
                )
                reason_lbl.pack(fill="x", padx=10, pady=(0, 6))
        else:
            ctk.CTkLabel(
                scr_issues, text="✅ ไม่พบภาพที่มีปัญหาในรอบการสแกนนี้ (ประมวลผลสมบูรณ์ 100%)",
                font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ECC71"
            ).pack(pady=40)

        # Populate Tab 4: Markdown Text
        from scheduler_task import ScanSessionTracker
        tracker_tmp = ScanSessionTracker()
        md_text = tracker_tmp.generate_markdown(report_data)

        txt_md = ctk.CTkTextbox(tab_markdown, fg_color="#0A111A", text_color="#2ECC71", font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        txt_md.pack(fill="both", expand=True, padx=5, pady=5)
        txt_md.insert("1.0", md_text)
        txt_md.configure(state="disabled")

        # 4. Bottom Action Bar
        action_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        action_frame.pack(fill="x", padx=10, pady=(0, 5))

        def open_folder():
            target_folder = os.path.dirname(saved_path) if saved_path else os.path.join(get_project_root(), "report_summary")
            if os.path.exists(target_folder):
                try:
                    os.startfile(os.path.abspath(target_folder))
                except Exception as err:
                    logger.error(f"Cannot open folder: {err}")

        def copy_markdown():
            try:
                dialog.clipboard_clear()
                dialog.clipboard_append(md_text)
                btn_copy.configure(text="✅ คัดลอกสำเร็จแล้ว!")
                dialog.after(2000, lambda: btn_copy.configure(text="📋 คัดลอก Markdown"))
            except Exception as e:
                logger.error(f"Copy error: {e}")

        btn_open = ctk.CTkButton(
            action_frame, text="📂 เปิดโฟลเดอร์เก็บรายงาน",
            fg_color="#1F3A60", hover_color="#20334F", font=ctk.CTkFont(size=12, weight="bold"),
            command=open_folder
        )
        btn_open.pack(side="left", padx=(0, 10))

        btn_copy = ctk.CTkButton(
            action_frame, text="📋 คัดลอก Markdown",
            fg_color="#8E44AD", hover_color="#9B59B6", font=ctk.CTkFont(size=12, weight="bold"),
            command=copy_markdown
        )
        btn_copy.pack(side="left", padx=(0, 10))

        btn_close = ctk.CTkButton(
            action_frame, text="❌ ปิดหน้าต่าง", width=100,
            fg_color="#34495E", hover_color="#2C3E50", font=ctk.CTkFont(size=12),
            command=dialog.destroy
        )
        btn_close.pack(side="right")

    def sort_teacher_table(self, col_key):
        """จัดเรียงตารางคุณครูตามคอลัมน์ที่เลือก (v6.34)"""
        if self.teacher_sort_col == col_key:
            self.teacher_sort_desc = not self.teacher_sort_desc
        else:
            self.teacher_sort_col = col_key
            self.teacher_sort_desc = False
        self.load_staff_list(refresh_db=False)

    def on_teacher_tree_select(self, event=None):
        """Handler เมื่อผู้ใช้คลิกเลือกแถวในตาราง Treeview ของคุณครู (v6.34)"""
        if not hasattr(self, 'teacher_tree'):
            return
        selected = self.teacher_tree.selection()
        if not selected:
            return
        item = selected[0]
        vals = self.teacher_tree.item(item, "values")
        if not vals or len(vals) < 4:
            return
        try:
            staff_id = int(vals[0])
        except (ValueError, TypeError):
            return
        staff_name = str(vals[1])
        dept = str(vals[2])
        try:
            photo_count = int(vals[3])
        except (ValueError, TypeError):
            photo_count = 0
        self.select_staff_item(staff_id, staff_name, photo_count, dept)

    def on_dept_add_option_selected(self, val):
        """Handler เมื่อเลือกตัวเลือกสังกัดในฟอร์มเพิ่มครูใหม่ (v6.34)"""
        if not hasattr(self, 'entry_staff_department'):
            return
        if val == "(เลือกสังกัด)":
            self.entry_staff_department.delete(0, "end")
        elif val == "อื่นๆ (ระบุเอง)":
            self.entry_staff_department.delete(0, "end")
            self.entry_staff_department.focus_set()
        else:
            self.entry_staff_department.delete(0, "end")
            self.entry_staff_department.insert(0, val)

    def load_staff_list(self, refresh_db=True):
        """โหลดรายชื่อคุณครู แสดงผลในตาราง Treeview พร้อมรองรับการเรียงลำดับและตัวกรองสังกัด (v6.34)"""
        if hasattr(self, 'teacher_tree'):
            self.teacher_tree.delete(*self.teacher_tree.get_children())
            
        self.staff_buttons = {}
        self.selected_staff_id = None
        self.selected_staff_name = None
        self.selected_staff_department = ""
        self.btn_upload_photo.configure(state="disabled")
        self.btn_delete_staff.configure(state="disabled")
        if hasattr(self, 'btn_edit_staff'):
            self.btn_edit_staff.configure(state="disabled")
        self.lbl_selected_info.configure(text="กรุณาเลือกคุณครูจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ")
        self.lbl_photo_count_detail.configure(text="")

        search_term = ""
        if hasattr(self, 'entry_staff_search'):
            search_term = self.entry_staff_search.get().strip().lower()

        dept_filter = "ทั้งหมด (ทุกสังกัด)"
        if hasattr(self, 'option_teacher_dept_filter'):
            dept_filter = self.option_teacher_dept_filter.get()

        if refresh_db or getattr(self, '_cached_teachers_list', None) is None:
            self._cached_teachers_list = self.db.get_all_teachers()
        all_staff = self._cached_teachers_list or []

        # 1. กรองข้อมูลตามคำค้นหาและตัวกรองสังกัด
        filtered_staff = []
        for s in all_staff:
            sid_str = str(s.get('id', ''))
            sname = s.get('name', '') or ''
            dep = clean_department_name(s.get('department', '') or '')
            
            # กรองสังกัด
            if dept_filter != "ทั้งหมด (ทุกสังกัด)" and dep != dept_filter:
                continue
                
            # กรองคำค้นหา
            if search_term:
                if (search_term not in sid_str.lower() and 
                    search_term not in sname.lower() and 
                    search_term not in dep.lower()):
                    continue
                    
            filtered_staff.append({
                "id": s.get('id', 0),
                "name": sname,
                "department": dep,
                "photo_count": s.get('photo_count', 0),
                "status": s.get('status', 'active')
            })

        # 2. จัดเรียงข้อมูลตามคอลัมน์ที่เลือก
        sort_col = getattr(self, 'teacher_sort_col', 'id')
        sort_desc = getattr(self, 'teacher_sort_desc', False)

        if sort_col == "id":
            sort_key = lambda x: int(x.get('id', 0))
        elif sort_col == "name":
            sort_key = lambda x: x.get('name', '').lower()
        elif sort_col == "department":
            sort_key = lambda x: x.get('department', '').lower()
        elif sort_col == "photos":
            sort_key = lambda x: int(x.get('photo_count', 0))
        else:
            sort_key = lambda x: int(x.get('id', 0))

        sorted_staff = sorted(filtered_staff, key=sort_key, reverse=sort_desc)

        # 3. อัปเดตหัวตารางพร้อมสัญลักษณ์ ▲ / ▼
        if hasattr(self, 'teacher_tree'):
            headings = {
                "id": "ID",
                "name": "ชื่อ-นามสกุล",
                "department": "สังกัด",
                "photos": "รูป"
            }
            for col_id, col_name in headings.items():
                indicator = ""
                if sort_col == col_id:
                    indicator = " ▼" if sort_desc else " ▲"
                self.teacher_tree.heading(col_id, text=f"{col_name}{indicator}", command=lambda c=col_id: self.sort_teacher_table(c))

            # 4. บันทึกแถวลง Treeview
            for s in sorted_staff:
                sid = s['id']
                sname = s['name']
                sdep = s['department']
                scnt = s['photo_count']
                self.teacher_tree.insert("", "end", iid=str(sid), values=(sid, sname, sdep, scnt))

    def filter_staff_list(self, event=None, immediate=False):
        if getattr(self, "_staff_search_timer", None) is not None:
            try:
                self.after_cancel(self._staff_search_timer)
            except Exception:
                pass
            self._staff_search_timer = None
        if immediate:
            self.load_staff_list(refresh_db=False)
        else:
            self._staff_search_timer = self.after(250, lambda: self.load_staff_list(refresh_db=False))

    def clear_staff_search(self):
        if getattr(self, "_staff_search_timer", None) is not None:
            try:
                self.after_cancel(self._staff_search_timer)
            except Exception:
                pass
            self._staff_search_timer = None
        if hasattr(self, 'entry_staff_search'):
            self.entry_staff_search.delete(0, "end")
        if hasattr(self, 'option_teacher_dept_filter'):
            self.option_teacher_dept_filter.set("ทั้งหมด (ทุกสังกัด)")
        self.load_staff_list(refresh_db=False)

    def select_staff_item(self, staff_id, staff_name, photo_count, department=""):
        self.selected_staff_id = staff_id
        self.selected_staff_name = staff_name
        self.selected_staff_department = clean_department_name(department)
        self.selected_thumb_paths = set()
        
        # เลือกแถวใน Treeview
        if hasattr(self, 'teacher_tree'):
            try:
                iid_str = str(staff_id)
                if self.teacher_tree.exists(iid_str):
                    if self.teacher_tree.selection() != (iid_str,):
                        self.teacher_tree.selection_set(iid_str)
                        self.teacher_tree.see(iid_str)
            except Exception:
                pass

        dep_info = f" ({self.selected_staff_department})" if self.selected_staff_department else ""
        self.lbl_selected_info.configure(text=f"คุณครูที่เลือก: {staff_name}{dep_info}")
        self.lbl_photo_count_detail.configure(text=f"รูปภาพที่ลงทะเบียนแล้วในระบบ: {photo_count} รูป")
        
        self.btn_upload_photo.configure(state="normal")
        self.btn_delete_staff.configure(state="normal")
        if hasattr(self, 'btn_edit_staff'):
            self.btn_edit_staff.configure(state="normal")
        self.btn_delete_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

        # ดึงภาพย่อมาแสดงผล
        self.show_staff_thumbnails(staff_id)

    def add_staff_name(self):
        raw_input = self.entry_staff_name.get().strip()
        if not raw_input:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อคุณครู")
            return
            
        m_name, parsed_dep, _ = parse_teacher_filename(raw_input)
        if not m_name:
            m_name = raw_input
            
        final_dep = parsed_dep
        if hasattr(self, 'entry_staff_department'):
            manual_dep = self.entry_staff_department.get().strip()
            if manual_dep:
                final_dep = manual_dep
                
        staff_id = self.db.register_staff_member(m_name, department=final_dep)
        if staff_id:
            logger.info(f"Registered new teacher '{m_name}' (department: '{final_dep}') successfully.")
            self.entry_staff_name.delete(0, "end")
            if hasattr(self, 'entry_staff_department'):
                self.entry_staff_department.delete(0, "end")
            self.load_staff_list()
        else:
            messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเพิ่มรายชื่อได้")

    def upload_staff_photos(self):
        if self.selected_staff_id is None:
            return
            
        file_paths = filedialog.askopenfilenames(
            title=f"เลือกรูปภาพใบหน้าของ {self.selected_staff_name}",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.webp")]
        )
        if not file_paths:
            return

        # เริ่มทำงานสแกนรูปเพื่อหาเวกเตอร์ใน Thread ย่อยเพื่อไม่ให้ GUI ค้าง
        def process_upload():
            logger.info(f"Processing {len(file_paths)} registration photos for: {self.selected_staff_name}")
            
            # โหลดตัวตรวจจับใบหน้า
            analyzer = FaceAnalyzer(use_gpu=False) # สแกนหน้าครูสั้นๆ ใช้ CPU ปกติได้
            if not analyzer.initialize():
                logger.error("Failed to initialize FaceAnalyzer.")
                return
                
            success_count = 0
            for path in file_paths:
                try:
                    logger.info(f"Extracting embedding from: {os.path.basename(path)}")
                    faces = analyzer.detect_and_extract_faces(path)
                    
                    if len(faces) == 0:
                        logger.warning(f"No face detected in file: {os.path.basename(path)}. Skipping.")
                        continue
                    elif len(faces) > 1:
                        logger.warning(f"Multiple faces ({len(faces)}) detected in file: {os.path.basename(path)}. Using the largest face.")
                        # ค้นหาใบหน้าที่พื้นที่ Bounding Box ใหญ่ที่สุด
                        largest_face = max(faces, key=lambda f: (f["bbox"][2]-f["bbox"][0]) * (f["bbox"][3]-f["bbox"][1]))
                        # ตัดรูปใบหน้าและบันทึกลงแอป
                        face_path = self.save_cropped_face(self.selected_staff_id, path, largest_face["bbox"], success_count)
                        self.db.add_staff_embedding(self.selected_staff_id, face_path, largest_face["embedding"])
                    else:
                        # มีใบหน้าเดียว
                        face_path = self.save_cropped_face(self.selected_staff_id, path, faces[0]["bbox"], success_count)
                        self.db.add_staff_embedding(self.selected_staff_id, face_path, faces[0]["embedding"])
                        
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error processing {os.path.basename(path)}: {e}")

            if success_count > 0:
                self.db.set_staff_backfill_status(self.selected_staff_id, 0)
                logger.info(f"Registered {success_count} / {len(file_paths)} face templates for {self.selected_staff_name} (set is_backfilled=0)")
            else:
                logger.info(f"Registered {success_count} / {len(file_paths)} face templates for {self.selected_staff_name}")
            
            # รีเฟรชรายชื่อและรูปภาพย่อยในหน่วยความจำ
            self.after(0, self.load_staff_list)
            self.after(0, lambda: self.show_staff_thumbnails(self.selected_staff_id))
            self.after(0, lambda: messagebox.showinfo(
                "ลงทะเบียนสำเร็จ", 
                f"ลงทะเบียนใบหน้าของคุณครู {self.selected_staff_name} สำเร็จ {success_count} รูป\n(พร้อมสำหรับการจับคู่ย้อนหลังอัตโนมัติใน Task 3)"
            ))

        threading.Thread(target=process_upload, daemon=True).start()

    def edit_selected_staff(self):
        """แก้ไขชื่อและสังกัดของคุณครู (v6.34)"""
        if self.selected_staff_id is None:
            return

        staff_id = self.selected_staff_id
        old_name = self.selected_staff_name or ""
        old_department = getattr(self, 'selected_staff_department', '') or ""

        # ดึงข้อมูลล่าสุดจากฐานข้อมูล SQLite
        staff_rec = self.db.get_staff_member_by_id(staff_id)
        if staff_rec:
            old_name = staff_rec.get("name") or old_name
            old_department = clean_department_name(staff_rec.get("department") or old_department)

        # สร้างหน้าต่าง Popup Dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("แก้ไขข้อมูลคุณครู")
        dialog.geometry("480x290")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 240
        y = self.winfo_y() + (self.winfo_height() // 2) - 145
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text="✏️ แก้ไขข้อมูลคุณครู (v6.34)", font=ctk.CTkFont(size=16, weight="bold"), text_color="#5CACEE").pack(pady=(15, 10))

        # ชื่อคุณครู
        frame_name = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_name.pack(fill="x", padx=25, pady=6)
        ctk.CTkLabel(frame_name, text="ชื่อคุณครู:", width=100, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        entry_name = ctk.CTkEntry(frame_name, width=280, font=ctk.CTkFont(size=13))
        entry_name.pack(side="left", fill="x", expand=True)
        entry_name.insert(0, old_name)
        self.bind_universal_entry_shortcuts(entry_name)

        # สังกัด
        frame_dep = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_dep.pack(fill="x", padx=25, pady=6)
        ctk.CTkLabel(frame_dep, text="สังกัด:", width=100, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        
        entry_dep = ctk.CTkEntry(frame_dep, width=160, font=ctk.CTkFont(size=13))
        entry_dep.insert(0, old_department)

        dept_options = ["(เลือกสังกัด)"] + SW_DEPARTMENTS
        def on_edit_dept_select(val):
            if val == "(เลือกสังกัด)":
                entry_dep.delete(0, "end")
            elif val == "อื่นๆ (ระบุเอง)":
                entry_dep.delete(0, "end")
                entry_dep.focus_set()
            else:
                entry_dep.delete(0, "end")
                entry_dep.insert(0, val)

        opt_dep = ctk.CTkOptionMenu(
            frame_dep, values=dept_options, height=32, width=150, font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13), dropdown_fg_color="#101B2B", dropdown_hover_color="#1F3A60",
            command=on_edit_dept_select
        )
        opt_dep.set(old_department if old_department in SW_DEPARTMENTS else "(เลือกสังกัด)")
        opt_dep.pack(side="left", padx=(0, 6))
        entry_dep.pack(side="left", fill="x", expand=True)
        self.bind_universal_entry_shortcuts(entry_dep)

        # ปุ่มบันทึกและยกเลิก
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=25, pady=(20, 15))

        def save_teacher_changes():
            new_name = entry_name.get().strip()
            new_dep = clean_department_name(entry_dep.get().strip())
            if not new_name:
                messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อคุณครู", parent=dialog)
                return

            self.db.update_staff_member_full(staff_id, name=new_name, department=new_dep)

            self.selected_staff_name = new_name
            self.selected_staff_department = new_dep
            dep_info = f" ({new_dep})" if new_dep else ""
            self.lbl_selected_info.configure(text=f"คุณครูที่เลือก: {new_name}{dep_info}")
            self._cached_teachers_list = None
            self.load_staff_list()
            dialog.destroy()
            messagebox.showinfo("สำเร็จ", "บันทึกการแก้ไขข้อมูลคุณครูเรียบร้อยแล้ว")

        btn_save = ctk.CTkButton(btn_frame, text="💾 บันทึกการแก้ไข", fg_color="#2ECC71", hover_color="#27AE60",
                                 font=ctk.CTkFont(size=13, weight="bold"), command=save_teacher_changes)
        btn_save.pack(side="left", fill="x", expand=True, padx=(0, 5))

        btn_cancel = ctk.CTkButton(btn_frame, text="ยกเลิก", fg_color="#7F8C8D", hover_color="#95A5A6",
                                   font=ctk.CTkFont(size=13), command=dialog.destroy)
        btn_cancel.pack(side="right", padx=(5, 0))

    def delete_selected_staff(self):
        if self.selected_staff_id is None:
            return
        self.delete_selected_staff_by_id(self.selected_staff_id, self.selected_staff_name)

    def delete_selected_staff_by_id(self, staff_id, staff_name):
        confirm = messagebox.askyesno(
            "ยืนยันการลบคุณครู", 
            f"คุณต้องการลบรายชื่อและประวัติการตรวจพบทั้งหมดของ '{staff_name}' ใช่หรือไม่?\n"
            f"การกระทำนี้จะล้างข้อมูลใน SQLite, Google Sheets และอัปเดตไฟล์ JSON บน Drive ทันที"
        )
        if not confirm:
            return

        def process_delete():
            try:
                logger.info(f"[SYSTEM] Starting deletion process for teacher: {staff_name} (ID: {staff_id})...")
                
                # 1. ลบจาก SQLite Local Database
                self.db.delete_staff_member(staff_id)
                logger.info(f"[DATABASE] Removed teacher '{staff_name}' and related embedding records from SQLite.")

                # 2. เชื่อมต่อ Google Sheets และอัปเดต Sheets + Excel + Drive JSON
                sheet_id = self.entry_sheets_id.get().strip()
                json_folder_id = self.entry_json_folder_id.get().strip()
                delete_req_file_id = self.entry_delete_req_file_id.get().strip()

                if sheet_id:
                    if self.sync_manager.connect(sheet_id):
                        sync_data = self.db.get_all_sync_data()
                        
                        # อัปเดต Sheets (faces + photos)
                        logger.info("[GSHEETS] Syncing updated data to Google Sheets after teacher deletion...")
                        self.sync_manager.sync_to_google_sheet(sync_data)
                        
                        # อัปเดต Local Excel
                        self.sync_manager.save_local_excel_mirror(sync_data)
                        
                        # อัปเดตไฟล์ดัชนี JSON 2 ไฟล์หลัก บน Google Drive
                        if json_folder_id:
                            logger.info("[GDRIVE] Updating person_index.json & photo_index.json on Google Drive...")
                            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id)
                    else:
                        logger.error("[GSHEETS] Failed to connect to Google Sheets during deletion sync.")
                
                # 3. อัปเดตลบคีย์ครูคนนี้ใน delete_request.json (ทั้งบน Drive และเครื่อง)
                loaded_requests = {}
                loaded_from_drive = False
                if delete_req_file_id and self.sync_manager.connected:
                    try:
                        media_content = self.sync_manager.drive_service.files().get_media(fileId=delete_req_file_id).execute()
                        loaded_requests = json.loads(media_content.decode("utf-8"))
                        loaded_from_drive = True
                    except Exception as e:
                        logger.error(f"[DELETE_REQ] Failed to download JSON for deletion filtering: {e}")

                if not loaded_from_drive:
                    req_file = os.path.join(get_project_root(), "delete_request.json")
                    if os.path.exists(req_file):
                        try:
                            with open(req_file, "r", encoding="utf-8") as f:
                                loaded_requests = json.load(f)
                        except Exception:
                            pass

                # หากเป็น Dictionary คีย์ชื่อครู ให้ลบคีย์ชื่อครูคนนี้ออกไป
                if isinstance(loaded_requests, dict):
                    if staff_name in loaded_requests:
                        del loaded_requests[staff_name]
                        logger.info(f"[DELETE_REQ] Removed '{staff_name}' key from delete requests.")
                elif isinstance(loaded_requests, list):
                    # หากเป็น Flat List ให้กรองรายการของครูคนนี้ออก
                    filtered_reqs = [r for r in loaded_requests if isinstance(r, dict) and r.get("staff_name") != staff_name and r.get("staff_id") != staff_id]
                    loaded_requests = filtered_reqs

                # บันทึกกลับขึ้น Google Drive (ถ้าเปิดจากไดรฟ์)
                if delete_req_file_id and loaded_from_drive and self.sync_manager.connected:
                    try:
                        from googleapiclient.http import MediaIoBaseUpload
                        import io
                        updated_json_str = json.dumps(loaded_requests, ensure_ascii=False, indent=2)
                        fh = io.BytesIO(updated_json_str.encode("utf-8"))
                        media = MediaIoBaseUpload(fh, mimetype='application/json', resumable=True)
                        self.sync_manager.drive_service.files().update(fileId=delete_req_file_id, media_body=media).execute()
                        logger.info(f"[DELETE_REQ] Successfully updated delete_request.json on Drive.")
                    except Exception as cloud_err:
                        logger.error(f"[DELETE_REQ] Error uploading filtered JSON: {cloud_err}")

                # บันทึกสำรองลงเครื่อง
                req_file = os.path.join(get_project_root(), "delete_request.json")
                try:
                    with open(req_file, "w", encoding="utf-8") as f:
                        json.dump(loaded_requests, f, ensure_ascii=False, indent=2)
                    logger.info("[DELETE_REQ] Saved updated delete requests to local mirror.")
                except Exception as file_err:
                    logger.error(f"Error updating local delete_request.json file: {file_err}")

                # 4. รีเฟรชหน้าจอทั้งหมดใน Thread หลัก
                self.after(0, self.load_staff_list)
                self.after(0, self.refresh_dashboard_stats)
                self.after(0, self.load_delete_requests_table)
                self.after(0, lambda: messagebox.showinfo("ลบสำเร็จ", f"ลบข้อมูลของคุณครู '{staff_name}' ออกจากระบบทั้งหมดเรียบร้อยแล้ว"))
                
            except Exception as ex:
                logger.error(f"[SYSTEM] Error during teacher deletion process: {ex}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการลบครู: {ex}"))

        threading.Thread(target=process_delete, daemon=True).start()

    # ==================== (3) หน้าสแกนภาพกิจกรรม (Scan Console) ====================
    def setup_scan_ui(self):
        self.frame_scan.grid_columnconfigure(0, weight=1)
        self.frame_scan.grid_rowconfigure(1, weight=1) # ให้ขยายพื้นที่รายการการกระทำ

        # หัวข้อ
        lbl_title = ctk.CTkLabel(
            self.frame_scan, text="สแกนและค้นหาใบหน้าในภาพกิจกรรม", 
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 20))

        # โซนตั้งค่าการสแกน (บน)
        self.scan_settings_frame = ctk.CTkFrame(self.frame_scan, fg_color="#101B2B")
        self.scan_settings_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15), padx=2)
        self.scan_settings_frame.grid_columnconfigure((0, 1), weight=1)

        # ลิงก์โฟลเดอร์ Google Drive และชีท พร้อมปุ่มค้นหาดึงจาก API
        ctk.CTkLabel(self.scan_settings_frame, text="ID โฟลเดอร์ภาพกิจกรรม (Google Drive):", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").grid(row=0, column=0, padx=15, pady=(15, 2), sticky="w")
        
        folder_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        folder_input_frame.grid(row=1, column=0, padx=15, pady=2, sticky="ew")
        folder_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_drive_folder_id = ctk.CTkEntry(folder_input_frame, placeholder_text="ตัวอย่าง: 1a2b3c4d5e6f7g8h9i0j...", height=36, font=ctk.CTkFont(size=14))
        self.entry_drive_folder_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_manage_root = ctk.CTkButton(
            folder_input_frame, text="📁 จัดการ Root ปีการศึกษา", width=165, height=36,
            font=ctk.CTkFont(size=13, weight="bold"), fg_color="#8E44AD", hover_color="#9B59B6",
            command=lambda: self.select_menu("settings")
        )
        btn_manage_root.pack(side="right", padx=(5, 0))

        btn_pick_folder = ctk.CTkButton(folder_input_frame, text="🔍 เลือกโฟลเดอร์", width=115, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("folder"))
        btn_pick_folder.pack(side="right")

        ctk.CTkLabel(self.scan_settings_frame, text="ID ของ Google Sheets (ฐานข้อมูลดัชนี):", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").grid(row=0, column=1, padx=15, pady=(15, 2), sticky="w")
        
        sheet_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        sheet_input_frame.grid(row=1, column=1, padx=15, pady=2, sticky="ew")
        sheet_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_sheets_id = ctk.CTkEntry(sheet_input_frame, placeholder_text="ตัวอย่าง: 1AbCdEfGhIjKlMnOpQrStUvWxYz...", height=36, font=ctk.CTkFont(size=14))
        self.entry_sheets_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_pick_sheet = ctk.CTkButton(sheet_input_frame, text="🔍 เลือก Sheets", width=115, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("sheet"))
        btn_pick_sheet.pack(side="right", padx=(0, 5))
        
        btn_open_sheet = ctk.CTkButton(sheet_input_frame, text="🌐 เปิด Sheets", width=115, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#107C41", hover_color="#0A5C30", command=self.open_sheets_in_browser)
        btn_open_sheet.pack(side="right")

        # แถวใหม่สำหรับโฟลเดอร์เก็บ JSON
        ctk.CTkLabel(self.scan_settings_frame, text="ID โฟลเดอร์เก็บไฟล์ JSON ดัชนี (Google Drive):", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").grid(row=2, column=0, columnspan=2, padx=15, pady=(8, 2), sticky="w")
        
        json_folder_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        json_folder_input_frame.grid(row=3, column=0, columnspan=2, padx=15, pady=2, sticky="ew")
        json_folder_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_json_folder_id = ctk.CTkEntry(json_folder_input_frame, placeholder_text="ระบุ ID โฟลเดอร์หลักที่แชร์ไฟล์ person_index.json และ photo_index.json", height=36, font=ctk.CTkFont(size=14))
        self.entry_json_folder_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_pick_json_folder = ctk.CTkButton(json_folder_input_frame, text="🔍 เลือกโฟลเดอร์", width=120, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("json_folder"))
        btn_pick_json_folder.pack(side="right", padx=(0, 5))
        
        btn_open_json_folder = ctk.CTkButton(json_folder_input_frame, text="🌐 โฟลเดอร์เก็บไฟล์ JSON", width=190, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#E67E22", hover_color="#D35400", text_color="white", command=self.open_json_folder_in_browser)
        btn_open_json_folder.pack(side="right")

        # ปรับค่า Threshold และ CPU/GPU (เลื่อนไป row 4)
        option_panel = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        option_panel.grid(row=4, column=0, columnspan=2, padx=15, pady=10, sticky="ew")
        option_panel.grid_columnconfigure(0, weight=1)
        option_panel.grid_columnconfigure(1, weight=1)

        # สไลเดอร์ Threshold
        thresh_frame = ctk.CTkFrame(option_panel, fg_color="transparent")
        thresh_frame.grid(row=0, column=0, sticky="w")
        self.lbl_threshold = ctk.CTkLabel(thresh_frame, text="ค่า Threshold ความคล้ายใบหน้า: 0.65", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD")
        self.lbl_threshold.pack(anchor="w")
        self.slider_threshold = ctk.CTkSlider(thresh_frame, from_=0.1, to=0.9, number_of_steps=80, command=self.update_thresh_label)
        self.slider_threshold.set(0.65)
        self.slider_threshold.pack(fill="x", pady=5)

        # การประมวลผล (CPU / GPU และ สแกนซ้ำ)
        device_frame = ctk.CTkFrame(option_panel, fg_color="transparent")
        device_frame.grid(row=0, column=1, sticky="e")
        
        self.chk_use_gpu = ctk.CTkCheckBox(device_frame, text="เปิดใช้งานการสแกนด้วย GPU (CUDA)", font=ctk.CTkFont(size=14), text_color="#A2B5CD")
        self.chk_use_gpu.pack(anchor="e", pady=(5, 2))

        self.chk_re_scan = ctk.CTkCheckBox(
            device_frame, text="เปิดฟังก์ชั่นให้สแกนรูปภาพเดิมซ้ำ (Re-scan)",
            font=ctk.CTkFont(size=14), text_color="#A2B5CD", command=self.toggle_rescan_options
        )
        self.chk_re_scan.pack(anchor="e", pady=(2, 2))

        self.chk_fast_rescan = ctk.CTkCheckBox(
            device_frame, text="⚡ Fast Rescan (นำเวกเตอร์เดิมใน DB มาจับคู่ซ้ำทันที)",
            font=ctk.CTkFont(size=14), text_color="#A2B5CD", state="disabled"
        )
        self.chk_fast_rescan.pack(anchor="e", pady=(2, 5))

        # เฟรมเลือกเป้าหมายการจับคู่ใบหน้า (Matching Target Panel v1.7.5)
        self.match_target_box = ctk.CTkFrame(option_panel, fg_color="#101B2B")
        self.match_target_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0), padx=5)
        self.match_target_box.grid_columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkLabel(self.match_target_box, text="เป้าหมายการค้นหาและจับคู่ใบหน้า:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, columnspan=3, sticky="w", padx=15, pady=(8, 4))
        
        self.match_mode = ctk.StringVar(value="all")
        
        # คอลัมน์ 0: ครู + นักเรียน ทั้งหมด
        self.rad_all = ctk.CTkRadioButton(self.match_target_box, text="ครู + นักเรียน ทั้งหมด", font=ctk.CTkFont(size=14), variable=self.match_mode, value="all", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_all.grid(row=1, column=0, sticky="w", padx=25, pady=4)
        
        # คอลัมน์ 1: กลุ่มคุณครู
        self.rad_teachers = ctk.CTkRadioButton(self.match_target_box, text="คุณครูทั้งหมด", font=ctk.CTkFont(size=14), variable=self.match_mode, value="teachers", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_teachers.grid(row=1, column=1, sticky="w", padx=25, pady=4)
        
        self.rad_sel_teachers = ctk.CTkRadioButton(self.match_target_box, text="เลือกเฉพาะคุณครูบางคน", font=ctk.CTkFont(size=14), variable=self.match_mode, value="selected_teachers", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_sel_teachers.grid(row=2, column=1, sticky="w", padx=25, pady=4)
        
        self.btn_select_teachers = ctk.CTkButton(
            self.match_target_box, text="เลือกรายชื่อคุณครู (0 คน)...", 
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            height=30, font=ctk.CTkFont(size=13), state="disabled",
            command=self.show_teachers_selection_popup
        )
        self.btn_select_teachers.grid(row=3, column=1, sticky="w", padx=50, pady=(2, 8))
        
        # คอลัมน์ 2: กลุ่มนักเรียน
        self.rad_students = ctk.CTkRadioButton(self.match_target_box, text="นักเรียนทั้งหมด", font=ctk.CTkFont(size=14), variable=self.match_mode, value="students", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_students.grid(row=1, column=2, sticky="w", padx=25, pady=4)
        
        self.rad_sel_students = ctk.CTkRadioButton(self.match_target_box, text="เลือกเฉพาะนักเรียนบางคน", font=ctk.CTkFont(size=14), variable=self.match_mode, value="selected_students", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_sel_students.grid(row=2, column=2, sticky="w", padx=25, pady=4)
        
        self.btn_select_students = ctk.CTkButton(
            self.match_target_box, text="เลือกรายชื่อนักเรียน (0 คน)...", 
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            height=30, font=ctk.CTkFont(size=13), state="disabled",
            command=self.show_students_selection_popup
        )
        self.btn_select_students.grid(row=3, column=2, sticky="w", padx=50, pady=(2, 8))

        # ปุ่มกดทำสแกนและ Progress Bar (เลื่อนไป row 5)
        self.action_panel = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        self.action_panel.grid(row=5, column=0, columnspan=2, padx=15, pady=(10, 15), sticky="ew")
        self.action_panel.grid_columnconfigure(0, weight=1)

        self.btn_start_scan = ctk.CTkButton(
            self.action_panel, text="3. เริ่มดาวน์โหลดและสแกนใบหน้า", 
            fg_color="#2ECC71", hover_color="#27AE60", text_color="black",
            font=ctk.CTkFont(size=15, weight="bold"), height=44,
            command=self.toggle_scanning
        )
        self.btn_start_scan.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.btn_pause_scan = ctk.CTkButton(
            self.action_panel, text="⏸️ พักการสแกน (Pause)", 
            fg_color="#F39C12", hover_color="#D68910", text_color="white",
            font=ctk.CTkFont(size=15, weight="bold"), height=44,
            command=self.toggle_pause_scanning,
            state="disabled"
        )
        self.btn_pause_scan.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.btn_open_float_preview_scan = ctk.CTkButton(
            self.action_panel, text="🔍 เปิดหน้าต่างพรีวิวแบบลอย (Floating Preview)", 
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"), height=36,
            command=self.open_floating_preview_window
        )
        self.btn_open_float_preview_scan.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(self.action_panel, height=18)
        self.progress_bar.set(0.0)
        self.progress_bar.grid(row=3, column=0, sticky="ew")
        self.progress_bar.grid_remove() # ซ่อนไว้ก่อนเริ่ม

        self.lbl_progress_text = ctk.CTkLabel(self.action_panel, text="พร้อมสแกน", font=ctk.CTkFont(size=14), text_color="#A2B5CD")
        self.lbl_progress_text.grid(row=4, column=0, pady=2)
        self.lbl_progress_text.grid_remove()

        # โซนแสดงผล Console Logs ย้ายไปก้นจอหลักถาวรแล้ว ไม่ต้องกริตเฟรมซ้ำซ้อนที่นี่

    def update_thresh_label(self, val):
        self.lbl_threshold.configure(text=f"ค่า Threshold ความคล้ายใบหน้า: {val:.2f}")

    def toggle_rescan_options(self):
        """เปิด/ปิด การใช้งาน Fast Rescan ตามสถานะของปุ่ม Re-scan (v5.40)"""
        if self.chk_re_scan.get():
            self.chk_fast_rescan.configure(state="normal")
        else:
            self.chk_fast_rescan.deselect()
            self.chk_fast_rescan.configure(state="disabled")

    def update_match_mode_ui(self):
        mode = self.match_mode.get()
        if mode == "selected_teachers":
            self.btn_select_teachers.configure(state="normal")
            self.btn_select_students.configure(state="disabled")
        elif mode == "selected_students":
            self.btn_select_teachers.configure(state="disabled")
            self.btn_select_students.configure(state="normal")
        else:
            self.btn_select_teachers.configure(state="disabled")
            self.btn_select_students.configure(state="disabled")

    def show_teachers_selection_popup(self):
        popup = ctk.CTkToplevel(self)
        popup.title("เลือกคุณครูในการ Matching")
        popup.geometry("380x450")
        popup.grab_set()
        
        lbl_title = ctk.CTkLabel(popup, text="เลือกคุณครูเป้าหมาย", font=ctk.CTkFont(size=14, weight="bold"))
        lbl_title.pack(pady=10)
        
        scr_popup = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        scr_popup.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        teachers = self.db.get_all_teachers()
        checkbox_vars = {}
        
        for t in teachers:
            s_id = t["id"]
            s_name = t["name"]
            var = ctk.BooleanVar(value=(s_id in self.selected_teacher_ids))
            checkbox_vars[s_id] = var
            
            cb = ctk.CTkCheckBox(scr_popup, text=f"{s_name} (ID: {s_id})", variable=var)
            cb.pack(anchor="w", pady=4, padx=10)
            
        def save_and_close():
            self.selected_teacher_ids = [s_id for s_id, var in checkbox_vars.items() if var.get()]
            self.btn_select_teachers.configure(text=f"เลือกรายชื่อคุณครู ({len(self.selected_teacher_ids)} คน)...")
            popup.destroy()
            
        btn_save = ctk.CTkButton(popup, text="บันทึกรายชื่อที่เลือก", fg_color="#2ECC71", hover_color="#27AE60", text_color="black", command=save_and_close)
        btn_save.pack(pady=(0, 15))

    def show_students_selection_popup(self):
        popup = ctk.CTkToplevel(self)
        popup.title("เลือกนักเรียนในการ Matching")
        popup.geometry("380x450")
        popup.grab_set()
        
        lbl_title = ctk.CTkLabel(popup, text="เลือกนักเรียนเป้าหมาย", font=ctk.CTkFont(size=14, weight="bold"))
        lbl_title.pack(pady=10)
        
        scr_popup = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        scr_popup.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        students = self.db.get_all_students()
        checkbox_vars = {}
        
        for s in students:
            s_id = s["id"]
            s_name = s["name"]
            s_sid = s.get("student_id", "")
            disp_text = f"{s_name} (ID: {s_sid})" if s_sid else f"{s_name}"
            var = ctk.BooleanVar(value=(s_id in self.selected_student_ids))
            checkbox_vars[s_id] = var
            
            cb = ctk.CTkCheckBox(scr_popup, text=disp_text, variable=var)
            cb.pack(anchor="w", pady=4, padx=10)
            
        def save_and_close():
            self.selected_student_ids = [s_id for s_id, var in checkbox_vars.items() if var.get()]
            self.btn_select_students.configure(text=f"เลือกรายชื่อนักเรียน ({len(self.selected_student_ids)} คน)...")
            popup.destroy()
            
        btn_save = ctk.CTkButton(popup, text="บันทึกรายชื่อที่เลือก", fg_color="#2ECC71", hover_color="#27AE60", text_color="black", command=save_and_close)
        btn_save.pack(pady=(0, 15))

    def open_floating_preview_window(self):
        """เปิดหน้าต่างพรีวิวแบบลอย (Floating Window) ขนาด 1/4 ของ Full HD (960x540) v5.50"""
        # ถ้าหน้าต่างเปิดอยู่แล้ว ให้ยกขึ้นมาข้างหน้า (focus)
        if hasattr(self, 'floating_preview_win') and self.floating_preview_win is not None:
            try:
                if self.floating_preview_win.winfo_exists():
                    self.floating_preview_win.lift()
                    self.floating_preview_win.focus_force()
                    return
            except Exception:
                self.floating_preview_win = None

        self.floating_preview_win = ctk.CTkToplevel(self)
        self.floating_preview_win.title("🔍 Real-time Face Matching Preview & Summary (Floating Window)")
        self.floating_preview_win.geometry("960x540")
        self.floating_preview_win.minsize(800, 450)
        self.floating_preview_win.protocol("WM_DELETE_WINDOW", self.close_floating_preview)

        # Main container
        main_float_frame = ctk.CTkFrame(self.floating_preview_win, fg_color="#0A111A", corner_radius=0)
        main_float_frame.pack(fill="both", expand=True)
        main_float_frame.grid_rowconfigure(1, weight=1)
        main_float_frame.grid_columnconfigure(0, weight=3) # Left Panel: Image (กว้างกว่า)
        main_float_frame.grid_columnconfigure(1, weight=2) # Right Panel: Match List

        # Top Bar in Floating Window
        top_bar = ctk.CTkFrame(main_float_frame, fg_color="#101B2B", height=42, corner_radius=0)
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        
        lbl_top_title = ctk.CTkLabel(
            top_bar, text="⚡ Real-time Face Matching Live Preview (1/4 FHD Window)",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ECC71"
        )
        lbl_top_title.pack(side="left", padx=15, pady=8)

        btn_close_float = ctk.CTkButton(
            top_bar, text="✖ ปิดหน้าต่างนี้", width=95, height=28,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#C0392B", hover_color="#962D22",
            command=self.close_floating_preview
        )
        btn_close_float.pack(side="right", padx=15, pady=8)

        # Left Panel: Live Image Preview
        left_preview_frame = ctk.CTkFrame(main_float_frame, fg_color="#050B14", corner_radius=6)
        left_preview_frame.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="nsew")
        left_preview_frame.grid_rowconfigure(0, weight=1)
        left_preview_frame.grid_columnconfigure(0, weight=1)

        self.lbl_float_preview = ctk.CTkLabel(
            left_preview_frame, text="[ รอรับภาพการสแกนใบหน้า Real-time... ]",
            font=ctk.CTkFont(size=14), text_color="#A2B5CD", fg_color="transparent"
        )
        self.lbl_float_preview.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Right Panel: Match Summary List
        right_summary_frame = ctk.CTkFrame(main_float_frame, fg_color="#101B2B", corner_radius=6)
        right_summary_frame.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="nsew")
        right_summary_frame.grid_rowconfigure(1, weight=1)
        right_summary_frame.grid_columnconfigure(0, weight=1)

        lbl_summary_title = ctk.CTkLabel(
            right_summary_frame, text="📋 รายชื่อที่ตรวจพบและผลการแมตช์:",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD"
        )
        lbl_summary_title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 5))

        self.txt_float_summary = ctk.CTkTextbox(
            right_summary_frame, font=ctk.CTkFont(family="Consolas", size=13),
            fg_color="#0D1622", text_color="#ECEFF1"
        )
        self.txt_float_summary.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.txt_float_summary.configure(state="normal")
        self.txt_float_summary.bind("<Key>", lambda e: "break")
        self.txt_float_summary.tag_config("green", foreground="#66BB6A")
        self.txt_float_summary.tag_config("red", foreground="#FF5252")

        # ซิงค์เนื้อหาเดิมจากหน้าจอหลัก (ถ้ามี)
        try:
            if hasattr(self, 'txt_match_summary') and self.txt_match_summary is not None:
                current_main_summary = self.txt_match_summary.get("1.0", "end").strip()
                if current_main_summary:
                    self.txt_float_summary.configure(state="normal")
                    self.txt_float_summary.delete("1.0", "end")
                    for line in current_main_summary.split("\n"):
                        if line.startswith("✓"):
                            self.txt_float_summary.insert("end", line + "\n", "green")
                        elif line.startswith("✗") or line.startswith("["):
                            self.txt_float_summary.insert("end", line + "\n", "red")
                        else:
                            self.txt_float_summary.insert("end", line + "\n")
                    self.txt_float_summary.configure(state="normal")
        except Exception:
            pass

    def close_floating_preview(self):
        """ปิดหน้าต่างพรีวิวแบบลอยอย่างปลอดภัย (v5.50)"""
        try:
            if hasattr(self, 'floating_preview_win') and self.floating_preview_win is not None:
                self.floating_preview_win.destroy()
        except Exception:
            pass
        finally:
            self.floating_preview_win = None
            self.lbl_float_preview = None
            self.txt_float_summary = None

    def check_log_queue(self):
        """ดึง Log จากคิวของ Thread ย่อย มาเติมลงในช่อง Console ของ GUI ในเธรดหลัก (v6.28 Batch Update)"""
        inserted_any = False
        processed_in_tick = 0
        while not self.log_queue.empty() and processed_in_tick < 60:
            try:
                msg = self.log_queue.get_nowait()
                processed_in_tick += 1
                
                # วิเคราะห์หาแท็กประเภทสีตาม Keyword 12 หมวดหมู่
                tag = "white"
                msg_upper = msg.upper()
                
                if "[ERROR]" in msg_upper or "ERROR:" in msg_upper:
                    tag = "red"
                elif "[WARNING]" in msg_upper or "WARNING:" in msg_upper:
                    tag = "orange_red"
                elif "[DEBUG]" in msg_upper:
                    tag = "cyan"
                elif "[SCHEDULE]" in msg_upper:
                    tag = "schedule"
                elif "[GALLERY]" in msg_upper:
                    tag = "magenta"
                elif "[GSHEETS]" in msg_upper or "GOOGLE SHEET" in msg_upper or "SHEET" in msg_upper:
                    tag = "yellow_green"
                elif "[GDRIVE]" in msg_upper or "GOOGLE DRIVE" in msg_upper or "[DOWNLOAD]" in msg_upper:
                    tag = "yellow"
                elif "[INIT]" in msg_upper or "[FULLSCAN]" in msg_upper:
                    tag = "orange"
                elif "[DATABASE]" in msg_upper or "SQLITE" in msg_upper or "DB_" in msg_upper:
                    tag = "yellow_orange"
                elif "[MATCH_OK]" in msg_upper or "SUCCESSFULLY" in msg_upper or "[FAST RESCAN]" in msg_upper:
                    tag = "green"
                elif "[SCAN_INFO]" in msg_upper or "[SETTINGS]" in msg_upper or "SCANNING" in msg_upper:
                    tag = "green_blue"
                elif "[FACE_AI]" in msg_upper or "INSIGHTFACE" in msg_upper or "EMBEDDING" in msg_upper:
                    tag = "blue"
                elif "[SYSTEM]" in msg_upper or "CONNECTED" in msg_upper:
                    tag = "navy"
                elif "[UI]" in msg_upper:
                    tag = "purple"
                elif "FALLBACK" in msg_upper:
                    tag = "magenta"

                # เก็บเข้าประวัติ Log ในหน่วยความจำ (จำกัด 6000 บรรทัด)
                if not hasattr(self, 'console_log_history'):
                    self.console_log_history = []
                self.console_log_history.append((msg, tag))
                if len(self.console_log_history) > 6000:
                    self.console_log_history.pop(0)

                # ตรวจสอบตัวกรองปัจจุบันว่าต้องแสดงบรรทัดนี้หรือไม่
                current_mode = getattr(self, 'console_filter_mode', 'all')
                should_display = True
                if current_mode == "warning":
                    should_display = (tag == "orange_red" or "WARNING" in msg_upper or "⚠️" in msg)
                elif current_mode == "error":
                    should_display = (tag == "red" or "ERROR" in msg_upper or "❌" in msg)

                if should_display:
                    self.console_text.insert("end", msg + "\n", tag)
                    inserted_any = True
            except queue.Empty:
                break

        if inserted_any:
            # จำกัดจำนวนบรรทัดของ Console เพื่อป้องกันค้าง และเลื่อนลงล่างสุดเพียง 1 ครั้งต่อรอบ (Batch UI Update)
            num_lines = float(self.console_text.index('end-1c').split('.')[0])
            if num_lines > 5000:
                delete_to = max(100, int(num_lines - 4900))
                self.console_text.delete('1.0', f'{delete_to}.0')
            self.console_text.see("end")

        # เช็คซ้ำทุก 100 มิลลิวินาที (หรือ 30ms หากยังมีคิวค้างอยู่เยอะ)
        next_delay = 30 if not self.log_queue.empty() else 100
        self.after(next_delay, self.check_log_queue)

    def set_console_log_filter(self, mode):
        """สลับตัวกรอง Console Log ('all', 'warning', 'error') (v6.11)"""
        self.console_filter_mode = mode
        
        # อัปเดตสีปุ่มไฮไลต์สถานะการเลือก
        if hasattr(self, 'btn_filter_all'):
            if mode == "all":
                self.btn_filter_all.configure(fg_color="#2ECC71", hover_color="#27AE60", text_color="black")
                self.btn_filter_warning.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#FFA726")
                self.btn_filter_error.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#FF5252")
            elif mode == "warning":
                self.btn_filter_all.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#ECEFF1")
                self.btn_filter_warning.configure(fg_color="#FFA726", hover_color="#FB8C00", text_color="black")
                self.btn_filter_error.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#FF5252")
            elif mode == "error":
                self.btn_filter_all.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#ECEFF1")
                self.btn_filter_warning.configure(fg_color="#1F3A60", hover_color="#20334F", text_color="#FFA726")
                self.btn_filter_error.configure(fg_color="#FF5252", hover_color="#E53935", text_color="white")

        # เรนเดอร์ข้อความใน Console Textbox ใหม่จากประวัติ
        self.console_text.delete('1.0', 'end')
        history = getattr(self, 'console_log_history', [])
        for m, t in history:
            m_upper = m.upper()
            show = True
            if mode == "warning":
                show = (t == "orange_red" or "WARNING" in m_upper or "⚠️" in m)
            elif mode == "error":
                show = (t == "red" or "ERROR" in m_upper or "❌" in m)
            
            if show:
                self.console_text.insert("end", m + "\n", t)
        self.console_text.see("end")

    def toggle_scanning(self):
        if self.is_scanning:
            # ผู้ใช้ต้องการหยุดการสแกน
            self.is_scanning = False
            self.is_paused = False
            logger.warning("Stop request sent. Halting scan process...")
            self.btn_pause_scan.configure(state="disabled")
        else:
            # เริ่มการสแกนภาพ
            folder_id = self.entry_drive_folder_id.get().strip()
            sheet_id = self.entry_sheets_id.get().strip()

            if not folder_id or not sheet_id:
                messagebox.showwarning("ระบุข้อมูลไม่ครบ", "กรุณาระบุ ID โฟลเดอร์ Google Drive และ ID Google Sheets ก่อนสแกน")
                return

            self.save_settings() # บันทึกการตั้งค่าไว้เปิดคราวหลัง
            
            self.is_scanning = True
            self.is_paused = False
            self.btn_start_scan.configure(text="🛑 กดเพื่อหยุดการสแกน", fg_color="#E74C3C", hover_color="#C0392B", text_color="white")
            self.btn_pause_scan.configure(state="normal", text="⏸️ พักการสแกน (Pause)", fg_color="#F39C12")
            self.progress_bar.grid()
            self.progress_bar.set(0.0)
            self.lbl_progress_text.grid()
            self.lbl_progress_text.configure(text="เริ่มการเชื่อมต่อระบบ Google...")
            
            # เคลียร์ Console Log ก่อนหน้า
            self.console_text.delete('1.0', 'end')

            # รันการทำงานสแกนใน Thread ย่อย
            self.scan_thread = threading.Thread(target=self.run_scanning_process, args=(folder_id, sheet_id), daemon=True)
            self.scan_thread.start()

            # เปิดหน้าต่างพรีวิว Real-time แบบลอย (Floating Preview Window) อัตโนมัติ (v5.50)
            try:
                self.open_floating_preview_window()
            except Exception as fe:
                logger.debug(f"Auto-open floating preview failed: {fe}")

    def toggle_pause_scanning(self):
        """ควบคุมสลับการพักการสแกนชั่วคราวและการทำงานต่อ"""
        if not self.is_scanning:
            return
        if self.is_paused:
            self.is_paused = False
            self.btn_pause_scan.configure(text="⏸️ พักการสแกน (Pause)", fg_color="#F39C12", hover_color="#D68910")
            logger.info("[UI] Scan process continued.")
            self.lbl_progress_text.configure(text="กำลังดำเนินการสแกนต่อ...")
        else:
            self.is_paused = True
            self.btn_pause_scan.configure(text="▶️ ดำเนินการต่อ (Continue)", fg_color="#2ECC71", hover_color="#27AE60")
            logger.info("[UI] Scan process paused by user.")
            self.lbl_progress_text.configure(text="⏸️ หยุดพักการสแกนชั่วคราว...")

    def toggle_rescan_options(self):
        """เปิด/ปิด การใช้งานปุ่มย่อย Fast Rescan สัมพันธ์กับ Re-scan"""
        if hasattr(self, 'chk_re_scan') and hasattr(self, 'chk_fast_rescan'):
            if self.chk_re_scan.get():
                self.chk_fast_rescan.configure(state="normal")
            else:
                self.chk_fast_rescan.deselect()
                self.chk_fast_rescan.configure(state="disabled")

    def get_current_scan_settings(self):
        """ดึงค่าการตั้งค่าสแกนปัจจุบันจาก GUI และพ่น Log แสดงการตั้งค่าในสีเขียวฟ้า"""
        thresh = self.slider_threshold.get() if hasattr(self, 'slider_threshold') else 0.5
        use_gpu = self.chk_use_gpu.get() if hasattr(self, 'chk_use_gpu') else False
        rescan = self.chk_re_scan.get() if hasattr(self, 'chk_re_scan') else False
        fast_rescan = self.chk_fast_rescan.get() if hasattr(self, 'chk_fast_rescan') else False
        
        target = "all"
        if hasattr(self, 'match_mode'):
            target = self.match_mode.get()
            
        target_str = "ครู + นักเรียน ทั้งหมด"
        if target == "teachers":
            target_str = "เฉพาะครู"
        elif target == "students":
            target_str = "เฉพาะนักเรียน"
        elif target in ["selected_teachers", "custom_teacher"]:
            target_str = "เลือกครูเฉพาะกลุ่ม"
        elif target in ["selected_students", "custom_student"]:
            target_str = "เลือกนักเรียนเฉพาะกลุ่ม"

        gpu_str = "เปิดใช้งาน (CUDA)" if use_gpu else "ปิดใช้งาน (CPU)"
        rescan_str = "เปิดใช้งาน" if rescan else "ปิดใช้งาน"
        if rescan and fast_rescan:
            rescan_str += " (Fast Rescan)"

        msg = f"[SETTINGS] ⚙️ การตั้งค่าสแกนปัจจุบัน -> Threshold: {thresh:.2f} | GPU: {gpu_str} | Re-scan: {rescan_str} | เป้าหมาย: {target_str}"
        logger.info(msg)
        return {
            "threshold": thresh,
            "use_gpu": use_gpu,
            "rescan": rescan,
            "fast_rescan": fast_rescan,
            "match_target": target
        }

    def load_staff_templates(self, match_mode="all"):
        """โหลดเวกเตอร์ภาพต้นแบบแม่แบบตามโหมดการเปรียบเทียบที่กำหนด (all, teachers, students, ฯลฯ)"""
        templates = self.db.get_all_embeddings()
        if not templates or "embeddings" not in templates or len(templates["embeddings"]) == 0:
            return {
                "embeddings": np.empty((0, 512), dtype=np.float32),
                "names": [],
                "staff_ids": [],
                "personal_thresholds": []
            }

        filtered_embeddings = []
        filtered_names = []
        filtered_staff_ids = []
        filtered_thresholds = []

        all_thresh = templates.get("personal_thresholds", [0.50] * len(templates["names"]))

        if match_mode == "all":
            filtered_embeddings = list(templates["embeddings"])
            filtered_names = list(templates["names"])
            filtered_staff_ids = list(templates["staff_ids"])
            filtered_thresholds = list(all_thresh)
        elif match_mode == "teachers":
            for i, role in enumerate(templates.get("roles", [])):
                if role == "teacher" or not role:
                    filtered_embeddings.append(templates["embeddings"][i])
                    filtered_names.append(templates["names"][i])
                    filtered_staff_ids.append(templates["staff_ids"][i])
                    filtered_thresholds.append(all_thresh[i] if i < len(all_thresh) else 0.50)
        elif match_mode == "students":
            for i, role in enumerate(templates.get("roles", [])):
                if role == "student":
                    filtered_embeddings.append(templates["embeddings"][i])
                    filtered_names.append(templates["names"][i])
                    filtered_staff_ids.append(templates["staff_ids"][i])
                    filtered_thresholds.append(all_thresh[i] if i < len(all_thresh) else 0.50)
        elif match_mode == "custom_teacher" or match_mode == "selected_teachers":
            selected_ids = getattr(self, 'selected_staff_ids', getattr(self, 'selected_teacher_ids', []))
            for i, role in enumerate(templates.get("roles", [])):
                if (role == "teacher" or not role) and templates["staff_ids"][i] in selected_ids:
                    filtered_embeddings.append(templates["embeddings"][i])
                    filtered_names.append(templates["names"][i])
                    filtered_staff_ids.append(templates["staff_ids"][i])
                    filtered_thresholds.append(all_thresh[i] if i < len(all_thresh) else 0.50)
        elif match_mode == "custom_student" or match_mode == "selected_students":
            selected_ids = getattr(self, 'selected_student_ids', [])
            for i, role in enumerate(templates.get("roles", [])):
                if role == "student" and templates["staff_ids"][i] in selected_ids:
                    filtered_embeddings.append(templates["embeddings"][i])
                    filtered_names.append(templates["names"][i])
                    filtered_staff_ids.append(templates["staff_ids"][i])
                    filtered_thresholds.append(all_thresh[i] if i < len(all_thresh) else 0.50)
        else:
            filtered_embeddings = list(templates["embeddings"])
            filtered_names = list(templates["names"])
            filtered_staff_ids = list(templates["staff_ids"])
            filtered_thresholds = list(all_thresh)

        return {
            "embeddings": np.array(filtered_embeddings) if len(filtered_embeddings) > 0 else np.empty((0, 512), dtype=np.float32),
            "names": filtered_names,
            "staff_ids": filtered_staff_ids,
            "personal_thresholds": filtered_thresholds
        }

    def process_scanning_headless(self, folder_ids, folder_name="Unknown"):
        """สำหรับเรียกผ่าน Scheduler (ทำงานเงียบๆ ใน Thread ของ Scheduler)"""
        if not hasattr(self, 'scheduler_scanning'):
            self.scheduler_scanning = False
            
        if self.scheduler_scanning:
            return
            
        self.scheduler_scanning = True
        try:
            sheet_id = self.entry_sheets_id.get().strip()
            if not sheet_id:
                logger.warning("[SCHEDULE] Sheet ID is empty. Cannot scan headless.")
                return
                
            logger.info("======================= START HEADLESS SCAN =======================")
            scan_settings = self.get_current_scan_settings()
            match_target = scan_settings.get("match_target", "all")
            templates = self.load_staff_templates(match_target)
            if len(templates["embeddings"]) == 0:
                logger.warning("[SCHEDULE] No target embeddings found.")
                return
                
            if not self.sync_manager.connect(sheet_id):
                logger.error("[SCHEDULE] Failed to connect to Google Sheets.")
                return
                
            use_gpu = self.chk_use_gpu.get()
            if not hasattr(self, 'analyzer') or self.analyzer is None or self.analyzer.use_gpu != use_gpu:
                self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if not self.analyzer.initialized:
                if not self.analyzer.initialize():
                    logger.error("[SCHEDULE] Could not initialize FaceAnalyzer.")
                    return
                
            # วนลูปโฟลเดอร์ย่อยที่ส่งเข้ามา
            # วนลูปโฟลเดอร์ย่อยที่ส่งเข้ามา
            for f_id in folder_ids:
                # ดึงชื่อโฟลเดอร์จริงจาก Google Drive API หากระบุชื่อเป็น TargetFolder หรือ Unknown หรือคำ Generic (v6.32 Anti-Generic Guard)
                if is_generic_folder_name(folder_name) and hasattr(self.sync_manager, "drive_service") and self.sync_manager.drive_service:
                    try:
                        f_meta = self.sync_manager.drive_service.files().get(fileId=f_id, fields="name, parents").execute()
                        if f_meta:
                            fname = f_meta.get("name", "")
                            # หากชื่อโฟลเดอร์เป็นคำ Generic ให้ไต่ระดับขึ้นหาโฟลเดอร์แม่
                            if is_generic_folder_name(fname) and f_meta.get("parents"):
                                p_meta = self.sync_manager.drive_service.files().get(fileId=f_meta["parents"][0], fields="name").execute()
                                if p_meta and p_meta.get("name") and not any(yr in p_meta.get("name", "") for yr in ['ภาพกิจกรรม', '256', '255']):
                                    folder_name = p_meta["name"]
                                elif fname:
                                    folder_name = fname
                            elif fname:
                                folder_name = fname
                    except Exception:
                        pass

                logger.info(f"[SCHEDULE] Processing scan for folder: '{folder_name}' (ID: {f_id})")
                images_to_scan = []
                query = f"'{f_id}' in parents and (mimeType contains 'image/') and trashed = false"
                try:
                    results = self.sync_manager.drive_service.files().list(
                        q=query, fields="nextPageToken, files(id, name, mimeType)", pageSize=500
                    ).execute()
                    files = results.get("files", [])
                    for file_info in files:
                        images_to_scan.append({
                            "file_id": file_info['id'],
                            "file_name": file_info['name'],
                            "event": folder_name
                        })
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error listing files in {f_id}: {e}")
                    continue
                    
                # --- ⚡ Fast Rescan Batch Mode (Ultra-Fast Sub-Second Vector Matching) ---
                is_fast_rescan = scan_settings.get("fast_rescan", False)
                drive_file_ids = [img["file_id"] for img in images_to_scan]
                batch_cached = self.db.get_batch_photo_face_embeddings(drive_file_ids) if drive_file_ids else {}

                if is_fast_rescan and batch_cached:
                    import time
                    t_fast_start = time.time()
                    current_thresh = self.slider_threshold.get() if hasattr(self, 'slider_threshold') else 0.5
                    photo_matches_dict = {}
                    total_matched_faces = 0

                    for photo_id, p_data in batch_cached.items():
                        if getattr(self.scheduler, 'stop_requested', False):
                            break
                        embs = p_data["embeddings"]
                        if len(embs) > 0:
                            detected_embeddings = np.array(embs)
                            match_results = self.analyzer.match_faces_matrix(
                                detected_embeddings,
                                templates["embeddings"],
                                templates["names"],
                                templates["staff_ids"],
                                threshold=current_thresh,
                                template_thresholds=templates.get("personal_thresholds")
                            )
                            valid_matches = [(m["staff_id"], m["confidence"]) for m in match_results if m]
                            photo_matches_dict[photo_id] = valid_matches
                            total_matched_faces += len(valid_matches)

                    # บันทึกผลลัพธ์ลง DB รวดเดียวทั้งโฟลเดอร์ใน 1 Transaction
                    self.db.batch_save_detected_faces(photo_matches_dict)
                    t_fast_elapsed = time.time() - t_fast_start
                    logger.info(f"[FAST RESCAN] ⚡ สแกนเปรียบเทียบซ้ำด้วย Fast Rescan สำเร็จทั้งโฟลเดอร์ '{folder_name}' (พบแมตช์ทั้งหมด {total_matched_faces} หน้า ใน {len(batch_cached)}/ {len(images_to_scan)} รูปถ่าย) ใช้เวลาทั้งหมด {t_fast_elapsed:.2f}s")
                    continue

                # --- Normal Scan / Full Scan Process (ทีละภาพ) ---
                success_scan_count = 0
                for idx, img_info in enumerate(images_to_scan):
                    if getattr(self.scheduler, 'stop_requested', False):
                        break
                    existing_photo_id = self.db.get_photo_id_by_drive_id(img_info["file_id"])
                    if existing_photo_id and self.db.has_cached_faces(existing_photo_id):
                        # Fallback Single Fast Rescan
                        if folder_name != "Unknown":
                            with self.db.get_connection() as conn:
                                conn.cursor().execute(
                                    "UPDATE scanned_photos SET event_name = ? WHERE photo_id = ? AND event_name = 'HeadlessScan'",
                                    (folder_name, existing_photo_id)
                                )
                        faces = self.db.get_photo_face_embeddings(existing_photo_id)
                        if len(faces) > 0:
                            detected_embeddings = np.array([f.embedding for f in faces])
                            current_thresh = self.slider_threshold.get()
                            match_results = self.analyzer.match_faces_matrix(
                                detected_embeddings,
                                templates["embeddings"],
                                templates["names"],
                                templates["staff_ids"],
                                threshold=current_thresh,
                                template_thresholds=templates.get("personal_thresholds")
                            )
                            valid_matches = [(m["staff_id"], m["confidence"]) for m in match_results if m]
                            if valid_matches:
                                self.db.save_detected_faces(existing_photo_id, valid_matches)
                                match_names = [m["name"] for m in match_results if m]
                                logger.info(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [MATCH_OK] เจอ: {', '.join(match_names)}")
                            else:
                                logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] ไม่พบใบหน้าที่แมตช์")
                        else:
                            logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] ไม่พบใบหน้าที่แมตช์")
                    else:
                        # Full Scan
                        img_bytes, dl_time, img_size = self.sync_manager.download_image_bytes_with_stats(img_info["file_id"], img_info["file_name"])
                        if img_bytes:
                            import time
                            img_cv = decode_image_bytes(img_bytes)
                            if img_cv is not None:
                                t_ai_start = time.time()
                                faces = self.analyzer.get_faces_optimized(img_cv)
                                t_ai_elapsed = time.time() - t_ai_start
                                logger.info(f"[AI SCAN] สแกนใบหน้าไฟล์ {img_info['file_name']} สำเร็จ พบ {len(faces)} ใบหน้า ใช้เวลาสแกน {t_ai_elapsed:.2f}s (เวลาดาวน์โหลด Drive: {dl_time:.1f}s)")
                                photo_id = existing_photo_id
                                if not photo_id:
                                    photo_serial = self.get_next_photo_serial()
                                    photo_id = f"P{photo_serial:05d}"
                                self.db.save_scanned_photo(photo_id, img_info["file_id"], img_info["event"], f"https://drive.google.com/file/d/{img_info['file_id']}/view", matches=[])
                                self.db.save_photo_face_embeddings(photo_id, faces)
                                
                                if faces:
                                    detected_embeddings = np.array([f.embedding for f in faces])
                                    current_thresh = self.slider_threshold.get()
                                    match_results = self.analyzer.match_faces_matrix(
                                        detected_embeddings,
                                        templates["embeddings"],
                                        templates["names"],
                                        templates["staff_ids"],
                                        threshold=current_thresh,
                                        template_thresholds=templates.get("personal_thresholds")
                                    )
                                    valid_matches = [(m["staff_id"], m["confidence"]) for m in match_results if m]
                                    if valid_matches:
                                        self.db.save_detected_faces(photo_id, valid_matches)
                                        match_names = [m["name"] for m in match_results if m]
                                        logger.info(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [MATCH_OK] เจอ: {', '.join(match_names)}")
                                    else:
                                        logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] ไม่พบใบหน้าที่แมตช์")
                                else:
                                    logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] ไม่พบใบหน้าที่แมตช์")
                            else:
                                photo_serial = self.get_next_photo_serial()
                                photo_id = f"P{photo_serial:05d}"
                                self.db.save_scanned_photo(photo_id, img_info["file_id"], img_info["event"], f"https://drive.google.com/file/d/{img_info['file_id']}/view", matches=[])
                                logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] อ่านไฟล์ภาพล้มเหลว (ข้าม)")
                        else:
                            photo_serial = self.get_next_photo_serial()
                            photo_id = f"P{photo_serial:05d}"
                            self.db.save_scanned_photo(photo_id, img_info["file_id"], img_info["event"], f"https://drive.google.com/file/d/{img_info['file_id']}/view", matches=[])
                            logger.warning(f"[SCHEDULE] โฟลเดอร์: {folder_name} | รูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']} -> [WARNING] ดาวน์โหลดไฟล์ภาพล้มเหลว (ข้าม)")
                    
                    success_scan_count += 1
                    
                    # Chunk Sync: อัปเดต JSON ทุกๆ 500 รูป
                    if success_scan_count % 500 == 0:
                        logger.info(f"[SCHEDULE] Reached {success_scan_count} images. Syncing JSON chunk...")
                        sync_data = self.db.get_all_sync_data()
                        self.sync_manager.sync_to_google_sheet(sync_data)
                        json_folder_id = self.entry_json_folder_id.get().strip()
                        if json_folder_id:
                            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
                        
                    # เช็คปุ่ม Stop
                    if getattr(self.scheduler, 'stop_requested', False):
                        logger.info("[SCHEDULE] Headless scan stopped by user.")
                        break

                if not getattr(self.scheduler, 'stop_requested', False):
                    self.record_matched_folder(f_id, folder_name)

            # อัปเดตข้อมูลขึ้น Sheet (Final Sync)
            sync_data = self.db.get_all_sync_data()
            self.sync_manager.sync_to_google_sheet(sync_data)
            json_folder_id = self.entry_json_folder_id.get().strip()
            if json_folder_id:
                self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
            logger.info("[SCHEDULE] Headless scan completed.")
            return True
            
        except Exception as e:
            logger.error(f"[SCHEDULE] Error in headless scan: {e}")
            return False
        finally:
            self.scheduler_scanning = False

    def process_retroactive_match_headless(self, matched_faces_to_process):
        """ทำ Retroactive Match เงียบๆ สำหรับหน้าใหม่ที่เพิ่งเพิ่ม (ใช้อัตรา Personal Threshold ของแต่ละคน)"""
        default_thresh = self.slider_threshold.get() if hasattr(self, 'slider_threshold') else 0.5
        logger.info(f"[SCHEDULE] Running retroactive match for {len(matched_faces_to_process)} faces with individual personal thresholds (default: {default_thresh:.2f})...")
        try:
            # ดึงแคชทั้งหมด
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT photo_id, embedding FROM scanned_photo_faces")
                all_cached = c.fetchall()
                cached_faces = [row for row in all_cached if row[1] and len(row[1]) > 0]
            
            for item in matched_faces_to_process:
                staff_id = item["staff_id"]
                target_emb = item["emb"]
                target_norm = target_emb / (np.linalg.norm(target_emb) or 1.0)
                
                # ดึงค่า personal_threshold ของบุคคลนี้จาก DB (ถ้าไม่มีให้ใช้ default_thresh)
                person_thresh = self.db.get_personal_threshold(staff_id) if hasattr(self.db, 'get_personal_threshold') else default_thresh
                if person_thresh is None:
                    person_thresh = default_thresh
                
                # เก็บเฉพาะค่า confidence สูงสุดของแต่ละ photo_id เพื่อไม่ให้ Insert ซ้ำ
                photo_best_sim = {}
                for row in cached_faces:
                    photo_id = row[0]
                    emb_blob = row[1]
                    cached_emb = np.frombuffer(emb_blob, dtype=np.float32)
                    c_norm = cached_emb / (np.linalg.norm(cached_emb) or 1.0)
                    
                    sim = float(np.dot(target_norm, c_norm))
                    if sim >= person_thresh:
                        if photo_id not in photo_best_sim or sim > photo_best_sim[photo_id]:
                            photo_best_sim[photo_id] = sim
                
                for photo_id, best_sim in photo_best_sim.items():
                    self.db.save_detected_faces(photo_id, [(staff_id, best_sim)])
            
            # อัปเดตข้อมูลขึ้น Sheet
            sync_data = self.db.get_all_sync_data()
            self.sync_manager.sync_to_google_sheet(sync_data)
            
            # ซิงค์ดัชนี JSON 3 ไฟล์ขึ้น Google Drive (v5.00 Auto Sync)
            json_folder_id = self.entry_json_folder_id.get().strip() if hasattr(self, 'entry_json_folder_id') else ""
            if not json_folder_id:
                json_folder_id = "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"
            logger.info("[SCHEDULE] 📤 กำลังซิงค์ดัชนี JSON 3 ไฟล์ขึ้น Google Drive ปิดท้าย...")
            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
            logger.info("[SCHEDULE] ✅ ซิงค์ดัชนี JSON 3 ไฟล์เรียบร้อยสมบูรณ์!")
            
        except Exception as e:
            logger.error(f"[SCHEDULE] Error in retroactive match: {e}")

    def run_scanning_process(self, folder_id, sheet_id):
        # ฟังก์ชันหลักสำหรับ Thread ย่อย
        try:
            logger.info("======================= START SCAN WORKFLOW =======================")
            # ดึง ID โฟลเดอร์สำหรับเก็บ JSON
            json_folder_id = self.entry_json_folder_id.get().strip()
            # 1. โหลดเวกเตอร์ภาพต้นแบบครูจาก SQLite
            logger.info("Loading staff template vectors from SQLite...")
            templates = self.db.get_all_embeddings()
            
            # ลอจิก v1.7.4: กรองเวกเตอร์ใบหน้าตามตัวเลือกเป้าหมายที่เลือก
            match_mode = self.match_mode.get()
            filtered_embeddings = []
            filtered_names = []
            filtered_staff_ids = []
            
            if match_mode == "all":
                filtered_embeddings = list(templates["embeddings"])
                filtered_names = templates["names"]
                filtered_staff_ids = templates["staff_ids"]
            elif match_mode == "teachers":
                for i, role in enumerate(templates.get("roles", [])):
                    if role == "teacher":
                        filtered_embeddings.append(templates["embeddings"][i])
                        filtered_names.append(templates["names"][i])
                        filtered_staff_ids.append(templates["staff_ids"][i])
            elif match_mode == "students":
                for i, role in enumerate(templates.get("roles", [])):
                    if role == "student":
                        filtered_embeddings.append(templates["embeddings"][i])
                        filtered_names.append(templates["names"][i])
                        filtered_staff_ids.append(templates["staff_ids"][i])
            elif match_mode == "selected_teachers":
                if not self.selected_teacher_ids:
                    logger.error("[SYSTEM] Selective matching for teachers is active but no teachers were selected!")
                    self.after(0, lambda: messagebox.showwarning("ยังไม่ได้เลือกรายชื่อ", "กรุณากดเลือกรายชื่อคุณครูอย่างน้อย 1 ท่านก่อนเริ่มสแกน"))
                    self.after(0, self.reset_scan_ui)
                    return
                for i, role in enumerate(templates.get("roles", [])):
                    if role == "teacher" and templates["staff_ids"][i] in self.selected_teacher_ids:
                        filtered_embeddings.append(templates["embeddings"][i])
                        filtered_names.append(templates["names"][i])
                        filtered_staff_ids.append(templates["staff_ids"][i])
            elif match_mode == "selected_students":
                if not self.selected_student_ids:
                    logger.error("[SYSTEM] Selective matching for students is active but no students were selected!")
                    self.after(0, lambda: messagebox.showwarning("ยังไม่ได้เลือกรายชื่อ", "กรุณากดเลือกรายชื่อนักเรียนอย่างน้อย 1 ท่านก่อนเริ่มสแกน"))
                    self.after(0, self.reset_scan_ui)
                    return
                for i, role in enumerate(templates.get("roles", [])):
                    if role == "student" and templates["staff_ids"][i] in self.selected_student_ids:
                        filtered_embeddings.append(templates["embeddings"][i])
                        filtered_names.append(templates["names"][i])
                        filtered_staff_ids.append(templates["staff_ids"][i])

            templates = {
                "embeddings": np.array(filtered_embeddings) if len(filtered_embeddings) > 0 else np.empty((0, 512), dtype=np.float32),
                "names": filtered_names,
                "staff_ids": filtered_staff_ids
            }
            
            if len(templates["embeddings"]) == 0:
                logger.error("No matching target embeddings found. Please register faces first!")
                self.after(0, lambda: messagebox.showerror("ไม่พบข้อมูลต้นแบบ", "ไม่พบเวกเตอร์ใบหน้าต้นแบบตามเงื่อนไขที่เลือก กรุณาลงทะเบียนใบหน้าก่อนเริ่มสแกน"))
                self.after(0, self.reset_scan_ui)
                return

            logger.info(f"Loaded {len(templates['embeddings'])} matching templates according to target mode: {match_mode}")
            
            # 2. เชื่อมต่อ Google APIs
            self.lbl_progress_text.configure(text="กำลังเชื่อมต่อ Google Drive & Sheets...")
            if not self.sync_manager.connect(sheet_id):
                logger.error("Failed to connect to Google Sheets or Sheets ID is invalid.")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเข้าถึง Google Sheets ได้ กรุณาเช็คไฟล์ credentials หรือ Sheet ID"))
                self.after(0, self.reset_scan_ui)
                return

            # 3. โหลดโมเดล InsightFace
            self.lbl_progress_text.configure(text="กำลังเตรียมโมเดล AI (InsightFace)...")
            use_gpu = self.chk_use_gpu.get()
            if self.analyzer is None or self.analyzer.use_gpu != use_gpu:
                self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if not self.analyzer.initialized:
                if not self.analyzer.initialize():
                    logger.error("Could not initialize FaceAnalyzer.")
                    self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถโหลดโมเดล AI ได้"))
                    self.after(0, self.reset_scan_ui)
                    return

            # 4. ดึงรายชื่อภาพจาก Google Drive (รองรับระบบ Multi-folders แยกประจุด้วยจุลภาค)
            self.lbl_progress_text.configure(text="กำลังตรวจสอบไฟล์ใน Google Drive...")
            
            drive_images = []
            folder_ids = [fid.strip() for fid in folder_id.split(",") if fid.strip()]
            logger.info(f"[SYSTEM] Multi-folder Scan: Parsing folder IDs -> {folder_ids}")
            
            for curr_fid in folder_ids:
                try:
                    logger.info(f"[SYSTEM] Fetching images from folder ID: {curr_fid}")
                    imgs = self.sync_manager.fetch_drive_folder_images_recursive(curr_fid)
                    if imgs:
                        drive_images.extend(imgs)
                except Exception as fetch_err:
                    logger.error(f"[SYSTEM] Error fetching folder ID {curr_fid}: {fetch_err}")
            
            if not drive_images:
                logger.warning("No image files found in the specified Google Drive folder.")
                self.after(0, lambda: messagebox.showinfo("ไม่พบไฟล์", "ไม่พบภาพถ่ายกิจกรรมในโฟลเดอร์ Google Drive นี้"))
                self.after(0, self.reset_scan_ui)
                return

            # คัดกรองภาพเฉพาะที่ยังไม่เคยสแกน (หรือเอาทั้งหมดหากผู้ใช้ระบุให้สแกนซ้ำ)
            images_to_scan = []
            use_re_scan = self.chk_re_scan.get()
            use_fast_rescan = self.chk_fast_rescan.get() if use_re_scan else False
            
            for img in drive_images:
                if use_re_scan or not self.db.is_photo_scanned(img["file_id"]):
                    images_to_scan.append(img)
                else:
                    logger.debug(f"Skipping already scanned file: {img['file_name']} (ID: {img['file_id']})")
            
            total_images = len(drive_images)
            scanned_in_db = total_images - len(images_to_scan)
            logger.info(f"Folder status: Total images = {total_images}, Already scanned = {scanned_in_db}, To scan = {len(images_to_scan)}")

            if not images_to_scan:
                logger.info("All images in this folder are already processed! Syncing to Google Sheets...")
                self.lbl_progress_text.configure(text="อัปเดตข้อมูลขึ้น Google Sheets...")
                sync_data = self.db.get_all_sync_data()
                self.sync_manager.sync_to_google_sheet(sync_data)
                self.sync_manager.save_local_excel_mirror(sync_data)
                self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id)
                
                # บันทึกประวัติสแกนโฟลเดอร์สำเร็จ
                for curr_fid in folder_ids:
                    try:
                        folder_meta = self.sync_manager.drive_service.files().get(fileId=curr_fid, fields="name").execute()
                        folder_name = folder_meta.get("name", "Unknown Folder")
                    except Exception:
                        folder_name = "Unknown Folder"
                    self.record_matched_folder(curr_fid, folder_name)
                    
                self.after(0, lambda: messagebox.showinfo("เสร็จสิ้น", "ภาพกิจกรรมได้รับการสแกนครบหมดแล้ว และปรับปรุงข้อมูลขึ้น Google Sheets, Excel Backup & Drive Cache เรียบร้อยแล้ว!"))
                self.after(0, self.reset_scan_ui)
                return

            # 5. ลุยตรวจจับใบหน้าแบบ Continuous Prefetch Pipeline (v5.20 / v5.40)
            thresh_val = self.slider_threshold.get()
            success_scan_count = 0
            
            # โครงสร้างคิว Buffer สำหรับดาวน์โหลดภาพต่อเนื่องล่วงหน้า (Producer-Consumer)
            download_queue = queue.Queue(maxsize=3)
            stop_download_event = threading.Event()
            
            def background_image_downloader():
                """Worker Thread โหลดภาพจาก Drive ต่อเนื่องยาวไปล่วงหน้า"""
                for img_item in images_to_scan:
                    if stop_download_event.is_set() or not self.is_scanning:
                        break
                    f_id = img_item["file_id"]
                    f_name = img_item["file_name"]
                    f_ext = os.path.splitext(f_name)[1].lower() if f_name else ""
                    camera_brand = RAW_EXTENSIONS_MAP.get(f_ext)

                    # กรณีไฟล์ RAW กล้องดิจิทัล (ข้ามการดาวน์โหลดภาพขนาดใหญ่) (v6.10)
                    if camera_brand:
                        download_queue.put({
                            "img_info": img_item,
                            "img_bytes": None,
                            "img_bgr": None,
                            "dl_time": 0.0,
                            "is_cached": False,
                            "is_raw": True,
                            "camera_brand": camera_brand,
                            "existing_photo_id": None
                        })
                        continue
                    
                    existing_pid = self.db.get_photo_id_by_drive_id(f_id)
                    # ถ้าผู้ใช้ติ๊ก Fast Rescan และมีแคชใบหน้าเดิมใน DB แล้ว -> ไม่ต้องดาวน์โหลดใหม่จาก Drive
                    if use_re_scan and use_fast_rescan and existing_pid and self.db.has_cached_faces(existing_pid):
                        # ดึงภาพ Thumbnail แคชในเครื่อง (ถ้ามี) มาส่งเข้าคิวเพื่อวาดบน Preview
                        thumb_bgr = None
                        try:
                            thumb_path = os.path.join(os.path.dirname(__file__), "data", "thumbnail_cache", f"thumb_{f_id}.jpg")
                            if os.path.exists(thumb_path):
                                thumb_bgr = read_image_file(thumb_path)
                        except Exception:
                            thumb_bgr = None
                            
                        download_queue.put({
                            "img_info": img_item,
                            "img_bytes": None,
                            "img_bgr": thumb_bgr,
                            "dl_time": 0.0,
                            "is_cached": True,
                            "is_raw": False,
                            "existing_photo_id": existing_pid
                        })
                        continue
                        
                    # ดาวน์โหลดไบต์รูปภาพจริง (กรณีปกติ หรือ Re-scan แบบเต็ม)
                    img_bytes, dl_time, _ = self.sync_manager.download_image_bytes_with_stats(f_id, f_name)
                    img_bgr = decode_image_bytes(img_bytes) if img_bytes else None
                            
                    download_queue.put({
                        "img_info": img_item,
                        "img_bytes": img_bytes,
                        "img_bgr": img_bgr,
                        "dl_time": dl_time,
                        "is_cached": False,
                        "is_raw": False,
                        "existing_photo_id": existing_pid
                    })
                # ใส่ Sentinel เพื่อแจ้ง Consumer ว่าโหลดครบทุกรูปแล้ว
                download_queue.put(None)
                
            dl_thread = threading.Thread(target=background_image_downloader, daemon=True)
            dl_thread.start()
            
            # Buffer สำหรับสะสมข้อมูลเขียนลง SQLite แบบ Batch ทุกๆ 10 รูป (v5.20)
            db_batch_buffer = []
            
            for idx in range(len(images_to_scan)):
                # ตรวจสอบปุ่ม Pause สลับลูปรอกรณีหยุดพักชั่วคราว
                while self.is_paused and self.is_scanning:
                    time.sleep(0.2)
                    
                if not self.is_scanning:
                    logger.warning("Scan process cancelled by user.")
                    stop_download_event.set()
                    break
                    
                # ดึงภาพจากคิวดาวน์โหลดที่พร้อมใช้งานทันที
                queue_item = download_queue.get()
                if queue_item is None:
                    break
                    
                img_info = queue_item["img_info"]
                img_bytes = queue_item["img_bytes"]
                img = queue_item["img_bgr"]
                dl_time = queue_item["dl_time"]
                is_cached = queue_item["is_cached"]
                is_raw = queue_item.get("is_raw", False)
                existing_photo_id = queue_item["existing_photo_id"]
                
                # แสดงความก้าวหน้าบน UI
                prog_val = (idx / len(images_to_scan))
                self.progress_bar.set(prog_val)
                self.lbl_progress_text.configure(text=f"กำลังสแกนรูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']}")
                logger.info(f"[{idx+1}/{len(images_to_scan)}] Processing image '{img_info['file_name']}' from event '{img_info['event']}'")

                # -------------------------------------------------------------
                # กรณีที่ 0: ไฟล์ภาพดิบกล้องดิจิทัล RAW Camera Files (v6.10)
                # -------------------------------------------------------------
                if is_raw:
                    camera_brand = queue_item.get("camera_brand", "Camera RAW")
                    f_ext = os.path.splitext(img_info["file_name"])[1].lower() if img_info["file_name"] else ""
                    logger.info(f"📷 [{idx+1}/{len(images_to_scan)}] ตรวจพบไฟล์ RAW กล้อง ({camera_brand} {f_ext}): {img_info['file_name']} -> บันทึกลงตาราง raw_camera_photos โดยอัตโนมัติ")
                    self.db.save_raw_photos_batch([{
                        "photo_id": img_info["file_id"],
                        "drive_file_id": img_info["file_id"],
                        "event_name": img_info.get("event", "Unknown Event"),
                        "drive_link": img_info.get("drive_link", f"https://drive.google.com/file/d/{img_info['file_id']}/view"),
                        "photo_date": img_info.get("photo_date", datetime.now().strftime("%Y-%m-%d")),
                        "file_name": img_info["file_name"],
                        "file_extension": f_ext,
                        "camera_brand": camera_brand
                    }])
                    success_scan_count += 1
                    continue
                
                # -------------------------------------------------------------
                # กรณีที่ 1: FAST RESCAN (มีแคชเดิมอยู่แล้ว)
                # -------------------------------------------------------------
                if is_cached:
                    logger.info(f"⚡ [FAST RESCAN] Using cached face embeddings for {img_info['file_name']} (Photo ID: {existing_photo_id})")
                    faces = self.db.get_photo_face_embeddings(existing_photo_id)
                    matches_in_photo = []
                    current_thresh = self.slider_threshold.get()
                    summary_list = []
                    
                    if len(faces) > 0:
                        detected_embeddings = np.array([f.embedding for f in faces])
                        match_results = self.analyzer.match_faces_matrix(
                            detected_embeddings,
                            templates["embeddings"],
                            templates["names"],
                            templates["staff_ids"],
                            threshold=current_thresh,
                            template_thresholds=templates.get("personal_thresholds")
                        )
                        
                        for i, f in enumerate(faces):
                            m_res = match_results[i]
                            if m_res:
                                matches_in_photo.append((m_res["staff_id"], m_res["confidence"]))
                                logger.info(f"🎯 Match (Cached): {m_res['name']} ({m_res['confidence']*100:.1f}%) in {img_info['file_name']}")
                                summary_list.append((m_res["name"], m_res["confidence"], True))
                            else:
                                best_sim = 0.0
                                best_name = "Unknown"
                                if len(templates["embeddings"]) > 0:
                                    f_norm = f.embedding / (np.linalg.norm(f.embedding) or 1.0)
                                    t_norms = templates["embeddings"] / np.linalg.norm(templates["embeddings"], axis=1, keepdims=True)
                                    sim_scores = np.dot(t_norms, f_norm)
                                    best_idx = np.argmax(sim_scores)
                                    best_sim = float(sim_scores[best_idx])
                                    best_name = templates["names"][best_idx]
                                summary_list.append((best_name, best_sim, False))
                    
                    # วาดภาพพรีวิวจาก Thumbnail แคช (ถ้ามี) บน GUI
                    ctk_preview = None
                    if img is not None:
                        try:
                            from PIL import ImageDraw, ImageFont
                            preview_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            preview_pil = Image.fromarray(preview_rgb)
                            draw = ImageDraw.Draw(preview_pil)
                            
                            font = None
                            for fp in ["tahoma.ttf", "cordia.ttf", "arial.ttf"]:
                                try:
                                    font_size = max(12, int(preview_pil.height * 0.04))
                                    font = ImageFont.truetype(fp, font_size)
                                    break
                                except Exception:
                                    continue
                            if font is None:
                                font = ImageFont.load_default()
                                
                            for i, f in enumerate(faces):
                                bbox = f.bbox
                                if bbox and len(bbox) >= 4:
                                    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                                    m_res = match_results[i] if i < len(match_results) else None
                                    if m_res:
                                        draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=3)
                                        text_label = f"{m_res['name']} ({m_res['confidence']*100:.0f}%)"
                                        draw.text((x1, max(0, y1 - font.getbbox(text_label)[3] - 4)), text_label, fill=(0, 255, 0), font=font)
                                    else:
                                        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
                                        
                            h_orig, w_orig = preview_pil.height, preview_pil.width
                            # พรีวิวสำหรับ Main Window (ขนาดเล็ก 240x380)
                            h_new = 240
                            w_new = int(w_orig * (h_new / h_orig))
                            if w_new > 380:
                                w_new = 380
                                h_new = int(h_orig * (w_new / w_orig))
                            preview_resized = preview_pil.resize((w_new, h_new), Image.Resampling.LANCZOS)
                            ctk_preview = ctk.CTkImage(light_image=preview_resized, size=(w_new, h_new))

                            # พรีวิวสำหรับ Floating Window (ขนาดใหญ่ คมชัด 460x550) v5.50
                            fh_new = 460
                            fw_new = int(w_orig * (fh_new / h_orig))
                            if fw_new > 550:
                                fw_new = 550
                                fh_new = int(h_orig * (fw_new / w_orig))
                            float_resized = preview_pil.resize((fw_new, fh_new), Image.Resampling.LANCZOS)
                            float_ctk_preview = ctk.CTkImage(light_image=float_resized, size=(fw_new, fh_new))
                        except Exception as draw_err:
                            logger.debug(f"Fast Rescan preview draw error: {draw_err}")
                            ctk_preview = None
                            float_ctk_preview = None

                    def update_fast_rescan_ui(preview_obj=ctk_preview, float_preview_obj=float_ctk_preview if 'float_ctk_preview' in locals() else None, items=summary_list):
                        # อัปเดต Main Window
                        if preview_obj:
                            self.lbl_realtime_preview.configure(image=preview_obj, text="")
                        else:
                            self.lbl_realtime_preview.configure(image="", text="⚡ [ Fast Rescan จากแคช ]")
                        self.txt_match_summary.configure(state="normal")
                        self.txt_match_summary.delete("1.0", "end")
                        if not items:
                            self.txt_match_summary.insert("end", "[ ไม่พบใบหน้าในรูป (แคช) ]\n", "red")
                        else:
                            for name, score, is_match in items:
                                pct = int(score * 100)
                                if is_match:
                                    self.txt_match_summary.insert("end", f"✓ {name} ({pct}%)\n", "green")
                                else:
                                    self.txt_match_summary.insert("end", f"✗ Unknown ({pct}%)\n", "red")
                        self.txt_match_summary.configure(state="normal")

                        # ซิงค์อัปเดต Floating Window หากเปิดอยู่ (v5.50)
                        if hasattr(self, 'floating_preview_win') and self.floating_preview_win is not None:
                            try:
                                if self.floating_preview_win.winfo_exists():
                                    if hasattr(self, 'lbl_float_preview') and self.lbl_float_preview is not None and self.lbl_float_preview.winfo_exists():
                                        if float_preview_obj:
                                            self.lbl_float_preview.configure(image=float_preview_obj, text="")
                                        else:
                                            self.lbl_float_preview.configure(image="", text="⚡ [ Fast Rescan จากแคช ]")
                                    if hasattr(self, 'txt_float_summary') and self.txt_float_summary is not None and self.txt_float_summary.winfo_exists():
                                        self.txt_float_summary.configure(state="normal")
                                        self.txt_float_summary.delete("1.0", "end")
                                        if not items:
                                            self.txt_float_summary.insert("end", "[ ไม่พบใบหน้าในรูป (แคช) ]\n", "red")
                                        else:
                                            for name, score, is_match in items:
                                                pct = int(score * 100)
                                                if is_match:
                                                    self.txt_float_summary.insert("end", f"✓ {name} ({pct}%)\n", "green")
                                                else:
                                                    self.txt_float_summary.insert("end", f"✗ Unknown ({pct}%)\n", "red")
                                        self.txt_float_summary.configure(state="normal")
                            except Exception as fe:
                                logger.debug(f"Float preview Fast Rescan UI update error: {fe}")
                    
                    self.after(0, update_fast_rescan_ui)
                    
                    if self.match_mode.get() != "all":
                        self.db.delete_photo_matches_selective(existing_photo_id, templates["staff_ids"])
                    else:
                        self.db.delete_photo_matches(existing_photo_id)
                    self.db.save_detected_faces(existing_photo_id, matches_in_photo)
                    success_scan_count += 1
                    continue

                # -------------------------------------------------------------
                # กรณีที่ 2: FULL SCAN (ดาวน์โหลดจาก Queue + สแกน AI + แสดง Preview)
                # -------------------------------------------------------------
                if use_re_scan:
                    self.db.delete_photo_scan_record(img_info["file_id"])

                if img is None:
                    logger.error(f"Cannot decode image {img_info['file_name']}. Skipping.")
                    continue

                # รัน InsightFace บน GPU
                t_ai_start = time.time()
                faces = self.analyzer.get_faces_optimized(img)
                t_ai_elapsed = time.time() - t_ai_start
                logger.info(f"[AI SCAN] สแกนใบหน้าไฟล์ {img_info['file_name']} สำเร็จ พบ {len(faces)} ใบหน้า ใช้เวลาสแกน {t_ai_elapsed:.2f}s (เวลาดาวน์โหลด Drive: {dl_time:.1f}s)")

                matches_in_photo = []
                current_thresh = self.slider_threshold.get()
                
                # วาดภาพพรีวิวด้วย PIL รองรับอักขระไทย
                from PIL import ImageDraw, ImageFont
                preview_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                preview_pil = Image.fromarray(preview_rgb)
                draw = ImageDraw.Draw(preview_pil)
                
                font = None
                font_paths = ["tahoma.ttf", "cordia.ttf", "arial.ttf"]
                for fp in font_paths:
                    try:
                        font_size = max(14, int(preview_pil.height * 0.03))
                        font = ImageFont.truetype(fp, font_size)
                        break
                    except Exception:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                summary_list = []
                if len(faces) > 0:
                    detected_embeddings = np.array([f.embedding for f in faces])
                    match_results = self.analyzer.match_faces_matrix(
                        detected_embeddings,
                        templates["embeddings"],
                        templates["names"],
                        templates["staff_ids"],
                        threshold=current_thresh,
                        template_thresholds=templates.get("personal_thresholds")
                    )
                    
                    for i, f in enumerate(faces):
                        bbox = f.bbox
                        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                        m_res = match_results[i]
                        if m_res:
                            matches_in_photo.append((m_res["staff_id"], m_res["confidence"]))
                            logger.info(f"🎯 Match: {m_res['name']} ({m_res['confidence']*100:.1f}%) in {img_info['file_name']}")
                            summary_list.append((m_res["name"], m_res["confidence"], True))
                            draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=4)
                            text_label = f"{m_res['name']} ({m_res['confidence']*100:.0f}%)"
                            draw.text((x1, max(0, y1 - font.getbbox(text_label)[3] - 5)), text_label, fill=(0, 255, 0), font=font)
                        else:
                            best_sim = 0.0
                            best_name = "Unknown"
                            if len(templates["embeddings"]) > 0:
                                f_norm = f.embedding / (np.linalg.norm(f.embedding) or 1.0)
                                t_norms = templates["embeddings"] / np.linalg.norm(templates["embeddings"], axis=1, keepdims=True)
                                sim_scores = np.dot(t_norms, f_norm)
                                best_idx = np.argmax(sim_scores)
                                best_sim = float(sim_scores[best_idx])
                                best_name = templates["names"][best_idx]
                            summary_list.append((best_name, best_sim, False))
                            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
                            text_label = f"Unknown ({best_sim*100:.1f}%)"
                            draw.text((x1, max(0, y1 - font.getbbox(text_label)[3] - 5)), text_label, fill=(255, 0, 0), font=font)

                # ปรับรูปพรีวิวย่อขนาดเพื่อแสดงผลบน GUI แบบสดๆ (Main Window)
                h_orig, w_orig = preview_pil.height, preview_pil.width
                h_new = 240
                w_new = int(w_orig * (h_new / h_orig))
                if w_new > 380:
                    w_new = 380
                    h_new = int(h_orig * (w_new / w_orig))
                    
                preview_resized = preview_pil.resize((w_new, h_new), Image.Resampling.LANCZOS)
                ctk_preview = ctk.CTkImage(light_image=preview_resized, size=(w_new, h_new))

                # ปรับรูปพรีวิวขนาดใหญ่คมชัดสำหรับ Floating Window (460x550) v5.50
                fh_new = 460
                fw_new = int(w_orig * (fh_new / h_orig))
                if fw_new > 550:
                    fw_new = 550
                    fh_new = int(h_orig * (fw_new / w_orig))
                float_resized = preview_pil.resize((fw_new, fh_new), Image.Resampling.LANCZOS)
                float_ctk_preview = ctk.CTkImage(light_image=float_resized, size=(fw_new, fh_new))
                
                def update_preview_and_summary(img_obj=ctk_preview, float_img_obj=float_ctk_preview, items=summary_list):
                    # อัปเดต Main Window
                    self.lbl_realtime_preview.configure(image=img_obj, text="")
                    self.txt_match_summary.configure(state="normal")
                    self.txt_match_summary.delete("1.0", "end")
                    if not items:
                        self.txt_match_summary.insert("end", "[ ไม่พบใบหน้าในรูป ]\n", "red")
                    else:
                        for name, score, is_match in items:
                            pct = int(score * 100)
                            if is_match:
                                self.txt_match_summary.insert("end", f"✓ {name} ({pct}%)\n", "green")
                            else:
                                self.txt_match_summary.insert("end", f"✗ Unknown ({pct}%)\n", "red")
                    self.txt_match_summary.configure(state="normal")

                    # ซิงค์อัปเดต Floating Window หากเปิดอยู่ (v5.50)
                    if hasattr(self, 'floating_preview_win') and self.floating_preview_win is not None:
                        try:
                            if self.floating_preview_win.winfo_exists():
                                if hasattr(self, 'lbl_float_preview') and self.lbl_float_preview is not None and self.lbl_float_preview.winfo_exists():
                                    if float_img_obj:
                                        self.lbl_float_preview.configure(image=float_img_obj, text="")
                                    else:
                                        self.lbl_float_preview.configure(image="", text="[ ไม่สามารถแสดงภาพพรีวิว ]")
                                if hasattr(self, 'txt_float_summary') and self.txt_float_summary is not None and self.txt_float_summary.winfo_exists():
                                    self.txt_float_summary.configure(state="normal")
                                    self.txt_float_summary.delete("1.0", "end")
                                    if not items:
                                        self.txt_float_summary.insert("end", "[ ไม่พบใบหน้าในรูป ]\n", "red")
                                    else:
                                        for name, score, is_match in items:
                                            pct = int(score * 100)
                                            if is_match:
                                                self.txt_float_summary.insert("end", f"✓ {name} ({pct}%)\n", "green")
                                            else:
                                                self.txt_float_summary.insert("end", f"✗ Unknown ({pct}%)\n", "red")
                                    self.txt_float_summary.configure(state="normal")
                        except Exception as fe:
                            logger.debug(f"Float preview Full Scan UI update error: {fe}")

                self.after(0, update_preview_and_summary)

                photo_id = existing_photo_id
                if not photo_id:
                    photo_serial = self.get_next_photo_serial() + len(db_batch_buffer)
                    photo_id = f"P{photo_serial:05d}"

                # รวบรวมข้อมูลลง Batch Buffer
                db_batch_buffer.append({
                    "photo_id": photo_id,
                    "drive_file_id": img_info["file_id"],
                    "event_name": img_info["event"],
                    "drive_link": img_info.get("drive_link", f"https://drive.google.com/file/d/{img_info['file_id']}/view"),
                    "matches": matches_in_photo,
                    "photo_date": img_info.get("date", ""),
                    "faces": faces
                })
                
                success_scan_count += 1

                # ⚡ บันทึกข้อมูลลง SQLite แบบ Batch ทุกๆ 10 รูป (v5.20)
                if len(db_batch_buffer) >= 10:
                    self.db.save_scanned_photos_batch(db_batch_buffer)
                    db_batch_buffer.clear()
            
            # บันทึกข้อมูลส่วนที่เหลือใน Buffer (หากไม่ครบ 10 รูป)
            if db_batch_buffer:
                self.db.save_scanned_photos_batch(db_batch_buffer)
                db_batch_buffer.clear()

            stop_download_event.set()
            
            # 8. สแกนจบหรือกดยกเลิก -> อัปเดตไฟล์ JSON บน Drive
            if success_scan_count > 0:
                logger.info("Performing final Drive JSON index update...")
                self.lbl_progress_text.configure(text="กำลังอัปเดตไฟล์ดัชนีบน Drive...")
                
                sync_data = self.db.get_all_sync_data()
                if json_folder_id:
                    try:
                        self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode=self.match_mode.get())
                        logger.info("Successfully updated Drive JSON indexes.")
                    except Exception as json_err:
                        logger.error(f"Error updating Drive JSON indexes: {json_err}")
                
                # บันทึกประวัติสแกนโฟลเดอร์สำเร็จ
                for curr_fid in folder_ids:
                    try:
                        folder_meta = self.sync_manager.drive_service.files().get(fileId=curr_fid, fields="name").execute()
                        folder_name = folder_meta.get("name", "Unknown Folder")
                    except Exception:
                        folder_name = "Unknown Folder"
                    self.record_matched_folder(curr_fid, folder_name)
                
                logger.info(f"Successfully processed final {success_scan_count} photos.")
                self.after(0, lambda: messagebox.showinfo("สแกนสำเร็จ", f"สแกนรูปภาพกิจกรรมเสร็จสิ้นสำเร็จ {success_scan_count} รูป (ดัชนีบนเว็บแอปฯ ได้รับการอัปเดตเรียบร้อยแล้ว)\n\n*หมายเหตุ: กรุณากดปุ่มซิงค์ข้อมูลบนหน้าแรกเพื่ออัปเดตแผ่นงาน Google Sheets ล่าสุด"))
            else:
                logger.warning("No new photos were successfully scanned.")
                
            self.after(0, self.reset_scan_ui)
            
        except Exception as e:
            logger.error(f"Error in scanning process thread: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการประมวลผล: {e}"))
            self.after(0, self.reset_scan_ui)

    def get_next_photo_serial(self):
        # ค้นหาเลข ID สูงสุดใน SQLite ปัจจุบัน
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT photo_id FROM scanned_photos WHERE photo_id LIKE 'P%' ORDER BY CAST(SUBSTR(photo_id, 2) AS INTEGER) DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            max_id = row[0] # รูปแบบ 'P00023'
            try:
                num_part = int(max_id[1:])
                return num_part + 1
            except ValueError:
                pass
        return 1

    def reset_scan_ui(self):
        self.is_scanning = False
        self.is_paused = False
        self.btn_start_scan.configure(text="3. เริ่มดาวน์โหลดและสแกนใบหน้า", fg_color="#2ECC71", hover_color="#27AE60", text_color="black", state="normal")
        self.btn_pause_scan.configure(state="disabled", text="⏸️ พักการสแกน (Pause)", fg_color="#F39C12", hover_color="#D68910")
        self.progress_bar.grid_remove()
        self.lbl_progress_text.grid_remove()
        # เคลียร์ภาพและคำอธิบายพรีวิวบน Main Window
        self.lbl_realtime_preview.configure(image="", text="[ แสดงภาพเปรียบเทียบการจับคู่ใบหน้าแบบ Real-time ]")
        self.txt_match_summary.configure(state="normal")
        self.txt_match_summary.delete("1.0", "end")
        self.txt_match_summary.configure(state="normal")

        # เคลียร์การแสดงผลบน Floating Window หากเปิดอยู่ (v5.50)
        if hasattr(self, 'floating_preview_win') and self.floating_preview_win is not None:
            try:
                if self.floating_preview_win.winfo_exists():
                    if hasattr(self, 'lbl_float_preview') and self.lbl_float_preview is not None and self.lbl_float_preview.winfo_exists():
                        self.lbl_float_preview.configure(image="", text="[ สแกนเสร็จสิ้น / รอรับภาพใหม่ ]")
                    if hasattr(self, 'txt_float_summary') and self.txt_float_summary is not None and self.txt_float_summary.winfo_exists():
                        self.txt_float_summary.configure(state="normal")
                        self.txt_float_summary.delete("1.0", "end")
                        self.txt_float_summary.configure(state="normal")
            except Exception:
                pass

    # ==================== (4) หน้าตั้งค่าระบบ (Settings & Root Year Folders v6.27) ====================
    def setup_settings_ui(self):
        self.frame_settings.grid_columnconfigure(0, weight=1)
        self.frame_settings.grid_rowconfigure(2, weight=1)
        
        lbl_title = ctk.CTkLabel(
            self.frame_settings, text="ตั้งค่าระบบและโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders)", 
            font=ctk.CTkFont(size=24, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        # แถวที่ 1: โซนไฟล์ Credentials และ โซนล้างประวัติสแกน (จัดวาง 2 คอลัมน์กะทัดรัด)
        top_settings_row = ctk.CTkFrame(self.frame_settings, fg_color="transparent")
        top_settings_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        top_settings_row.grid_columnconfigure(0, weight=3)
        top_settings_row.grid_columnconfigure(1, weight=2)

        # ซ้าย: โซนไฟล์ Credentials
        cred_frame = ctk.CTkFrame(top_settings_row, fg_color="#101B2B")
        cred_frame.grid(row=0, column=0, sticky="nsew", padx=(2, 6))
        cred_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cred_frame, text="🔑 ที่อยู่ไฟล์คีย์สิทธิ์ Google (Service Account JSON):",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD"
        ).grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 2), sticky="w")
        
        self.entry_cred_path = ctk.CTkEntry(
            cred_frame, placeholder_text="ตัวอย่าง: config/service_account.json",
            height=34, font=ctk.CTkFont(size=13)
        )
        self.entry_cred_path.grid(row=1, column=0, padx=(15, 8), pady=(2, 10), sticky="ew")
        
        btn_select_cred = ctk.CTkButton(
            cred_frame, text="📂 เลือกไฟล์ JSON...", fg_color="#1F3A60", hover_color="#20334F",
            width=145, height=34, font=ctk.CTkFont(size=13, weight="bold"),
            command=self.select_cred_file
        )
        btn_select_cred.grid(row=1, column=1, padx=(0, 15), pady=(2, 10), sticky="e")

        # ขวา: โซนจัดการขยะล้างประวัติ
        db_settings_frame = ctk.CTkFrame(top_settings_row, fg_color="#101B2B")
        db_settings_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 2))
        db_settings_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            db_settings_frame, text="🗑️ จัดการฐานข้อมูลสแกน:",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#E74C3C"
        ).grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")
        
        btn_clear_history = ctk.CTkButton(
            db_settings_frame, text="ล้างประวัติภาพสแกนกิจกรรมทั้งหมด (ไม่ลบครู/นร.)", 
            fg_color="#C0392B", hover_color="#962D22", height=34, font=ctk.CTkFont(size=13, weight="bold"),
            command=self.clear_scan_history
        )
        btn_clear_history.grid(row=1, column=0, padx=15, pady=(2, 10), sticky="ew")

        # แถวที่ 2: โซนจัดการโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders Management v6.27)
        root_mgr_frame = ctk.CTkFrame(self.frame_settings, fg_color="#101B2B")
        root_mgr_frame.grid(row=2, column=0, sticky="nsew", padx=2, pady=(0, 5))
        root_mgr_frame.grid_columnconfigure(0, weight=1)
        root_mgr_frame.grid_rowconfigure(2, weight=1)

        # Header Bar ของ Root Folders
        hdr_frame = ctk.CTkFrame(root_mgr_frame, fg_color="transparent")
        hdr_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 4))
        hdr_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr_frame,
            text="📁 จัดการโฟลเดอร์หลักประจำปีการศึกษา (Root Year Folders - ซิงค์ SQLite & year_folders.json อัตโนมัติ)",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#AEEA00"
        ).grid(row=0, column=0, sticky="w")

        self.lbl_root_folders_summary = ctk.CTkLabel(
            hdr_frame, text="ทั้งหมด 0 โฟลเดอร์",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD"
        )
        self.lbl_root_folders_summary.grid(row=0, column=1, padx=(10, 10), sticky="e")

        btn_refresh_roots = ctk.CTkButton(
            hdr_frame, text="🔄 รีเฟรช", width=85, height=30,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F",
            command=self.refresh_root_folders_table
        )
        btn_refresh_roots.grid(row=0, column=2, sticky="e")

        # Form Bar สำหรับเพิ่ม / แก้ไข Root Folder
        form_bar = ctk.CTkFrame(root_mgr_frame, fg_color="#162438", corner_radius=8)
        form_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=(2, 8))
        form_bar.grid_columnconfigure(0, weight=3)
        form_bar.grid_columnconfigure(3, weight=2)

        self.entry_root_folder_id = ctk.CTkEntry(
            form_bar, placeholder_text="วางลิงก์ Google Drive Folder URL หรือ Folder ID...",
            height=34, font=ctk.CTkFont(size=13)
        )
        self.entry_root_folder_id.grid(row=0, column=0, padx=(10, 5), pady=8, sticky="ew")
        self.entry_root_folder_id.bind("<FocusOut>", lambda e: self._auto_clean_root_folder_id_entry())

        btn_pick_root_drive = ctk.CTkButton(
            form_bar, text="🔍 เลือกจาก Drive", width=125, height=34,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F",
            command=lambda: self.open_google_picker("root_year_folder")
        )
        btn_pick_root_drive.grid(row=0, column=1, padx=3, pady=8)

        btn_fetch_root_meta = ctk.CTkButton(
            form_bar, text="🔄 ดึงชื่อจาก Drive", width=125, height=34,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#2980B9", hover_color="#2471A3",
            command=self.fetch_root_folder_info_from_drive
        )
        btn_fetch_root_meta.grid(row=0, column=2, padx=3, pady=8)

        self.entry_root_folder_name = ctk.CTkEntry(
            form_bar, placeholder_text="ชื่อโฟลเดอร์ (เช่น ภาพกิจกรรม 2570)",
            height=34, font=ctk.CTkFont(size=13)
        )
        self.entry_root_folder_name.grid(row=0, column=3, padx=5, pady=8, sticky="ew")
        self.entry_root_folder_name.bind("<KeyRelease>", lambda e: self._auto_extract_year_from_name_entry())

        self.entry_root_folder_year = ctk.CTkEntry(
            form_bar, placeholder_text="ปี พ.ศ. (2570)",
            width=105, height=34, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_root_folder_year.grid(row=0, column=4, padx=5, pady=8)

        self.btn_save_root_folder = ctk.CTkButton(
            form_bar, text="➕ เพิ่ม / บันทึก", width=125, height=34,
            font=ctk.CTkFont(size=13, weight="bold"), fg_color="#2ECC71", hover_color="#27AE60", text_color="black",
            command=self.save_root_year_folder_from_ui
        )
        self.btn_save_root_folder.grid(row=0, column=5, padx=4, pady=8)

        btn_clear_root_form = ctk.CTkButton(
            form_bar, text="🧹 ล้างช่อง", width=80, height=34,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#34495E", hover_color="#2C3E50",
            command=self.clear_root_folder_form
        )
        btn_clear_root_form.grid(row=0, column=6, padx=(3, 10), pady=8)

        # ตารางรายการ Root Year Folders (Scrollable)
        self.scr_root_folders = ctk.CTkScrollableFrame(root_mgr_frame, fg_color="#0D1622")
        self.scr_root_folders.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 10))
        self.scr_root_folders.grid_columnconfigure(2, weight=1)

        # โหลดข้อมูลเริ่มต้น
        self.refresh_root_folders_table()

    @staticmethod
    def extract_drive_folder_id(raw_text):
        """สกัด Google Drive Folder ID จาก URL เต็ม หรือคืนค่า ID เดิม (v6.27)"""
        if not raw_text:
            return ""
        s = str(raw_text).strip()
        m = re.search(r'/folders/([a-zA-Z0-9_-]{15,})', s)
        if m:
            return m.group(1)
        m2 = re.search(r'[?&]id=([a-zA-Z0-9_-]{15,})', s)
        if m2:
            return m2.group(1)
        m3 = re.search(r'/d/([a-zA-Z0-9_-]{15,})', s)
        if m3:
            return m3.group(1)
        return s.split("?")[0].split("#")[0].strip()

    def _auto_clean_root_folder_id_entry(self):
        raw_val = self.entry_root_folder_id.get().strip()
        cleaned = self.extract_drive_folder_id(raw_val)
        if cleaned and cleaned != raw_val:
            self.entry_root_folder_id.delete(0, "end")
            self.entry_root_folder_id.insert(0, cleaned)

    def _auto_extract_year_from_name_entry(self):
        name_val = self.entry_root_folder_name.get().strip()
        yr = self.db.extract_year_from_text(name_val)
        if yr:
            self.entry_root_folder_year.delete(0, "end")
            self.entry_root_folder_year.insert(0, yr)

    def clear_root_folder_form(self):
        if hasattr(self, 'entry_root_folder_id'):
            self.entry_root_folder_id.delete(0, "end")
        if hasattr(self, 'entry_root_folder_name'):
            self.entry_root_folder_name.delete(0, "end")
        if hasattr(self, 'entry_root_folder_year'):
            self.entry_root_folder_year.delete(0, "end")

    def fetch_root_folder_info_from_drive(self):
        """ดึงชื่อโฟลเดอร์จริงจาก Google Drive API ด้วย Folder ID และสกัดเลขปี พ.ศ. ให้อัตโนมัติ (v6.27)"""
        self._auto_clean_root_folder_id_entry()
        folder_id = self.entry_root_folder_id.get().strip()
        if not folder_id:
            messagebox.showwarning("คำเตือน", "กรุณาวางลิงก์โฟลเดอร์ หรือกรอก Folder ID ก่อนกดดึงชื่อจาก Drive")
            return

        if not self.sync_manager.connected:
            cred_path = self.entry_cred_path.get().strip() if hasattr(self, 'entry_cred_path') else "config/service_account.json"
            if cred_path and os.path.exists(cred_path):
                self.sync_manager.credentials_path = cred_path
            if not self.sync_manager.connect():
                messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเชื่อมต่อ Google Drive API ได้ กรุณาตรวจสอบไฟล์ Service Account JSON")
                return

        try:
            meta = self.sync_manager.drive_service.files().get(fileId=folder_id, fields="id, name, mimeType").execute()
            f_name = meta.get("name", "").strip()
            if f_name:
                self.entry_root_folder_name.delete(0, "end")
                self.entry_root_folder_name.insert(0, f_name)
                yr = self.db.extract_year_from_text(f_name)
                if yr:
                    self.entry_root_folder_year.delete(0, "end")
                    self.entry_root_folder_year.insert(0, yr)
                logger.info(f"[ROOT_FOLDERS] Fetched folder metadata from Drive: '{f_name}' (ID={folder_id}, Year={yr})")
            else:
                messagebox.showwarning("ไม่พบชื่อโฟลเดอร์", f"เชื่อมต่อสำเร็จแต่ไม่พบชื่อของ Folder ID: {folder_id}")
        except Exception as e:
            logger.error(f"[ROOT_FOLDERS] Error fetching Drive metadata for {folder_id}: {e}")
            messagebox.showerror("ไม่พบโฟลเดอร์บน Drive", f"ไม่สามารถดึงข้อมูลของ Folder ID '{folder_id}' ได้:\n{e}")

    def save_root_year_folder_from_ui(self):
        """บันทึกหรืออัปเดตโฟลเดอร์หลักประจำปีการศึกษาจากฟอร์ม UI ลง SQLite และ JSON (v6.27)"""
        self._auto_clean_root_folder_id_entry()
        folder_id = self.entry_root_folder_id.get().strip()
        folder_name = self.entry_root_folder_name.get().strip()
        academic_year = self.entry_root_folder_year.get().strip()

        if not folder_id:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณาระบุ Folder ID หรือวางลิงก์ Google Drive ของโฟลเดอร์")
            return

        # ถ้าผู้ใช้กรอกแค่ Folder ID/URL แต่ยังไม่กรอกชื่อโฟลเดอร์ ให้ลองดึงชื่อจาก Drive อัตโนมัติ
        if not folder_name and self.sync_manager:
            try:
                if not self.sync_manager.connected:
                    self.sync_manager.connect()
                if self.sync_manager.connected:
                    meta = self.sync_manager.drive_service.files().get(fileId=folder_id, fields="name").execute()
                    folder_name = meta.get("name", "").strip()
            except Exception:
                pass

        if not folder_name:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณาระบุชื่อโฟลเดอร์ (เช่น ภาพกิจกรรม 2570) หรือกดปุ่ม '🔄 ดึงชื่อจาก Drive'")
            return

        if not academic_year:
            academic_year = self.db.extract_year_from_text(folder_name)

        if not academic_year:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณาระบุปีการศึกษา พ.ศ. 4 หลัก (เช่น 2570)")
            return

        try:
            self.db.upsert_root_year_folder(
                folder_id=folder_id,
                folder_name=folder_name,
                academic_year=academic_year,
                is_active=1
            )
            self.clear_root_folder_form()
            self.refresh_root_folders_table()
            messagebox.showinfo(
                "บันทึกสำเร็จ",
                f"บันทึกโฟลเดอร์หลักเรียบร้อยแล้ว:\n"
                f"• ชื่อโฟลเดอร์: {folder_name}\n"
                f"• ปีการศึกษา: {academic_year}\n"
                f"• Folder ID: {folder_id}\n\n"
                f"(ซิงค์ลงตาราง SQLite root_year_folders และ config/year_folders.json อัตโนมัติแล้ว)"
            )
        except Exception as e:
            logger.error(f"[ROOT_FOLDERS] Error saving root folder: {e}")
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถบันทึกโฟลเดอร์หลักได้: {e}")

    def populate_root_folder_form_for_edit(self, item):
        """นำข้อมูลแถวที่เลือกขึ้นไปใส่ในช่องกรอกเพื่อแก้ไขได้ทันที (v6.27)"""
        self.clear_root_folder_form()
        self.entry_root_folder_id.insert(0, item.get("id", ""))
        self.entry_root_folder_name.insert(0, item.get("name", ""))
        self.entry_root_folder_year.insert(0, item.get("academic_year", ""))

    def on_toggle_root_folder_active(self, folder_id, switch_var):
        """สลับสถานะเปิด/ปิดการสแกนของโฟลเดอร์หลัก (v6.27)"""
        new_state = 1 if switch_var.get() else 0
        self.db.toggle_root_year_folder_active(folder_id, new_state)
        self.refresh_root_folders_table()

    def on_delete_root_folder_click(self, item):
        """ลบโฟลเดอร์หลักออกจากรายการหลังจากยืนยัน (v6.27)"""
        f_id = item.get("id", "")
        f_name = item.get("name", "")
        f_year = item.get("academic_year", "")
        confirm = messagebox.askyesno(
            "ยืนยันการลบโฟลเดอร์หลัก",
            f"คุณต้องการลบโฟลเดอร์หลัก '{f_name}' (ปี {f_year})\n"
            f"Folder ID: {f_id}\n"
            f"ออกจากรายการสแกนประจำปีใช่หรือไม่?\n\n"
            f"* หมายเหตุ: รูปภาพที่เคยสแกนไว้แล้วในฐานข้อมูลจะไม่ถูกลบ *"
        )
        if confirm:
            self.db.delete_root_year_folder(f_id)
            self.refresh_root_folders_table()

    def open_root_folder_in_browser(self, folder_id):
        if not folder_id:
            return
        import webbrowser
        webbrowser.open(f"https://drive.google.com/drive/folders/{folder_id}")

    def refresh_root_folders_table(self):
        """วาดตารางรายการโฟลเดอร์หลักประจำปีการศึกษาใหม่จากฐานข้อมูล SQLite (v6.27)"""
        if not hasattr(self, 'scr_root_folders'):
            return
        for w in self.scr_root_folders.winfo_children():
            w.destroy()

        folders = self.db.get_root_year_folders(active_only=False, include_photo_counts=True)
        active_cnt = sum(1 for f in folders if f.get("is_active", 1))
        total_photos_all = sum(f.get("photo_count", 0) for f in folders)

        if hasattr(self, 'lbl_root_folders_summary'):
            self.lbl_root_folders_summary.configure(
                text=f"ทั้งหมด {len(folders)} โฟลเดอร์ | เปิดสแกน {active_cnt} โฟลเดอร์ | รวมภาพในระบบ {total_photos_all:,} รูป"
            )

        if not folders:
            ctk.CTkLabel(
                self.scr_root_folders,
                text="ยังไม่มีโฟลเดอร์หลักประจำปีการศึกษา กรุณาเพิ่มโฟลเดอร์จากแถบด้านบน",
                font=ctk.CTkFont(size=14), text_color="#A2B5CD"
            ).pack(pady=30)
            return

        for idx, item in enumerate(folders):
            f_id = item["id"]
            f_name = item["name"]
            f_year = item["academic_year"] or "-"
            is_active = bool(item.get("is_active", 1))
            p_count = item.get("photo_count", 0)

            row_bg = "#162438" if is_active else "#111A26"
            row_card = ctk.CTkFrame(self.scr_root_folders, fg_color=row_bg, corner_radius=8)
            row_card.pack(fill="x", padx=4, pady=3)

            # 1. สวิตช์เปิด/ปิดการสแกน
            sw_var = ctk.BooleanVar(value=is_active)
            sw = ctk.CTkSwitch(
                row_card,
                text="เปิดสแกน" if is_active else "พักสแกน",
                variable=sw_var,
                width=95,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#2ECC71" if is_active else "#7F8C8D",
                progress_color="#27AE60",
                command=lambda fid=f_id, v=sw_var: self.on_toggle_root_folder_active(fid, v)
            )
            sw.pack(side="left", padx=(12, 8), pady=8)

            # 2. ป้ายปีการศึกษา (Badge)
            badge_color = "#8E44AD" if is_active else "#34495E"
            lbl_year = ctk.CTkLabel(
                row_card,
                text=f"ปี {f_year}",
                width=80,
                height=28,
                corner_radius=6,
                fg_color=badge_color,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="white"
            )
            lbl_year.pack(side="left", padx=6, pady=8)

            # 3. ชื่อโฟลเดอร์
            lbl_name = ctk.CTkLabel(
                row_card,
                text=f_name,
                width=200,
                anchor="w",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="white" if is_active else "#7F8C8D"
            )
            lbl_name.pack(side="left", padx=8, pady=8)

            # 4. Folder ID
            lbl_id = ctk.CTkLabel(
                row_card,
                text=f"ID: {f_id}",
                anchor="w",
                font=ctk.CTkFont(family="Consolas", size=12),
                text_color="#A2B5CD"
            )
            lbl_id.pack(side="left", padx=8, pady=8, fill="x", expand=True)

            # 5. จำนวนรูปภาพในฐานข้อมูลของปีนั้น
            lbl_cnt = ctk.CTkLabel(
                row_card,
                text=f"📸 {p_count:,} รูป",
                width=115,
                anchor="e",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#2ECC71" if p_count > 0 else "#95A5A6"
            )
            lbl_cnt.pack(side="left", padx=10, pady=8)

            # 6. ปุ่มจัดการ (ลบ / แก้ไข / เปิด Drive)
            btn_del = ctk.CTkButton(
                row_card, text="🗑️ ลบ", width=65, height=28,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#C0392B", hover_color="#962D22",
                command=lambda it=item: self.on_delete_root_folder_click(it)
            )
            btn_del.pack(side="right", padx=(4, 10), pady=8)

            btn_edit = ctk.CTkButton(
                row_card, text="✏️ แก้ไข", width=75, height=28,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#F39C12", hover_color="#D68910", text_color="black",
                command=lambda it=item: self.populate_root_folder_form_for_edit(it)
            )
            btn_edit.pack(side="right", padx=4, pady=8)

            btn_open = ctk.CTkButton(
                row_card, text="🌐 เปิด Drive", width=95, height=28,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#1F3A60", hover_color="#20334F",
                command=lambda fid=f_id: self.open_root_folder_in_browser(fid)
            )
            btn_open.pack(side="right", padx=4, pady=8)

    def select_cred_file(self):
        file_path = filedialog.askopenfilename(
            title="เลือกไฟล์ Google Service Account JSON",
            filetypes=[("JSON Files", "*.json")]
        )
        if file_path:
            self.entry_cred_path.delete(0, "end")
            self.entry_cred_path.insert(0, file_path)
            self.save_settings()
            messagebox.showinfo("บันทึกที่อยู่สำเร็จ", "บันทึกที่อยู่ไฟล์คีย์สิทธิ์ Google สำเร็จ")

    def clear_scan_history(self):
        confirm = messagebox.askyesno(
            "ล้างประวัติกิจกรรม", 
            "คุณแน่ใจหรือไม่ว่าต้องการลบฐานข้อมูลการสแกนกิจกรรมและรายชื่อใบหน้าที่ถูกจับคู่ก่อนหน้าทั้งหมดบน SQLite?\n(การกระทำนี้จะล้างประวัติในโปรแกรมใหม่เพื่อให้คุณสแกนใหม่ แต่จะไม่ส่งผลกระทบต่อใบหน้าครูต้นแบบ)"
        )
        if confirm:
            self.db.clear_scan_history()
            messagebox.showinfo("ล้างประวัติสำเร็จ", "ทำการล้างประวัติภาพกิจกรรมใน SQLite เรียบร้อยแล้ว")

    # ==================== (5) การจัดการ Settings & Configuration ====================
    def save_settings(self):
        """บันทึกข้อมูลการตั้งค่าลงไฟล์เก็บสถานะ"""
        settings_file = os.path.join(get_project_root(), "data", "app_settings.json")
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        
        settings = {
            "credentials_path": self.entry_cred_path.get().strip(),
            "drive_folder_id": self.entry_drive_folder_id.get().strip(),
            "sheets_id": self.entry_sheets_id.get().strip(),
            "json_folder_id": self.entry_json_folder_id.get().strip(),
            "delete_req_file_id": self.entry_delete_req_file_id.get().strip() if hasattr(self, "entry_delete_req_file_id") else "",
            "threshold": self.slider_threshold.get(),
            "use_gpu": self.chk_use_gpu.get(),
            "re_scan": self.chk_re_scan.get(),
            "fast_rescan": self.chk_fast_rescan.get() if hasattr(self, "chk_fast_rescan") else False
        }
        
        try:
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            # ปรับปรุงที่อยู่ credentials ใน gdrive_sync
            if settings["credentials_path"]:
                self.sync_manager.credentials_path = settings["credentials_path"]
        except Exception as e:
            logger.error(f"Error saving settings file: {e}")

    def load_settings(self):
        """โหลดข้อมูลการตั้งค่าเก่าจากไฟล์คืนในช่องป้อนข้อมูล"""
        settings_file = os.path.join(get_project_root(), "data", "app_settings.json")
        
        # กำหนดที่อยู่ตั้งต้นของไฟล์ credentials เป็นโฟลเดอร์โครงการ
        default_cred_path = os.path.join(get_project_root(), "config", "service_account.json")
        self.entry_cred_path.insert(0, default_cred_path)

        if not os.path.exists(settings_file):
            return

        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)

            # เก็บ settings ไว้ใน self.settings สำหรับใช้งานทั่วไป
            self.settings = settings

            if "credentials_path" in settings and settings["credentials_path"]:
                self.entry_cred_path.delete(0, "end")
                self.entry_cred_path.insert(0, settings["credentials_path"])
                self.sync_manager.credentials_path = settings["credentials_path"]
                
            if "drive_folder_id" in settings:
                self.entry_drive_folder_id.insert(0, settings["drive_folder_id"])
                
            if "sheets_id" in settings:
                self.entry_sheets_id.insert(0, settings["sheets_id"])
                
            if "json_folder_id" in settings:
                self.entry_json_folder_id.insert(0, settings["json_folder_id"])

            if "delete_req_file_id" in settings and hasattr(self, "entry_delete_req_file_id"):
                self.entry_delete_req_file_id.insert(0, settings["delete_req_file_id"])
                
            if "threshold" in settings:
                self.slider_threshold.set(settings["threshold"])
                self.update_thresh_label(settings["threshold"])
                
            if "use_gpu" in settings:
                if settings["use_gpu"]:
                    self.chk_use_gpu.select()
                else:
                    self.chk_use_gpu.deselect()
                    
            if "re_scan" in settings:
                if settings["re_scan"]:
                    self.chk_re_scan.select()
                else:
                    self.chk_re_scan.deselect()
                self.toggle_rescan_options()

            if "fast_rescan" in settings and hasattr(self, "chk_fast_rescan"):
                if settings["fast_rescan"] and self.chk_re_scan.get():
                    self.chk_fast_rescan.select()
                else:
                    self.chk_fast_rescan.deselect()
                    
        except Exception as e:
            logger.error(f"Error loading settings file: {e}")

    # ==================== (5) เมธอดสร้างและจัดการเพิ่มเติม ====================

    def create_global_console(self):
        # โซนแสดงผล Console Logs (ล่างสุดของฝั่งขวา) - แบ่ง 2 คอลัมน์ ซ้าย (Log Text) และ ขวา (Preview Image)
        # ปลด height=185 คงที่ออก เพื่อให้ขยายขอบเต็มพื้นที่ครึ่งล่างตาม Row Weight 1:1 อย่างเป็นธรรมชาติ
        self.console_frame = ctk.CTkFrame(self, fg_color="#101B2B")
        self.console_frame.grid(row=1, column=1, padx=20, pady=(0, 20), sticky="nsew")
        self.console_frame.grid_rowconfigure(0, weight=1)
        self.console_frame.grid_columnconfigure(0, weight=1) # ฝั่งซ้าย (Log)
        self.console_frame.grid_columnconfigure(1, weight=1) # ฝั่งขวา (Preview)

        # 1. เฟรมฝั่งซ้ายสำหรับ Console Debug Logs
        left_frame = ctk.CTkFrame(self.console_frame, fg_color="transparent")
        left_frame.grid(row=0, column=0, padx=(15, 7), pady=10, sticky="nsew")
        left_frame.grid_rowconfigure(1, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # แถบหัว Log และปุ่มควบคุม
        log_header = ctk.CTkFrame(left_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, pady=(0, 4), sticky="ew")
        log_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_header, text="Console Debug logs (แสดงสถานะ):", 
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD"
        ).grid(row=0, column=0, sticky="w")

        # กลุ่มปุ่มคัดกรอง Log (v6.11: All / Warning / Error)
        self.btn_filter_all = ctk.CTkButton(
            log_header, text="🌐 ทั้งหมด", width=75, height=28,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#2ECC71", hover_color="#27AE60", text_color="black",
            command=lambda: self.set_console_log_filter("all")
        )
        self.btn_filter_all.grid(row=0, column=1, padx=(0, 4), sticky="e")

        self.btn_filter_warning = ctk.CTkButton(
            log_header, text="⚠️ Warning", width=85, height=28,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", text_color="#FFA726",
            command=lambda: self.set_console_log_filter("warning")
        )
        self.btn_filter_warning.grid(row=0, column=2, padx=(0, 4), sticky="e")

        self.btn_filter_error = ctk.CTkButton(
            log_header, text="❌ Error", width=75, height=28,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", text_color="#FF5252",
            command=lambda: self.set_console_log_filter("error")
        )
        self.btn_filter_error.grid(row=0, column=3, padx=(0, 8), sticky="e")

        btn_copy_log = ctk.CTkButton(
            log_header, text="📋 คัดลอกที่เลือก", width=110, height=28, 
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F",
            command=self.copy_console_selection
        )
        btn_copy_log.grid(row=0, column=4, padx=(0, 4), sticky="e")

        btn_copy_all = ctk.CTkButton(
            log_header, text="📋 คัดลอกทั้งหมด", width=110, height=28, 
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F",
            command=self.copy_all_console_log
        )
        btn_copy_all.grid(row=0, column=5, padx=(0, 4), sticky="e")

        btn_clear_log = ctk.CTkButton(
            log_header, text="🧹 ล้าง Log", width=80, height=28, 
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#1F3A60", hover_color="#20334F",
            command=self.clear_console_log
        )
        btn_clear_log.grid(row=0, column=6, sticky="e")

        # กล่อง Textbox แสดง Log สีขาวพื้นฐานบนพื้นดำสไตล์ Terminal (ฟอนต์ขนาด 12pt อ่านง่าย)
        self.console_text = ctk.CTkTextbox(
            left_frame, font=ctk.CTkFont(family="Consolas", size=12), 
            fg_color="#0A111A", text_color="#ECEFF1"
        )
        self.console_text.grid(row=1, column=0, sticky="nsew")
        self.console_text.configure(state="normal") # คงสถานะ normal เพื่อให้เมาส์คลิกลาก Drag คลุมดำได้
        
        # ผูกอีเวนต์คีย์บอร์ดปิดกั้นการพิมพ์ และคลิกขวาเมนูสำหรับคัดลอกข้อความ
        self.console_text.bind("<Key>", self._block_console_keys)
        self.console_text.bind("<Button-3>", self.show_console_context_menu)

        # กำหนดคอนฟิกูเรชันสีข้อความสำหรับ 12 เฉดสีใน Textbox Console
        tb = self.console_text._textbox
        tb.tag_config("red", foreground="#FF5252")          # 1. แดง (Error)
        tb.tag_config("orange_red", foreground="#FF7043")   # 2. แดงส้ม (Warning)
        tb.tag_config("orange", foreground="#FFA726")       # 3. ส้ม (Init)
        tb.tag_config("yellow_orange", foreground="#FFCC80")# 4. เหลืองส้ม (Database)
        tb.tag_config("yellow", foreground="#FFEE58")       # 5. เหลือง (GDrive)
        tb.tag_config("yellow_green", foreground="#D4E157")  # 6. เหลืองเขียว (GSheets)
        tb.tag_config("green", foreground="#66BB6A")        # 7. เขียว (Match OK)
        tb.tag_config("green_blue", foreground="#26A69A")   # 8. เขียวอมฟ้า (Scan Info)
        tb.tag_config("blue", foreground="#26C6DA")         # 9. ฟ้า (Face AI)
        tb.tag_config("navy", foreground="#42A5F5")         # 10. น้ำเงิน (System)
        tb.tag_config("purple", foreground="#AB47BC")       # 11. ม่วง (UI)
        tb.tag_config("magenta", foreground="#E040FB")      # 12. ม่วงนีออน (Gallery / Fallback)
        tb.tag_config("cyan", foreground="#00E5FF")         # 13. ฟ้าสว่าง (Debug)
        tb.tag_config("schedule", foreground="#AEEA00")     # 14. เขียวมะนาว (Task Schedule)
        tb.tag_config("white", foreground="#ECEFF1")        # สีขาวปกติ

        # 2. เฟรมฝั่งขวาสำหรับ Real-time Bounding Box Preview และสตริงข้อความสรุปรายชื่อคู่แมตช์
        right_frame = ctk.CTkFrame(self.console_frame, fg_color="#0A111A")
        right_frame.grid(row=0, column=1, padx=(7, 15), pady=10, sticky="nsew")
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=2) # พื้นที่ภาพพรีวิว (กว้างกว่า)
        right_frame.grid_columnconfigure(1, weight=1) # พื้นที่ข้อความรายชื่อ (แคบกว่า)

        preview_header = ctk.CTkFrame(right_frame, fg_color="transparent")
        preview_header.grid(row=0, column=0, columnspan=2, padx=10, pady=(5, 2), sticky="ew")
        ctk.CTkLabel(
            preview_header, text="Real-time Face Matching Preview & Summary:", 
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ECC71"
        ).pack(side="left", anchor="w")

        self.btn_open_float_preview = ctk.CTkButton(
            preview_header, text="🔍 หน้าต่างแยก (Floating)",
            font=ctk.CTkFont(size=12, weight="bold"), height=24, width=150,
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.open_floating_preview_window
        )
        self.btn_open_float_preview.pack(side="right")

        # ป้ายสำหรับวาดแปะภาพพรีวิวผลงานการตรวจจับ (ด้านซ้ายของ right_frame)
        self.lbl_realtime_preview = ctk.CTkLabel(
            right_frame, text="[ แสดงภาพเปรียบเทียบการจับคู่ใบหน้าแบบ Real-time ]",
            font=ctk.CTkFont(size=13), text_color="#A2B5CD", fg_color="transparent"
        )
        self.lbl_realtime_preview.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # กล่องสำหรับพ่นรายชื่อครูและผลการแมตช์แบบสีเขียว/แดง (ด้านขวาของ right_frame)
        self.txt_match_summary = ctk.CTkTextbox(
            right_frame, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#0D1622", text_color="#ECEFF1"
        )
        self.txt_match_summary.grid(row=1, column=1, padx=(5, 10), pady=(0, 10), sticky="nsew")
        self.txt_match_summary.configure(state="normal")
        self.txt_match_summary.bind("<Key>", lambda e: "break") # บล็อกคีย์บอร์ด

        # ตั้งค่าสีข้อความในกล่องสรุปผลรายชื่อ
        self.txt_match_summary.tag_config("green", foreground="#66BB6A")
        self.txt_match_summary.tag_config("red", foreground="#FF5252")

    def clear_console_log(self):
        self.console_text.delete('1.0', 'end')
        self.console_log_history = []

    # ==================== (4) หน้าดูฐานข้อมูล SQLite ====================
    def setup_database_ui(self):
        from tkinter import ttk
        
        self.frame_database.grid_columnconfigure(0, weight=1)
        self.frame_database.grid_rowconfigure(4, weight=1)

        # หัวข้อ
        lbl_title = ctk.CTkLabel(
            self.frame_database, text="ดูข้อมูลในฐานข้อมูล SQLite", 
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 15))

        # โซนควบคุม (แถวบน)
        control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        control_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10), padx=2)
        
        ctk.CTkLabel(control_frame, text="เลือกตารางข้อมูล:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=15)
        
        self.option_db_table = ctk.CTkOptionMenu(
            control_frame, 
            values=[
                "รายชื่อคุณครู (staff_members - ครู)", 
                "รายชื่อนักเรียน (staff_members - นักเรียน)", 
                "ประวัติภาพถ่ายกิจกรรม (scanned_photos)", 
                "📷 ภาพที่ไม่พบใบหน้าคน (0 Faces - สิ่งของ/ป้าย/วิว)",
                "📷 ไฟล์ภาพดิบกล้อง (raw_camera_photos - RAW Files)",
                "ผลจับคู่ใบหน้าครู (detected_faces - ครู)",
                "ผลจับคู่ใบหน้านักเรียน (detected_faces - นักเรียน)",
                "📋 ตารางทั้งหมด: staff_members",
                "📋 ตารางทั้งหมด: scanned_photos",
                "📋 ตารางทั้งหมด: raw_camera_photos",
                "📋 ตารางทั้งหมด: detected_faces",
                "📋 ตารางทั้งหมด: scanned_photo_faces",
                "📋 ตารางทั้งหมด: staff_embeddings",
                "📋 ตารางทั้งหมด: root_year_folders"
            ],
            width=360,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            dropdown_font=ctk.CTkFont(size=14, weight="normal"),
            dropdown_fg_color="#101B2B",
            dropdown_hover_color="#1F3A60",
            dropdown_text_color="white",
            command=self.on_db_table_option_selected
        )
        self.option_db_table.pack(side="left", padx=5, pady=15)

        # ปุ่มรีเฟรช
        btn_refresh = ctk.CTkButton(control_frame, text="🔄 รีเฟรช", width=95, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.load_db_table_data(self.option_db_table.get(), page=1))
        btn_refresh.pack(side="left", padx=10, pady=15)

        # ปุ่มแก้ไขข้อมูลแถวที่เลือก (v6.34)
        self.btn_edit_db_record = ctk.CTkButton(
            control_frame, text="✏️ แก้ไขแถวที่เลือก", width=155, height=36,
            fg_color="#F39C12", hover_color="#D68910", text_color="#101B2B",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.show_db_record_edit_dialog
        )
        self.btn_edit_db_record.pack(side="left", padx=5, pady=15)

        # ปุ่มรีเซ็ตผลการจับคู่ของบุคคล
        self.btn_reset_matching = ctk.CTkButton(
            control_frame, text="🗑️ รีเซ็ตประวัติจับคู่", width=155, height=36,
            fg_color="#C0392B", hover_color="#962D22", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.reset_selected_person_matches
        )
        self.btn_reset_matching.pack(side="left", padx=10, pady=15)

        # ส่วนตั้งค่าและแก้ไข Personal Threshold ของบุคคล
        self.lbl_personal_thresh = ctk.CTkLabel(control_frame, text="Threshold บุคคล:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#AEEA00")
        self.lbl_personal_thresh.pack(side="left", padx=(10, 2), pady=15)

        self.entry_personal_thresh = ctk.CTkEntry(control_frame, width=75, height=36, placeholder_text="0.50", font=ctk.CTkFont(size=14, weight="bold"), justify="center")
        self.entry_personal_thresh.insert(0, "0.50")
        self.entry_personal_thresh.pack(side="left", padx=2, pady=15)
        self.bind_universal_entry_shortcuts(self.entry_personal_thresh)

        self.btn_save_personal_thresh = ctk.CTkButton(
            control_frame, text="💾 บันทึก Threshold", width=140, height=36,
            fg_color="#1F3A60", hover_color="#20334F", text_color="#00E5FF",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.save_selected_person_threshold
        )
        self.btn_save_personal_thresh.pack(side="left", padx=5, pady=15)

        # ปุ่มเปิดโฟลเดอร์ DB
        btn_open_folder = ctk.CTkButton(control_frame, text="📂 เปิดโฟลเดอร์ DB", width=150, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=self.open_db_folder)
        btn_open_folder.pack(side="right", padx=15, pady=15)

        # ปุ่มส่งออก CSV
        btn_export = ctk.CTkButton(control_frame, text="📊 ส่งออก CSV", width=115, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#2ECC71", hover_color="#27AE60", text_color="black", command=self.export_current_table)
        btn_export.pack(side="right", padx=5, pady=15)

        # โซนควบคุมที่สอง: ซิงค์ข้อมูล JSON และรูปภาพ ขึ้น Google Drive (v2.5/v2.8)
        sync_control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        sync_control_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15), padx=2)
        
        ctk.CTkLabel(sync_control_frame, text="ซิงค์ดัชนีและรูปภาพไป Google Drive:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=10)
        
        self.btn_sync_photos = ctk.CTkButton(
            sync_control_frame, text="0. 🖼️ ซิงค์รูปภาพทั้งหมดไป Drive", width=240, height=36,
            fg_color="#27AE60", hover_color="#219552", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.run_manual_photos_sync
        )
        self.btn_sync_photos.pack(side="left", padx=5, pady=10)

        self.btn_sync_json_all = ctk.CTkButton(
            sync_control_frame, text="1. ซิงค์ทั้งครูและนักเรียน", width=165, height=36,
            fg_color="#8E44AD", hover_color="#7D3C98", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.run_manual_json_sync("all")
        )
        self.btn_sync_json_all.pack(side="left", padx=5, pady=10)
        
        self.btn_sync_json_teachers = ctk.CTkButton(
            sync_control_frame, text="2. ซิงค์เฉพาะครู", width=125, height=36,
            fg_color="#2980B9", hover_color="#2471A3", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.run_manual_json_sync("teachers")
        )
        self.btn_sync_json_teachers.pack(side="left", padx=5, pady=10)
        
        self.btn_sync_json_students = ctk.CTkButton(
            sync_control_frame, text="3. ซิงค์เฉพาะนักเรียน", width=145, height=36,
            fg_color="#D35400", hover_color="#BA4A00", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.run_manual_json_sync("students")
        )
        self.btn_sync_json_students.pack(side="left", padx=5, pady=10)

        # โซนควบคุมที่สาม: ค้นหาข้อมูลในตารางฐานข้อมูล (v1.8.4 / v5.70 Blazing Fast & Debounce / v6.00 Universal Clipboard)
        search_control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        search_control_frame.grid(row=3, column=0, sticky="ew", pady=(0, 15), padx=2)
        
        ctk.CTkLabel(search_control_frame, text="🔍 ค้นหาข้อมูล:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=10)
        
        self.entry_db_search = ctk.CTkEntry(
            search_control_frame, 
            placeholder_text="พิมพ์คำค้นหา (Drive File ID, ลิงก์ Drive, Photo ID, ชื่อไฟล์, สกุลไฟล์ .HEIC/.JPG, ชื่อ, กิจกรรม...)", 
            height=36,
            font=ctk.CTkFont(size=14),
            width=480
        )
        self.entry_db_search.pack(side="left", padx=5, pady=10, fill="x", expand=True)
        self.entry_db_search.bind("<KeyRelease>", self.on_db_search_key_release)
        self.entry_db_search.bind("<Return>", lambda e: self.trigger_db_search_instant())
        self.bind_universal_entry_shortcuts(self.entry_db_search, on_change_callback=self.on_db_search_key_release)

        btn_run_search = ctk.CTkButton(
            search_control_frame, text="🔍 ค้นหา", width=100, height=36,
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.trigger_db_search_instant
        )
        btn_run_search.pack(side="right", padx=(5, 15), pady=10)

        btn_clear_search = ctk.CTkButton(
            search_control_frame, text="❌ ล้างการค้นหา", width=120, height=36,
            fg_color="#34495E", hover_color="#2C3E50", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.clear_db_search
        )
        btn_clear_search.pack(side="right", padx=5, pady=10)

        # โซนแสดงตาราง (Treeview)
        table_container = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        table_container.grid(row=4, column=0, sticky="nsew", padx=2, pady=(0, 5))
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        # สไตล์ตาราง Treeview (ขยายความสูงแถวเป็น 32px และฟอนต์ 12pt)
        self.style = ttk.Style()
        self.style.theme_use("default")
        self.style.configure(
            "Treeview",
            background="#1C2D42",
            foreground="white",
            rowheight=32,
            font=("Segoe UI", 12),
            fieldbackground="#1C2D42",
            bordercolor="#101B2B",
            borderwidth=0
        )
        self.style.configure("Treeview.Heading", background="#101B2B", foreground="#6CA6CD", font=("Segoe UI", 13, "bold"))
        self.style.map("Treeview", background=[("selected", "#1F3A60")])

        # สร้าง Treeview (รองรับ Shift+Click และ Ctrl+Click เพื่อเลือกหลายแถวพร้อมกัน v5.40)
        self.db_tree = ttk.Treeview(table_container, show="headings", selectmode="extended")
        self.db_tree.grid(row=0, column=0, sticky="nsew", padx=(15, 0), pady=(0, 15))
        
        # ป้ายแนะนำการดับเบิ้ลคลิก (v2.6)
        self.lbl_db_hint = ctk.CTkLabel(table_container, text="💡 ดับเบิ้ลคลิกที่แถวข้อมูล (ตาราง scanned_photos, detected_faces ผลการจับคู่ ฯลฯ) เพื่อเปิดลิงก์รูปภาพบน Google Drive ในเบราว์เซอร์", font=ctk.CTkFont(size=13, slant="italic"), text_color="#F39C12")
        self.lbl_db_hint.grid(row=1, column=0, columnspan=2, pady=(0, 5), sticky="e", padx=15)

        self.db_tree.bind("<Double-1>", self.on_db_tree_double_click)
        self.db_tree.bind("<<TreeviewSelect>>", self.on_db_tree_select)

        # แถบสกรอลด้านแนวตั้ง
        tree_scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.db_tree.yview)
        tree_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 15), pady=15)
        self.db_tree.configure(yscrollcommand=tree_scrollbar.set)

        # โซนควบคุมการแบ่งหน้า Pagination (v2.5/v2.8)
        pagination_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        pagination_frame.grid(row=5, column=0, sticky="ew", pady=(5, 15), padx=2)

        self.btn_db_first_page = ctk.CTkButton(pagination_frame, text="⏮️ หน้าแรก", width=105, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.change_db_page(1))
        self.btn_db_first_page.pack(side="left", padx=5, pady=8)

        self.btn_db_prev_page = ctk.CTkButton(pagination_frame, text="◀️ ก่อนหน้า", width=105, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.change_db_page(self.db_current_page - 1))
        self.btn_db_prev_page.pack(side="left", padx=5, pady=8)

        self.lbl_db_page_info = ctk.CTkLabel(pagination_frame, text="หน้า 1 / 1 (พบทั้งหมด 0 รายการ)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD")
        self.lbl_db_page_info.pack(side="left", padx=20, pady=8, expand=True)

        self.btn_db_next_page = ctk.CTkButton(pagination_frame, text="ถัดไป ▶️", width=105, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.change_db_page(self.db_current_page + 1))
        self.btn_db_next_page.pack(side="right", padx=5, pady=8)

        self.btn_db_last_page = ctk.CTkButton(pagination_frame, text="หน้าสุดท้าย ⏭️", width=115, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.change_db_page(999999))
        self.btn_db_last_page.pack(side="right", padx=5, pady=8)

    def change_db_page(self, target_page):
        """เปลี่ยนหน้าการแสดงผลในตาราง SQL Viewer"""
        self.db_current_page = max(1, target_page)
        self.load_db_table_data(page=self.db_current_page)

    def update_pagination_controls(self, total_rows):
        """อัปเดตสถานะปุ่มกด และข้อความแสดงจำนวนหน้าของ Pagination Bar"""
        import math
        total_pages = max(1, math.ceil(total_rows / self.db_page_size))
        if self.db_current_page > total_pages:
            self.db_current_page = total_pages

        self.lbl_db_page_info.configure(text=f"หน้า {self.db_current_page} / {total_pages} (พบทั้งหมด {total_rows:,} รายการ)")
        
        self.btn_db_first_page.configure(state="normal" if self.db_current_page > 1 else "disabled")
        self.btn_db_prev_page.configure(state="normal" if self.db_current_page > 1 else "disabled")
        self.btn_db_next_page.configure(state="normal" if self.db_current_page < total_pages else "disabled")
        self.btn_db_last_page.configure(state="normal" if self.db_current_page < total_pages else "disabled")

    def run_manual_photos_sync(self):
        """รันกระบวนการซิงค์ข้อมูลดัชนีภาพถ่ายไปยัง Google Drive (v4.19 Fix)"""
        self.run_manual_json_sync("all")

    def on_db_tree_double_click(self, event):
        """Handler สำหรับเมื่อผู้ใช้ดับเบิ้ลคลิกที่แถวใน Treeview: เปิดแก้ไขสำหรับ staff_members หรือเปิดลิงก์ Drive (v6.34)"""
        selected_items = self.db_tree.selection()
        if not selected_items:
            return
            
        selected_table_text = self.option_db_table.get()
        if "staff_members" in selected_table_text:
            self.show_db_record_edit_dialog()
            return

        item = selected_items[0]
        item_values = self.db_tree.item(item, "values")
        if not item_values:
            return

        import webbrowser
        # 1. เช็คว่ามี URL ตรงๆ ใน values หรือไม่
        for val in item_values:
            val_str = str(val).strip()
            if val_str.startswith("http://") or val_str.startswith("https://"):
                target_url = self.sync_manager.format_drive_view_url(val_str) if hasattr(self, 'sync_manager') and hasattr(self.sync_manager, 'format_drive_view_url') else val_str
                webbrowser.open(target_url)
                return

        # 2. ค้นหา photo_id / drive_file_id จากแถวที่ดับเบิ้ลคลิก
        photo_id = None
        for val in item_values:
            val_str = str(val).strip()
            # รองรับทั้งแบบ P00123 หรือ Drive File ID ความยาวมากกว่า 10 ตัวอักษร
            if (val_str.startswith("P") and len(val_str) == 6 and val_str[1:].isdigit()) or (len(val_str) >= 10 and not " " in val_str and not val_str.endswith("%")):
                photo_id = val_str
                break

        # ถ้าในแถวมีคอลัมน์ที่ 2 (index 1) ให้ลองใช้เป็น Photo ID
        if not photo_id and len(item_values) > 1:
            possible_id = str(item_values[1]).strip()
            if len(possible_id) >= 5 and not " " in possible_id:
                photo_id = possible_id

        if photo_id:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT drive_link, drive_file_id FROM scanned_photos WHERE photo_id = ? OR drive_file_id = ?
                    UNION
                    SELECT drive_link, drive_file_id FROM raw_camera_photos WHERE photo_id = ? OR drive_file_id = ?
                    LIMIT 1
                """, (photo_id, photo_id, photo_id, photo_id))
                row = cursor.fetchone()
                if row:
                    link, fid = row
                    if link and link.startswith("http"):
                        target_url = self.sync_manager.format_drive_view_url(link) if hasattr(self, 'sync_manager') and hasattr(self.sync_manager, 'format_drive_view_url') else link
                        webbrowser.open(target_url)
                    elif fid:
                        webbrowser.open(f"https://drive.google.com/file/d/{fid}/view")
                elif len(photo_id) >= 10:
                    # ถ้าค้นใน DB ไม่เจอ แต่หน้าตาเหมือน Drive File ID ให้เปิดตรงๆ
                    webbrowser.open(f"https://drive.google.com/file/d/{photo_id}/view")

    def show_db_record_edit_dialog(self):
        """เปิดหน้าต่างแก้ไขข้อมูลของแถวที่เลือกในฐานข้อมูล SQLite รองรับ staff_members และ scanned_photos (v6.34)"""
        selected_items = self.db_tree.selection()
        if not selected_items:
            messagebox.showwarning("คำเตือน", "กรุณาคลิกเลือกแถวข้อมูลที่ต้องการแก้ไขในตารางก่อน")
            return

        item = selected_items[0]
        item_values = self.db_tree.item(item, "values")
        if not item_values:
            messagebox.showwarning("คำเตือน", "ไม่พบข้อมูลในแถวที่เลือก")
            return

        selected_table_text = self.option_db_table.get()

        # =========================================================================
        # CASE 1: ตาราง staff_members (ครู, นักเรียน, หรือ ตารางทั้งหมด: staff_members)
        # =========================================================================
        if "staff_members" in selected_table_text:
            try:
                staff_id = int(item_values[0])
            except (ValueError, TypeError):
                messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถอ่านรหัส ID จากแถวข้อมูลได้: {item_values[0]}")
                return

            staff_rec = self.db.get_staff_member_by_id(staff_id)
            if not staff_rec:
                messagebox.showerror("ข้อผิดพลาด", f"ไม่พบข้อมูลบุคลากร ID: {staff_id} ในฐานข้อมูล")
                return

            # สร้าง Modal Dialog แก้ไขข้อมูลบุคลากร
            dialog = ctk.CTkToplevel(self)
            dialog.title(f"✏️ แก้ไขข้อมูลบุคลากร (ID: {staff_id}) - SQLite DB Editor")
            dialog.geometry("560x650")
            dialog.resizable(False, False)
            dialog.transient(self)
            dialog.grab_set()

            self.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() // 2) - 280
            y = self.winfo_y() + (self.winfo_height() // 2) - 325
            dialog.geometry(f"+{x}+{y}")

            # หัวข้อ Dialog
            ctk.CTkLabel(
                dialog, text=f"✏️ แก้ไขข้อมูลบุคลากรใน SQLite (v6.34)",
                font=ctk.CTkFont(size=18, weight="bold"), text_color="#5CACEE"
            ).pack(pady=(15, 5))

            ctk.CTkLabel(
                dialog, text=f"รหัส ID ในระบบ: #{staff_id} • ตาราง staff_members",
                font=ctk.CTkFont(size=13), text_color="#A2B5CD"
            ).pack(pady=(0, 10))

            form_scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent", height=490)
            form_scroll.pack(fill="both", expand=True, padx=20, pady=5)

            # 1. บทบาท (Role)
            f_role = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_role.pack(fill="x", pady=5)
            ctk.CTkLabel(f_role, text="บทบาท (Role):", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            curr_role = (staff_rec.get("role") or "teacher").strip()
            role_options = ["teacher", "student"]
            if curr_role not in role_options:
                role_options.append(curr_role)
            opt_role = ctk.CTkOptionMenu(
                f_role, values=role_options, height=32, font=ctk.CTkFont(size=13),
                dropdown_font=ctk.CTkFont(size=13), dropdown_fg_color="#101B2B", dropdown_hover_color="#1F3A60"
            )
            opt_role.set(curr_role)
            opt_role.pack(side="left", fill="x", expand=True)

            # 2. สถานะ (Status) - Dropdown active / inactive ตามที่ผู้ใช้ระบุ
            f_status = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_status.pack(fill="x", pady=5)
            ctk.CTkLabel(f_status, text="สถานะ (Status):", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            curr_status = (staff_rec.get("status") or "active").strip()
            status_options = ["active", "inactive"]
            if curr_status not in status_options:
                status_options.append(curr_status)
            opt_status = ctk.CTkOptionMenu(
                f_status, values=status_options, height=32, font=ctk.CTkFont(size=13),
                dropdown_font=ctk.CTkFont(size=13), dropdown_fg_color="#101B2B", dropdown_hover_color="#1F3A60"
            )
            opt_status.set(curr_status)
            opt_status.pack(side="left", fill="x", expand=True)

            # 3. ชื่อ-นามสกุล (Name)
            f_name = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_name.pack(fill="x", pady=5)
            ctk.CTkLabel(f_name, text="ชื่อ-นามสกุล:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_name = ctk.CTkEntry(f_name, height=32, font=ctk.CTkFont(size=13))
            entry_name.insert(0, staff_rec.get("name") or "")
            entry_name.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_name)

            # 4. หมวดในสังกัด (Department) - Dropdown 12 หมวดหมู่สวีวิทยา (ไม่มีคำว่ากลุ่มสาระ) + อื่นๆ
            f_dept = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_dept.pack(fill="x", pady=5)
            ctk.CTkLabel(f_dept, text="หมวดในสังกัด:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            
            curr_dept = clean_department_name(staff_rec.get("department") or "")
            entry_dept = ctk.CTkEntry(f_dept, height=32, font=ctk.CTkFont(size=13), placeholder_text="ระบุสังกัด...")
            entry_dept.insert(0, curr_dept)

            dept_menu_values = ["(เลือกสังกัด)"] + SW_DEPARTMENTS
            def on_dialog_dept_select(val):
                if val == "(เลือกสังกัด)":
                    entry_dept.delete(0, "end")
                elif val == "อื่นๆ (ระบุเอง)":
                    entry_dept.delete(0, "end")
                    entry_dept.focus_set()
                else:
                    entry_dept.delete(0, "end")
                    entry_dept.insert(0, val)

            opt_dept = ctk.CTkOptionMenu(
                f_dept, values=dept_menu_values, height=32, width=170, font=ctk.CTkFont(size=13),
                dropdown_font=ctk.CTkFont(size=13), dropdown_fg_color="#101B2B", dropdown_hover_color="#1F3A60",
                command=on_dialog_dept_select
            )
            opt_dept.set(curr_dept if curr_dept in SW_DEPARTMENTS else "(เลือกสังกัด)")
            opt_dept.pack(side="left", padx=(0, 6))
            entry_dept.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_dept)

            # 5. รหัสประจำตัว (Student ID / Staff Code)
            f_sid = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_sid.pack(fill="x", pady=5)
            ctk.CTkLabel(f_sid, text="รหัสประจำตัว:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_sid = ctk.CTkEntry(f_sid, height=32, font=ctk.CTkFont(size=13), placeholder_text="เช่น 12345")
            entry_sid.insert(0, staff_rec.get("student_id") or "")
            entry_sid.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_sid)

            # 6. ห้องเรียน / ระดับชั้น (Classroom)
            f_class = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_class.pack(fill="x", pady=5)
            ctk.CTkLabel(f_class, text="ระดับชั้น / ห้องเรียน:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_class = ctk.CTkEntry(f_class, height=32, font=ctk.CTkFont(size=13), placeholder_text="เช่น ม.1/1")
            entry_class.insert(0, staff_rec.get("class_room") or "")
            entry_class.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_class)

            # 7. ปีการศึกษาที่จบ (Graduation Year)
            f_grad = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_grad.pack(fill="x", pady=5)
            ctk.CTkLabel(f_grad, text="ปีการศึกษาที่จบ:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_grad = ctk.CTkEntry(f_grad, height=32, font=ctk.CTkFont(size=13), placeholder_text="เช่น 2568")
            entry_grad.insert(0, staff_rec.get("graduation_year") or "")
            entry_grad.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_grad)

            # 8. ปีการศึกษาที่เข้า (Entry Year)
            f_entry = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_entry.pack(fill="x", pady=5)
            ctk.CTkLabel(f_entry, text="ปีการศึกษาที่เข้า:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_entry_yr = ctk.CTkEntry(f_entry, height=32, font=ctk.CTkFont(size=13), placeholder_text="เช่น 2566")
            entry_entry_yr.insert(0, staff_rec.get("entry_year") or "")
            entry_entry_yr.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_entry_yr)

            # 9. Personal Threshold
            f_thresh = ctk.CTkFrame(form_scroll, fg_color="transparent")
            f_thresh.pack(fill="x", pady=5)
            ctk.CTkLabel(f_thresh, text="Personal Threshold:", width=140, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_thresh = ctk.CTkEntry(f_thresh, height=32, font=ctk.CTkFont(size=13), placeholder_text="0.50")
            entry_thresh.insert(0, str(staff_rec.get("personal_threshold") or 0.50))
            entry_thresh.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_thresh)

            # โซนปุ่มบันทึกและยกเลิก
            f_btns = ctk.CTkFrame(dialog, fg_color="transparent")
            f_btns.pack(fill="x", padx=20, pady=(10, 15))

            def save_staff_record_changes():
                new_name = entry_name.get().strip()
                if not new_name:
                    messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อ-นามสกุล", parent=dialog)
                    return

                new_role = opt_role.get().strip()
                new_status = opt_status.get().strip()
                new_dept = clean_department_name(entry_dept.get().strip())
                new_sid = entry_sid.get().strip()
                new_cls = entry_class.get().strip()
                new_grad = entry_grad.get().strip()
                new_entry = entry_entry_yr.get().strip()
                
                try:
                    new_pt = float(entry_thresh.get().strip())
                except ValueError:
                    messagebox.showwarning("คำเตือน", "Personal Threshold ต้องเป็นตัวเลข เช่น 0.50", parent=dialog)
                    return

                # บันทึกลง SQLite
                success = self.db.update_staff_member_full(
                    staff_id=staff_id,
                    name=new_name,
                    department=new_dept,
                    status=new_status,
                    role=new_role,
                    student_id=new_sid,
                    class_room=new_cls,
                    personal_threshold=new_pt,
                    graduation_year=new_grad,
                    entry_year=new_entry
                )

                if success:
                    self._cached_teachers_list = None
                    self._db_cached_count_key = None
                    if hasattr(self, 'load_staff_list'):
                        self.load_staff_list(refresh_db=True)
                    self.load_db_table_data(selected_table_text, page=self.db_current_page)
                    dialog.destroy()
                    messagebox.showinfo("สำเร็จ", f"บันทึกข้อมูลบุคลากร ID: {staff_id} ({new_name}) ลงฐานข้อมูล SQLite เรียบร้อยแล้ว")
                else:
                    messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถบันทึกข้อมูลได้ กรุณาลองใหม่อีกครั้ง", parent=dialog)

            btn_save = ctk.CTkButton(
                f_btns, text="💾 บันทึกการแก้ไข", height=38, font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="#2ECC71", hover_color="#27AE60", text_color="#101B2B",
                command=save_staff_record_changes
            )
            btn_save.pack(side="left", fill="x", expand=True, padx=(0, 6))

            btn_cancel = ctk.CTkButton(
                f_btns, text="ยกเลิก", height=38, width=110, font=ctk.CTkFont(size=13),
                fg_color="#34495E", hover_color="#2C3E50", command=dialog.destroy
            )
            btn_cancel.pack(side="right")

        # =========================================================================
        # CASE 2: ตาราง scanned_photos (ประวัติภาพถ่าย หรือ ตารางทั้งหมด: scanned_photos)
        # =========================================================================
        elif "scanned_photos" in selected_table_text:
            photo_id = str(item_values[0]).strip()
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id, event_name, academic_year, drive_file_id FROM scanned_photos WHERE photo_id = ?", (photo_id,))
            p_row = cursor.fetchone()
            conn.close()

            if not p_row:
                messagebox.showerror("ข้อผิดพลาด", f"ไม่พบข้อมูลภาพถ่าย ID: {photo_id} ในฐานข้อมูล")
                return

            curr_event = p_row[1] or ""
            curr_year = p_row[2] or ""
            curr_fid = p_row[3] or ""

            dialog = ctk.CTkToplevel(self)
            dialog.title(f"✏️ แก้ไขข้อมูลภาพถ่าย ({photo_id}) - SQLite DB Editor")
            dialog.geometry("500x320")
            dialog.resizable(False, False)
            dialog.transient(self)
            dialog.grab_set()

            self.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() // 2) - 250
            y = self.winfo_y() + (self.winfo_height() // 2) - 160
            dialog.geometry(f"+{x}+{y}")

            ctk.CTkLabel(
                dialog, text=f"✏️ แก้ไขข้อมูลภาพถ่ายใน SQLite (v6.34)",
                font=ctk.CTkFont(size=18, weight="bold"), text_color="#5CACEE"
            ).pack(pady=(15, 5))

            ctk.CTkLabel(
                dialog, text=f"Photo ID: {photo_id} • Drive File ID: {curr_fid}",
                font=ctk.CTkFont(size=13), text_color="#A2B5CD"
            ).pack(pady=(0, 15))

            # ชื่อกิจกรรม (Event Name)
            f_ev = ctk.CTkFrame(dialog, fg_color="transparent")
            f_ev.pack(fill="x", padx=25, pady=6)
            ctk.CTkLabel(f_ev, text="ชื่อกิจกรรม:", width=120, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_ev = ctk.CTkEntry(f_ev, height=34, font=ctk.CTkFont(size=13))
            entry_ev.insert(0, curr_event)
            entry_ev.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_ev)

            # ปีการศึกษา (Academic Year)
            f_yr = ctk.CTkFrame(dialog, fg_color="transparent")
            f_yr.pack(fill="x", padx=25, pady=6)
            ctk.CTkLabel(f_yr, text="ปีการศึกษา:", width=120, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            entry_yr = ctk.CTkEntry(f_yr, height=34, font=ctk.CTkFont(size=13), placeholder_text="เช่น 2568")
            entry_yr.insert(0, curr_year)
            entry_yr.pack(side="left", fill="x", expand=True)
            self.bind_universal_entry_shortcuts(entry_yr)

            # ปุ่มบันทึกและยกเลิก
            f_btns2 = ctk.CTkFrame(dialog, fg_color="transparent")
            f_btns2.pack(fill="x", padx=25, pady=(20, 15))

            def save_photo_record_changes():
                new_event = entry_ev.get().strip()
                new_year = entry_yr.get().strip()
                success = self.db.update_scanned_photo_record(photo_id, event_name=new_event, academic_year=new_year)
                if success:
                    self.load_db_table_data(selected_table_text, page=self.db_current_page)
                    dialog.destroy()
                    messagebox.showinfo("สำเร็จ", f"บันทึกข้อมูลภาพถ่าย {photo_id} เรียบร้อยแล้ว")
                else:
                    messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถบันทึกข้อมูลได้", parent=dialog)

            btn_save2 = ctk.CTkButton(
                f_btns2, text="💾 บันทึกการแก้ไข", height=38, font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="#2ECC71", hover_color="#27AE60", text_color="#101B2B",
                command=save_photo_record_changes
            )
            btn_save2.pack(side="left", fill="x", expand=True, padx=(0, 6))

            btn_cancel2 = ctk.CTkButton(
                f_btns2, text="ยกเลิก", height=38, width=110, font=ctk.CTkFont(size=13),
                fg_color="#34495E", hover_color="#2C3E50", command=dialog.destroy
            )
            btn_cancel2.pack(side="right")

        else:
            messagebox.showinfo(
                "ข้อมูล",
                "ระบบแก้ไขข้อมูลแถวรองรับการแก้ไขตาราง:\n"
                "1. รายชื่อคุณครู / รายชื่อนักเรียน / ตาราง staff_members ทั้งหมด\n"
                "2. ประวัติภาพถ่ายกิจกรรม / ตาราง scanned_photos ทั้งหมด\n\n"
                "สำหรับตารางอื่น ๆ เป็นตารางผลการคำนวณและเวกเตอร์ใบหน้า"
            )

    def bind_universal_entry_shortcuts(self, entry_widget, on_change_callback=None):
        """
        ผูกปุ่มลัดคีย์บอร์ดสากล (Ctrl+V, Ctrl+C, Ctrl+A, Ctrl+X) รองรับแป้นพิมพ์ภาษาไทย (Virtual Keycodes 86, 67, 65, 88)
        พร้อมสร้างเมนูคลิกขวา (Context Menu) สไตล์ Modern Dark Navy Blue (v6.00)
        """
        target_widget = getattr(entry_widget, "_entry", entry_widget)

        def do_paste(event=None):
            try:
                text = self.clipboard_get()
                if text:
                    try:
                        if target_widget.select_present():
                            target_widget.delete("sel.first", "sel.last")
                    except Exception:
                        pass
                    target_widget.insert("insert", text)
                    if on_change_callback:
                        on_change_callback()
            except Exception:
                pass
            return "break"

        def do_copy(event=None):
            try:
                if target_widget.select_present():
                    text = target_widget.selection_get()
                    self.clipboard_clear()
                    self.clipboard_append(text)
            except Exception:
                pass
            return "break"

        def do_cut(event=None):
            try:
                if target_widget.select_present():
                    text = target_widget.selection_get()
                    self.clipboard_clear()
                    self.clipboard_append(text)
                    target_widget.delete("sel.first", "sel.last")
                    if on_change_callback:
                        on_change_callback()
            except Exception:
                pass
            return "break"

        def do_select_all(event=None):
            try:
                target_widget.select_range(0, "end")
                target_widget.icursor("end")
            except Exception:
                pass
            return "break"

        def do_clear(event=None):
            try:
                entry_widget.delete(0, "end")
                if on_change_callback:
                    on_change_callback()
            except Exception:
                pass
            return "break"

        def on_control_key(event):
            kc = getattr(event, "keycode", 0)
            if kc == 86 or event.keysym in ("v", "V", "Thai_oang"):
                return do_paste(event)
            elif kc == 67 or event.keysym in ("c", "C", "Thai_ae"):
                return do_copy(event)
            elif kc == 88 or event.keysym in ("x", "X", "Thai_popla"):
                return do_cut(event)
            elif kc == 65 or event.keysym in ("a", "A", "Thai_fofan"):
                return do_select_all(event)

        for w in (target_widget, entry_widget):
            try:
                w.bind("<Control-KeyPress>", on_control_key, add="+")
                w.bind("<Control-v>", do_paste, add="+")
                w.bind("<Control-V>", do_paste, add="+")
                w.bind("<Control-c>", do_copy, add="+")
                w.bind("<Control-C>", do_copy, add="+")
                w.bind("<Control-x>", do_cut, add="+")
                w.bind("<Control-X>", do_cut, add="+")
                w.bind("<Control-a>", do_select_all, add="+")
                w.bind("<Control-A>", do_select_all, add="+")
            except Exception:
                pass

        # Context menu (Right-click menu)
        context_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#101B2B",
            fg="#E0E6ED",
            activebackground="#1F3A60",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 11)
        )
        context_menu.add_command(label="📋  วาง (Paste)", command=do_paste)
        context_menu.add_command(label="📄  คัดลอก (Copy)", command=do_copy)
        context_menu.add_command(label="✂️  ตัด (Cut)", command=do_cut)
        context_menu.add_separator()
        context_menu.add_command(label="🔘  เลือกทั้งหมด (Select All)", command=do_select_all)
        context_menu.add_command(label="❌  ล้างข้อความ (Clear)", command=do_clear)

        def show_context_menu(event):
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

        for w in (target_widget, entry_widget):
            try:
                w.bind("<Button-3>", show_context_menu, add="+")
            except Exception:
                pass

    def on_db_table_option_selected(self, selected_table_text):
        """เมื่อผู้ใช้เปลี่ยนตารางที่ต้องการดูใน OptionMenu (v6.10)"""
        if "staff_members" in selected_table_text:
            self.db_sort_col = "id"
            self.db_sort_desc = False
        elif "detected_faces" in selected_table_text:
            self.db_sort_col = "match_id"
            self.db_sort_desc = True
        elif "scanned_photos" in selected_table_text or "0 Faces" in selected_table_text or "raw_camera_photos" in selected_table_text or "ไฟล์ภาพดิบกล้อง" in selected_table_text:
            self.db_sort_col = "photo_id"
            self.db_sort_desc = True
        else:
            self.db_sort_col = None
            self.db_sort_desc = True
        self.load_db_table_data(selected_table_text, page=1)

    def sort_db_table_by_column(self, col_id):
        """สลับการเรียงลำดับ ASC / DESC เมื่อผู้ใช้คลิกหัวตาราง (v6.10)"""
        if self.db_sort_col == col_id:
            self.db_sort_desc = not self.db_sort_desc
        else:
            self.db_sort_col = col_id
            if col_id in ("name", "department", "event", "file_name", "file_ext", "brand_ext"):
                self.db_sort_desc = False
            else:
                self.db_sort_desc = True
        self.load_db_table_data(page=1)

    def on_db_search_key_release(self, event=None):
        """Debounce การค้นหาฐานข้อมูล 350ms เพื่อให้ผู้ใช้พิมพ์ได้ลื่นไหล ไม่ค้าง (v5.70)"""
        if event and event.keysym in ("Return", "Up", "Down", "Left", "Right", "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Tab"):
            return
            
        if self._db_search_timer is not None:
            try:
                self.after_cancel(self._db_search_timer)
            except Exception:
                pass
        self._db_search_timer = self.after(350, self._exec_debounced_db_search)

    def _exec_debounced_db_search(self):
        self._db_search_timer = None
        self.load_db_table_data(page=1)

    def trigger_db_search_instant(self):
        """สั่งค้นหาทันทีเมื่อกดปุ่ม Enter หรือคลิกปุ่มค้นหา (v5.70)"""
        if self._db_search_timer is not None:
            try:
                self.after_cancel(self._db_search_timer)
            except Exception:
                pass
            self._db_search_timer = None
        self.load_db_table_data(page=1)

    def clear_db_search(self):
        if self._db_search_timer is not None:
            try:
                self.after_cancel(self._db_search_timer)
            except Exception:
                pass
            self._db_search_timer = None
        if hasattr(self, 'entry_db_search'):
            self.entry_db_search.delete(0, "end")
        self.load_db_table_data(page=1)

    def load_db_table_data(self, selected_table_text=None, page=1):
        if not selected_table_text:
            selected_table_text = self.option_db_table.get()

        self.db_current_page = page
        offset = (self.db_current_page - 1) * self.db_page_size

        search_query = ""
        if hasattr(self, 'entry_db_search'):
            search_query = self.entry_db_search.get().strip()
        
        # ล้างข้อมูลเดิมใน Treeview
        self.db_tree.delete(*self.db_tree.get_children())
        
        def fmt_cell(v):
            if v is None:
                return ""
            s = str(v)
            return s[:100] + "..." if len(s) > 100 else s

        def set_tree_heading(col_key, label):
            indicator = ""
            if self.db_sort_col == col_key:
                indicator = " ▼" if self.db_sort_desc else " ▲"
            self.db_tree.heading(col_key, text=f"{label}{indicator}", command=lambda c=col_key: self.sort_db_table_by_column(c))

        sort_dir = "DESC" if self.db_sort_desc else "ASC"

        conn = self.db.get_connection()
        cursor = conn.cursor()
        total_rows = 0
        cache_key = (selected_table_text, search_query)

        def get_total_rows(count_sql, count_params=()):
            if (
                self.db_current_page > 1
                and getattr(self, "_db_cached_count_key", None) == cache_key
                and getattr(self, "_db_cached_total_rows", 0) > 0
            ):
                return self._db_cached_total_rows
            cursor.execute(count_sql, count_params)
            cnt = cursor.fetchone()[0]
            self._db_cached_count_key = cache_key
            self._db_cached_total_rows = cnt
            return cnt
        
        try:
            # --- 1. โหมดดูทุกตารางดิบ (📋 ตารางทั้งหมด: <table_name>) ---
            if "📋 ตารางทั้งหมด:" in selected_table_text:
                table_name = selected_table_text.split("📋 ตารางทั้งหมด:")[1].strip()
                
                # ดึงรายชื่อคอลัมน์แบบไดนามิกผ่าน PRAGMA table_info
                cursor.execute(f"PRAGMA table_info({table_name})")
                col_info = cursor.fetchall()
                col_names = [col[1] for col in col_info]
                
                self.db_tree["columns"] = col_names
                for col in col_names:
                    self.db_tree.column(col, width=130, anchor="w")
                    set_tree_heading(col, col)
                    
                order_by = f"ORDER BY {self.db_sort_col} {sort_dir}" if (self.db_sort_col and self.db_sort_col in col_names) else "ORDER BY 1 DESC"

                # นับจำนวนแถวทั้งหมด (Global Count พร้อมระบบแคชเมื่อเปลี่ยนหน้า)
                if search_query:
                    where_clauses = [f"CAST({c} AS TEXT) LIKE ?" for c in col_names]
                    params = [f"%{search_query}%"] * len(col_names)
                    count_sql = f"SELECT COUNT(*) FROM {table_name} WHERE {' OR '.join(where_clauses)}"
                    total_rows = get_total_rows(count_sql, params)
                    
                    data_sql = f"SELECT * FROM {table_name} WHERE {' OR '.join(where_clauses)} {order_by} LIMIT ? OFFSET ?"
                    cursor.execute(data_sql, params + [self.db_page_size, offset])
                else:
                    total_rows = get_total_rows(f"SELECT COUNT(*) FROM {table_name}")
                    cursor.execute(f"SELECT * FROM {table_name} {order_by} LIMIT ? OFFSET ?", (self.db_page_size, offset))
                    
                rows = cursor.fetchall()
                for r in rows:
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in r])

            elif "staff_members" in selected_table_text and "ครู" in selected_table_text:
                # ตาราง staff_members (ครู) — v6.34 เพิ่ม status และสังกัด (ตัดคำว่ากลุ่มสาระออก)
                sort_col_map = {
                    "id": "ts.id", "name": "ts.name", "department": "ts.department",
                    "status": "ts.status", "photos": "photos"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'ts.id')} {sort_dir}"

                if search_query:
                    total_rows = get_total_rows("""
                        SELECT COUNT(s.id)
                        FROM staff_members s
                        WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                          AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ? OR COALESCE(s.department, '') LIKE ? OR COALESCE(s.status, '') LIKE ?)
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))

                    cursor.execute(f"""
                        WITH top_staff AS (
                            SELECT s.id, s.name, COALESCE(s.department, '') as department,
                                   COALESCE(s.status, 'active') as status,
                                   (SELECT COUNT(*) FROM staff_embeddings e WHERE e.staff_id = s.id) as photos
                            FROM staff_members s
                            WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                              AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ? OR COALESCE(s.department, '') LIKE ? OR COALESCE(s.status, '') LIKE ?)
                        )
                        SELECT ts.id, ts.name, ts.department, ts.status, ts.photos
                        FROM top_staff ts
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("SELECT COUNT(*) FROM staff_members WHERE role = 'teacher' OR role IS NULL OR role = ''")

                    cursor.execute(f"""
                        WITH top_staff AS (
                            SELECT s.id, s.name, COALESCE(s.department, '') as department,
                                   COALESCE(s.status, 'active') as status,
                                   (SELECT COUNT(*) FROM staff_embeddings e WHERE e.staff_id = s.id) as photos
                            FROM staff_members s
                            WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        )
                        SELECT ts.id, ts.name, ts.department, ts.status, ts.photos
                        FROM top_staff ts
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("id", "name", "department", "status", "photos")
                self.db_tree.column("id", width=70, anchor="center")
                self.db_tree.column("name", width=250, anchor="w")
                self.db_tree.column("department", width=180, anchor="w")
                self.db_tree.column("status", width=95, anchor="center")
                self.db_tree.column("photos", width=110, anchor="center")
                
                set_tree_heading("id", "ID ครู")
                set_tree_heading("name", "ชื่อ-นามสกุล คุณครู")
                set_tree_heading("department", "สังกัด")
                set_tree_heading("status", "สถานะ")
                set_tree_heading("photos", "จำนวนรูป (รูป)")
                
                for r in rows:
                    row_list = list(r)
                    row_list[2] = clean_department_name(row_list[2])
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_list])
                    
            elif "staff_members" in selected_table_text and "นักเรียน" in selected_table_text:
                # ตาราง staff_members (นักเรียน) — v6.29 เพิ่ม class_room, status, graduation_year
                sort_col_map = {
                    "id": "ts.id", "name": "ts.name", "student_id": "ts.student_id",
                    "class_room": "ts.class_room", "status": "ts.status",
                    "graduation_year": "ts.graduation_year", "photos": "photos"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'ts.id')} {sort_dir}"

                if search_query:
                    total_rows = get_total_rows("""
                        SELECT COUNT(s.id)
                        FROM staff_members s
                        WHERE s.role = 'student'
                          AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ? OR s.student_id LIKE ? OR COALESCE(s.class_room, '') LIKE ? OR COALESCE(s.status, '') LIKE ?)
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))

                    cursor.execute(f"""
                        WITH top_students AS (
                            SELECT s.id, s.name, s.student_id,
                                   COALESCE(s.class_room, '') as class_room,
                                   COALESCE(s.status, 'active') as status,
                                   COALESCE(s.graduation_year, '') as graduation_year,
                                   (SELECT COUNT(*) FROM staff_embeddings e WHERE e.staff_id = s.id) as photos
                            FROM staff_members s
                            WHERE s.role = 'student'
                              AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ? OR s.student_id LIKE ? OR COALESCE(s.class_room, '') LIKE ? OR COALESCE(s.status, '') LIKE ?)
                        )
                        SELECT ts.id, ts.name, ts.student_id, ts.class_room, ts.status, ts.graduation_year, ts.photos
                        FROM top_students ts
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("SELECT COUNT(*) FROM staff_members WHERE role = 'student'")

                    cursor.execute(f"""
                        WITH top_students AS (
                            SELECT s.id, s.name, s.student_id,
                                   COALESCE(s.class_room, '') as class_room,
                                   COALESCE(s.status, 'active') as status,
                                   COALESCE(s.graduation_year, '') as graduation_year,
                                   (SELECT COUNT(*) FROM staff_embeddings e WHERE e.staff_id = s.id) as photos
                            FROM staff_members s
                            WHERE s.role = 'student'
                        )
                        SELECT ts.id, ts.name, ts.student_id, ts.class_room, ts.status, ts.graduation_year, ts.photos
                        FROM top_students ts
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("id", "name", "student_id", "class_room", "status", "graduation_year", "photos")
                self.db_tree.column("id", width=60, anchor="center")
                self.db_tree.column("name", width=220, anchor="w")
                self.db_tree.column("student_id", width=110, anchor="center")
                self.db_tree.column("class_room", width=90, anchor="center")
                self.db_tree.column("status", width=110, anchor="center")
                self.db_tree.column("graduation_year", width=90, anchor="center")
                self.db_tree.column("photos", width=100, anchor="center")
                
                set_tree_heading("id", "ID")
                set_tree_heading("name", "ชื่อ-นามสกุล นักเรียน")
                set_tree_heading("student_id", "รหัสประจำตัว")
                set_tree_heading("class_room", "ห้องเรียน")
                set_tree_heading("status", "สถานะ")
                set_tree_heading("graduation_year", "ปีที่จบ")
                set_tree_heading("photos", "รูปที่ลงทะเบียน (รูป)")
                
                status_th_map = {"active": "🟢 กำลังศึกษา", "graduated": "🎓 จบการศึกษา", "inactive": "⚪ ย้าย/พัก"}
                for r in rows:
                    formatted_row = list(r)
                    if len(formatted_row) >= 5:
                        formatted_row[4] = status_th_map.get(formatted_row[4], formatted_row[4])
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in formatted_row])
                    
            elif "0 Faces" in selected_table_text or "ไม่พบใบหน้าคน" in selected_table_text or "ยังไม่มีแคชใบหน้า" in selected_table_text:
                # ตารางภาพที่ไม่พบใบหน้าคน (0 Faces เช่น สิ่งของ/ป้าย/วิว) — v6.28 ใช้ COALESCE(p.total_faces_detected, 0) = 0 แทน Correlated Subquery
                sort_col_map = {
                    "photo_id": "p.photo_id",
                    "file_name": "COALESCE(p.file_name, p.photo_id)",
                    "file_ext": "COALESCE(p.file_extension, '')",
                    "event": "p.event_name",
                    "cache_status": "p.photo_id",
                    "link": "p.drive_link"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'p.photo_id')} {sort_dir}"

                if search_query:
                    where_clause = "WHERE COALESCE(p.total_faces_detected, 0) = 0 AND (p.photo_id LIKE ? OR p.drive_file_id LIKE ? OR p.event_name LIKE ? OR p.drive_link LIKE ? OR p.file_name LIKE ? OR p.file_extension LIKE ?)"
                    search_params = (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
                    total_rows = get_total_rows(f"SELECT COUNT(*) FROM scanned_photos p {where_clause}", search_params)

                    query_sql = f"""
                        SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.file_name, p.file_extension, 0 as face_cache_count
                        FROM scanned_photos p
                        {where_clause}
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, search_params + (self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("SELECT COUNT(*) FROM scanned_photos p WHERE COALESCE(p.total_faces_detected, 0) = 0")

                    query_sql = f"""
                        SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.file_name, p.file_extension, 0 as face_cache_count
                        FROM scanned_photos p
                        WHERE COALESCE(p.total_faces_detected, 0) = 0
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("photo_id", "file_name", "file_ext", "event", "cache_status", "link")
                self.db_tree.column("photo_id", width=90, anchor="center")
                self.db_tree.column("file_name", width=180, anchor="w")
                self.db_tree.column("file_ext", width=80, anchor="center")
                self.db_tree.column("event", width=160, anchor="w")
                self.db_tree.column("cache_status", width=150, anchor="center")
                self.db_tree.column("link", width=220, anchor="w")
                
                set_tree_heading("photo_id", "Photo ID")
                set_tree_heading("file_name", "ชื่อไฟล์ภาพ")
                set_tree_heading("file_ext", "สกุลไฟล์")
                set_tree_heading("event", "ชื่องานกิจกรรม")
                set_tree_heading("cache_status", "สถานะใบหน้า")
                set_tree_heading("link", "ลิงก์ไดรฟ์รูปภาพ")
                
                for r in rows:
                    pid, fid, evt, link, fname, fext, c_count = r
                    display_name = fname if fname else pid
                    display_ext = fext if fext else (os.path.splitext(display_name)[1].lower() if "." in display_name else "-")
                    c_status = "ℹ️ ไม่พบใบหน้าคน (0)"
                    row_vals = (pid, display_name, display_ext, evt, c_status, link)
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_vals])
                    
            elif "scanned_photos" in selected_table_text:
                # ตาราง scanned_photos (v6.28 ใช้ COALESCE(p.total_faces_detected, 0) + EXISTS ตรวจสอบแคช 0 หน้า)
                sort_col_map = {
                    "photo_id": "p.photo_id",
                    "file_name": "COALESCE(p.file_name, p.photo_id)",
                    "file_ext": "COALESCE(p.file_extension, '')",
                    "event": "p.event_name",
                    "cache_status": "COALESCE(p.total_faces_detected, 0)",
                    "link": "p.drive_link"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'p.photo_id')} {sort_dir}"

                if search_query:
                    where_clause = "WHERE p.photo_id LIKE ? OR p.drive_file_id LIKE ? OR p.event_name LIKE ? OR p.drive_link LIKE ? OR p.file_name LIKE ? OR p.file_extension LIKE ?"
                    search_params = (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
                    total_rows = get_total_rows(f"SELECT COUNT(*) FROM scanned_photos p {where_clause}", search_params)

                    query_sql = f"""
                        SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.file_name, p.file_extension,
                               COALESCE(p.total_faces_detected, 0) as face_cache_count,
                               EXISTS(SELECT 1 FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id LIMIT 1) as has_cache_row
                        FROM scanned_photos p
                        {where_clause}
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, search_params + (self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("SELECT COUNT(*) FROM scanned_photos")

                    query_sql = f"""
                        SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, p.file_name, p.file_extension,
                               COALESCE(p.total_faces_detected, 0) as face_cache_count,
                               EXISTS(SELECT 1 FROM scanned_photo_faces pf WHERE pf.photo_id = p.photo_id LIMIT 1) as has_cache_row
                        FROM scanned_photos p
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("photo_id", "file_name", "file_ext", "event", "cache_status", "link")
                self.db_tree.column("photo_id", width=90, anchor="center")
                self.db_tree.column("file_name", width=180, anchor="w")
                self.db_tree.column("file_ext", width=80, anchor="center")
                self.db_tree.column("event", width=160, anchor="w")
                self.db_tree.column("cache_status", width=165, anchor="center")
                self.db_tree.column("link", width=220, anchor="w")
                
                set_tree_heading("photo_id", "Photo ID")
                set_tree_heading("file_name", "ชื่อไฟล์ภาพ")
                set_tree_heading("file_ext", "สกุลไฟล์")
                set_tree_heading("event", "ชื่องานกิจกรรม")
                set_tree_heading("cache_status", "สถานะแคชใบหน้า")
                set_tree_heading("link", "ลิงก์ไดรฟ์รูปภาพ")
                
                for r in rows:
                    pid, fid, evt, link, fname, fext, c_count, has_cache = r
                    display_name = fname if fname else pid
                    display_ext = fext if fext else (os.path.splitext(display_name)[1].lower() if "." in display_name else "-")
                    if c_count > 0:
                        c_status = f"✅ มีแคชแล้ว ({c_count} หน้า)"
                    elif has_cache:
                        c_status = "⚪ สแกนแล้ว (0 หน้า - ไม่มีคน)"
                    else:
                        c_status = "❌ ยังไม่มีแคช (0)"
                    row_vals = (pid, display_name, display_ext, evt, c_status, link)
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_vals])

            elif "raw_camera_photos" in selected_table_text or "ไฟล์ภาพดิบกล้อง" in selected_table_text:
                # ตาราง raw_camera_photos (ไฟล์ RAW เช่น .ARW, .CR2, .CR3, .NEF, .RAF, .DNG)
                sort_col_map = {
                    "photo_id": "r.photo_id",
                    "file_name": "COALESCE(r.file_name, r.photo_id)",
                    "brand_ext": "r.camera_brand",
                    "event": "r.event_name",
                    "date": "r.photo_date",
                    "link": "r.drive_link"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'r.photo_id')} {sort_dir}"

                if search_query:
                    where_clause = """
                        WHERE r.photo_id LIKE ? OR r.drive_file_id LIKE ? OR r.event_name LIKE ? 
                           OR r.file_name LIKE ? OR r.file_extension LIKE ? OR r.camera_brand LIKE ? 
                           OR r.photo_date LIKE ? OR r.drive_link LIKE ?
                    """
                    search_params = (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", 
                                     f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", 
                                     f"%{search_query}%", f"%{search_query}%")
                    total_rows = get_total_rows(f"SELECT COUNT(*) FROM raw_camera_photos r {where_clause}", search_params)

                    query_sql = f"""
                        SELECT r.photo_id, r.file_name, r.file_extension, r.camera_brand, r.event_name, r.photo_date, r.drive_link
                        FROM raw_camera_photos r
                        {where_clause}
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, search_params + (self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("SELECT COUNT(*) FROM raw_camera_photos")

                    query_sql = f"""
                        SELECT r.photo_id, r.file_name, r.file_extension, r.camera_brand, r.event_name, r.photo_date, r.drive_link
                        FROM raw_camera_photos r
                        {order_by}
                        LIMIT ? OFFSET ?
                    """
                    cursor.execute(query_sql, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("photo_id", "file_name", "brand_ext", "event", "date", "link")
                self.db_tree.column("photo_id", width=90, anchor="center")
                self.db_tree.column("file_name", width=180, anchor="w")
                self.db_tree.column("brand_ext", width=160, anchor="center")
                self.db_tree.column("event", width=160, anchor="w")
                self.db_tree.column("date", width=110, anchor="center")
                self.db_tree.column("link", width=220, anchor="w")
                
                set_tree_heading("photo_id", "Photo ID")
                set_tree_heading("file_name", "ชื่อไฟล์ RAW")
                set_tree_heading("brand_ext", "ยี่ห้อกล้อง / สกุลไฟล์")
                set_tree_heading("event", "ชื่องานกิจกรรม")
                set_tree_heading("date", "วันที่ถ่ายภาพ")
                set_tree_heading("link", "ลิงก์ไดรฟ์รูปภาพ")
                
                for r in rows:
                    pid, fname, fext, brand, evt, pdate, link = r
                    display_name = fname if fname else pid
                    display_brand_ext = f"{brand} ({fext})" if (brand and fext) else (brand or fext or "-")
                    display_date = pdate if pdate else "-"
                    row_vals = (pid, display_name, display_brand_ext, evt, display_date, link)
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_vals])
                    
            elif "detected_faces" in selected_table_text and "ครู" in selected_table_text:
                # ตาราง detected_faces (ครู) — v6.28 Deferred Join CTE สำหรับการแบ่งหน้าความเร็วสูง
                sort_col_map = {
                    "match_id": "df.id",
                    "photo_id": "df.photo_id",
                    "file_name": "COALESCE(p.file_name, df.photo_id)",
                    "name": "s.name",
                    "event": "COALESCE(p.event_name, '')",
                    "conf": "df.confidence"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'df.id')} {sort_dir}"

                if search_query:
                    where_clause = """
                        WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                          AND (df.photo_id LIKE ? OR s.name LIKE ? OR CAST(s.id AS TEXT) LIKE ? OR p.event_name LIKE ? OR p.drive_file_id LIKE ? OR p.file_name LIKE ?)
                    """
                    search_params = (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
                    total_rows = get_total_rows(f"""
                        SELECT COUNT(*)
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        {where_clause}
                    """, search_params)

                    cursor.execute(f"""
                        SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(p.event_name, '-'), df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        {where_clause}
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, search_params + (self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("""
                        SELECT COUNT(*)
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                    """)

                    if self.db_sort_col in (None, "match_id", "photo_id", "conf"):
                        fast_col = {"match_id": "df.id", "photo_id": "df.photo_id", "conf": "df.confidence"}.get(self.db_sort_col, "df.id")
                        cursor.execute(f"""
                            WITH page_df AS (
                                SELECT df.id, df.photo_id, df.confidence, s.name
                                FROM detected_faces df
                                JOIN staff_members s ON df.staff_id = s.id
                                WHERE +s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                                ORDER BY {fast_col} {sort_dir}
                                LIMIT ? OFFSET ?
                            )
                            SELECT pf.id, pf.photo_id, COALESCE(p.file_name, '-'), pf.name, COALESCE(p.event_name, '-'), pf.confidence
                            FROM page_df pf
                            LEFT JOIN scanned_photos p ON pf.photo_id = p.photo_id
                        """, (self.db_page_size, offset))
                    else:
                        cursor.execute(f"""
                            SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(p.event_name, '-'), df.confidence
                            FROM detected_faces df
                            JOIN staff_members s ON df.staff_id = s.id
                            LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                            WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                            {order_by}
                            LIMIT ? OFFSET ?
                        """, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("match_id", "photo_id", "file_name", "name", "event", "conf")
                self.db_tree.column("match_id", width=80, anchor="center")
                self.db_tree.column("photo_id", width=90, anchor="center")
                self.db_tree.column("file_name", width=160, anchor="w")
                self.db_tree.column("name", width=220, anchor="w")
                self.db_tree.column("event", width=160, anchor="w")
                self.db_tree.column("conf", width=130, anchor="center")
                
                set_tree_heading("match_id", "Match ID")
                set_tree_heading("photo_id", "Photo ID")
                set_tree_heading("file_name", "ชื่อไฟล์ภาพ")
                set_tree_heading("name", "คุณครูที่ตรวจพบ")
                set_tree_heading("event", "ชื่องานกิจกรรม")
                set_tree_heading("conf", "ระดับความเหมือน (Similarity)")
                
                for r in rows:
                    match_id, pid, fname, name, evt, conf = r
                    conf_val = self.db.safe_float(conf)
                    row_vals = (match_id, pid, fname, name, evt, f"{conf_val*100:.2f}%")
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_vals])
                    
            elif "detected_faces" in selected_table_text and "นักเรียน" in selected_table_text:
                # ตาราง detected_faces (นักเรียน) — v6.28 Deferred Join CTE สำหรับการแบ่งหน้าความเร็วสูง
                sort_col_map = {
                    "match_id": "df.id",
                    "photo_id": "df.photo_id",
                    "file_name": "COALESCE(p.file_name, df.photo_id)",
                    "name": "s.name",
                    "student_id": "s.student_id",
                    "event": "COALESCE(p.event_name, '')",
                    "conf": "df.confidence"
                }
                order_by = f"ORDER BY {sort_col_map.get(self.db_sort_col, 'df.id')} {sort_dir}"

                if search_query:
                    where_clause = """
                        WHERE s.role = 'student'
                          AND (df.photo_id LIKE ? OR s.name LIKE ? OR s.student_id LIKE ? OR p.event_name LIKE ? OR p.drive_file_id LIKE ? OR p.file_name LIKE ?)
                    """
                    search_params = (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
                    total_rows = get_total_rows(f"""
                        SELECT COUNT(*)
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        {where_clause}
                    """, search_params)

                    cursor.execute(f"""
                        SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(s.student_id, '-'), COALESCE(p.event_name, '-'), df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        {where_clause}
                        {order_by}
                        LIMIT ? OFFSET ?
                    """, search_params + (self.db_page_size, offset))
                else:
                    total_rows = get_total_rows("""
                        SELECT COUNT(*)
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'student'
                    """)

                    if self.db_sort_col in (None, "match_id", "photo_id", "conf"):
                        fast_col = {"match_id": "df.id", "photo_id": "df.photo_id", "conf": "df.confidence"}.get(self.db_sort_col, "df.id")
                        cursor.execute(f"""
                            WITH page_df AS (
                                SELECT df.id, df.photo_id, df.confidence, s.name, s.student_id
                                FROM detected_faces df
                                JOIN staff_members s ON df.staff_id = s.id
                                WHERE +s.role = 'student'
                                ORDER BY {fast_col} {sort_dir}
                                LIMIT ? OFFSET ?
                            )
                            SELECT pf.id, pf.photo_id, COALESCE(p.file_name, '-'), pf.name, COALESCE(pf.student_id, '-'), COALESCE(p.event_name, '-'), pf.confidence
                            FROM page_df pf
                            LEFT JOIN scanned_photos p ON pf.photo_id = p.photo_id
                        """, (self.db_page_size, offset))
                    else:
                        cursor.execute(f"""
                            SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(s.student_id, '-'), COALESCE(p.event_name, '-'), df.confidence
                            FROM detected_faces df
                            JOIN staff_members s ON df.staff_id = s.id
                            LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                            WHERE s.role = 'student'
                            {order_by}
                            LIMIT ? OFFSET ?
                        """, (self.db_page_size, offset))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("match_id", "photo_id", "file_name", "name", "student_id", "event", "conf")
                self.db_tree.column("match_id", width=75, anchor="center")
                self.db_tree.column("photo_id", width=85, anchor="center")
                self.db_tree.column("file_name", width=150, anchor="w")
                self.db_tree.column("name", width=200, anchor="w")
                self.db_tree.column("student_id", width=110, anchor="center")
                self.db_tree.column("event", width=150, anchor="w")
                self.db_tree.column("conf", width=120, anchor="center")
                
                set_tree_heading("match_id", "Match ID")
                set_tree_heading("photo_id", "Photo ID")
                set_tree_heading("file_name", "ชื่อไฟล์ภาพ")
                set_tree_heading("name", "นักเรียนที่ตรวจพบ")
                set_tree_heading("student_id", "รหัสประจำตัว")
                set_tree_heading("event", "ชื่องานกิจกรรม")
                set_tree_heading("conf", "ระดับความเหมือน (Similarity)")
                
                for r in rows:
                    match_id, pid, fname, name, std_id, evt, conf = r
                    conf_val = self.db.safe_float(conf)
                    row_vals = (match_id, pid, fname, name, std_id, evt, f"{conf_val*100:.2f}%")
                    self.db_tree.insert("", "end", values=[fmt_cell(v) for v in row_vals])

            # อัปเดตสถานะปุ่มและข้อความบน Pagination Bar
            self.update_pagination_controls(total_rows)

        except Exception as e:
            logger.error(f"Error loading SQLite table into Treeview: {e}", exc_info=True)
        finally:
            conn.close()

    def open_db_folder(self):
        try:
            db_dir = os.path.dirname(self.db.db_path)
            os.startfile(db_dir)
            logger.info(f"Opened database folder in Explorer: {db_dir}")
        except Exception as e:
            logger.error(f"Failed to open database folder: {e}")

    def export_current_table(self):
        selected_table_text = self.option_db_table.get()
        default_name = "export_staff.csv"
        if "scanned_photos" in selected_table_text:
            default_name = "export_photos.csv"
        elif "detected_faces" in selected_table_text:
            default_name = "export_matches.csv"
            
        file_path = filedialog.asksaveasfilename(
            title="เลือกที่บันทึกไฟล์ส่งออก CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile=default_name
        )
        if not file_path:
            return
            
        logger.info(f"Exporting table '{selected_table_text}' to CSV: {file_path}")
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            import csv
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                
                if "staff_members" in selected_table_text and "ครู" in selected_table_text:
                    cursor.execute("""
                        SELECT s.id, s.name, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        GROUP BY s.id, s.name
                        ORDER BY s.id ASC
                    """)
                    writer.writerow(["ID ครู", "ชื่อ-นามสกุล คุณครู", "จำนวนรูปที่บันทึก"])
                    writer.writerows(cursor.fetchall())
                    
                elif "staff_members" in selected_table_text and "นักเรียน" in selected_table_text:
                    cursor.execute("""
                        SELECT s.id, s.name, s.student_id, COALESCE(s.class_room, ''),
                               COALESCE(s.status, 'active'), COALESCE(s.graduation_year, ''),
                               COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'student'
                        GROUP BY s.id, s.name, s.student_id, s.class_room, s.status, s.graduation_year
                        ORDER BY s.id ASC
                    """)
                    writer.writerow(["ID", "ชื่อ-นามสกุล นักเรียน", "รหัสประจำตัว", "ห้องเรียน", "สถานะ", "ปีการศึกษาที่จบ", "จำนวนรูปที่บันทึก"])
                    writer.writerows(cursor.fetchall())
                    
                elif "0 Faces" in selected_table_text or "ไม่พบใบหน้าคน" in selected_table_text or "ยังไม่มีแคชใบหน้า" in selected_table_text:
                    cursor.execute("""
                        SELECT p.photo_id, COALESCE(p.file_name, '-'), COALESCE(p.file_extension, '-'), p.drive_file_id, p.event_name, p.drive_link 
                        FROM scanned_photos p
                        WHERE COALESCE(p.total_faces_detected, 0) = 0
                        ORDER BY p.photo_id ASC
                    """)
                    writer.writerow(["Photo ID", "ชื่อไฟล์ภาพ", "สกุลไฟล์", "Drive File ID", "ชื่องานกิจกรรม", "ลิงก์ไดรฟ์รูปภาพ"])
                    writer.writerows(cursor.fetchall())
                    
                elif "scanned_photos" in selected_table_text:
                    cursor.execute("SELECT photo_id, COALESCE(file_name, '-'), COALESCE(file_extension, '-'), drive_file_id, event_name, drive_link FROM scanned_photos ORDER BY photo_id ASC")
                    writer.writerow(["Photo ID", "ชื่อไฟล์ภาพ", "สกุลไฟล์", "Drive File ID", "ชื่องานกิจกรรม", "ลิงก์ไดรฟ์รูปภาพ"])
                    writer.writerows(cursor.fetchall())

                elif "raw_camera_photos" in selected_table_text or "ไฟล์ภาพดิบกล้อง" in selected_table_text:
                    cursor.execute("""
                        SELECT r.photo_id, COALESCE(r.file_name, '-'), COALESCE(r.file_extension, '-'), 
                               COALESCE(r.camera_brand, '-'), r.event_name, COALESCE(r.photo_date, '-'), r.drive_link 
                        FROM raw_camera_photos r 
                        ORDER BY r.photo_id ASC
                    """)
                    writer.writerow(["Photo ID", "ชื่อไฟล์ RAW", "สกุลไฟล์", "ยี่ห้อกล้อง", "ชื่องานกิจกรรม", "วันที่ถ่ายภาพ", "ลิงก์ไดรฟ์รูปภาพ"])
                    writer.writerows(cursor.fetchall())
                    
                elif "detected_faces" in selected_table_text and "ครู" in selected_table_text:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(p.event_name, '-'), df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        ORDER BY df.id ASC
                    """)
                    writer.writerow(["Match ID", "Photo ID", "ชื่อไฟล์ภาพ", "คุณครูที่ตรวจพบ", "ชื่องานกิจกรรม", "ระดับความเหมือน"])
                    writer.writerows(cursor.fetchall())
                    
                elif "detected_faces" in selected_table_text and "นักเรียน" in selected_table_text:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, COALESCE(p.file_name, '-'), s.name, COALESCE(s.student_id, '-'), COALESCE(p.event_name, '-'), df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        WHERE s.role = 'student'
                        ORDER BY df.id ASC
                    """)
                    writer.writerow(["Match ID", "Photo ID", "ชื่อไฟล์ภาพ", "นักเรียนที่ตรวจพบ", "รหัสประจำตัว", "ชื่องานกิจกรรม", "ระดับความเหมือน"])
                    writer.writerows(cursor.fetchall())
                    
            logger.info("CSV Export completed successfully.")
            messagebox.showinfo("ส่งออกสำเร็จ", "ส่งออกไฟล์ข้อมูล CSV เรียบร้อยแล้ว")
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}", exc_info=True)
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถส่งออกไฟล์ได้: {e}")
            conn.close()

    def reset_selected_person_matches(self):
        selected_table_text = self.option_db_table.get()
        if "staff_members" not in selected_table_text:
            messagebox.showwarning("คำเตือน", "กรุณาเลือกตารางรายชื่อครู หรือ รายชื่อนักเรียน ก่อนใช้ปุ่มนี้")
            return
            
        selected_item = self.db_tree.selection()
        if not selected_item:
            messagebox.showwarning("คำเตือน", "กรุณาคลิกเลือกชื่อบุคคลจากตารางที่ต้องการรีเซ็ตก่อน")
            return
            
        values = self.db_tree.item(selected_item[0], "values")
        if not values:
            return
            
        staff_id = values[0]
        name = values[1]
        
        confirm = messagebox.askyesno(
            "ยืนยันการรีเซ็ต",
            f"คุณต้องการลบข้อมูลประวัติการสแกนจับคู่รูปภาพทั้งหมดของ '{name}' หรือไม่?\n\n"
            "* ข้อมูลชื่อและรูปใบหน้าที่ลงทะเบียนของบุคคลนี้จะไม่ถูกลบ และยังคงอยู่ในระบบ *"
        )
        
        if confirm:
            logger.info(f"Resetting matching history for staff_id={staff_id} ({name})")
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM detected_faces WHERE staff_id = ?", (staff_id,))
                conn.commit()
                messagebox.showinfo("รีเซ็ตสำเร็จ", f"รีเซ็ตประวัติการจับคู่ของ '{name}' เรียบร้อยแล้ว")
                self.load_db_table_data(selected_table_text)
                self.refresh_dashboard_stats()
            except Exception as e:
                logger.error(f"Error resetting person matching data: {e}", exc_info=True)
                messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการรีเซ็ตข้อมูล: {e}")
            finally:
                conn.close()

    def on_db_tree_select(self, event=None):
        """เมื่อผู้ใช้คลิกเลือกแถวในตาราง Treeview หน้าค้นหาฐานข้อมูล"""
        selected_items = self.db_tree.selection()
        if not selected_items:
            return
        selected_table_text = self.option_db_table.get()
        if "staff_members" not in selected_table_text:
            return
        item_values = self.db_tree.item(selected_items[0], "values")
        if not item_values:
            return
        staff_id = item_values[0]
        thresh = self.db.get_personal_threshold(staff_id)
        if hasattr(self, 'entry_personal_thresh'):
            self.entry_personal_thresh.delete(0, "end")
            self.entry_personal_thresh.insert(0, f"{thresh:.2f}")

    def save_selected_person_threshold(self):
        """บันทึกค่า Personal Threshold ของบุคคลที่เลือกจากตาราง (รองรับ Multi-Select / Shift+Click v5.40)"""
        selected_table_text = self.option_db_table.get()
        if "staff_members" not in selected_table_text:
            messagebox.showwarning("คำเตือน", "กรุณาเลือกตารางรายชื่อครู หรือ รายชื่อนักเรียน ก่อนใช้งานปุ่มนี้")
            return
            
        selected_items = self.db_tree.selection()
        if not selected_items:
            messagebox.showwarning("คำเตือน", "กรุณาคลิกเลือกชื่อบุคคลจากตารางที่ต้องการบันทึก Threshold ก่อน (เลือกหลายคนด้วย Shift+Click หรือ Ctrl+Click ได้)")
            return
            
        try:
            val_str = self.entry_personal_thresh.get().strip()
            new_thresh = float(val_str)
            if new_thresh < 0.10 or new_thresh > 1.00:
                messagebox.showerror("ข้อผิดพลาด", "กรุณากรอกค่า Threshold ระหว่าง 0.10 ถึง 1.00 (เช่น 0.50)")
                return
        except ValueError:
            messagebox.showerror("ข้อผิดพลาด", "กรุณากรอกตัวเลขทศนิยมที่ถูกต้อง (เช่น 0.50)")
            return

        staff_ids = []
        names = []
        for item_id in selected_items:
            values = self.db_tree.item(item_id, "values")
            if values:
                staff_ids.append(values[0])
                names.append(values[1])

        if not staff_ids:
            return

        success = self.db.update_personal_thresholds_batch(staff_ids, new_thresh)
        if success:
            if len(staff_ids) == 1:
                msg_text = f"บันทึก Personal Threshold ของ '{names[0]}' เป็น {new_thresh:.2f} เรียบร้อยแล้ว"
            else:
                msg_text = f"บันทึก Personal Threshold เป็น {new_thresh:.2f} ให้กับ {len(staff_ids)} รายการที่เลือกเรียบร้อยแล้ว"
            messagebox.showinfo("บันทึกสำเร็จ", msg_text)
            logger.info(f"[SETTINGS] Updated personal_threshold to {new_thresh:.2f} for {len(staff_ids)} items.")
            self.load_db_table_data(selected_table_text)
        else:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถบันทึกข้อมูล Threshold ได้")

    def run_manual_json_sync(self, mode):
        if not self.sync_manager.connected:
            cred_path = self.entry_cred_path.get().strip()
            if not os.path.exists(cred_path):
                messagebox.showerror("ข้อผิดพลาด", "ไม่พบไฟล์ Service Account JSON กรุณาตั้งค่าในหน้าตั้งค่าระบบก่อน")
                return
            self.sync_manager.credentials_path = cred_path
            success = self.sync_manager.connect()
            if not success:
                messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเชื่อมต่อ Google API ได้ (กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือไฟล์ Service Account)")
                return

        json_folder_id = self.entry_json_folder_id.get().strip()
        if not json_folder_id:
            messagebox.showerror("ข้อผิดพลาด", "กรุณาระบุ ID โฟลเดอร์เก็บไฟล์ JSON ดัชนีก่อนซิงค์")
            return

        mode_th = "ทั้งหมด (ครู+นักเรียน)" if mode == "all" else ("เฉพาะครู" if mode == "teachers" else "เฉพาะนักเรียน")
        
        self.btn_sync_json_all.configure(state="disabled")
        self.btn_sync_json_teachers.configure(state="disabled")
        self.btn_sync_json_students.configure(state="disabled")

        def task():
            try:
                logger.info(f"[GDRIVE] Manual JSON Sync: starting sync for mode={mode}")
                sync_data = self.db.get_all_sync_data()
                self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode=mode)
                logger.info(f"[GDRIVE] Manual JSON Sync: mode={mode} completed.")
                self.after(0, lambda: messagebox.showinfo("ซิงค์สำเร็จ", f"อัปเดตไฟล์ JSON ดัชนีกลุ่ม {mode_th} ขึ้น Google Drive สำเร็จ!"))
            except Exception as e:
                logger.error(f"[GDRIVE] Manual JSON Sync Error: {e}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการซิงค์ JSON: {e}"))
            finally:
                self.after(0, lambda: [
                    self.btn_sync_json_all.configure(state="normal"),
                    self.btn_sync_json_teachers.configure(state="normal"),
                    self.btn_sync_json_students.configure(state="normal")
                ])

        import threading
        threading.Thread(target=task, daemon=True).start()

    # ==================== (6) หน้าภาพกิจกรรมที่แมตช์แล้ว (v3.2 Fix Bug 5) ====================
    def setup_matched_gallery_ui(self):
        """จัดสร้างส่วนแสดงผลแกลเลอรีรูปภาพกิจกรรมที่แมตช์แล้วคัดแยกรายบุคคลและเรียงตามเดือน"""
        self.frame_matched_gallery.grid_columnconfigure(0, weight=1)
        self.frame_matched_gallery.grid_rowconfigure(1, weight=1)

        # 1. แถบควบคุมเมนูด้านบน (Header Bar)
        ctrl_frame = ctk.CTkFrame(self.frame_matched_gallery, fg_color="#1A2636")
        ctrl_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        ctk.CTkLabel(ctrl_frame, text="หมวดบุคคล:", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(15, 5), pady=10)
        self.combo_matched_role = ctk.CTkOptionMenu(
            ctrl_frame, values=["คุณครู", "นักเรียน"], width=130, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            dropdown_font=ctk.CTkFont(size=14, weight="normal"),
            dropdown_fg_color="#101B2B",
            dropdown_hover_color="#1F3A60",
            dropdown_text_color="white",
            command=self.on_matched_role_change
        )
        self.combo_matched_role.pack(side="left", padx=5, pady=10)

        ctk.CTkLabel(ctrl_frame, text="เลือกรายชื่อ:", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(15, 5), pady=10)
        self.combo_matched_person = ctk.CTkOptionMenu(
            ctrl_frame, values=["-- กรุณาเลือก --"], width=320, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            dropdown_font=ctk.CTkFont(size=14, weight="normal"),
            dropdown_fg_color="#101B2B",
            dropdown_hover_color="#1F3A60",
            dropdown_text_color="white",
            command=self.on_matched_person_change
        )
        self.combo_matched_person.pack(side="left", padx=5, pady=10)

        self.entry_matched_search = ctk.CTkEntry(ctrl_frame, placeholder_text="🔍 กรองชื่อ...", width=180, height=36, font=ctk.CTkFont(size=14))
        self.entry_matched_search.pack(side="left", padx=10, pady=10)
        self.entry_matched_search.bind("<KeyRelease>", lambda event: self.filter_matched_person_dropdown())

        btn_refresh_gallery = ctk.CTkButton(
            ctrl_frame, text="🔄 รีเฟรช", width=95, height=36, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#34495E", hover_color="#2C3E50",
            command=lambda: self.on_matched_person_change(self.combo_matched_person.get())
        )
        btn_refresh_gallery.pack(side="left", padx=5, pady=10)

        self.lbl_matched_summary = ctk.CTkLabel(ctrl_frame, text="พบ 0 รูปภาพ", font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ECC71")
        self.lbl_matched_summary.pack(side="right", padx=15, pady=10)

        # 2. พื้นที่แสดงรูปภาพแบบ Scrollable Frame (รองรับเมาส์ Scroll & Drag)
        self.scr_matched_gallery = ctk.CTkScrollableFrame(self.frame_matched_gallery, fg_color="#0D1622")
        self.scr_matched_gallery.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.bind_scroll_events(self.scr_matched_gallery)

        self.matched_persons_map = {}

    def bind_scroll_events(self, widget):
        """ผูกการ Scroll เมาส์ล้อหมุน เลื่อนรวดเร็วและราบรื่น 150x"""
        def _on_mousewheel(event):
            try:
                units = int(-1 * (event.delta / 120) * 150)
                self.scr_matched_gallery._parent_canvas.yview_scroll(units, "units")
            except Exception:
                pass
        try:
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                self.bind_scroll_events(child)
        except Exception:
            pass

    def on_matched_role_change(self, role):
        """เมื่อเปลี่ยนหมวดระหว่าง คุณครู และ นักเรียน ให้โหลดรายชื่อใหม่"""
        self.matched_persons_map.clear()
        if role == "คุณครู":
            persons = self.db.get_all_teachers()
            options = []
            for p in persons:
                disp = f"{p['name']} (ID: {p['id']})"
                options.append(disp)
                self.matched_persons_map[disp] = p["id"]
        else:
            persons = self.db.get_all_students()
            options = []
            for p in persons:
                sid = p.get("student_id", "")
                disp = f"{p['name']} (รหัส: {sid})" if sid else f"{p['name']} (ID: {p['id']})"
                options.append(disp)
                self.matched_persons_map[disp] = p["id"]

        if not options:
            options = ["-- ไม่พบข้อมูล --"]
        
        self.full_matched_options = options
        self.combo_matched_person.configure(values=options)
        self.combo_matched_person.set(options[0])
        self.on_matched_person_change(options[0])

    def filter_matched_person_dropdown(self, event=None, immediate=False):
        """กรองรายชื่อใน Dropdown ตามคำค้นหาในช่อง entry_matched_search (พร้อม Debounce 250ms v6.28)"""
        if getattr(self, "_matched_search_timer", None) is not None:
            try:
                self.after_cancel(self._matched_search_timer)
            except Exception:
                pass
            self._matched_search_timer = None

        def _do_filter():
            self._matched_search_timer = None
            query = self.entry_matched_search.get().strip().lower()
            if not hasattr(self, 'full_matched_options'):
                return
            if not query:
                filtered = self.full_matched_options
            else:
                filtered = [opt for opt in self.full_matched_options if query in opt.lower()]
            
            if not filtered:
                filtered = ["-- ไม่พบรายชื่อ --"]
            self.combo_matched_person.configure(values=filtered)
            self.combo_matched_person.set(filtered[0])
            self.on_matched_person_change(filtered[0])

        if immediate:
            _do_filter()
        else:
            self._matched_search_timer = self.after(250, _do_filter)

    def on_matched_person_change(self, selected_disp):
        """เมื่อเลือกบุคคลใน Dropdown ให้คิวรีรูปภาพและสร้าง UI แกลเลอรี (v3.2 Fix Bug 9)"""
        if not hasattr(self, 'gallery_worker_gen'):
            self.gallery_worker_gen = 0
        self.gallery_worker_gen += 1
        current_gen = self.gallery_worker_gen

        # ล้างวิดเจ็ตในแกลเลอรีทันทีที่กดเลือกรายชื่อใหม่ (Immediate UI Reset)
        for widget in self.scr_matched_gallery.winfo_children():
            widget.destroy()

        staff_id = self.matched_persons_map.get(selected_disp)
        if not staff_id:
            self.lbl_matched_summary.configure(text="พบ 0 รูปภาพ")
            return

        self.lbl_matched_summary.configure(text=f"⌛ กำลังคิวรีรูปภาพของ {selected_disp}...")

        def load_thread():
            try:
                matched_photos = self.db.get_matched_photos_for_staff(staff_id)
                if current_gen == self.gallery_worker_gen:
                    self.after(0, lambda: self.render_matched_gallery(selected_disp, matched_photos, current_gen))
            except Exception as err:
                logger.error(f"[GALLERY] Error querying matched photos for {selected_disp}: {err}")
                if current_gen == self.gallery_worker_gen:
                    self.after(0, lambda: self.lbl_matched_summary.configure(text=f"❌ เกิดข้อผิดพลาดในการโหลดรูปภาพของ {selected_disp}"))

        threading.Thread(target=load_thread, daemon=True).start()

    def format_month_year_header(self, date_str):
        """แปลงข้อความวันที่ YYYY-MM-DD เป็นชื่อเดือนภาษาไทย พ.ศ. (เช่น 2026-02 -> กุมภาพันธ์ 2569 / 2026)"""
        if not date_str or len(date_str) < 7 or "-" not in date_str:
            return "📅 รูปภาพกิจกรรมที่ไม่ระบุช่วงเวลา"
        parts = date_str.split("-")
        try:
            year = int(parts[0])
            month = int(parts[1])
            months_th = [
                "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
            ]
            month_name = months_th[month] if 1 <= month <= 12 else f"เดือน {month}"
            buddhist_year = year + 543
            return f"📅 เดือน{month_name} พ.ศ. {buddhist_year} ({year})"
        except Exception:
            return f"📅 ช่วงเวลา {date_str[:7]}"

    def render_matched_gallery(self, person_name, matched_photos, gen_id=0, limit=30):
        """วาดองค์ประกอบรูปภาพในแกลเลอรี แบบ Chunk Pagination (จำกัด 30 รูปแรกต่อการโหลด) ป้องกัน Not Responding (v4.16)"""
        for widget in self.scr_matched_gallery.winfo_children():
            widget.destroy()

        total_count = len(matched_photos)
        displayed_photos = matched_photos[:limit]
        
        self.lbl_matched_summary.configure(text=f"พบ {total_count} รูปภาพที่แมตช์ (กำลังแสดง {len(displayed_photos)} รูป)")

        if not matched_photos:
            lbl_empty = ctk.CTkLabel(
                self.scr_matched_gallery,
                text=f"ไม่พบประวัติรูปภาพกิจกรรมที่สแกนพบ '{person_name}'",
                font=ctk.CTkFont(size=14),
                text_color="#A2B5CD"
            )
            lbl_empty.pack(pady=40)
            return

        # 1. จัดกลุ่มเฉพาะรูปภาพที่จะแสดงผลตามเดือน/ปี (YYYY-MM)
        from collections import defaultdict
        grouped_photos = defaultdict(list)
        for item in displayed_photos:
            pdate = item.get("photo_date", "")
            month_key = pdate[:7] if pdate and len(pdate) >= 7 and "-" in pdate else "9999-99"
            grouped_photos[month_key].append(item)

        sorted_month_keys = sorted(grouped_photos.keys(), reverse=True)

        cols = 3
        for c in range(cols):
            self.scr_matched_gallery.grid_columnconfigure(c, weight=1)

        cache_dir = os.path.join(get_project_root(), "data", "thumbnail_cache")
        os.makedirs(cache_dir, exist_ok=True)

        try:
            cache_files = set(os.listdir(cache_dir))
        except Exception:
            cache_files = set()

        def get_cached_thumb_path_fast(pid, fid):
            pid_str = str(pid).strip()
            fid_str = str(fid).strip()
            f1 = f"{pid_str}.jpg"
            if f1 in cache_files: return os.path.join(cache_dir, f1)
            f2 = f"thumb_{fid_str}.jpg"
            if f2 in cache_files: return os.path.join(cache_dir, f2)
            f3 = f"{fid_str}.jpg"
            if f3 in cache_files: return os.path.join(cache_dir, f3)
            return None

        cached_load_items = []
        uncached_queue = []
        row_counter = 0
        for month_key in sorted_month_keys:
            items_in_month = grouped_photos[month_key]
            sample_date = items_in_month[0].get("photo_date", "") if items_in_month else ""
            header_text = self.format_month_year_header(sample_date)

            header_frame = ctk.CTkFrame(self.scr_matched_gallery, fg_color="#1E2D40", corner_radius=6)
            header_frame.grid(row=row_counter, column=0, columnspan=cols, sticky="ew", padx=5, pady=(15, 8))
            
            lbl_h = ctk.CTkLabel(
                header_frame,
                text=f"{header_text}  ({len(items_in_month)} รูปภาพ)",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#6CA6CD"
            )
            lbl_h.pack(side="left", padx=15, pady=8)
            self.bind_scroll_events(header_frame)
            row_counter += 1

            for idx, item in enumerate(items_in_month):
                r_idx = row_counter + (idx // cols)
                c_idx = idx % cols

                card = ctk.CTkFrame(self.scr_matched_gallery, fg_color="#141E2B", corner_radius=8, border_width=1, border_color="#26384D")
                card.grid(row=r_idx, column=c_idx, padx=6, pady=6, sticky="nsew")

                fid = item["drive_file_id"]
                pid_code = item["photo_id"]
                event_name = item["event_name"]
                conf_pct = item["confidence"] * 100.0 if item["confidence"] <= 1.0 else item["confidence"]
                drive_link = item["drive_link"]

                img_label = ctk.CTkLabel(card, text="⌛ กำลังโหลดรูป...", width=200, height=180, fg_color="#0A111A", corner_radius=6)
                img_label.pack(padx=8, pady=(8, 4), fill="both", expand=True)

                lbl_info = ctk.CTkLabel(
                    card,
                    text=f"📌 {event_name[:24]}\n🎯 ตรงกัน: {conf_pct:.1f}% | {pid_code}",
                    font=ctk.CTkFont(size=11),
                    text_color="#E0E6ED",
                    justify="center"
                )
                lbl_info.pack(padx=6, pady=(0, 4))

                open_view_url = self.sync_manager.format_drive_view_url(drive_link) if hasattr(self, 'sync_manager') and hasattr(self.sync_manager, 'format_drive_view_url') else drive_link

                btn_open = ctk.CTkButton(
                    card,
                    text="🌐 เปิดดูรูปบน Google Drive",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#27AE60", hover_color="#219150", text_color="white", height=24,
                    command=lambda url=open_view_url: webbrowser.open(url)
                )
                btn_open.pack(padx=8, pady=(0, 8), fill="x")

                self.bind_scroll_events(card)

                existing_path = get_cached_thumb_path_fast(pid_code, fid)
                if existing_path:
                    cached_load_items.append((existing_path, img_label, drive_link))
                else:
                    uncached_queue.append((pid_code, fid, drive_link, img_label))

            row_counter += (len(items_in_month) + cols - 1) // cols

        # หากมีรูปภาพมากกว่าที่แสดงอยู่ ให้สร้างปุ่ม "โหลดรูปภาพเพิ่มเติม..."
        if limit < total_count:
            btn_load_more = ctk.CTkButton(
                self.scr_matched_gallery,
                text=f"📥 โหลดรูปภาพเพิ่มเติม... (เหลืออีก {total_count - limit} รูป)",
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="#2980B9", hover_color="#1F618D", text_color="white", height=40,
                command=lambda: self.render_matched_gallery(person_name, matched_photos, gen_id, limit + 30)
            )
            btn_load_more.grid(row=row_counter, column=0, columnspan=cols, pady=20, padx=20, sticky="ew")

        # Async Background Loader
        if cached_load_items:
            def async_cached_loader(items, task_gen):
                for path, lbl, url in items:
                    if task_gen != self.gallery_worker_gen:
                        return
                    try:
                        pil_img = Image.open(path).convert("RGB")
                        pil_img = pil_img.resize((200, 180), Image.Resampling.LANCZOS)
                        
                        def update_ui(p_img, target_lbl, target_url):
                            if task_gen == self.gallery_worker_gen:
                                ctk_img = ctk.CTkImage(light_image=p_img, dark_image=p_img, size=(200, 180))
                                target_lbl.configure(image=ctk_img, text="")
                                target_lbl.bind("<Double-Button-1>", lambda ev, u=target_url: webbrowser.open(u))

                        self.after(0, lambda p=pil_img, l=lbl, u=url: update_ui(p, l, u))
                    except Exception:
                        self.after(0, lambda l=lbl: l.configure(text="🖼️ อ่านรูปไม่ได้"))

            threading.Thread(target=async_cached_loader, args=(cached_load_items, gen_id), daemon=True).start()

            row_counter += (len(items_in_month) + cols - 1) // cols

        # 3. ลูปดาวน์โหลดทีละภาพเรียงตามคิวในเธรดเบื้องหลังเดี่ยว (Sequential Worker Thread)
        if uncached_queue:
            def sequential_download_worker(q_items, task_gen):
                import time, requests
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                
                for p_code, target_fid, target_link, target_lbl in q_items:
                    # ถ้าผู้ใช้สลับไปเลือกครู/นักเรียน คนอื่น ให้ยกเลิกคิวเดิมทันที!
                    if task_gen != self.gallery_worker_gen:
                        logger.info(f"[GALLERY] ⏹️ สลับรายชื่อบุคคล ยกเลิกคิวดาวน์โหลดรูปภาพเดิม ({p_code})")
                        return

                    try:
                        logger.info(f"[GALLERY] 🌐 ทยอยดาวน์โหลด Thumbnail รูป {p_code} จาก Google Drive (File ID: {target_fid})...")
                        t_start = time.time()
                        target_thumb_path = os.path.join(cache_dir, f"{p_code}.jpg")
                        downloaded = False

                        # Auto-Connect Google Drive API หากยังไม่ได้เชื่อมต่อ
                        if hasattr(self, 'sync_manager') and self.sync_manager:
                            if hasattr(self, 'entry_cred_path') and self.entry_cred_path and self.entry_cred_path.get().strip():
                                self.sync_manager.credentials_path = self.entry_cred_path.get().strip()
                            if not self.sync_manager.connected or not getattr(self.sync_manager, 'drive_service', None):
                                if not hasattr(self, '_drive_connect_lock'):
                                    self._drive_connect_lock = threading.Lock()
                                with self._drive_connect_lock:
                                    if not self.sync_manager.connected or not getattr(self.sync_manager, 'drive_service', None):
                                        logger.info("[GALLERY] 🔑 Auto-connecting Google Sync Manager Drive API...")
                                        self.sync_manager.connect()

                        # 1. ลองใช้ Drive API thumbnailLink (=s500) เพื่อความเร็วสูงสุด 0.1s
                        if hasattr(self, 'sync_manager') and self.sync_manager and getattr(self.sync_manager, 'drive_service', None):
                            try:
                                f_meta = self.sync_manager.drive_service.files().get(fileId=target_fid, fields='thumbnailLink').execute()
                                thumb_url = f_meta.get('thumbnailLink')
                                if thumb_url:
                                    t_url_500 = thumb_url.replace('=s220', '=s500')
                                    fast_resp = requests.get(t_url_500, headers=headers, timeout=10)
                                    if fast_resp.status_code == 200 and len(fast_resp.content) > 0:
                                        import cv2
                                        nparr = np.frombuffer(fast_resp.content, np.uint8)
                                        img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                                        if img_cv is not None:
                                            success, encoded = cv2.imencode('.jpg', img_cv)
                                            if success:
                                                encoded.tofile(target_thumb_path)
                                                downloaded = True
                                                t_elapsed = time.time() - t_start
                                                logger.info(f"[GALLERY] ⚡ ดาวน์โหลดสำเร็จ: {p_code}.jpg (ใช้เวลา {t_elapsed:.2f}s)")
                            except Exception as thumb_err:
                                logger.warning(f"[GALLERY] Fast thumbnail fetch failed for {target_fid}: {thumb_err}")

                        # 2. Fallback สแกนดาวน์โหลดภาพเต็ม
                        if not downloaded and hasattr(self, 'sync_manager') and self.sync_manager:
                            img_bytes, dl_time, _ = self.sync_manager.download_image_bytes_with_stats(target_fid, f"thumb_{target_fid}")
                            if img_bytes:
                                img_cv = decode_image_bytes(img_bytes)
                                if img_cv is not None:
                                    h, w = img_cv.shape[:2]
                                    scale = 300.0 / max(h, w)
                                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                                    resized = cv2.resize(img_cv, (new_w, new_h), interpolation=cv2.INTER_AREA)
                                    success, encoded = cv2.imencode('.jpg', resized)
                                    if success:
                                        encoded.tofile(target_thumb_path)
                                        downloaded = True
                                        t_elapsed = time.time() - t_start
                                        logger.info(f"[GALLERY] ✅ บันทึกแคช Thumbnail สำเร็จ: {p_code}.jpg (ใช้เวลา {t_elapsed:.2f}s)")

                        # 3. อัปเดตหน้าจอ GUI สำหรับภาพนี้หากผู้ใช้ยังไม่ได้สลับรายชื่อไปคนอื่น
                        if task_gen == self.gallery_worker_gen:
                            cache_files.add(f"{p_code}.jpg")
                            cache_files.add(f"thumb_{target_fid}.jpg")
                            cache_files.add(f"{target_fid}.jpg")
                            
                            final_path = target_thumb_path if (downloaded and os.path.exists(target_thumb_path)) else get_cached_thumb_path_fast(p_code, target_fid)
                            if final_path:
                                pil_img = Image.open(final_path).convert("RGB")
                                pil_img = pil_img.resize((200, 180), Image.Resampling.LANCZOS)
                                
                                target_view_url = self.sync_manager.format_drive_view_url(target_link) if hasattr(self, 'sync_manager') and hasattr(self.sync_manager, 'format_drive_view_url') else target_link

                                def render_on_main(p_img, lbl, url):
                                    ctk_img = ctk.CTkImage(light_image=p_img, dark_image=p_img, size=(200, 180))
                                    lbl.configure(image=ctk_img, text="")
                                    lbl.bind("<Double-Button-1>", lambda ev, u=url: webbrowser.open(u))

                                self.after(0, lambda p=pil_img, l=target_lbl, u=target_view_url: render_on_main(p, l, u))
                            else:
                                self.after(0, lambda lbl=target_lbl: lbl.configure(text="🖼️ ไม่มีพรีวิว"))
                    except Exception as err:
                        logger.error(f"[GALLERY] Error loading thumbnail {target_fid}: {err}")
                        self.after(0, lambda lbl=target_lbl: lbl.configure(text="🖼️ อ่านรูปไม่ได้"))

            threading.Thread(target=sequential_download_worker, args=(uncached_queue, gen_id), daemon=True).start()


    def save_cropped_face(self, staff_id, original_path, bbox, count, orig_filename=None):
        """ตัดส่วนใบหน้าคุณครูแล้วเก็บเป็นไฟล์ย่อยลงในแอป ป้องกันไฟล์ต้นฉบับหาย"""
        try:
            # อ่านภาพดึงข้อมูลไบต์แบบรองรับภาษาไทย และ Apple HEIC
            img = read_image_file(original_path)
            if img is None:
                return original_path # fallback
                
            h, w, _ = img.shape
            x1, y1, x2, y2 = map(int, bbox)
            
            # ขยาย Padding 10%
            pad_x = int((x2 - x1) * 0.1)
            pad_y = int((y2 - y1) * 0.1)
            
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(w, x2 + pad_x)
            y2 = min(h, y2 + pad_y)
            
            cropped = img[y1:y2, x1:x2]
            
            face_dir = os.path.join(get_project_root(), "data", "registered_teachers")
            os.makedirs(face_dir, exist_ok=True)

            # ดึงชื่อไฟล์ดั้งเดิมมาฝังท้าย
            if orig_filename:
                orig_name = os.path.splitext(os.path.basename(orig_filename))[0]
            else:
                orig_name = os.path.splitext(os.path.basename(original_path))[0]
            orig_name_clean = "".join(c for c in orig_name if c.isalnum() or c in ('-', '_'))

            face_filename = f"teacher_{staff_id}_{int(time.time())}_{count}_{orig_name_clean}.jpg"
            face_path = os.path.join(face_dir, face_filename)
            
            # เขียนไฟล์ภาพ
            success, img_encoded = cv2.imencode('.jpg', cropped)
            if success:
                img_encoded.tofile(face_path)
                return face_path
        except Exception as e:
            logger.error(f"Error cropping and saving face: {e}")
        return original_path # fallback

    def show_staff_thumbnails(self, staff_id):
        """แสดงรูปภาพย่อยของคุณครูที่เลือกในรูปแบบตารางกริด (Grid) พร้อมระบบล้างขยะอัตโนมัติ"""
        self.selected_thumb_paths = set()
        if hasattr(self, 'btn_delete_photo'):
            self.btn_delete_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

        # ล้างข้อมูลเก่า
        for widget in self.thumbs_scrollable.winfo_children():
            widget.destroy()

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
        rows = cursor.fetchall()
        conn.close()

        # ลบ DB Record ขยะที่ไม่มีไฟล์จริงบนดิสก์ให้อัตโนมัติ (Auto-Clean Orphan DB Records)
        orphan_paths = [row[0] for row in rows if not os.path.exists(row[0])]
        if orphan_paths:
            try:
                conn = self.db.get_connection()
                cursor = conn.cursor()
                for p in orphan_paths:
                    cursor.execute("DELETE FROM staff_embeddings WHERE staff_id = ? AND image_path = ?", (staff_id, p))
                conn.commit()
                conn.close()
                logger.info(f"Auto-cleaned {len(orphan_paths)} orphan DB face records for teacher ID {staff_id}")
            except Exception as e:
                logger.error(f"Error auto-cleaning teacher orphan records: {e}")

        rows = [row for row in rows if os.path.exists(row[0])]
        logger.info(f"Registry: Loaded {len(rows)} templates thumbnails for teacher ID {staff_id}")
        
        if not rows:
            lbl_empty = ctk.CTkLabel(self.thumbs_scrollable, text="ไม่มีรูปภาพใบหน้าในฐานข้อมูล", text_color="#A2B5CD", font=ctk.CTkFont(size=11))
            lbl_empty.pack(pady=15)
            return

        # กำหนดคอลัมน์กริดตาราง
        cols = 4
        # ให้ทุกคอลัมน์ขยายตัวกระจายกันสวยงามใน Scrollable Frame
        for col_idx in range(cols):
            self.thumbs_scrollable.grid_columnconfigure(col_idx, weight=1)

        for idx, row in enumerate(rows):
            path = row[0]
            r_idx = idx // cols
            c_idx = idx % cols
            
            if os.path.exists(path):
                try:
                    pil_img = Image.open(path).convert("RGB")
                    pil_img = pil_img.resize((70, 70), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=pil_img, size=(70, 70))
                    
                    # สร้าง CTkFrame เป็นกรอบรอบรูปภาพย่อย (ไม่มี border_color="transparent")
                    frame_border = ctk.CTkFrame(self.thumbs_scrollable, width=80, height=80, fg_color="transparent", border_width=0)
                    frame_border.grid(row=r_idx, column=c_idx, padx=5, pady=5)
                    frame_border.grid_propagate(False)
                    frame_border.pack_propagate(False)
                    
                    lbl_thumb = ctk.CTkLabel(frame_border, image=ctk_img, text="")
                    lbl_thumb.pack(padx=2, pady=2, expand=True, fill="both")
                    
                    # ผูกอีเวนต์เมื่อแอดมินคลิกเลือกภาพใบหน้าย่อย
                    lbl_thumb.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_thumbnail(p, w))
                    frame_border.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_thumbnail(p, w))
                except Exception as e:
                    logger.error(f"Error reading image: {e}")
                    self.show_fallback_thumbnail(r_idx, c_idx, path)
            else:
                self.show_fallback_thumbnail(r_idx, c_idx, path)

    def show_fallback_thumbnail(self, r_idx, c_idx, path):
        frame_border = ctk.CTkFrame(self.thumbs_scrollable, width=80, height=80, fg_color="transparent", border_width=0)
        frame_border.grid(row=r_idx, column=c_idx, padx=5, pady=5)
        frame_border.grid_propagate(False)
        frame_border.pack_propagate(False)
        
        lbl_fallback = ctk.CTkLabel(
            frame_border, text="X", 
            fg_color="#1C2D42", text_color="#E74C3C",
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=6
        )
        lbl_fallback.pack(padx=2, pady=2, expand=True, fill="both")
        
        # ผูกอีเวนต์คลิกเพื่อลบรูปที่พัง
        lbl_fallback.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_thumbnail(p, w))
        frame_border.bind("<Button-1>", lambda event, p=path, w=frame_border: self.select_thumbnail(p, w))
            
    def open_google_picker(self, mode):
        """เปิดหน้าต่างค้นหาและดึงไฟล์สิทธิ์บนคลาวด์"""
        logger.info(f"Drive Picker: Opening popup window for {mode} selection...")
        cred_path = self.entry_cred_path.get().strip()
        if not os.path.exists(cred_path):
            messagebox.showwarning("ข้อผิดพลาด", "ไม่พบไฟล์คีย์สิทธิ์ Service Account JSON กรุณาตรวจสอบการตั้งค่าที่หน้า 'ตั้งค่าระบบ' ก่อน")
            return
            
        self.sync_manager.credentials_path = cred_path
        
        # ปรับโหมดจริงสำหรับตัวเลือก Google Drive Picker
        picker_mode = "folder" if "folder" in mode else mode
        
        # รันเปิด Modal popup picker
        GoogleDrivePicker(self, mode=picker_mode, callback=lambda m, i_id, i_name: self.on_google_item_picked(mode, i_id, i_name))

    def on_google_item_picked(self, mode, item_id, item_name):
        logger.info(f"Drive Picker: User selected -> {item_name} (ID: {item_id})")
        if mode == "folder":
            self.entry_drive_folder_id.delete(0, "end")
            self.entry_drive_folder_id.insert(0, item_id)
            logger.info(f"Drive Picker: Set folder ID to {item_id}")
            # ตรวจสอบว่าเคยสแกนโฟลเดอร์นี้แล้วหรือยัง
            self.check_folder_matched_status(item_id, item_name)
        elif mode == "json_folder":
            self.entry_json_folder_id.delete(0, "end")
            self.entry_json_folder_id.insert(0, item_id)
            logger.info(f"Drive Picker: Set JSON folder ID to {item_id}")
        elif mode == "sheet":
            self.entry_sheets_id.delete(0, "end")
            self.entry_sheets_id.insert(0, item_id)
            logger.info(f"Drive Picker: Set spreadsheet ID to {item_id}")
        elif mode == "delete_req_json":
            self.entry_delete_req_file_id.delete(0, "end")
            self.entry_delete_req_file_id.insert(0, item_id)
            logger.info(f"Drive Picker: Set Delete Request JSON file ID to {item_id}")
            self.load_delete_requests_table()
        elif mode == "root_year_folder":
            first_id = item_id.split(",")[0].strip() if item_id else ""
            first_name = item_name.split(",")[0].strip() if item_name else ""
            if hasattr(self, "entry_root_folder_id"):
                self.entry_root_folder_id.delete(0, "end")
                self.entry_root_folder_id.insert(0, first_id)
            if hasattr(self, "entry_root_folder_name"):
                self.entry_root_folder_name.delete(0, "end")
                self.entry_root_folder_name.insert(0, first_name)
            if hasattr(self, "entry_root_folder_year"):
                yr = self.db.extract_year_from_text(first_name)
                self.entry_root_folder_year.delete(0, "end")
                if yr:
                    self.entry_root_folder_year.insert(0, yr)
            logger.info(f"Drive Picker: Selected Root Year Folder -> {first_name} (ID: {first_id})")
            return
            
        # บันทึกการตั้งค่าลงสถานะทันที เพื่อเก็บค่าค้างไว้
        self.save_settings()

    def open_sheets_in_browser(self):
        """ดึง ID สเปรดชีตปัจจุบันแล้วเรียกเปิดบนหน้า Chrome Browser"""
        sheets_id = self.entry_sheets_id.get().strip()
        if not sheets_id:
            messagebox.showwarning("คำเตือน", "กรุณาระบุหรือเลือก ID ของ Google Sheets ก่อนเปิดดู")
            return
            
        url = f"https://docs.google.com/spreadsheets/d/{sheets_id}/edit"
        logger.info(f"[UI] Opening Google Sheets in Web Browser: {url}")
        import webbrowser
        webbrowser.open(url)

    def open_json_folder_in_browser(self):
        """เปิดโฟลเดอร์สำหรับเก็บไฟล์ JSON บนเว็บเบราว์เซอร์"""
        folder_id = self.entry_json_folder_id.get().strip()
        if not folder_id:
            messagebox.showwarning("คำเตือน", "กรุณาระบุหรือเลือก ID โฟลเดอร์ที่จัดเก็บไฟล์ JSON ก่อนเปิดดู")
            return
            
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        logger.info(f"[UI] Opening Google Drive JSON Folder in Web Browser: {url}")
        import webbrowser
        webbrowser.open(url)

    def get_matched_folders(self):
        """ดึงประวัติโฟลเดอร์ที่เคยสแกนจับคู่สำเร็จจากไฟล์ matched_folders.json"""
        import json
        settings_dir = os.path.join(get_project_root(), "data")
        log_path = os.path.join(settings_dir, "matched_folders.json")
        if not os.path.exists(log_path):
            return {}
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading matched folders log: {e}")
            return {}

    def record_matched_folder(self, folder_id, folder_name):
        """บันทึกโฟลเดอร์กิจกรรมที่ทำการสแกนสำเร็จลง matched_folders.json"""
        import json
        settings_dir = os.path.join(get_project_root(), "data")
        os.makedirs(settings_dir, exist_ok=True)
        log_path = os.path.join(settings_dir, "matched_folders.json")
        data = self.get_matched_folders()
        data[folder_id] = folder_name
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"[LOG] Recorded matched folder: {folder_name} (ID: {folder_id})")
        except Exception as e:
            logger.error(f"Error writing matched folders log: {e}")

    def check_folder_matched_status(self, folder_id, folder_name):
        """ตรวจสอบสถานะประวัติการจับคู่สำเร็จ พร้อมทำ Pop-up แจ้งเตือนหรือ Log บอกสถานะ"""
        matched_data = self.get_matched_folders()
        
        # รองรับการส่งโฟลเดอร์แบบเลือกพร้อมกันหลายตัวแยกด้วยคอมมา
        folder_ids = [fid.strip() for fid in folder_id.split(",") if fid.strip()]
        folder_names = [fname.strip() for fname in folder_name.split(",") if fname.strip()]
        
        already_matched = []
        for fid, fname in zip(folder_ids, folder_names):
            if fid in matched_data:
                already_matched.append(fname)
                
        if already_matched:
            names_str = ", ".join(already_matched)
            messagebox.showwarning(
                "เคยสแกนบางโฟลเดอร์แล้ว", 
                f"โฟลเดอร์กิจกรรมต่อไปนี้ เคยทำการสแกนจับคู่ใบหน้า (Matching) สำเร็จแล้ว:\n\n'{names_str}'\n\n(หากต้องการสแกนทับใหม่อีกครั้ง กรุณาติ๊กถูกที่ช่อง 'สแกนซ้ำภาพเดิม' ก่อนเริ่มสแกน)"
            )
            logger.warning(f"[SCAN_INFO] โฟลเดอร์กิจกรรมเหล่านี้เคยผ่านการสแกนแล้ว: {names_str}")
            return True
        else:
            logger.info(f"[SCAN_INFO] ทุกโฟลเดอร์ที่เลือกยังไม่เคยทำการสแกนจับคู่ใบหน้ามาก่อน")
            return False

    def destroy(self):
        """บันทึกการตั้งค่าทับลงสถานะเมื่อแอดมินปิดโปรแกรม"""
        try:
            self.save_settings()
            logger.info("[SYSTEM] Automatically saved configurations on application destroy.")
        except Exception as e:
            logger.error(f"Error saving settings on destroy: {e}")
        super().destroy()

    def select_thumbnail(self, path, frame_widget):
        """เลือก/ยกเลิกการเลือกรูปภาพย่อยของคุณครู (Multi-Select)"""
        if not hasattr(self, 'selected_thumb_paths'):
            self.selected_thumb_paths = set()

        if path in self.selected_thumb_paths:
            self.selected_thumb_paths.remove(path)
            try:
                frame_widget.configure(fg_color="transparent", border_width=0, border_color="transparent")
            except Exception:
                pass
        else:
            self.selected_thumb_paths.add(path)
            try:
                frame_widget.configure(fg_color="transparent", border_width=3, border_color="#FF5252")
            except Exception:
                pass

        count = len(self.selected_thumb_paths)
        if hasattr(self, 'btn_delete_photo'):
            if count > 0:
                self.btn_delete_photo.configure(state="normal", text=f"❌ ลบรูปภาพที่เลือก ({count} รูป)")
            else:
                self.btn_delete_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

    def delete_selected_photo(self):
        """ทำการลบรูปภาพใบหน้าย่อยคุณครูที่แอดมินเลือกจากระบบ (Bulk Delete)"""
        if not hasattr(self, 'selected_thumb_paths') or not self.selected_thumb_paths or not hasattr(self, 'selected_staff_id') or not self.selected_staff_id:
            return

        count = len(self.selected_thumb_paths)
        confirm = messagebox.askyesno(
            "ยืนยันการลบรูปภาพ", 
            f"คุณแน่ใจหรือไม่ว่าต้องการลบรูปภาพใบหน้าจำนวน {count} รูปภาพที่เลือกออกจากระบบ?"
        )
        if not confirm:
            return

        try:
            paths_to_delete = list(self.selected_thumb_paths)
            conn = self.db.get_connection()
            cursor = conn.cursor()
            for p in paths_to_delete:
                cursor.execute("DELETE FROM staff_embeddings WHERE image_path = ? AND staff_id = ?", (p, self.selected_staff_id))
            conn.commit()
            conn.close()

            deleted_files = 0
            for p in paths_to_delete:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        deleted_files += 1
                    except Exception as fe:
                        logger.error(f"Failed to delete file {p}: {fe}")

            logger.info(f"Deleted {count} teacher photos from DB ({deleted_files} files from disk)")

            self.selected_thumb_paths = set()
            if hasattr(self, 'btn_delete_photo'):
                self.btn_delete_photo.configure(state="disabled", text="❌ ลบรูปภาพที่เลือก")

            self.load_staff_list()
            self.show_staff_thumbnails(self.selected_staff_id)

            messagebox.showinfo("ลบสำเร็จ", f"ลบรูปภาพใบหน้าจำนวน {count} รูป เรียบร้อยแล้ว")
        except Exception as e:
            logger.error(f"[SYSTEM] Error deleting photo: {e}", exc_info=True)
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถลบภาพได้: {e}")

    def batch_import_teachers(self):
        """เลือกโฟลเดอร์หลักแล้วนำเข้าโฟลเดอร์ย่อยหรือไฟล์ภาพโดยตรงเป็นรายชื่อครูและรูปภาพย่อยแบบอัตโนมัติ (v6.33)"""
        main_dir = filedialog.askdirectory(title="เลือกโฟลเดอร์รูปภาพคุณครู (รองรับทั้งไฟล์ภาพโดยตรงและโฟลเดอร์ย่อย)")
        if not main_dir:
            return
            
        # ล้างการเลือกตัวพรีวิวเก่าออกชั่วคราว
        self.selected_thumb_path = None
        self.selected_thumb_widget = None
        self.btn_delete_photo.configure(state="disabled")
        
        # รัน Thread เบื้องหลังเพื่อไม่ให้ GUI ค้าง
        import threading
        threading.Thread(target=self._batch_import_thread, args=(main_dir,), daemon=True).start()

    def _batch_import_thread(self, main_dir):
        logger.info(f"[INIT] เริ่มนำเข้าข้อมูลใบหน้าครูอัตโนมัติแบบกลุ่ม (Smart Batch Import v6.33) จาก: {main_dir}")
        
        try:
            # 1. โหลดระบบวิเคราะห์ใบหน้า AI (ป้องกัน NoneType)
            if self.analyzer is None:
                use_gpu = self.chk_use_gpu.get()
                self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if not self.analyzer.initialize():
                logger.error("[SYSTEM] ไม่สามารถเริ่มระบบ InsightFace AI ได้ การนำเข้าล้มเหลว")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเปิดระบบตรวจจับใบหน้า AI ได้"))
                return
                
            valid_extensions = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff")
            
            # ตรวจสอบไฟล์รูปภาพโดยตรงในโฟลเดอร์หลัก
            direct_files = [
                f for f in os.listdir(main_dir) 
                if os.path.splitext(f)[1].lower() in valid_extensions and os.path.isfile(os.path.join(main_dir, f))
            ]
            
            # ตรวจสอบโฟลเดอร์ย่อย
            subdirs = [
                (item, os.path.join(main_dir, item)) 
                for item in os.listdir(main_dir) 
                if os.path.isdir(os.path.join(main_dir, item))
            ]
            
            if not direct_files and not subdirs:
                logger.warning(f"[UI] ไม่พบไฟล์รูปภาพหรือโฟลเดอร์ย่อยในโฟลเดอร์หลักที่เลือก: {main_dir}")
                self.after(0, lambda: messagebox.showwarning("คำเตือน", "ไม่พบไฟล์รูปภาพหรือโฟลเดอร์ย่อยในโฟลเดอร์ที่เลือก"))
                return
                
            total_imported_photos = 0
            
            # ==================== MODE 1: Smart Direct Files Mode (ไฟล์ภาพโดยตรงในโฟลเดอร์) ====================
            if direct_files:
                logger.info(f"[SMART_BATCH] พบไฟล์ภาพโดยตรง {len(direct_files)} ไฟล์ -> เข้าสู่โหมดจำแนกชื่อและสังกัดอัตโนมัติ")
                
                # จัดกลุ่มไฟล์ตามคุณครูแต่ละท่าน (main_name)
                teachers_map = {} # main_name -> {'department': str, 'files': [(photo_index, file_name, full_path)]}
                for f in direct_files:
                    full_path = os.path.join(main_dir, f)
                    m_name, dept, p_idx = parse_teacher_filename(f)
                    if not m_name:
                        m_name = os.path.splitext(f)[0]
                    if m_name not in teachers_map:
                        teachers_map[m_name] = {'department': dept, 'files': []}
                    elif dept and not teachers_map[m_name]['department']:
                        teachers_map[m_name]['department'] = dept
                    teachers_map[m_name]['files'].append((p_idx, f, full_path))
                    
                # เรียงลำดับรูปภาพของคุณครูแต่ละท่านตาม photo_index
                for m_name in teachers_map:
                    teachers_map[m_name]['files'].sort(key=lambda x: (x[0], x[1]))
                    
                teachers_count = len(teachers_map)
                logger.info(f"[SMART_BATCH] จำแนกคุณครูได้ทั้งหมด {teachers_count} ท่าน จากภาพ {len(direct_files)} รูป")
                
                for t_idx, (m_name, info) in enumerate(teachers_map.items()):
                    dept = info['department']
                    files = info['files']
                    logger.info(f"[BATCH_IMPORT] ({t_idx+1}/{teachers_count}) กำลังประมวลผลครู: '{m_name}' สังกัด: '{dept or 'ทั่วไป'}' ({len(files)} รูป)")
                    
                    # 1. ลงทะเบียนหรือดึง ID ครู พร้อมบันทึกกลุ่มสาระ
                    staff_id = self.db.register_staff_member(m_name, department=dept)
                    
                    # 2. ดึงรายชื่อภาพเดิมใน DB เพื่อตรวจซ้ำ
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
                    existing_paths = [row[0] for row in cursor.fetchall()]
                    conn.close()
                    
                    for p_idx, orig_file, full_path in files:
                        orig_base = os.path.splitext(orig_file)[0]
                        orig_clean = "".join(c for c in orig_base if c.isalnum() or c in ('-', '_'))
                        seq_clean = "".join(c for c in f"{m_name}_{p_idx}" if c.isalnum() or c in ('-', '_'))
                        
                        already_imported = False
                        for ep in existing_paths:
                            ep_base = os.path.basename(ep)
                            if orig_clean in ep_base or seq_clean in ep_base:
                                already_imported = True
                                break
                                
                        if already_imported:
                            logger.info(f"[BATCH_IMPORT] รูปภาพ '{orig_file}' (ลำดับ {p_idx}) ของครู '{m_name}' เคยนำเข้าแล้ว -> ข้าม")
                            continue
                            
                        logger.info(f"[FACE_AI] ({p_idx}/{len(files)}) กำลังตรวจหาพิกัดใบหน้าจาก: {orig_file}")
                        try:
                            faces_in_img = self.analyzer.detect_and_extract_faces(full_path)
                            if not faces_in_img:
                                logger.warning(f"[FACE_AI] ไม่พบใบหน้าเด่นชัดในรูปภาพ: {orig_file}")
                                continue
                                
                            best_face = max(faces_in_img, key=lambda x: x["det_score"])
                            
                            # บันทึกรูปครอปใบหน้าโดยระบุชื่อครูและลำดับรูป เช่น นายสมชาย ใจดี 1
                            cropped_path = self.save_cropped_face(
                                staff_id=staff_id,
                                original_path=full_path,
                                bbox=best_face["bbox"],
                                count=p_idx,
                                orig_filename=f"{m_name}_{p_idx}"
                            )
                            
                            self.db.add_staff_embedding(
                                staff_id=staff_id,
                                image_path=cropped_path,
                                embedding_vector=best_face["embedding"]
                            )
                            
                            total_imported_photos += 1
                            logger.info(f"[MATCH_OK] ลงทะเบียนใบหน้า '{m_name} {p_idx}' สำเร็จ!")
                            
                        except Exception as img_err:
                            logger.error(f"[FACE_AI] เกิดข้อผิดพลาดขณะประมวลผลภาพ {orig_file}: {img_err}")
                            
                logger.info(f"[SYSTEM] นำเข้าครูและใบหน้าทั้งหมดเสร็จสิ้น รวมลงทะเบียน {total_imported_photos} รูป จากครู {teachers_count} ท่าน")
                self.after(0, lambda: messagebox.showinfo(
                    "นำเข้าสำเร็จ", 
                    f"นำเข้าข้อมูลครูแบบกลุ่มเสร็จสิ้น!\n"
                    f"• ตรวจพบคุณครูทั้งหมด: {teachers_count} ท่าน\n"
                    f"• ลงทะเบียนใบหน้าสำเร็จ: {total_imported_photos} ภาพ"
                ))
                self.after(0, self.load_staff_list)
                return

            # ==================== MODE 2: Legacy Subfolder Mode (1 โฟลเดอร์ต่อครู 1 ท่าน) ====================
            logger.info(f"[SYSTEM] ตรวจพบข้อมูลโฟลเดอร์ครูทั้งหมด {len(subdirs)} คน")
            
            for idx, (folder_name, path) in enumerate(subdirs):
                m_name, dept, _ = parse_teacher_filename(folder_name)
                if not m_name:
                    m_name = folder_name
                    
                logger.info(f"[INIT] ({idx+1}/{len(subdirs)}) กำลังตรวจสอบโฟลเดอร์ครู: '{m_name}' สังกัด: '{dept}'")
                
                # ตรวจเช็คหรือสร้างชื่อคนในระบบ SQLite พร้อมสังกัด
                staff_id = self.db.register_staff_member(m_name, department=dept)
                
                # ดึงรายชื่อภาพที่บันทึกไว้แล้วทั้งหมดสำหรับครูคนนี้ เพื่อนำมาตรวจไฟล์ซ้ำ
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
                existing_paths = [row[0] for row in cursor.fetchall()]
                conn.close()
                
                files = [f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in valid_extensions]
                if not files:
                    logger.warning(f"[UI] โฟลเดอร์ของ '{m_name}' ไม่มีรูปภาพที่เหมาะสม")
                    continue
                    
                logger.info(f"[SCAN_INFO] พบรูปภาพ {len(files)} รูปในโฟลเดอร์ครู '{m_name}'")
                
                for f_idx, file in enumerate(files):
                    already_imported = False
                    file_base = os.path.splitext(file)[0].lower()
                    for ep in existing_paths:
                        ep_base = os.path.basename(ep).lower()
                        if f"_{file_base}." in ep_base or ep_base.endswith(f"_{file_base}"):
                            already_imported = True
                            break
                            
                    if already_imported:
                        logger.info(f"[SYSTEM] รูปภาพ '{file}' ของครู '{m_name}' เคยนำเข้าแล้ว -> ข้ามการทำงาน")
                        continue
                        
                    filepath = os.path.join(path, file)
                    logger.info(f"[FACE_AI] ({f_idx+1}/{len(files)}) กำลังตรวจหาพิกัดใบหน้าจาก: {file}")
                    
                    try:
                        faces_in_img = self.analyzer.detect_and_extract_faces(filepath)
                        if not faces_in_img:
                            logger.warning(f"[FACE_AI] ไม่พบใบหน้าเด่นชัดในรูปภาพ: {file}")
                            continue
                            
                        best_face = max(faces_in_img, key=lambda x: x["det_score"])
                        
                        cropped_path = self.save_cropped_face(
                            staff_id=staff_id,
                            original_path=filepath,
                            bbox=best_face["bbox"],
                            count=len(existing_paths) + total_imported_photos + 1,
                            orig_filename=file
                        )
                        
                        self.db.add_staff_embedding(
                            staff_id=staff_id,
                            image_path=cropped_path,
                            embedding_vector=best_face["embedding"]
                        )
                        
                        total_imported_photos += 1
                        logger.info(f"[MATCH_OK] ลงทะเบียนใบหน้าครู '{m_name}' จากรูป {file} สำเร็จ!")
                        
                    except Exception as img_err:
                        logger.error(f"[FACE_AI] เกิดข้อผิดพลาดขณะประมวลผลภาพ {file}: {img_err}")
                                
            # นำเข้าจบกระบวนการ -> รีเฟรชหน้า GUI เธรดหลัก
            logger.info(f"[SYSTEM] นำเข้าครูและใบหน้าทั้งหมดเสร็จสิ้น รวมลงทะเบียน {total_imported_photos} รูป")
            self.after(0, lambda: messagebox.showinfo(
                "นำเข้าสำเร็จ", 
                f"นำเข้าข้อมูลครูแบบกลุ่มเสร็จสิ้น!\n"
                f"• ตรวจพบโฟลเดอร์ครู: {len(subdirs)} ท่าน\n"
                f"• ลงทะเบียนใบหน้าสำเร็จทั้งหมด: {total_imported_photos} ภาพ"
            ))
            self.after(0, self.load_staff_list)
            
        except Exception as thread_err:
            logger.error(f"[SYSTEM] เกิดความขัดข้องใน Thread นำเข้ากลุ่ม: {thread_err}", exc_info=True)
            self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"กระบวนการนำเข้าล้มเหลว: {thread_err}"))

    def _block_console_keys(self, event):
        """บล็อกปุ่มคีย์บอร์ดในกล่องล็อก Console ยกเว้น Ctrl+C (ก็อปปี้) และ Ctrl+A (คลุมดำทั้งหมด)"""
        ctrl_pressed = (event.state & 0x0004) != 0 # 0x0004 คือ Control Key ใน Windows/Linux
        key = event.keysym.lower()
        if ctrl_pressed:
            if key == 'c':
                self.copy_console_selection()
                return "break"
            elif key == 'a':
                self.console_text.tag_add("sel", "1.0", "end")
                return "break"
        return "break" # ปิดกั้นการเขียนหรือป้อนข้อมูลอื่น ๆ ทั้งหมด

    def show_console_context_menu(self, event):
        """สร้างและแสดงหน้าต่างเมนูคลิกขวาใน Console Log"""
        menu = tk.Menu(self, tearoff=0, bg="#101B2B", fg="#ECEFF1", activebackground="#1F3A60", activeforeground="white")
        menu.add_command(label="📋 คัดลอกข้อความที่เลือก (Copy)", command=self.copy_console_selection)
        menu.add_command(label="🧹 ล้างข้อความทั้งหมด (Clear Log)", command=self.clear_console_log)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def copy_console_selection(self):
        """คัดลอกข้อความเฉพาะบริเวณที่คลิกเมาส์ลากคลุมดำไว้ หรือทั้งหมดหากไม่ได้เลือกอะไรไว้ลงสู่ Clipboard"""
        try:
            selected_text = self.console_text.get("sel.first", "sel.last")
        except tk.TclError:
            # ไม่มีข้อความที่ถูกลากคลุมดำไว้ -> คัดลอกทั้งหมด
            selected_text = self.console_text.get("1.0", "end-1c")
            
        if selected_text:
            self.clipboard_clear()
            self.clipboard_append(selected_text)
            logger.info("[UI] คัดลอกข้อความล็อกไปยัง Clipboard สำเร็จ")

    def copy_all_console_log(self):
        """คัดลอกข้อความ Log ทั้งหมด 100% ลงสู่ Clipboard ทันที"""
        text = self.console_text.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            logger.info("[UI] คัดลอกข้อความ Log ทั้งหมดไปยัง Clipboard เรียบร้อยแล้ว")

    # ==================== (6) หน้าเฟรมคำขอลบรูปภาพจากไฟล์ JSON (v1.6.7) ====================
    def setup_delete_req_ui(self):
        self.frame_delete_req.grid_columnconfigure(0, weight=1)
        self.frame_delete_req.grid_rowconfigure(3, weight=1)

        # หัวข้อหลัก
        lbl_title = ctk.CTkLabel(
            self.frame_delete_req, text="ระบบจัดการคำขอลบรูปภาพกิจกรรม", 
            font=ctk.CTkFont(size=26, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        # แถวป้อนไฟล์ JSON คำขอบนคลาวด์ (Google Drive)
        gdrive_file_frame = ctk.CTkFrame(self.frame_delete_req, fg_color="transparent")
        gdrive_file_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        gdrive_file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            gdrive_file_frame, text="ไฟล์ JSON คำขอลบบน Google Drive:", 
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD"
        ).grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.entry_delete_req_file_id = ctk.CTkEntry(
            gdrive_file_frame, placeholder_text="ระบุ ID ไฟล์ delete_request.json บน Google Drive ของท่าน",
            height=36, font=ctk.CTkFont(size=14)
        )
        self.entry_delete_req_file_id.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        btn_pick_file = ctk.CTkButton(
            gdrive_file_frame, text="🔍 เลือกไฟล์ JSON", width=140, height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=lambda: self.open_google_picker("delete_req_json")
        )
        btn_pick_file.grid(row=0, column=2, padx=(0, 5), sticky="e")

        btn_open_file = ctk.CTkButton(
            gdrive_file_frame, text="🌐 เปิดดูไฟล์", width=120, height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#E67E22", hover_color="#D35400", text_color="white",
            command=self.open_delete_req_file_in_browser
        )
        btn_open_file.grid(row=0, column=3, sticky="e")

        # โซนปุ่มควบคุมด้านล่าง (แถวที่ 2)
        action_bar = ctk.CTkFrame(self.frame_delete_req, fg_color="transparent")
        action_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        btn_refresh = ctk.CTkButton(
            action_bar, text="🔄 รีเฟรชตารางคำขอ", height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.load_delete_requests_table
        )
        btn_refresh.pack(side="left", padx=(0, 10))

        self.btn_approve_delete = ctk.CTkButton(
            action_bar, text="🗑️ อนุมัติการลบรูปภาพที่เลือก", height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#E74C3C", hover_color="#C0392B", text_color="white",
            command=self.approve_delete_requests
        )
        self.btn_approve_delete.pack(side="left")

        # แถบสลับหน้า Pagination คำขอลบ
        self.btn_next_delete_req = ctk.CTkButton(
            action_bar, text="▶️", width=42, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.next_delete_req_page
        )
        self.btn_next_delete_req.pack(side="right", padx=(5, 0))

        self.lbl_delete_req_page = ctk.CTkLabel(
            action_bar, text="หน้า 1/1",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#A2B5CD"
        )
        self.lbl_delete_req_page.pack(side="right", padx=10)

        self.btn_prev_delete_req = ctk.CTkButton(
            action_bar, text="◀️", width=42, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.prev_delete_req_page
        )
        self.btn_prev_delete_req.pack(side="right", padx=(0, 5))

        # ตารางคำขอแบบ Scrollable Frame (แถวที่ 3)
        self.scr_delete_requests = ctk.CTkScrollableFrame(self.frame_delete_req, fg_color="#101B2B")
        self.scr_delete_requests.grid(row=3, column=0, sticky="nsew", pady=5)
        
        # แสดงข้อความคำแนะนำเริ่มต้น
        lbl_info = ctk.CTkLabel(
            self.scr_delete_requests, 
            text="[ กรุณาเลือกไฟล์ JSON หรือกดปุ่ม 🔄 รีเฟรชตารางคำขอ เพื่อดึงรายการจาก Google Drive ]",
            font=ctk.CTkFont(size=14), text_color="#A2B5CD"
        )
        lbl_info.pack(pady=40)

    def open_delete_req_file_in_browser(self):
        """ดึง ID ไฟล์ JSON ของคำขอลบ แล้วเปิดลิงก์บน Google Drive ใน Web Browser"""
        file_id = self.entry_delete_req_file_id.get().strip()
        if not file_id:
            messagebox.showwarning("คำเตือน", "กรุณาระบุหรือเลือก ID ไฟล์ JSON คำขอลบก่อนเปิดดู")
            return
            
        url = f"https://drive.google.com/open?id={file_id}"
        logger.info(f"[UI] Opening Delete Request JSON File in Web Browser: {url}")
        import webbrowser
        webbrowser.open(url)

    def load_delete_requests_table(self):
        # ล้างข้อมูลเก่า
        for widget in self.scr_delete_requests.winfo_children():
            widget.destroy()

        # ตรวจสอบและประกาศค่าตัวแปรเริ่มต้นหากยังไม่มี
        if not hasattr(self, "delete_req_page"):
            self.delete_req_page = 0
            self.delete_req_page_size = 15
            self.delete_req_selections = {}
            self.parsed_requests_list = []

        # ตรวจสอบและดึงข้อมูลไฟล์ delete_request.json
        import json
        
        # ตรวจสอบและดึงข้อมูลไฟล์ person_index.json จากคลาวด์เพื่อใช้ตรวจสอบการคงอยู่ของภาพ
        self.person_index = {}
        json_folder_id = self.entry_json_folder_id.get().strip()
        if json_folder_id and self.sync_manager.connected:
            try:
                # ค้นหาไฟล์ person_index.json ในโฟลเดอร์หลัก
                query = f"'{json_folder_id}' in parents and name = 'person_index.json' and trashed = false"
                search_results = self.sync_manager.drive_service.files().list(q=query, fields="files(id)").execute()
                files = search_results.get("files", [])
                
                # ถ้าไม่พบในโฟลเดอร์หลัก ลองค้นหาแบบ Global
                if not files:
                    query = "name = 'person_index.json' and trashed = false"
                    search_results = self.sync_manager.drive_service.files().list(q=query, fields="files(id)").execute()
                    files = search_results.get("files", [])
                    
                if files:
                    person_index_file_id = files[0]['id']
                    logger.info(f"[DELETE_REQ] Downloading person_index.json from Google Drive (ID: {person_index_file_id})...")
                    media_content = self.sync_manager.drive_service.files().get_media(fileId=person_index_file_id).execute()
                    self.person_index = json.loads(media_content.decode("utf-8"))
                    logger.info(f"[DELETE_REQ] Loaded person_index.json successfully. Total keys: {len(self.person_index)}")
                else:
                    logger.warning("[DELETE_REQ] person_index.json file not found on Google Drive.")
            except Exception as e:
                logger.error(f"[DELETE_REQ] Error downloading person_index.json: {e}")

        # ดึงสำรองจาก Local เผื่อกรณีเชื่อมต่อขัดข้อง
        if not self.person_index:
            local_person_index_path = os.path.join(get_project_root(), "person_index.json")
            if os.path.exists(local_person_index_path):
                try:
                    with open(local_person_index_path, "r", encoding="utf-8") as f:
                        self.person_index = json.load(f)
                    logger.info("[DELETE_REQ] Loaded person_index.json from local file.")
                except Exception:
                    pass

        # ตรวจสอบและดึงข้อมูลไฟล์ photo_index.json จากคลาวด์
        self.photo_index = {}
        if json_folder_id and self.sync_manager.connected:
            try:
                # ค้นหาไฟล์ photo_index.json ในโฟลเดอร์หลัก
                query = f"'{json_folder_id}' in parents and name = 'photo_index.json' and trashed = false"
                search_results = self.sync_manager.drive_service.files().list(q=query, fields="files(id)").execute()
                files = search_results.get("files", [])
                
                # ถ้าไม่พบในโฟลเดอร์หลัก ลองค้นหาแบบ Global
                if not files:
                    query = "name = 'photo_index.json' and trashed = false"
                    search_results = self.sync_manager.drive_service.files().list(q=query, fields="files(id)").execute()
                    files = search_results.get("files", [])
                    
                if files:
                    photo_index_file_id = files[0]['id']
                    logger.info(f"[DELETE_REQ] Downloading photo_index.json from Google Drive (ID: {photo_index_file_id})...")
                    media_content = self.sync_manager.drive_service.files().get_media(fileId=photo_index_file_id).execute()
                    self.photo_index = json.loads(media_content.decode("utf-8"))
                    logger.info(f"[DELETE_REQ] Loaded photo_index.json successfully. Total keys: {len(self.photo_index)}")
                else:
                    logger.warning("[DELETE_REQ] photo_index.json file not found on Google Drive.")
            except Exception as e:
                logger.error(f"[DELETE_REQ] Error downloading photo_index.json: {e}")

        # ดึงสำรองจาก Local เผื่อกรณีเชื่อมต่อขัดข้อง
        if not self.photo_index:
            local_photo_index_path = os.path.join(get_project_root(), "photo_index.json")
            if os.path.exists(local_photo_index_path):
                try:
                    with open(local_photo_index_path, "r", encoding="utf-8") as f:
                        self.photo_index = json.load(f)
                    logger.info("[DELETE_REQ] Loaded photo_index.json from local file.")
                except Exception:
                    pass

        delete_req_file_id = self.entry_delete_req_file_id.get().strip()
        requests = []
        loaded_from_drive = False
        
        if delete_req_file_id:
            try:
                if not self.sync_manager.connected:
                    sheet_id = self.entry_sheets_id.get().strip()
                    self.sync_manager.connect(sheet_id)
                
                logger.info(f"[DELETE_REQ] Downloading delete_request.json from Google Drive (ID: {delete_req_file_id})...")
                media_content = self.sync_manager.drive_service.files().get_media(fileId=delete_req_file_id).execute()
                requests = json.loads(media_content.decode("utf-8"))
                loaded_from_drive = True
                logger.info(f"[DELETE_REQ] Loaded delete requests from Google Drive.")
            except Exception as e:
                logger.error(f"[DELETE_REQ] Failed to download delete requests JSON from Google Drive: {e}. Falling back to local file.")

        if not loaded_from_drive:
            req_file = os.path.join(get_project_root(), "delete_request.json")
            if not os.path.exists(req_file):
                try:
                    with open(req_file, "w", encoding="utf-8") as f:
                        json.dump({}, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    requests = json.load(f)
                logger.info(f"[DELETE_REQ] Loaded delete requests from local delete_request.json")
            except Exception as e:
                logger.error(f"Error reading delete_request.json: {e}")
                requests = {}

        # ฟังก์ชันสกัดกูเกิลไดรฟ์ไอดีจากลิงก์
        def extract_gdrive_file_id(url):
            if not url:
                return ""
            import urllib.parse
            parsed_url = urllib.parse.urlparse(url)
            queries = urllib.parse.parse_qs(parsed_url.query)
            if "id" in queries:
                return queries["id"][0]
            if "/d/" in url:
                parts = url.split("/d/")
                if len(parts) > 1:
                    subparts = parts[1].split("/")
                    return subparts[0]
            return ""

        # --- Smart Parser: แปลง Dictionary หรือ List ให้เป็น Flat List รูปแบบมาตรฐาน ---
        flattened_requests = []
        if isinstance(requests, dict):
            conn = self.db.get_connection()
            cursor = conn.cursor()
            for staff_name, file_ids in requests.items():
                cursor.execute("SELECT id FROM staff_members WHERE name = ? LIMIT 1", (staff_name,))
                staff_row = cursor.fetchone()
                staff_id = staff_row[0] if staff_row else "unknown"
                
                for f_id in file_ids:
                    # ค้นหาข้อมูลภาพถ่ายแบบ Hybrid (photo_index.json คลาวด์ก่อน -> SQLite ท้องถิ่นทีหลัง)
                    file_name = f_id
                    real_drive_file_id = f_id
                    drive_link = f"https://drive.google.com/open?id={f_id}"
                    event_name = "ไม่ระบุ"
                    found_in_cloud_index = False
                    
                    if getattr(self, "photo_index", {}) and f_id in self.photo_index:
                        cloud_meta = self.photo_index[f_id]
                        file_name = f_id
                        drive_link = cloud_meta.get("drive_link", "")
                        real_drive_file_id = extract_gdrive_file_id(drive_link) or f_id
                        event_name = cloud_meta.get("event", "ไม่ระบุ")
                        found_in_cloud_index = True
                        
                    if not found_in_cloud_index:
                        cursor.execute(
                            "SELECT photo_id, drive_file_id, drive_link FROM scanned_photos WHERE photo_id = ? OR drive_file_id = ? LIMIT 1",
                            (f_id, f_id)
                        )
                        photo_row = cursor.fetchone()
                        if photo_row:
                            file_name = photo_row[0]
                            real_drive_file_id = photo_row[1]
                            drive_link = photo_row[2]

                    flattened_requests.append({
                        "drive_file_id": real_drive_file_id,
                        "file_name": file_name,
                        "drive_link": drive_link,
                        "staff_id": staff_id,
                        "staff_name": staff_name,
                        "event_name": event_name
                    })
            conn.close()
            requests = flattened_requests
            logger.info(f"[DELETE_REQ] Smart Parser: Parsed Dictionary JSON to {len(requests)} flat requests.")
        elif isinstance(requests, list):
            parsed_list = []
            conn = self.db.get_connection()
            cursor = conn.cursor()
            for item in requests:
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except Exception:
                        continue
                if isinstance(item, dict):
                    s_name = item.get("staff_name", "")
                    s_id = item.get("staff_id", "")
                    f_id = item.get("drive_file_id", "")
                    
                    if not s_id and s_name:
                        cursor.execute("SELECT id FROM staff_members WHERE name = ? LIMIT 1", (s_name,))
                        row = cursor.fetchone()
                        s_id = row[0] if row else "unknown"
                    if s_id and not s_name:
                        cursor.execute("SELECT name FROM staff_members WHERE id = ? LIMIT 1", (s_id,))
                        row = cursor.fetchone()
                        s_name = row[0] if row else "ไม่ระบุชื่อ"
                        
                    file_name = item.get("file_name", f_id)
                    drive_link = item.get("drive_link", "")
                    real_drive_file_id = f_id
                    event_name = item.get("event_name", "ไม่ระบุ")
                    found_in_cloud_index = False
                    
                    if getattr(self, "photo_index", {}) and f_id in self.photo_index:
                        cloud_meta = self.photo_index[f_id]
                        file_name = f_id
                        drive_link = cloud_meta.get("drive_link", "")
                        real_drive_file_id = extract_gdrive_file_id(drive_link) or f_id
                        event_name = cloud_meta.get("event", "ไม่ระบุ")
                        found_in_cloud_index = True
                        
                    if not found_in_cloud_index and f_id:
                        cursor.execute(
                            "SELECT photo_id, drive_file_id, drive_link FROM scanned_photos WHERE photo_id = ? OR drive_file_id = ? LIMIT 1",
                            (f_id, f_id)
                        )
                        photo_row = cursor.fetchone()
                        if photo_row:
                            file_name = file_name if (file_name and file_name != f_id) else photo_row[0]
                            real_drive_file_id = photo_row[1]
                            drive_link = drive_link or photo_row[2]
                            
                    parsed_list.append({
                        "drive_file_id": real_drive_file_id,
                        "file_name": file_name or f_id,
                        "drive_link": drive_link or f"https://drive.google.com/open?id={real_drive_file_id}",
                        "staff_id": s_id,
                        "staff_name": s_name,
                        "event_name": event_name
                    })
            conn.close()
            requests = parsed_list
            logger.info(f"[DELETE_REQ] Smart Parser: Standardized List JSON to {len(requests)} requests.")

        # อัปเดตเก็บประจุลงตัวแปรคลาส
        self.parsed_requests_list = requests
        
        # ตั้งค่าเลือกเริ่มต้น (ติ๊กถูก) สำหรับคีย์ลบใหม่ๆ
        for req in self.parsed_requests_list:
            req_key = f"{req['drive_file_id']}_{req['staff_id']}"
            if req_key not in self.delete_req_selections:
                # ถ้าภาพนี้ยังคงเชื่อมโยงอยู่กับคนคนนี้ใน person_index.json ให้ติ๊กถูกเริ่มต้นเป็น True
                # แต่หากไม่มีภาพนี้เชื่อมโยงกับคนคนนี้แล้ว (โดนลบไปแล้ว) ให้ติ๊กออกเป็น False โดยอัตโนมัติ
                connected_photos = getattr(self, "person_index", {}).get(req['staff_name'], [])
                is_active = (req['file_name'] in connected_photos) or (req['drive_file_id'] in connected_photos)
                self.delete_req_selections[req_key] = is_active
                
        self.delete_req_page = 0
        self.render_delete_requests_page()

    def prev_delete_req_page(self):
        if hasattr(self, "delete_req_page") and self.delete_req_page > 0:
            self.delete_req_page -= 1
            self.render_delete_requests_page()

    def next_delete_req_page(self):
        if hasattr(self, "delete_req_page") and hasattr(self, "parsed_requests_list"):
            import math
            total_pages = math.ceil(len(self.parsed_requests_list) / self.delete_req_page_size)
            if self.delete_req_page < total_pages - 1:
                self.delete_req_page += 1
                self.render_delete_requests_page()

    def render_delete_requests_page(self):
        # ล้างคำขอเก่าในตารางยกเว้นหัวตาราง
        for widget in self.scr_delete_requests.winfo_children():
            widget.destroy()

        # สร้างหัวตาราง (Table Header)
        header_frame = ctk.CTkFrame(self.scr_delete_requests, fg_color="#1C2D42")
        header_frame.pack(fill="x", pady=(0, 8), padx=5)
        header_frame.grid_columnconfigure(0, weight=1) # Checkbox
        header_frame.grid_columnconfigure(1, weight=2) # ภาพครูต้นแบบ
        header_frame.grid_columnconfigure(2, weight=4) # ภาพกิจกรรมที่มีปัญหา

        # ตรวจสอบสถานะการเลือกทั้งหมด
        all_checked = False
        if self.parsed_requests_list:
            all_checked = all(self.delete_req_selections.get(f"{r['drive_file_id']}_{r['staff_id']}", False) for r in self.parsed_requests_list)
            
        self.select_all_var = ctk.BooleanVar(value=all_checked)
        
        def toggle_select_all():
            new_val = self.select_all_var.get()
            for r in self.parsed_requests_list:
                rk = f"{r['drive_file_id']}_{r['staff_id']}"
                self.delete_req_selections[rk] = new_val
            self.render_delete_requests_page()
            
        cb_all = ctk.CTkCheckBox(
            header_frame, text="เลือกทั้งหมด",
            variable=self.select_all_var, command=toggle_select_all,
            font=ctk.CTkFont(weight="bold", size=12)
        )
        cb_all.grid(row=0, column=0, pady=8, padx=5, sticky="w")
        ctk.CTkLabel(header_frame, text="บุคลากรที่ขอลบ", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, pady=8, padx=5, sticky="w")
        ctk.CTkLabel(header_frame, text="ภาพกิจกรรมบน Cloud", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, pady=8, padx=5, sticky="w")

        if not self.parsed_requests_list:
            lbl_empty = ctk.CTkLabel(
                self.scr_delete_requests, text="[ ไม่มีคำขอลบรูปภาพในระบบขณะนี้ ]",
                font=ctk.CTkFont(size=13), text_color="#A2B5CD"
            )
            lbl_empty.pack(pady=40)
            self.lbl_delete_req_page.configure(text="หน้า 0/0")
            self.btn_prev_delete_req.configure(state="disabled")
            self.btn_next_delete_req.configure(state="disabled")
            return

        import math
        total_items = len(self.parsed_requests_list)
        total_pages = max(1, math.ceil(total_items / self.delete_req_page_size))
        
        if self.delete_req_page >= total_pages:
            self.delete_req_page = total_pages - 1
        if self.delete_req_page < 0:
            self.delete_req_page = 0
            
        start_idx = self.delete_req_page * self.delete_req_page_size
        end_idx = min(start_idx + self.delete_req_page_size, total_items)
        
        # ปรับปรุงปุ่ม Pagination
        self.lbl_delete_req_page.configure(text=f"หน้า {self.delete_req_page + 1}/{total_pages} ({start_idx + 1}-{end_idx} จาก {total_items})")
        self.btn_prev_delete_req.configure(state="normal" if self.delete_req_page > 0 else "disabled")
        self.btn_next_delete_req.configure(state="normal" if self.delete_req_page < total_pages - 1 else "disabled")

        page_items = self.parsed_requests_list[start_idx:end_idx]
        self.delete_req_vars = {} 
        
        for idx, req in enumerate(page_items):
            row_frame = ctk.CTkFrame(self.scr_delete_requests, fg_color="transparent")
            row_frame.pack(fill="x", pady=5, padx=5)
            row_frame.grid_columnconfigure(0, weight=1)
            row_frame.grid_columnconfigure(1, weight=2)
            row_frame.grid_columnconfigure(2, weight=4)

            # --- ตรวจสอบความเชื่อมโยงใน person_index (เช็คว่าเคยถูกลบไปแล้วหรือยัง) ---
            connected_photos = getattr(self, "person_index", {}).get(req['staff_name'], [])
            is_active = (req['file_name'] in connected_photos) or (req['drive_file_id'] in connected_photos)

            # --- คอลัมน์ 1: Checkbox ---
            req_key = f"{req['drive_file_id']}_{req['staff_id']}"
            is_selected = self.delete_req_selections.get(req_key, True)
            var = ctk.BooleanVar(value=is_selected)
            self.delete_req_vars[req_key] = (var, req)
            
            def on_check(v=var, k=req_key):
                self.delete_req_selections[k] = v.get()
                
            cb = ctk.CTkCheckBox(row_frame, text="", variable=var, command=on_check)
            cb.grid(row=0, column=0, padx=10, pady=10, sticky="w")

            # --- คอลัมน์ 2: ข้อมูลและรูปถ่ายครูต้นแบบ ---
            staff_info_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            staff_info_frame.grid(row=0, column=1, padx=5, pady=5, sticky="w")
            
            ctk.CTkLabel(
                staff_info_frame, 
                text=f"{req['staff_name']}\nID: {req['staff_id']}", 
                anchor="w", justify="left"
            ).pack(anchor="w")

            lbl_staff_img = ctk.CTkLabel(staff_info_frame, text="[ Pending / กำลังโหลดใบหน้า... ]", text_color="#A2B5CD")
            lbl_staff_img.pack(anchor="w", pady=(5, 0))

            # --- คอลัมน์ 3: ภาพกิจกรรม Thumbnail ---
            activity_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            activity_frame.grid(row=0, column=2, padx=5, pady=5, sticky="w")

            ctk.CTkLabel(
                activity_frame, 
                text=f"ไฟล์: {req['file_name']}\nเหตุการณ์: {req.get('event_name', 'ไม่ระบุ')}", 
                anchor="w", justify="left", font=ctk.CTkFont(size=11)
            ).pack(anchor="w")

            lbl_activity_img = ctk.CTkLabel(activity_frame, text="[ Pending / กำลังโหลดพรีวิวรูป... ]", text_color="#A2B5CD")
            lbl_activity_img.pack(anchor="w", pady=(5, 0))

            def make_open_link_cmd(link=req['drive_link']):
                return lambda: self.open_drive_link(link)
                
            btn_link = ctk.CTkButton(
                activity_frame, text="🔗 เปิดลิงก์รูป", width=80, height=22,
                fg_color="#1F3A60", hover_color="#20334F", command=make_open_link_cmd()
            )
            btn_link.pack(anchor="w", pady=(5, 0))

            # โหลดรูปในเบื้องหลังอัตโนมัติเฉพาะในหน้าปัจจุบัน (15 รายการ)
            def load_previews_thread(s_id=req['staff_id'], f_id=req['drive_file_id'], lbl_staff=lbl_staff_img, lbl_act=lbl_activity_img, active=is_active):
                try:
                    # สร้างโฟลเดอร์เก็บแคชพรีวิว
                    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "thumbnail_cache")
                    os.makedirs(cache_dir, exist_ok=True)
                    cache_file = os.path.join(cache_dir, f"{f_id}.jpg")

                    # 1. โหลดรูปหน้าครูจาก SQLite (โลคอล)
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ? LIMIT 1", (s_id,))
                    img_row = cursor.fetchone()
                    conn.close()
                    
                    staff_img_path = img_row[0] if (img_row and os.path.exists(img_row[0])) else None

                    # ส่งคิวอัปเดตหน้าครูต้นแบบไปเรนเดอร์ในเธรดหลัก (Main Thread)
                    def update_staff_ui(path=staff_img_path, w=lbl_staff):
                        try:
                            if w.winfo_exists():
                                if path:
                                    from PIL import Image
                                    pil_s = Image.open(path).convert("RGB").resize((70, 70), Image.Resampling.LANCZOS)
                                    ctk_s = ctk.CTkImage(light_image=pil_s, size=(70, 70))
                                    w.configure(image=ctk_s, text="")
                                else:
                                    w.configure(text="[ ไม่มีรูปต้นแบบ ]")
                        except Exception:
                            pass
                    self.after(0, update_staff_ui)

                    # 2. โหลดรูปกิจกรรมจาก Local Cache หรือ Google Drive
                    img_bytes = None
                    # ตรวจสอบว่ามีแคชอยู่ในคอมพิวเตอร์หรือไม่
                    if os.path.exists(cache_file):
                        try:
                            with open(cache_file, "rb") as cf:
                                img_bytes = cf.read()
                        except Exception:
                            pass

                    # หากไม่มีในแคช ค่อยดาวน์โหลดจาก Google Drive
                    if not img_bytes:
                        downloaded = self.sync_manager.download_image_thumbnail_bytes(f_id)
                        if downloaded:
                            img_bytes = downloaded
                            # เขียนไฟล์แคชลงเครื่อง
                            try:
                                with open(cache_file, "wb") as cf:
                                    cf.write(downloaded)
                            except Exception:
                                pass

                    # ส่งไบต์รูปภาพไปสร้าง CTkImage และเรนเดอร์ในเธรดหลัก
                    def update_act_ui(bytes_data=img_bytes, w=lbl_act, is_active_status=active):
                        try:
                            if w.winfo_exists():
                                if bytes_data:
                                    import io
                                    from PIL import Image
                                    pil_a = Image.open(io.BytesIO(bytes_data)).convert("RGB").resize((120, 80), Image.Resampling.LANCZOS)
                                    ctk_a = ctk.CTkImage(light_image=pil_a, size=(120, 80))
                                    w.configure(image=ctk_a, text="")
                                else:
                                    # หากโหลดไม่ได้จริงๆ หรือไฟล์ไม่มีอยู่บน Google Drive
                                    from PIL import Image, ImageDraw
                                    err_img = Image.new("RGB", (120, 80), color="#E67E22" if not is_active_status else "#C0392B")
                                    draw = ImageDraw.Draw(err_img)
                                    msg = "Photo Not Found" if not is_active_status else "Error: No Image"
                                    draw.text((12 if not is_active_status else 10, 35), msg, fill="white")
                                    ctk_err = ctk.CTkImage(light_image=err_img, size=(120, 80))
                                    w.configure(image=ctk_err, text="")
                        except Exception:
                            pass
                    self.after(0, update_act_ui)

                except Exception as preview_err:
                    logger.error(f"Error loading preview for request: {preview_err}")

            threading.Thread(target=load_previews_thread, daemon=True).start()
            
            # เส้นคั่น
            ctk.CTkFrame(self.scr_delete_requests, height=2, fg_color="#1C2D42").pack(fill="x", pady=5)
            
    def approve_delete_requests(self):
        selected_requests = []
        if hasattr(self, "parsed_requests_list") and hasattr(self, "delete_req_selections"):
            for req in self.parsed_requests_list:
                req_key = f"{req['drive_file_id']}_{req['staff_id']}"
                if self.delete_req_selections.get(req_key, True):
                    selected_requests.append(req)

        if not selected_requests:
            messagebox.showinfo("ไม่ได้เลือกคำขอ", "ยังไม่มีคำขอลบรูปภาพใดที่ถูกเลือกติ๊กถูก")
            return

        confirm = messagebox.askyesno(
            "ยืนยันการอนุมัติลบ",
            f"คุณต้องการอนุมัติลบรูปภาพกิจกรรมคุณครูที่เลือกจำนวน {len(selected_requests)} รายการออกจากระบบ?\nการกระทำนี้จะลบข้อมูลจาก SQLite และ Google Sheets โดยถาวร"
        )
        if not confirm:
            return

        # เริ่มเธรดย่อยลบประวัติเพื่อไม่ให้ UI ค้าง
        def process_delete():
            try:
                # 1. คอนเนค Google Sheets ก่อน
                sheet_id = self.entry_sheets_id.get().strip()
                if not self.sync_manager.connect(sheet_id):
                    self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเข้าถึง Google Sheets ได้ กระบวนการลบล้มเหลว!"))
                    return

                logger.info(f"[DELETE_REQ] Starting approval process for {len(selected_requests)} requests...")
                
                # ดึง Google Sheets Credentials
                gc = self.sync_manager.gspread_client
                sh = gc.open_by_key(sheet_id)
                wks_faces = sh.worksheet("faces")
                wks_photos = sh.worksheet("photos")
                
                # ดึง ID โฟลเดอร์ JSON
                json_folder_id = self.entry_json_folder_id.get().strip()

                for req in selected_requests:
                    staff_id = req["staff_id"]
                    drive_file_id = req["drive_file_id"]

                    # 1. ลบความสัมพันธ์ใน SQLite `detected_faces`
                    # หา photo_id ก่อน
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT photo_id FROM scanned_photos WHERE drive_file_id = ?", (drive_file_id,))
                    p_row = cursor.fetchone()
                    
                    count_left = -1
                    photo_id = None
                    if p_row:
                        photo_id = p_row[0]
                        # ลบใน detected_faces ของคู่ความสัมพันธ์นี้
                        cursor.execute("DELETE FROM detected_faces WHERE photo_id = ? AND staff_id = ?", (photo_id, staff_id))
                        conn.commit()
                        logger.info(f"[DATABASE] Removed match: photo_id={photo_id}, staff_id={staff_id}")
                        
                        # ตรวจสอบว่าภาพกิจกรรมนี้ยังเหลือบุคลากรครูคนอื่นๆ อยู่หรือไม่
                        cursor.execute("SELECT COUNT(*) FROM detected_faces WHERE photo_id = ?", (photo_id,))
                        count_left = cursor.fetchone()[0]
                        if count_left == 0:
                            # ถ้าไม่เหลือใครเกี่ยวแล้ว ให้ลบภาพนี้ออกจาก scanned_photos
                            cursor.execute("DELETE FROM scanned_photos WHERE photo_id = ?", (photo_id,))
                            conn.commit()
                            logger.info(f"[DATABASE] Removed empty photo record: photo_id={photo_id}")
                    conn.close()

                    # 2. ลบแถวใน Google Sheets `faces`
                    if photo_id:
                        try:
                            all_faces = wks_faces.get_all_values()
                            # หัวตาราง: photo_id, staff_id, confidence, name
                            rows_to_delete = []
                            # เก็บ index แถวที่จะลบ (เริ่มจาก 1 ตาม API Sheets)
                            for r_idx, row in enumerate(all_faces):
                                if r_idx == 0:
                                    continue
                                if row[0] == photo_id and row[1] == staff_id:
                                    rows_to_delete.append(r_idx + 1)
                            
                            # ลบจากล่างขึ้นบนเพื่อป้องกัน index คลาดเคลื่อน
                            for r_num in reversed(rows_to_delete):
                                wks_faces.delete_rows(r_num)
                                logger.info(f"[GSHEETS] Deleted row {r_num} in sheet 'faces'")
                        except Exception as sheet_err:
                            logger.error(f"[GSHEETS] Error deleting row in sheet 'faces': {sheet_err}")

                    # 3. หากภาพนี้ไม่เหลือใครเกี่ยวแล้ว ให้ลบแถวภาพนี้ในแผ่นงาน `photos`
                    if photo_id and count_left == 0:
                        try:
                            all_photos = wks_photos.get_all_values()
                            # หัวตาราง: photo_id, drive_file_id, event_name, drive_link, photo_date
                            photo_rows_to_delete = []
                            for r_idx, row in enumerate(all_photos):
                                if r_idx == 0:
                                    continue
                                if row[0] == photo_id:
                                    photo_rows_to_delete.append(r_idx + 1)
                                    
                            for r_num in reversed(photo_rows_to_delete):
                                wks_photos.delete_rows(r_num)
                                logger.info(f"[GSHEETS] Deleted row {r_num} in sheet 'photos'")
                        except Exception as sheet_err:
                            logger.error(f"[GSHEETS] Error deleting row in sheet 'photos': {sheet_err}")

                # 2. ทำการอัปเดตไฟล์ดัชนี JSON และ Excel ท้องถิ่นใหม่ทั้งหมด
                sync_data = self.db.get_all_sync_data()
                self.sync_manager.save_local_excel_mirror(sync_data)
                self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id)
                logger.info("[DELETE_REQ] Final cloud and excel indexes updated successfully.")

                # 3. อัปเดตไฟล์ลบประวัติ delete_request.json ทั้งบนคลาวด์และเครื่องท้องถิ่น
                import json
                delete_req_file_id = self.entry_delete_req_file_id.get().strip()
                
                # 3.1 อ่านข้อมูลตั้งต้นขึ้นมาก่อน (ไม่ว่าจะมาจากเครื่องหรือไดรฟ์)
                loaded_requests = {}
                loaded_from_drive = False
                if delete_req_file_id:
                    try:
                        media_content = self.sync_manager.drive_service.files().get_media(fileId=delete_req_file_id).execute()
                        loaded_requests = json.loads(media_content.decode("utf-8"))
                        loaded_from_drive = True
                    except Exception as e:
                        logger.error(f"[DELETE_REQ] Failed to download JSON for update filtering: {e}")
                
                if not loaded_from_drive:
                    req_file = os.path.join(get_project_root(), "delete_request.json")
                    if os.path.exists(req_file):
                        try:
                            with open(req_file, "r", encoding="utf-8") as f:
                                loaded_requests = json.load(f)
                        except Exception:
                            pass

                # แปลง loaded_requests ให้เป็น flat list ก่อนทำการกรองเปรียบเทียบ
                flat_loaded = []
                conn = self.db.get_connection()
                cursor = conn.cursor()
                if isinstance(loaded_requests, dict):
                    for staff_name, file_ids in loaded_requests.items():
                        cursor.execute("SELECT id FROM staff_members WHERE name = ? LIMIT 1", (staff_name,))
                        staff_row = cursor.fetchone()
                        staff_id = staff_row[0] if staff_row else "unknown"
                        for f_id in file_ids:
                            flat_loaded.append({
                                "drive_file_id": f_id,
                                "staff_id": staff_id,
                                "staff_name": staff_name
                            })
                elif isinstance(loaded_requests, list):
                    for item in loaded_requests:
                        if isinstance(item, str):
                            try:
                                item = json.loads(item)
                            except Exception:
                                continue
                        if isinstance(item, dict):
                            s_name = item.get("staff_name", "")
                            s_id = item.get("staff_id", "")
                            f_id = item.get("drive_file_id", "")
                            if not s_id and s_name:
                                cursor.execute("SELECT id FROM staff_members WHERE name = ? LIMIT 1", (s_name,))
                                row = cursor.fetchone()
                                s_id = row[0] if row else "unknown"
                            if s_id and not s_name:
                                cursor.execute("SELECT name FROM staff_members WHERE id = ? LIMIT 1", (s_id,))
                                row = cursor.fetchone()
                                s_name = row[0] if row else "ไม่ระบุชื่อ"
                            flat_loaded.append({
                                "drive_file_id": f_id,
                                "staff_id": s_id,
                                "staff_name": s_name
                            })
                conn.close()

                # 3.2 กรองเอาคำขอที่ถูกอนุมัติออกไป
                flat_remaining = []
                for req in flat_loaded:
                    match_found = False
                    for s_req in selected_requests:
                        # เปรียบเทียบรหัสไฟล์ และ (รหัสครู หรือ ชื่อครู)
                        # เปรียบเทียบไฟล์ (รองรับทั้ง ID ยาว และชื่อไฟล์/ID สั้น) และ (รหัสครู หรือ ชื่อครู)
                        if (
                            req.get("drive_file_id") == s_req.get("drive_file_id") or 
                            req.get("drive_file_id") == s_req.get("file_name")
                        ) and (
                            req.get("staff_id") == s_req.get("staff_id") or 
                            req.get("staff_name") == s_req.get("staff_name")
                        ):
                            match_found = True
                            break
                    if not match_found:
                        flat_remaining.append(req)

                # 3.3 ทำ Reverse Parser แปลง Flat List ที่เหลือคืนกลับเป็น Dictionary {"ชื่อคุณครู": [list_ของ_file_id]}
                final_dict = {}
                conn = self.db.get_connection()
                cursor = conn.cursor()
                for req in flat_remaining:
                    s_name = req.get("staff_name")
                    if not s_name and req.get("staff_id"):
                        cursor.execute("SELECT name FROM staff_members WHERE id = ? LIMIT 1", (req.get("staff_id"),))
                        row = cursor.fetchone()
                        s_name = row[0] if row else "unknown"
                    if not s_name:
                        s_name = "ไม่ระบุชื่อ"
                    
                    f_id = req.get("drive_file_id")
                    if f_id:
                        if s_name not in final_dict:
                            final_dict[s_name] = []
                        if f_id not in final_dict[s_name]:
                            final_dict[s_name].append(f_id)
                conn.close()
                
                # 3.4 บันทึกกลับขึ้น Google Drive (ถ้าโหลดมาจากไดรฟ์)
                if delete_req_file_id and loaded_from_drive:
                    try:
                        from googleapiclient.http import MediaIoBaseUpload
                        import io
                        updated_json_str = json.dumps(final_dict, ensure_ascii=False, indent=2)
                        fh = io.BytesIO(updated_json_str.encode("utf-8"))
                        media = MediaIoBaseUpload(fh, mimetype='application/json', resumable=True)
                        self.sync_manager.drive_service.files().update(fileId=delete_req_file_id, media_body=media).execute()
                        logger.info(f"[DELETE_REQ] Successfully updated delete_request.json on Google Drive (ID: {delete_req_file_id})")
                    except Exception as cloud_err:
                        logger.error(f"[DELETE_REQ] Error uploading updated JSON to Google Drive: {cloud_err}")
                
                # 3.5 บันทึกสำรองลงเครื่องโลคอล
                req_file = os.path.join(get_project_root(), "delete_request.json")
                try:
                    with open(req_file, "w", encoding="utf-8") as f:
                        json.dump(final_dict, f, ensure_ascii=False, indent=2)
                    logger.info("[DELETE_REQ] Saved updated delete requests (dictionary format) to local mirror.")
                except Exception as file_err:
                    logger.error(f"Error updating local delete_request.json file: {file_err}")

                # 4. เสร็จสิ้น -> โหลดตารางและแสดง Pop-up
                self.after(0, lambda: messagebox.showinfo("ลบภาพเสร็จสิ้น", f"อนุมัติและลบข้อมูลคุณครูออกจากภาพที่ระบุจำนวน {len(selected_requests)} รายการ เรียบร้อยสมบูรณ์!"))
                self.after(0, self.load_delete_requests_table)
                self.after(0, self.refresh_dashboard_stats)

            except Exception as ex:
                logger.error(f"Error in approve_delete_requests thread: {ex}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการอนุมัติลบ: {ex}"))

        threading.Thread(target=process_delete, daemon=True).start()

    # ==================== (7) เมนูสถิติบุคคลนิรนาม (Unknown Faces VIP & Yearly Analytics v6.20) ====================
    def setup_unknown_analytics_ui(self):
        """จัดสร้างส่วนแสดงผลสถิติและจัดกลุ่มบุคคลนิรนาม (Unknown Faces Analytics) พร้อมกราฟแท่งเฉดสีรายปี"""
        self.frame_unknown_analytics.grid_columnconfigure(0, weight=1)
        self.frame_unknown_analytics.grid_rowconfigure(1, weight=1)

        # 1. แถบควบคุมเมนูด้านบน (Top Bar Header & Filters)
        top_bar = ctk.CTkFrame(self.frame_unknown_analytics, fg_color="#1A2636")
        top_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        lbl_header = ctk.CTkLabel(
            top_bar, text="👥 สถิติและจัดกลุ่มบุคคลนิรนาม",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="white"
        )
        lbl_header.pack(side="left", padx=(15, 15), pady=10)

        # Dropdown ปี
        ctk.CTkLabel(top_bar, text="ปี พ.ศ.:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(5, 3), pady=10)
        self.combo_unknown_year = ctk.CTkComboBox(
            top_bar, values=["🌐 ภาพรวมทั้งหมด (Overall)"], width=190, height=34,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            command=self.on_unknown_year_change
        )
        self.combo_unknown_year.set("🌐 ภาพรวมทั้งหมด (Overall)")
        self.combo_unknown_year.pack(side="left", padx=5, pady=10)

        # ช่องกรองความถี่ขั้นต่ำ (Min photos)
        ctk.CTkLabel(top_bar, text="รูปขั้นต่ำ:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(10, 3), pady=10)
        self.entry_unknown_min_photos = ctk.CTkEntry(top_bar, width=50, height=34, font=ctk.CTkFont(size=13))
        self.entry_unknown_min_photos.insert(0, "3")
        self.entry_unknown_min_photos.pack(side="left", padx=3, pady=10)
        self.entry_unknown_min_photos.bind("<Return>", lambda e: self.load_unknown_clusters_list())

        btn_filter = ctk.CTkButton(
            top_bar, text="🔍 กรอง", width=65, height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2980B9", hover_color="#1F618D",
            command=self.load_unknown_clusters_list
        )
        btn_filter.pack(side="left", padx=5, pady=10)

        # ปุ่มประมวลผลจัดกลุ่มสถิติใหม่
        self.btn_run_recluster = ctk.CTkButton(
            top_bar, text="🔄 ประมวลผลจัดกลุ่มสถิติใหม่", width=195, height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#8E44AD", hover_color="#732D91",
            command=self.run_recluster_thread
        )
        self.btn_run_recluster.pack(side="left", padx=10, pady=10)

        # สรุปผล
        self.lbl_unknown_summary = ctk.CTkLabel(
            top_bar, text="พบ 0 กลุ่ม",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#2ECC71"
        )
        self.lbl_unknown_summary.pack(side="right", padx=15, pady=10)

        # 2. พื้นที่เนื้อหาหลักแบ่ง 2 ฝั่ง (Split-Pane Main Container)
        main_pane = ctk.CTkFrame(self.frame_unknown_analytics, fg_color="transparent")
        main_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        main_pane.grid_columnconfigure(0, weight=4)  # ตารางซ้าย 40%
        main_pane.grid_columnconfigure(1, weight=6)  # รายละเอียดขวา 60%
        main_pane.grid_rowconfigure(0, weight=1)

        # ------------------- 2.1 ฝั่งซ้าย: ตารางจัดอันดับ (Left Pane) -------------------
        left_box = ctk.CTkFrame(main_pane, fg_color="#101B2B")
        left_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left_box.grid_columnconfigure(0, weight=1)
        left_box.grid_rowconfigure(2, weight=1)

        # ส่วนหัวฝั่งซ้าย
        lbl_left_title = ctk.CTkLabel(
            left_box, text="📋 ตารางจัดอันดับบุคคลนิรนาม",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD"
        )
        lbl_left_title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        # ช่องค้นหารหัสกลุ่ม (พร้อม Debounce 250ms v6.28)
        self.entry_unknown_search = ctk.CTkEntry(
            left_box, placeholder_text="🔍 ค้นหารหัสกลุ่ม (เช่น UNK_00001)...",
            height=32, font=ctk.CTkFont(size=12)
        )
        self.entry_unknown_search.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.entry_unknown_search.bind("<KeyRelease>", self.on_unknown_search_keyrelease)

        # คอนเทนเนอร์ตาราง Treeview
        table_frame = ctk.CTkFrame(left_box, fg_color="#1C2D42")
        table_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 4))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        from tkinter import ttk
        cols = ("rank", "cluster_id", "year_count", "total_count", "active_years")
        self.tree_unknown = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        
        self.tree_unknown.heading("rank", text="#")
        self.tree_unknown.heading("cluster_id", text="รหัสกลุ่ม")
        self.tree_unknown.heading("year_count", text="รูปปีนี้")
        self.tree_unknown.heading("total_count", text="รูปรวม")
        self.tree_unknown.heading("active_years", text="ช่วงปีที่พบ")

        self.tree_unknown.column("rank", width=36, anchor="center")
        self.tree_unknown.column("cluster_id", width=85, anchor="center")
        self.tree_unknown.column("year_count", width=65, anchor="center")
        self.tree_unknown.column("total_count", width=65, anchor="center")
        self.tree_unknown.column("active_years", width=120, anchor="w")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree_unknown.yview)
        self.tree_unknown.configure(yscrollcommand=tree_scroll.set)

        self.tree_unknown.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")

        self.tree_unknown.bind("<<TreeviewSelect>>", self.on_unknown_cluster_select)

        # แถบควบคุมการแบ่งหน้าตารางนิรนาม (Unknowns Pagination Bar - 250 แถว/หน้า v6.28)
        unk_page_bar = ctk.CTkFrame(left_box, fg_color="transparent")
        unk_page_bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(2, 8))
        unk_page_bar.grid_columnconfigure(1, weight=1)

        self.btn_unknown_prev_page = ctk.CTkButton(
            unk_page_bar, text="◀ ก่อนหน้า", width=78, height=26,
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#1F3A60", hover_color="#2980B9",
            state="disabled", command=self.prev_unknown_page
        )
        self.btn_unknown_prev_page.grid(row=0, column=0, sticky="w")

        self.lbl_unknown_page_info = ctk.CTkLabel(
            unk_page_bar, text="หน้า 1 / 1 (0 กลุ่ม)",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#A2B5CD"
        )
        self.lbl_unknown_page_info.grid(row=0, column=1, sticky="ew")

        self.btn_unknown_next_page = ctk.CTkButton(
            unk_page_bar, text="ถัดไป ▶", width=78, height=26,
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#1F3A60", hover_color="#2980B9",
            state="disabled", command=self.next_unknown_page
        )
        self.btn_unknown_next_page.grid(row=0, column=2, sticky="e")

        # ------------------- 2.2 ฝั่งขวา: รายละเอียด, กราฟแท่ง, แกลเลอรี (Right Pane) -------------------
        right_box = ctk.CTkFrame(main_pane, fg_color="transparent")
        right_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
        right_box.grid_columnconfigure(0, weight=1)
        right_box.grid_rowconfigure(0, weight=0) # Profile Card
        right_box.grid_rowconfigure(1, weight=0) # Gradient Bar Chart
        right_box.grid_rowconfigure(2, weight=1) # Photo Gallery

        # 2.2.1 Profile Card (ส่วนบน)
        profile_card = ctk.CTkFrame(right_box, fg_color="#101B2B")
        profile_card.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 6))
        profile_card.grid_columnconfigure(1, weight=1)

        # รูปหน้าตัวอย่าง (Representative Cropped Face)
        self.lbl_unknown_face_preview = ctk.CTkLabel(
            profile_card, text="[ รูปตัวแทน ]", width=95, height=95,
            fg_color="#18283D", corner_radius=6, font=ctk.CTkFont(size=11), text_color="#A2B5CD"
        )
        self.lbl_unknown_face_preview.grid(row=0, column=0, rowspan=4, padx=12, pady=10)

        # ข้อมูลและรหัสกลุ่ม
        self.lbl_unknown_info_id = ctk.CTkLabel(
            profile_card, text="รหัสกลุ่ม: -- กรุณาเลือกบุคคลในตาราง --",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#5CACEE", anchor="w"
        )
        self.lbl_unknown_info_id.grid(row=0, column=1, sticky="w", padx=5, pady=(8, 2))

        self.lbl_unknown_info_stats = ctk.CTkLabel(
            profile_card, text="จำนวนรูปถ่าย: - รูป | กิจกรรม: - กิจกรรม",
            font=ctk.CTkFont(size=12), text_color="#ECEFF1", anchor="w"
        )
        self.lbl_unknown_info_stats.grid(row=1, column=1, sticky="w", padx=5, pady=1)

        self.lbl_unknown_info_years = ctk.CTkLabel(
            profile_card, text="ช่วงปีที่ปรากฏตัว: -",
            font=ctk.CTkFont(size=12), text_color="#BDC3C7", anchor="w"
        )
        self.lbl_unknown_info_years.grid(row=2, column=1, sticky="w", padx=5, pady=1)

        # ปุ่มบันทึกรูปครอปใบหน้าลงเครื่อง (Save Cropped Face)
        btn_action_box = ctk.CTkFrame(profile_card, fg_color="transparent")
        btn_action_box.grid(row=3, column=1, sticky="w", padx=5, pady=(4, 8))

        self.btn_export_cropped_face = ctk.CTkButton(
            btn_action_box, text="💾 บันทึกรูปครอปใบหน้าลงเครื่อง (Save Cropped Face)",
            height=30, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2ECC71", hover_color="#27AE60", text_color="#0A111A",
            state="disabled", command=self.export_cropped_unknown_face
        )
        self.btn_export_cropped_face.pack(side="left")

        # 2.2.2 กราฟแท่งเปรียบเทียบสถิติรายปีพร้อมไล่เฉดสี (Gradient Bar Chart Widget)
        chart_box = ctk.CTkFrame(right_box, fg_color="#101B2B")
        chart_box.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 6))
        chart_box.grid_columnconfigure(0, weight=1)

        lbl_chart_title = ctk.CTkLabel(
            chart_box,
            text="📈 สถิติจำนวนรูปภาพรายปี (เรียงปัจจุบัน ➔ อดีต | แดง=น้อย, ส้ม=กลาง, เขียว=มาก)",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#A2B5CD", anchor="w"
        )
        lbl_chart_title.pack(anchor="w", padx=12, pady=(8, 2))

        # Canvas Widget สำหรับกราฟแท่ง
        self.chart_unknown = GradientBarChart(chart_box, on_bar_click=self.on_unknown_bar_click, height=140)
        self.chart_unknown.pack(fill="x", padx=10, pady=(0, 8))

        # 2.2.3 แกลเลอรีรูปภาพกิจกรรม (Photo Gallery)
        gallery_box = ctk.CTkFrame(right_box, fg_color="#101B2B")
        gallery_box.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        gallery_box.grid_columnconfigure(0, weight=1)
        gallery_box.grid_rowconfigure(1, weight=1)

        gal_header = ctk.CTkFrame(gallery_box, fg_color="transparent")
        gal_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 4))
        gal_header.grid_columnconfigure(0, weight=1)

        self.lbl_unknown_gal_title = ctk.CTkLabel(
            gal_header, text="🖼️ ภาพกิจกรรมที่พบบุคคลนี้",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD", anchor="w"
        )
        self.lbl_unknown_gal_title.pack(side="left")

        self.btn_reset_gal_filter = ctk.CTkButton(
            gal_header, text="แสดงทุกปี", width=75, height=24,
            font=ctk.CTkFont(size=11), fg_color="#34495E", hover_color="#2C3E50",
            state="disabled", command=self.reset_unknown_gallery_filter
        )
        self.btn_reset_gal_filter.pack(side="right")

        self.scr_unknown_gallery = ctk.CTkScrollableFrame(gallery_box, fg_color="#09101A")
        self.scr_unknown_gallery.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.bind_scroll_events(self.scr_unknown_gallery)

    def update_unknown_year_dropdown(self):
        """อัปเดตตัวเลือกใน Dropdown ปีตามข้อมูลปี พ.ศ. ที่มีในฐานข้อมูล"""
        available_years = self.db.get_unknown_available_years()
        current_selection = self.combo_unknown_year.get()
        values = ["🌐 ภาพรวมทั้งหมด (Overall)"] + [f"📅 ปี {y}" for y in available_years]
        self.combo_unknown_year.configure(values=values)
        if current_selection in values:
            self.combo_unknown_year.set(current_selection)
        else:
            self.combo_unknown_year.set("🌐 ภาพรวมทั้งหมด (Overall)")

    def on_unknown_year_change(self, value=None):
        """เมื่อผู้ใช้สลับตัวกรองปี ให้รีเซ็ตตัวกรองแกลเลอรีและโหลดตารางใหม่"""
        self.unknown_gallery_filter_year = None
        self.btn_reset_gal_filter.configure(state="disabled")
        self.lbl_unknown_gal_title.configure(text="🖼️ ภาพกิจกรรมที่พบบุคคลนี้")
        self.load_unknown_clusters_list()

    def on_unknown_search_keyrelease(self, event=None):
        """หน่วงเวลา 250ms ก่อนกรองตารางกลุ่มนิรนาม เพื่อความลื่นไหลขณะพิมพ์ (v6.28)"""
        if getattr(self, "_unknown_search_timer", None) is not None:
            try:
                self.after_cancel(self._unknown_search_timer)
            except Exception:
                pass
            self._unknown_search_timer = None
        self._unknown_search_timer = self.after(250, lambda: self.filter_unknown_table(select_first=False))

    def prev_unknown_page(self):
        if getattr(self, "unknown_page", 1) > 1:
            self.unknown_page -= 1
            self._render_unknown_table_page(select_first=False)

    def next_unknown_page(self):
        total_items = len(getattr(self, "unknown_filtered_rows", []))
        page_size = getattr(self, "unknown_page_size", 250)
        max_page = max(1, (total_items + page_size - 1) // page_size)
        if getattr(self, "unknown_page", 1) < max_page:
            self.unknown_page += 1
            self._render_unknown_table_page(select_first=False)

    def _render_unknown_table_page(self, select_first=False):
        """วาดแถวใน Treeview เฉพาะหน้าปัจจุบัน (250 แถว/หน้า) และลบข้อมูลเก่าแบบ Batch Delete (v6.28)"""
        children = self.tree_unknown.get_children()
        if children:
            self.tree_unknown.delete(*children)

        filtered = getattr(self, "unknown_filtered_rows", [])
        page_size = getattr(self, "unknown_page_size", 250)
        total_items = len(filtered)
        max_page = max(1, (total_items + page_size - 1) // page_size)
        self.unknown_page = max(1, min(getattr(self, "unknown_page", 1), max_page))

        start_idx = (self.unknown_page - 1) * page_size
        end_idx = start_idx + page_size
        page_slice = filtered[start_idx:end_idx]

        for rank, cid, y_count, t_count, years in page_slice:
            self.tree_unknown.insert("", "end", iid=cid, values=(rank, cid, y_count, t_count, years))

        if hasattr(self, "lbl_unknown_page_info"):
            self.lbl_unknown_page_info.configure(text=f"หน้า {self.unknown_page:,} / {max_page:,} ({total_items:,} กลุ่ม)")
        if hasattr(self, "btn_unknown_prev_page"):
            self.btn_unknown_prev_page.configure(state="normal" if self.unknown_page > 1 else "disabled")
        if hasattr(self, "btn_unknown_next_page"):
            self.btn_unknown_next_page.configure(state="normal" if self.unknown_page < max_page else "disabled")

        if select_first:
            new_children = self.tree_unknown.get_children()
            if new_children:
                first_id = new_children[0]
                self.tree_unknown.selection_set(first_id)
                self.tree_unknown.focus(first_id)
                self.display_unknown_cluster_detail(first_id)
            else:
                self.clear_unknown_detail_view()

    def load_unknown_clusters_list(self):
        """โหลดข้อมูลจัดอันดับกลุ่มบุคคลนิรนามเข้าสู่ตาราง Treeview (พร้อมระบบแบ่งหน้า 250 แถว/หน้า v6.28)"""
        raw_year = self.combo_unknown_year.get()
        if "ภาพรวม" in raw_year or "Overall" in raw_year:
            selected_year = "all"
        else:
            match = re.search(r'(\d{4})', raw_year)
            selected_year = match.group(1) if match else "all"

        try:
            min_photos = int(self.entry_unknown_min_photos.get().strip())
        except (ValueError, AttributeError):
            min_photos = 1

        rows = self.db.get_unknown_clusters_summary(selected_year=selected_year, min_photos=min_photos)
        self.unknown_clusters_cache = rows
        self.lbl_unknown_summary.configure(text=f"พบ {len(rows):,} กลุ่ม")
        self.filter_unknown_table(select_first=True)

    def filter_unknown_table(self, event=None, select_first=False):
        """กรองตารางตามรหัสกลุ่มที่พิมพ์ในช่องค้นหา และแบ่งหน้าแสดงผล 250 รายการต่อหน้า (v6.28)"""
        query = self.entry_unknown_search.get().strip().upper() if hasattr(self, "entry_unknown_search") else ""
        raw_year = self.combo_unknown_year.get()
        is_all = ("ภาพรวม" in raw_year or "Overall" in raw_year)

        filtered = []
        rank = 1
        for row in getattr(self, "unknown_clusters_cache", []):
            cid = row[0]
            if query and query not in cid.upper():
                continue

            if is_all:
                y_count = row[1]
                t_count = row[1]
                years = row[8] or "-"
            else:
                y_count = row[1]
                t_count = row[2]
                years = row[9] or "-"

            filtered.append((rank, cid, y_count, t_count, years))
            rank += 1

        self.unknown_filtered_rows = filtered
        self.unknown_page = 1
        self._render_unknown_table_page(select_first=select_first)

    def on_unknown_cluster_select(self, event=None):
        """เมื่อคลิกเลือกแถวในตาราง Treeview ให้แสดงรายละเอียด กราฟแท่ง และแกลเลอรี"""
        selected = self.tree_unknown.selection()
        if not selected:
            return
        cid = selected[0]
        self.display_unknown_cluster_detail(cid)

    def display_unknown_cluster_detail(self, cluster_id):
        """ดึงและแสดงรายละเอียดของกลุ่มบุคคลนิรนามที่เลือก"""
        self.selected_unknown_cluster_id = cluster_id
        
        # ดึงข้อมูลคลัสเตอร์จากแคชหรือคิวรี
        cdata = None
        for r in self.unknown_clusters_cache:
            if r[0] == cluster_id:
                raw_year = self.combo_unknown_year.get()
                if "ภาพรวม" in raw_year or "Overall" in raw_year:
                    cdata = {
                        "cluster_id": r[0], "photo_count": r[1], "event_count": r[2],
                        "rep_photo_id": r[3], "rep_face_index": r[4], "rep_bbox": r[5],
                        "first_seen_year": r[6], "last_seen_year": r[7], "active_years": r[8]
                    }
                else:
                    cdata = {
                        "cluster_id": r[0], "year_photos": r[1], "photo_count": r[2],
                        "event_count": r[3], "rep_photo_id": r[4], "rep_face_index": r[5], "rep_bbox": r[6],
                        "first_seen_year": r[7], "last_seen_year": r[8], "active_years": r[9]
                    }
                break

        if not cdata:
            return

        self.selected_unknown_cluster_data = cdata

        # 1. อัปเดตข้อมูลบน Profile Card
        self.lbl_unknown_info_id.configure(text=f"รหัสกลุ่ม: {cluster_id}")
        self.lbl_unknown_info_stats.configure(
            text=f"จำนวนรูปถ่ายสะสม: {cdata.get('photo_count', 0):,} รูป | ปรากฏใน {cdata.get('event_count', 0):,} กิจกรรม"
        )
        first_y = cdata.get('first_seen_year', '-')
        last_y = cdata.get('last_seen_year', '-')
        self.lbl_unknown_info_years.configure(
            text=f"ช่วงปีที่ปรากฏตัว: พ.ศ. {first_y} – {last_y} ({cdata.get('active_years', '-')})"
        )
        self.btn_export_cropped_face.configure(state="normal")

        # 2. โหลดรูปพรีวิวใบหน้าตัวแทน (Cropped Face Preview)
        rep_pid = cdata.get("rep_photo_id", "")
        rep_bbox = cdata.get("rep_bbox", [])
        if isinstance(rep_bbox, str):
            try:
                import json
                rep_bbox = json.loads(rep_bbox)
            except Exception:
                rep_bbox = []
        self.load_rep_face_preview_async(rep_pid, rep_bbox)

        # 3. ดึงสถิติรายปีและวาดกราฟแท่งไล่เฉดสี
        yearly_stats = self.db.get_unknown_cluster_yearly_breakdown(cluster_id)
        self.chart_unknown.set_data(yearly_stats)

        # 4. โหลดแกลเลอรีรูปภาพกิจกรรม
        photos = self.db.get_unknown_cluster_member_photos(cluster_id, filter_year=self.unknown_gallery_filter_year)
        self.render_unknown_gallery(cluster_id, photos)

    def clear_unknown_detail_view(self):
        """ล้างหน้าจอรายละเอียดเมื่อไม่มีข้อมูลในตาราง"""
        self.selected_unknown_cluster_id = None
        self.selected_unknown_cluster_data = None
        self.lbl_unknown_info_id.configure(text="รหัสกลุ่ม: -")
        self.lbl_unknown_info_stats.configure(text="จำนวนรูปถ่าย: - รูป | กิจกรรม: - กิจกรรม")
        self.lbl_unknown_info_years.configure(text="ช่วงปีที่ปรากฏตัว: -")
        self.lbl_unknown_face_preview.configure(image=None, text="[ ไม่มีรูป ]")
        self.btn_export_cropped_face.configure(state="disabled")
        self.chart_unknown.set_data([])
        for widget in self.scr_unknown_gallery.winfo_children():
            widget.destroy()

    def load_rep_face_preview_async(self, photo_id, bbox):
        """โหลดและครอปรูปหน้าตัวแทนขึ้นพรีวิวบน GUI แบบ Asynchronous"""
        def _loader():
            cache_dir = os.path.join(get_project_root(), "data", "thumbnail_cache")
            img_path = os.path.join(cache_dir, f"{photo_id}.jpg")
            drive_fid = None
            if not os.path.exists(img_path) or os.path.getsize(img_path) == 0:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT drive_file_id FROM scanned_photos WHERE photo_id = ? LIMIT 1", (photo_id,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        drive_fid = row[0]
                        alt1 = os.path.join(cache_dir, f"thumb_{drive_fid}.jpg")
                        alt2 = os.path.join(cache_dir, f"{drive_fid}.jpg")
                        if os.path.exists(alt1) and os.path.getsize(alt1) > 0: img_path = alt1
                        elif os.path.exists(alt2) and os.path.getsize(alt2) > 0: img_path = alt2

            # ถ้ายังไม่มีไฟล์ในแคช ให้ลองดาวน์โหลดจาก Google Drive
            if (not os.path.exists(img_path) or os.path.getsize(img_path) == 0) and drive_fid:
                if hasattr(self, 'sync_manager') and self.sync_manager:
                    try:
                        img_bytes, _, _ = self.sync_manager.download_image_bytes_with_stats(drive_fid, f"rep_{drive_fid}")
                        if img_bytes:
                            target_p = os.path.join(cache_dir, f"{photo_id}.jpg")
                            with open(target_p, "wb") as f_out:
                                f_out.write(img_bytes)
                            img_path = target_p
                    except Exception as dl_err:
                        logger.debug(f"Rep face auto-download failed: {dl_err}")

            if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
                try:
                    img = read_image_file(img_path)
                    if img is not None and img.size > 0:
                        h, w = img.shape[:2]
                        if bbox and len(bbox) == 4 and (bbox[2] > bbox[0]) and (bbox[3] > bbox[1]):
                            x1, y1, x2, y2 = bbox
                            # ตรวจสอบสเกลกรณี img เป็น thumbnail ที่ถูกย่อขนาด แต่ bbox เป็นพิกัดภาพเดิม
                            if (x2 > w or y2 > h) and w > 0 and h > 0:
                                orig_max = max(x2 * 1.05, y2 * 1.05, max(w, h))
                                scale_f = max(w, h) / orig_max
                                x1, y1, x2, y2 = x1 * scale_f, y1 * scale_f, x2 * scale_f, y2 * scale_f

                            bw = x2 - x1
                            bh = y2 - y1
                            pad_x = int(bw * 0.25)
                            pad_y = int(bh * 0.25)
                            cx1 = max(0, min(w - 1, int(x1 - pad_x)))
                            cy1 = max(0, min(h - 1, int(y1 - pad_y)))
                            cx2 = max(cx1 + 1, min(w, int(x2 + pad_x)))
                            cy2 = max(cy1 + 1, min(h, int(y2 + pad_y)))
                            cropped = img[cy1:cy2, cx1:cx2]
                            if cropped is None or cropped.size == 0 or cropped.shape[0] == 0 or cropped.shape[1] == 0:
                                cropped = img
                        else:
                            cropped = img

                        from PIL import Image
                        import cv2
                        rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(rgb)
                        pil_img.thumbnail((95, 95), Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
                        self._unknown_face_preview_img = ctk_img
                        self.after(0, lambda: self.lbl_unknown_face_preview.configure(image=ctk_img, text=""))
                        return
                except Exception as e:
                    logger.warning(f"Error previewing rep face {photo_id}: {e}")

            self.after(0, lambda: self.lbl_unknown_face_preview.configure(image=None, text="[ ไม่มีรูป ]"))

        self.thumb_executor.submit(_loader)

    def on_unknown_bar_click(self, year):
        """เมื่อคลิกแท่งกราฟปี ให้กรองแสดงเฉพาะรูปภาพกิจกรรมของปีนั้นในแกลเลอรี"""
        self.unknown_gallery_filter_year = str(year)
        self.lbl_unknown_gal_title.configure(text=f"🖼️ ภาพกิจกรรมที่พบบุคคลนี้ (เฉพาะปี {year})")
        self.btn_reset_gal_filter.configure(state="normal")
        if self.selected_unknown_cluster_id:
            photos = self.db.get_unknown_cluster_member_photos(self.selected_unknown_cluster_id, filter_year=year)
            self.render_unknown_gallery(self.selected_unknown_cluster_id, photos)

    def reset_unknown_gallery_filter(self):
        """รีเซ็ตตัวกรองปีของแกลเลอรีกลับเป็นแสดงรูปทั้งหมด"""
        self.unknown_gallery_filter_year = None
        self.lbl_unknown_gal_title.configure(text="🖼️ ภาพกิจกรรมที่พบบุคคลนี้")
        self.btn_reset_gal_filter.configure(state="disabled")
        if self.selected_unknown_cluster_id:
            photos = self.db.get_unknown_cluster_member_photos(self.selected_unknown_cluster_id, filter_year=None)
            self.render_unknown_gallery(self.selected_unknown_cluster_id, photos)

    def render_unknown_gallery(self, cluster_id, photos):
        """วาดการ์ดแสดงรูปภาพกิจกรรมในแกลเลอรีแบบ Grid Responsive"""
        for widget in self.scr_unknown_gallery.winfo_children():
            widget.destroy()

        if not photos:
            lbl_empty = ctk.CTkLabel(
                self.scr_unknown_gallery,
                text="ไม่พบรูปภาพกิจกรรมตามเงื่อนไขที่เลือก",
                font=ctk.CTkFont(size=13), text_color="#A2B5CD"
            )
            lbl_empty.pack(pady=30)
            return

        cache_dir = os.path.join(get_project_root(), "data", "thumbnail_cache")
        cols = 3
        for c in range(cols):
            self.scr_unknown_gallery.grid_columnconfigure(c, weight=1)

        limit_photos = photos[:48]  # จำกัด 48 รูปแรกเพื่อความลื่นไหล
        for idx, item in enumerate(limit_photos):
            pid, f_idx, y, e_name, link, p_date, x1, y1, x2, y2 = item
            r = idx // cols
            c = idx % cols

            card = ctk.CTkFrame(self.scr_unknown_gallery, fg_color="#142132", corner_radius=6)
            card.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")

            # กล่องใส่รูป Thumbnail
            target_thumb = os.path.join(cache_dir, f"{pid}.jpg")
            lbl_thumb = ctk.CTkLabel(card, text="⌛ กำลังโหลด...", width=140, height=100, fg_color="#0A111A", corner_radius=4)
            lbl_thumb.pack(padx=6, pady=(6, 2))

            # ข้อมูลรหัสรูปและวันที่
            txt_date = p_date if p_date else f"ปี {y}"
            lbl_meta = ctk.CTkLabel(
                card, text=f"{pid} | {txt_date}",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="#6CA6CD"
            )
            lbl_meta.pack(padx=6, pady=0)

            short_event = e_name if len(e_name) <= 22 else e_name[:20] + "..."
            lbl_event = ctk.CTkLabel(
                card, text=short_event, font=ctk.CTkFont(size=10), text_color="#95A5A6"
            )
            lbl_event.pack(padx=6, pady=(0, 4))

            # ผูกคลิกคู่เปิดลิงก์ Google Drive
            def open_link(e, l=link, p=pid):
                if l and l.startswith("http"):
                    import webbrowser
                    webbrowser.open(l)
                else:
                    self.open_drive_photo_link(p)

            card.bind("<Double-1>", open_link)
            lbl_thumb.bind("<Double-1>", open_link)

            # โหลดรูปภาพ Thumbnail เข้าสู่การ์ดแบบ Background Worker
            def load_card_thumb(p_path, label):
                if os.path.exists(p_path):
                    try:
                        from PIL import Image
                        im = Image.open(p_path)
                        im.thumbnail((140, 100), Image.Resampling.LANCZOS)
                        ctk_im = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                        self.after(0, lambda: label.configure(image=ctk_im, text=""))
                        return
                    except Exception:
                        pass
                self.after(0, lambda: label.configure(text="🖼️ ไม่มีรูปย่อ"))

            self.thumb_executor.submit(load_card_thumb, target_thumb, lbl_thumb)

    def export_cropped_unknown_face(self):
        """ครอปภาพใบหน้าของบุคคลนิรนามที่เลือก พร้อมขอบ Padding Margin แล้วเปิด Dialog บันทึกไฟล์ภาพลงเครื่อง"""
        if not self.selected_unknown_cluster_id or not self.selected_unknown_cluster_data:
            messagebox.showwarning("คำเตือน", "กรุณาเลือกบุคคลนิรนามจากตารางก่อนทำการบันทึก")
            return

        cid = self.selected_unknown_cluster_id
        cdata = self.selected_unknown_cluster_data
        pid = cdata.get("rep_photo_id", "")
        bbox = cdata.get("rep_bbox", [])
        if isinstance(bbox, str):
            try:
                import json
                bbox = json.loads(bbox)
            except Exception:
                bbox = []

        cache_dir = os.path.join(get_project_root(), "data", "thumbnail_cache")
        img_path = os.path.join(cache_dir, f"{pid}.jpg")

        # ตรวจสอบหาไฟล์ในแคชหรือ drive_file_id
        if not os.path.exists(img_path):
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT drive_file_id FROM scanned_photos WHERE photo_id = ? LIMIT 1", (pid,))
                row = cursor.fetchone()
                if row and row[0]:
                    fid = row[0]
                    alt1 = os.path.join(cache_dir, f"thumb_{fid}.jpg")
                    alt2 = os.path.join(cache_dir, f"{fid}.jpg")
                    if os.path.exists(alt1): img_path = alt1
                    elif os.path.exists(alt2): img_path = alt2

        if not os.path.exists(img_path):
            messagebox.showerror("ไม่พบไฟล์รูปภาพ", f"ไม่พบไฟล์รูปถ่าย {pid} ในแคชเครื่อง")
            return

        try:
            img = read_image_file(img_path)
            if img is None:
                messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถถอดรหัสรูปภาพ {img_path} ได้")
                return

            h, w = img.shape[:2]
            if bbox and len(bbox) == 4 and (bbox[2] > bbox[0]) and (bbox[3] > bbox[1]):
                x1, y1, x2, y2 = bbox
                if (x2 > w or y2 > h) and w > 0 and h > 0:
                    orig_max = max(x2 * 1.05, y2 * 1.05, max(w, h))
                    scale_f = max(w, h) / orig_max
                    x1, y1, x2, y2 = x1 * scale_f, y1 * scale_f, x2 * scale_f, y2 * scale_f

                bw = x2 - x1
                bh = y2 - y1
                pad_x = int(bw * 0.25)
                pad_y = int(bh * 0.25)
                cx1 = max(0, min(w - 1, int(x1 - pad_x)))
                cy1 = max(0, min(h - 1, int(y1 - pad_y)))
                cx2 = max(cx1 + 1, min(w, int(x2 + pad_x)))
                cy2 = max(cy1 + 1, min(h, int(y2 + pad_y)))
                cropped = img[cy1:cy2, cx1:cx2]
                if cropped is None or cropped.size == 0 or cropped.shape[0] == 0 or cropped.shape[1] == 0:
                    cropped = img
            else:
                cropped = img

            from tkinter import filedialog
            initial_filename = f"{cid}_{pid}_face.jpg"
            save_path = filedialog.asksaveasfilename(
                parent=self,
                title="บันทึกรูปภาพใบหน้าลงเครื่อง (Save Cropped Face)",
                defaultextension=".jpg",
                initialfile=initial_filename,
                filetypes=[("JPEG Image", "*.jpg"), ("PNG Image", "*.png"), ("All Files", "*.*")]
            )
            if not save_path:
                return

            import cv2
            if cropped is None or cropped.size == 0:
                cropped = img
            success, encoded_img = cv2.imencode('.jpg', cropped)
            if success:
                encoded_img.tofile(save_path)
                logger.info(f"[UNKNOWN ANALYTICS] บันทึกรูปภาพครอปใบหน้า {cid} ไปยัง {save_path} เรียบร้อยแล้ว")
                messagebox.showinfo("บันทึกสำเร็จ", f"บันทึกรูปภาพครอปใบหน้าของ {cid} เรียบร้อยแล้ว:\n{save_path}")
            else:
                messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถแปลงข้อมูลรูปภาพเพื่อบันทึกไฟล์ได้")

        except Exception as ex:
            logger.error(f"[UNKNOWN ANALYTICS] ข้อผิดพลาดในการครอปรูปภาพ: {ex}", exc_info=True)
            messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการครอปรูปภาพ: {ex}")

    def run_recluster_thread(self):
        """ประมวลผลจัดกลุ่มสถิติบุคคลนิรนามบน Background Thread (ไม่บล็อก UI)"""
        self.btn_run_recluster.configure(state="disabled", text="⏳ กำลังประมวลผล...")
        self.lbl_unknown_summary.configure(text="⌛ กำลังวิเคราะห์ใบหน้านิรนาม...", text_color="#F39C12")

        def worker():
            try:
                logger.info("[UNKNOWN ANALYTICS] 🔄 กำลังดึงเวกเตอร์ใบหน้านิรนามจากฐานข้อมูล...")
                face_items = self.db.get_unmatched_face_embeddings()
                if not face_items:
                    logger.info("[UNKNOWN ANALYTICS] ไม่พบใบหน้านิรนามในฐานข้อมูล (อาจแมตช์ครบหมดแล้ว หรือยังไม่ได้สแกนรูปกิจกรรม)")
                    self.after(0, lambda: messagebox.showinfo("แจ้งเตือน", "ไม่พบใบหน้านิรนามที่ต้องจัดกลุ่ม\n(อาจจับคู่ครบหมดแล้ว หรือยังไม่มีข้อมูลการสแกนรูปภาพกิจกรรม)"))
                    return

                logger.info(f"[UNKNOWN ANALYTICS] ดึงข้อมูลสำเร็จ {len(face_items):,} ใบหน้า กำลังทำการ Clustering...")
                
                def on_progress(current, total, num_clusters, speed, eta_sec):
                    pct = (current / total) * 100.0 if total > 0 else 0
                    self.after(0, lambda: self.lbl_unknown_summary.configure(
                        text=f"⌛ จัดกลุ่ม {current:,}/{total:,} ({pct:.1f}%) | พบ {num_clusters:,} กลุ่ม | {speed:,.0f} หน้า/วิ | ETA: {eta_sec:.0f}s"
                    ))

                clusters_data, members_data, year_stats_data = unknown_analyzer.cluster_unknown_faces(
                    face_items, sim_threshold=0.68, min_cluster_size=1, min_face_size=35, progress_callback=on_progress
                )

                logger.info("[UNKNOWN ANALYTICS] บันทึกผลลัพธ์ลงตารางฐานข้อมูล SQLite...")
                self.db.save_unknown_clusters_batch(clusters_data, members_data, year_stats_data)
                logger.info(f"[UNKNOWN ANALYTICS] ✅ จัดกลุ่มเสร็จสมบูรณ์: {len(clusters_data):,} กลุ่ม")

                def on_done():
                    self.update_unknown_year_dropdown()
                    self.load_unknown_clusters_list()
                    messagebox.showinfo("ประมวลผลสำเร็จ", f"จัดกลุ่มและวิเคราะห์สถิติบุคคลนิรนามเสร็จสิ้น!\nพบทั้งหมด {len(clusters_data):,} กลุ่มบุคคล")

                self.after(0, on_done)
            except Exception as e:
                logger.error(f"[UNKNOWN ANALYTICS] เกิดข้อผิดพลาดขณะจัดกลุ่ม: {e}", exc_info=True)
                self.after(0, lambda err=e: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการประมวลผล: {err}"))
            finally:
                self.after(0, lambda: self.btn_run_recluster.configure(state="normal", text="🔄 ประมวลผลจัดกลุ่มสถิติใหม่"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    # บังคับระบบควบคุม Windows Scaling เพื่อความคมชัดของวิดเจ็ต
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    app = FaceSearchApp()
    app.mainloop()
