import os
import sys
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

# นำเข้าโมดูลหลังบ้านที่เราพัฒนาไว้
from db_manager import DatabaseManager
from face_analyzer import FaceAnalyzer, get_antelopev2_dir, get_project_root
from gdrive_sync import GoogleSyncManager
from scheduler_task import SchedulerTask

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
        
        for idx, item in enumerate(self.filtered_items):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                prefix = "📂 [Folder] "
                is_matched = item["id"] in matched_folders
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
        self.last_col_front = parent.settings.get("last_import_col_front", "C")

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

        # คอลัมน์รูปหน้าตรง
        col3_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        col3_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(col3_frame, text="คอลัมน์รูปหน้าตรง:", width=130, anchor="w",
                   text_color="#A2B5CD").pack(side="left")
        self.col_front = ctk.CTkOptionMenu(col3_frame, values=["A", "B", "C", "D", "E", "F", "G", "H"])
        self.col_front.set(self.last_col_front)
        self.col_front.pack(side="left", padx=(5, 0))
        ctk.CTkLabel(col3_frame, text="(บังคับ - ระบบจะหารูปเพิ่มเติมอัตโนมัติ)", text_color="#27AE60",
                   font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 0))

        # คำอธิบาย
        desc_label = ctk.CTkLabel(main_frame,
                                  text="• 1 คน = 1 แถว (รหัส + ชื่อ)\n"
                                      "• รูปหน้าตรง: บังคับต้องมี (เป็นรูปหลัก)\n"
                                      "• รูปเพิ่มเติม: ระบบจะหาอัตโนมัติจากคอลัมน์ถัดไป\n"
                                      "  (หยุดเมื่อเจอคอลัมน์ว่าง)",
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
            "col_front": self.col_front.get()
        }

        # บันทึกค่าล่าสุด
        self.parent.settings["last_import_sheet_id"] = self.selected_sheet_id
        self.parent.settings["last_import_sheet_name"] = self.selected_sheet_name
        self.parent.settings["last_import_col_id"] = self.col_id.get()
        self.parent.settings["last_import_col_name"] = self.col_name.get()
        self.parent.settings["last_import_col_front"] = self.col_front.get()
        self.parent.save_settings()

        self.destroy()
        if self.callback:
            self.callback(settings)

class FaceSearchApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- การตั้งค่าธีมและหน้าต่างโปรแกรม (Navy Blue Theme) ---
        ctk.set_appearance_mode("dark")
        # เราใช้ธีมสีน้ำเงินพื้นฐานของ CTk เป็นฐาน และตกแต่งด้วยสี Navy เฉพาะตัว
        ctk.set_default_color_theme("blue")
        
        self.title("ระบบค้นหาและวิเคราะห์ใบหน้าบุคลากร (แอดมิน) v1.8.4")
        self.geometry("1100x700")
        self.minsize(1000, 650)

        # --- ส่วนประกอบฐานข้อมูลและหลังบ้าน ---
        self.db = DatabaseManager()
        self.sync_manager = GoogleSyncManager()
        self.analyzer = None
        
        # คิวจัดการ Log เพื่อป้องกันหน้าจอค้าง
        self.log_queue = queue.Queue()
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
        self.selected_staff_ids_for_scan = []  # รายชื่อ ID ครูที่เลือกสำหรับสแกนแบบเจาะจง (Selective Matching)
        self.selected_teacher_ids = []  # v1.7.4 รายชื่อ ID ครูที่เลือกสแกนเฉพาะเจาะจง
        self.selected_student_ids = []  # v1.7.4 รายชื่อ ID นักเรียนที่เลือกสแกนเฉพาะเจาะจง
        self.dashboard_sort_desc = True  # True = เรียงมากไปน้อย, False = เรียงน้อยไปมาก

        # Settings cache
        self.settings = {}

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
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#101B2B")
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        # โลโก้หรือหัวข้อโปรแกรม
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="FACE MATCHING\nSYSTEM v1.8.4",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#6CA6CD"
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=25)

        # ปุ่มเมนูต่างๆ
        self.btn_dashboard = ctk.CTkButton(
            self.sidebar_frame, text="Dashboard",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("dashboard")
        )
        self.btn_dashboard.grid(row=1, column=0, padx=15, pady=8, sticky="ew")

        self.btn_registry = ctk.CTkButton(
            self.sidebar_frame, text="ลงทะเบียนครู",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("registry")
        )
        self.btn_registry.grid(row=2, column=0, padx=15, pady=8, sticky="ew")

        self.btn_student_registry = ctk.CTkButton(
            self.sidebar_frame, text="ลงทะเบียนนักเรียน",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("student_registry")
        )
        self.btn_student_registry.grid(row=3, column=0, padx=15, pady=8, sticky="ew")

        self.btn_scan = ctk.CTkButton(
            self.sidebar_frame, text="สแกนรูปภาพกิจกรรม",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("scan")
        )
        self.btn_scan.grid(row=4, column=0, padx=15, pady=8, sticky="ew")

        self.btn_database = ctk.CTkButton(
            self.sidebar_frame, text="ดูฐานข้อมูล SQLite",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("database")
        )
        self.btn_database.grid(row=5, column=0, padx=15, pady=8, sticky="ew")

        self.btn_settings = ctk.CTkButton(
            self.sidebar_frame, text="ตั้งค่าระบบ",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("settings")
        )
        self.btn_settings.grid(row=6, column=0, padx=15, pady=8, sticky="ew")

        self.btn_delete_req = ctk.CTkButton(
            self.sidebar_frame, text="คำขอลบภาพ (Requests)",
            fg_color="transparent", text_color="#A2B5CD", hover_color="#20334F",
            anchor="w", command=lambda: self.select_menu("delete_req")
        )
        self.btn_delete_req.grid(row=7, column=0, padx=15, pady=8, sticky="ew")
        self.btn_start_schedule = ctk.CTkButton(
            self.sidebar_frame, text="▶️ Start Schedule Now",
            fg_color="#8E44AD", text_color="white", hover_color="#9B59B6",
            anchor="w", command=lambda: self.scheduler.run_scheduled_tasks_manual()
        )
        self.btn_start_schedule.grid(row=8, column=0, padx=15, pady=(15, 5), sticky="ew")

        self.btn_start_task2 = ctk.CTkButton(
            self.sidebar_frame, text="▶️ Start Task 2 (Sync Students)",
            fg_color="#D35400", text_color="white", hover_color="#E67E22",
            anchor="w", command=lambda: self.scheduler.run_task_2_manual()
        )
        self.btn_start_task2.grid(row=9, column=0, padx=15, pady=5, sticky="ew")

        self.btn_stop_schedule = ctk.CTkButton(
            self.sidebar_frame, text="🛑 Stop Schedule Task",
            fg_color="#E74C3C", text_color="white", hover_color="#C0392B",
            anchor="w", command=lambda: self.scheduler.request_stop()
        )
        self.btn_stop_schedule.grid(row=10, column=0, padx=15, pady=(5, 15), sticky="ew")

        # เครดิตด้านล่าง
        self.credit_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Admin Console\n© 2026 School Face Finder",
            font=ctk.CTkFont(size=10),
            text_color="#4F6580"
        )
        self.credit_label.grid(row=11, column=0, pady=20, sticky="s")
        self.sidebar_frame.grid_rowconfigure(11, weight=1)

    def select_menu(self, menu_name):
        # รีเซ็ตสีปุ่มทั้งหมด
        self.btn_dashboard.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_registry.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_student_registry.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_scan.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_database.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_settings.configure(fg_color="transparent", text_color="#A2B5CD")
        self.btn_delete_req.configure(fg_color="transparent", text_color="#A2B5CD")

        # ซ่อนเฟรมเนื้อหาทั้งหมด
        self.frame_dashboard.grid_forget()
        self.frame_registry.grid_forget()
        self.frame_student_registry.grid_forget()
        self.frame_scan.grid_forget()
        self.frame_database.grid_forget()
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
        elif menu_name == "settings":
            self.btn_settings.configure(fg_color="#1F3A60", text_color="white")
            self.frame_settings.grid(row=0, column=1, padx=25, pady=(25, 10), sticky="nsew")
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

        # 6. เฟรมหน้าตั้งค่าระบบ
        self.frame_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.setup_settings_ui()

        # 7. เฟรมหน้าคำขอลบภาพ (Delete Requests)
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
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))

        # การ์ดแสดงสถิติต่างๆ
        self.stats_container = ctk.CTkFrame(self.frame_dashboard, fg_color="transparent")
        self.stats_container.grid(row=1, column=0, columnspan=3, sticky="new", pady=(0, 20))
        self.stats_container.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # การ์ด 1: จำนวนครู
        self.card_teachers = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=130)
        self.card_teachers.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.card_teachers.grid_propagate(False)
        self.lbl_stat_teachers = ctk.CTkLabel(self.card_teachers, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_teachers.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_teachers, text="ครูที่ลงทะเบียน (คน)", font=ctk.CTkFont(size=13), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 2: จำนวนนักเรียน
        self.card_students = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=130)
        self.card_students.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.card_students.grid_propagate(False)
        self.lbl_stat_students = ctk.CTkLabel(self.card_students, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_students.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_students, text="นักเรียนที่ลงทะเบียน (คน)", font=ctk.CTkFont(size=13), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 3: จำนวนภาพกิจกรรมที่สแกนแล้ว
        self.card_photos = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=130)
        self.card_photos.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        self.card_photos.grid_propagate(False)
        self.lbl_stat_photos = ctk.CTkLabel(self.card_photos, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_photos.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_photos, text="ภาพกิจกรรมที่สแกน (รูป)", font=ctk.CTkFont(size=13), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # การ์ด 4: จำนวนใบหน้าที่ตรวจพบ
        self.card_matches = ctk.CTkFrame(self.stats_container, fg_color="#1C2D42", height=130)
        self.card_matches.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")
        self.card_matches.grid_propagate(False)
        self.lbl_stat_matches = ctk.CTkLabel(self.card_matches, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#5CACEE")
        self.lbl_stat_matches.pack(expand=True, pady=(15, 0))
        ctk.CTkLabel(self.card_matches, text="การตรวจพบ (ครั้ง)", font=ctk.CTkFont(size=13), text_color="#A2B5CD").pack(expand=True, pady=(0, 15))

        # 2.1 กล่องตรวจสอบโมเดลและไลบรารี (ฝั่งซ้ายของแถว 2)
        self.status_box = ctk.CTkFrame(self.frame_dashboard, fg_color="#101B2B")
        self.status_box.grid(row=2, column=0, padx=(0, 10), pady=10, sticky="nsew")
        
        lbl_status_title = ctk.CTkLabel(self.status_box, text="สถานะไลบรารีและโมเดล AI", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD")
        lbl_status_title.pack(anchor="w", padx=20, pady=(15, 5))

        self.lbl_model_status = ctk.CTkLabel(self.status_box, text="กำลังตรวจสอบโมเดล...", text_color="#A2B5CD", font=ctk.CTkFont(size=12))
        self.lbl_model_status.pack(anchor="w", padx=20, pady=5)
        
        self.lbl_db_status = ctk.CTkLabel(self.status_box, text="ตรวจสอบฐานข้อมูล: เชื่อมต่อแล้ว (SQLite)", text_color="#A2B5CD", font=ctk.CTkFont(size=12))
        self.lbl_db_status.pack(anchor="w", padx=20, pady=(5, 10))

        # ส่วนซิงค์ข้อมูล Google Sheets แบบ Manual
        lbl_sync_title = ctk.CTkLabel(self.status_box, text="การซิงค์ข้อมูลคลาวด์", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD")
        lbl_sync_title.pack(anchor="w", padx=20, pady=(10, 5))
        
        self.btn_manual_sync = ctk.CTkButton(
            self.status_box, 
            text="📤 ซิงค์ข้อมูลขึ้น Google Sheets", 
            fg_color="#27AE60", hover_color="#229954", text_color="white",
            font=ctk.CTkFont(weight="bold"),
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
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#2ECC71"
        )
        self.lbl_teacher_title.pack(side="left", anchor="w")
        
        self.btn_teacher_sort = ctk.CTkButton(
            teacher_title_frame, 
            text="สลับ 🔼", 
            width=50, height=22,
            font=ctk.CTkFont(size=10, weight="bold"),
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
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#F39C12"
        )
        self.lbl_student_title.pack(side="left", anchor="w")
        
        self.btn_student_sort = ctk.CTkButton(
            student_title_frame, 
            text="สลับ 🔼", 
            width=50, height=22,
            font=ctk.CTkFont(size=10, weight="bold"),
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
            # ดึงข้อมูลจากฐานข้อมูล SQLite แยกครูและนักเรียน
            teachers = self.db.get_all_teachers()
            students = self.db.get_all_students()
            sync_data = self.db.get_all_sync_data()

            num_teachers = len(teachers)
            num_students = len(students)
            num_photos = len(sync_data["photos"])
            num_matches = len(sync_data["faces"])

            self.lbl_stat_teachers.configure(text=str(num_teachers))
            self.lbl_stat_students.configure(text=str(num_students))
            self.lbl_stat_photos.configure(text=str(num_photos))
            self.lbl_stat_matches.configure(text=str(num_matches))
            
            # ตรวจโมเดล
            model_dir = get_antelopev2_dir()
            required_files = ["scrfd_10g_bnkps.onnx", "glintr100.onnx"]
            model_exists = all(os.path.exists(os.path.join(model_dir, f)) for f in required_files)
            
            if model_exists:
                self.lbl_model_status.configure(text="โมเดล InsightFace (antelopev2): พร้อมในเครื่อง", text_color="#2ECC71")
            else:
                self.lbl_model_status.configure(text="โมเดล InsightFace: ยังไม่มีไฟล์ในเครื่อง", text_color="#E67E22")
                
            # ดึงและแสดงตารางสถิติจำนวนภาพแยกรายบุคคล
            for widget in self.scr_teacher_faces.winfo_children():
                widget.destroy()
            for widget in self.scr_student_faces.winfo_children():
                widget.destroy()
                
            sort_dir = "DESC" if self.dashboard_sort_desc else "ASC"
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # 1. โหลดข้อมูลคุณครู
            cursor.execute(f"""
                SELECT sm.name, COUNT(df.photo_id) as photo_count
                FROM staff_members sm
                LEFT JOIN detected_faces df ON sm.id = df.staff_id
                WHERE sm.role = 'teacher' OR sm.role IS NULL OR sm.role = ''
                GROUP BY sm.id, sm.name
                ORDER BY photo_count {sort_dir}, sm.name ASC
            """)
            teacher_rows = cursor.fetchall()
            
            # 2. โหลดข้อมูลนักเรียน
            cursor.execute(f"""
                SELECT sm.name, COUNT(df.photo_id) as photo_count
                FROM staff_members sm
                LEFT JOIN detected_faces df ON sm.id = df.staff_id
                WHERE sm.role = 'student'
                GROUP BY sm.id, sm.name
                ORDER BY photo_count {sort_dir}, sm.name ASC
            """)
            student_rows = cursor.fetchall()
            conn.close()
            
            # ฟังก์ชันวาดแถวข้อมูลสถิติ
            def draw_rows(rows, scroll_frame):
                all_counts = [r[1] for r in rows]
                max_count = max(all_counts) if all_counts else 0
                if max_count == 0:
                    max_count = 1
                
                for idx, r in enumerate(rows):
                    name = r[0]
                    count = r[1]
                    ratio = count / max_count
                    
                    # ไล่เฉดสีจากเขียวเข้ม (#27AE60) ไปหาแดงเข้ม (#C0392B)
                    r_val = int(192 + (39 - 192) * ratio)
                    g_val = int(57 + (174 - 57) * ratio)
                    b_val = int(43 + (96 - 43) * ratio)
                    color_hex = f"#{r_val:02x}{g_val:02x}{b_val:02x}"
                    
                    row_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
                    row_frame.pack(fill="x", pady=2)
                    
                    rank_str = f"{idx+1}."
                    lbl_rank = ctk.CTkLabel(row_frame, text=rank_str, width=20, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=color_hex)
                    lbl_rank.pack(side="left")
                    
                    lbl_name = ctk.CTkLabel(row_frame, text=name, anchor="w", text_color=color_hex, font=ctk.CTkFont(size=11, weight="bold" if ratio > 0.5 else "normal"))
                    lbl_name.pack(side="left", fill="x", expand=True)
                    
                    lbl_count = ctk.CTkLabel(row_frame, text=f"{count} รูป", width=45, anchor="e", text_color=color_hex, font=ctk.CTkFont(size=11))
                    lbl_count.pack(side="right")
                    
                    def _on_mousewheel(event, sf=scroll_frame):
                        try:
                            sf._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                        except Exception:
                            pass
                    
                    row_frame.bind("<MouseWheel>", _on_mousewheel)
                    lbl_rank.bind("<MouseWheel>", _on_mousewheel)
                    lbl_name.bind("<MouseWheel>", _on_mousewheel)
                    lbl_count.bind("<MouseWheel>", _on_mousewheel)
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
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        # ซีกซ้าย: รายชื่อครูที่ลงทะเบียนไว้
        self.list_frame = ctk.CTkFrame(self.frame_registry, fg_color="#101B2B")
        self.list_frame.grid(row=1, column=0, padx=(0, 10), sticky="nsew")
        self.list_frame.grid_rowconfigure(2, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.list_frame, text="รายชื่อคุณครูที่บันทึกแล้ว", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, padx=15, pady=10, sticky="w")
        
        # ช่องค้นหาคุณครู
        search_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        search_frame.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_staff_search = ctk.CTkEntry(search_frame, placeholder_text="🔍 ค้นหาชื่อคุณครู...")
        self.entry_staff_search.grid(row=0, column=0, sticky="ew")
        self.entry_staff_search.bind("<KeyRelease>", lambda event: self.filter_staff_list())
        
        btn_clear_staff_search = ctk.CTkButton(search_frame, text="✕", width=28, height=28, fg_color="transparent", hover_color="#20334F", text_color="#A2B5CD", command=self.clear_staff_search)
        btn_clear_staff_search.grid(row=0, column=1, padx=(5, 0))
        
        # Listbox แสดงรายชื่อ (ใช้ CTkTextbox จำลองการเป็น List หรือสร้าง Scrollable Frame)
        self.staff_list_scrollable = ctk.CTkScrollableFrame(self.list_frame, fg_color="transparent")
        self.staff_list_scrollable.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
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
        ctk.CTkLabel(self.form_frame, text="1. เพิ่มรายชื่อครูใหม่", font=ctk.CTkFont(size=14, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))
        
        add_input_frame = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        add_input_frame.pack(fill="x", padx=20, pady=5)
        
        self.entry_staff_name = ctk.CTkEntry(add_input_frame, placeholder_text="กรอกชื่อคุณครู (เช่น ครูสมชาย ใจดี)")
        self.entry_staff_name.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        btn_add_staff = ctk.CTkButton(add_input_frame, text="เพิ่มชื่อ", width=80, command=self.add_staff_name)
        btn_add_staff.pack(side="right")

        # ปุ่มนำเข้ายกโฟลเดอร์อัตโนมัติ
        btn_batch_import = ctk.CTkButton(
            self.form_frame, text="📁 นำเข้าคุณครูยกโฟลเดอร์อัตโนมัติ (Batch Import)", 
            fg_color="#1F3A60", hover_color="#20334F", command=self.batch_import_teachers
        )
        btn_batch_import.pack(fill="x", padx=20, pady=(2, 10))

        # จัดการภาพใบหน้าคุณครูที่เลือก
        ctk.CTkLabel(self.form_frame, text="2. จัดการภาพใบหน้าต้นแบบ", font=ctk.CTkFont(size=14, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))
        
        self.lbl_selected_info = ctk.CTkLabel(self.form_frame, text="กรุณาเลือกคุณครูจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ", text_color="#A2B5CD")
        self.lbl_selected_info.pack(anchor="w", padx=20, pady=5)

        # ปุ่มอัปโหลดรูปต้นแบบเพิ่ม
        self.btn_upload_photo = ctk.CTkButton(
            self.form_frame, text="อัปโหลดรูปใบหน้าต้นแบบเพิ่ม (จากคอมพิวเตอร์)", 
            state="disabled", fg_color="#1F3A60", hover_color="#20334F", command=self.upload_staff_photos
        )
        self.btn_upload_photo.pack(fill="x", padx=20, pady=10)

        # แสดงจำนวนรูปที่ลงทะเบียน
        self.lbl_photo_count_detail = ctk.CTkLabel(self.form_frame, text="", text_color="white")
        self.lbl_photo_count_detail.pack(anchor="w", padx=20, pady=5)

        # พื้นที่แสดงรูปภาพใบหน้าครูต้นแบบ (เป็น Grid ใน Scrollable Frame แบบแนวนอน)
        # พื้นที่แสดงรูปภาพใบหน้าครูต้นแบบ (เป็นตาราง Grid ใน Scrollable Frame แนวตั้ง)
        self.thumbs_frame = ctk.CTkFrame(self.form_frame, fg_color="#101B2B", height=180)
        self.thumbs_frame.pack(fill="x", expand=False, padx=20, pady=(5, 10))
        self.thumbs_frame.pack_propagate(False)
        
        ctk.CTkLabel(self.thumbs_frame, text="ภาพใบหน้าที่เรียนรู้แล้ว (ตารางภาพ):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#6CA6CD").pack(anchor="w", padx=10, pady=(5, 0))
        
        self.thumbs_scrollable = ctk.CTkScrollableFrame(self.thumbs_frame, orientation="vertical", fg_color="transparent", height=140)
        self.thumbs_scrollable.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ปุ่มลบรูปที่เลือก
        self.btn_delete_photo = ctk.CTkButton(
            self.form_frame, text="❌ ลบรูปภาพที่เลือก", 
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_photo
        )
        self.btn_delete_photo.pack(fill="x", padx=20, pady=(5, 10))

        # ลบชื่อครูที่เลือก
        ctk.CTkLabel(self.form_frame, text="3. การดำเนินการอื่น ๆ", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E74C3C").pack(anchor="w", padx=20, pady=(15, 5))
        self.btn_delete_staff = ctk.CTkButton(
            self.form_frame, text="ลบรายชื่อคุณครู (ลบข้อมูลและภาพทั้งหมด)", 
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_staff
        )
        self.btn_delete_staff.pack(fill="x", padx=20, pady=10)

    # ==================== (3) หน้าลงทะเบียนนักเรียน (Student Registry) ====================
    def setup_student_registry_ui(self):
        self.frame_student_registry.grid_columnconfigure(0, weight=2)
        self.frame_student_registry.grid_columnconfigure(1, weight=3)
        self.frame_student_registry.grid_rowconfigure(1, weight=1)

        # หัวข้อหน้า
        lbl_title = ctk.CTkLabel(
            self.frame_student_registry, text="ลงทะเบียนใบหน้านักเรียน",
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        # ซีกซ้าย: รายชื่อนักเรียนที่ลงทะเบียนไว้
        self.student_list_frame = ctk.CTkFrame(self.frame_student_registry, fg_color="#101B2B")
        self.student_list_frame.grid(row=1, column=0, padx=(0, 10), sticky="nsew")
        self.student_list_frame.grid_rowconfigure(2, weight=1)
        self.student_list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.student_list_frame, text="รายชื่อนักเรียนที่บันทึกแล้ว", font=ctk.CTkFont(size=14, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, padx=15, pady=10, sticky="w")

        # ช่องค้นหานักเรียน
        student_search_frame = ctk.CTkFrame(self.student_list_frame, fg_color="transparent")
        student_search_frame.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")
        student_search_frame.grid_columnconfigure(0, weight=1)

        self.entry_student_search = ctk.CTkEntry(student_search_frame, placeholder_text="🔍 ค้นหารหัส หรือชื่อนักเรียน...")
        self.entry_student_search.grid(row=0, column=0, sticky="ew")
        self.entry_student_search.bind("<KeyRelease>", lambda event: self.filter_student_list())

        btn_clear_student_search = ctk.CTkButton(student_search_frame, text="✕", width=28, height=28, fg_color="transparent", hover_color="#20334F", text_color="#A2B5CD", command=self.clear_student_search)
        btn_clear_student_search.grid(row=0, column=1, padx=(5, 0))

        # Listbox แสดงรายชื่อ (ใช้ CTkTextbox จำลองการเป็น List หรือสร้าง Scrollable Frame)
        self.student_list_scrollable = ctk.CTkScrollableFrame(self.student_list_frame, fg_color="transparent")
        self.student_list_scrollable.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")

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
        ctk.CTkLabel(self.student_form_frame, text="1. เพิ่มรายชื่อนักเรียนใหม่", font=ctk.CTkFont(size=14, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))

        # ฟิลด์รหัสประจำตัว
        id_input_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        id_input_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(id_input_frame, text="รหัสประจำตัว:", text_color="#A2B5CD", width=100, anchor="w").pack(side="left")
        self.entry_student_id = ctk.CTkEntry(id_input_frame, placeholder_text="เช่น 66001")
        self.entry_student_id.pack(side="left", fill="x", expand=True, padx=(5, 10))

        # ฟิลด์ชื่อ-นามสกุล
        name_input_frame = ctk.CTkFrame(self.student_form_frame, fg_color="transparent")
        name_input_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(name_input_frame, text="ชื่อ-นามสกุล:", text_color="#A2B5CD", width=100, anchor="w").pack(side="left")
        self.entry_student_name = ctk.CTkEntry(name_input_frame, placeholder_text="กรอกชื่อนักเรียน (เช่น นายรักเรียน มัธยม1)")
        self.entry_student_name.pack(side="left", fill="x", expand=True, padx=(5, 10))

        btn_add_student = ctk.CTkButton(name_input_frame, text="เพิ่มชื่อ", width=80, command=self.add_student_name)
        btn_add_student.pack(side="right")

        # ปุ่มนำเข้าจาก Google Sheets
        btn_import_from_sheets = ctk.CTkButton(
            self.student_form_frame, text="📊 นำเข้านักเรียนจาก Google Sheets (Batch Import)",
            fg_color="#27AE60", hover_color="#229954", command=self.open_sheets_import_dialog
        )
        btn_import_from_sheets.pack(fill="x", padx=20, pady=(2, 5))

        # จัดการภาพใบหน้านักเรียนที่เลือก
        ctk.CTkLabel(self.student_form_frame, text="2. จัดการภาพใบหน้าต้นแบบ", font=ctk.CTkFont(size=14, weight="bold"), text_color="#5CACEE").pack(anchor="w", padx=20, pady=(20, 5))

        self.lbl_student_selected_info = ctk.CTkLabel(self.student_form_frame, text="กรุณาเลือกนักเรียนจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ", text_color="#A2B5CD")
        self.lbl_student_selected_info.pack(anchor="w", padx=20, pady=5)

        # ปุ่มอัปโหลดรูปต้นแบทเพิ่ม
        self.btn_upload_student_photo = ctk.CTkButton(
            self.student_form_frame, text="อัปโหลดรูปใบหน้าต้นแบบเพิ่ม (จากคอมพิวเตอร์)",
            state="disabled", fg_color="#1F3A60", hover_color="#20334F", command=self.upload_student_photos
        )
        self.btn_upload_student_photo.pack(fill="x", padx=20, pady=10)

        # แสดงจำนวนรูปที่ลงทะเบียน
        self.lbl_student_photo_count_detail = ctk.CTkLabel(self.student_form_frame, text="", text_color="white")
        self.lbl_student_photo_count_detail.pack(anchor="w", padx=20, pady=5)

        # ปุ่มลบรูปที่เลือก (ย้ายมาก่อน thumbs_frame เพื่อให้แสดงได้เสมอ)
        self.btn_delete_student_photo = ctk.CTkButton(
            self.student_form_frame, text="❌ ลบรูปภาพที่เลือก",
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_student_photo
        )
        self.btn_delete_student_photo.pack(fill="x", padx=20, pady=(5, 10))

        # พื้นที่แสดงรูปภาพใบหน้านักเรียนต้นแบบ (เป็นตาราง Grid ใน Scrollable Frame แนวตั้ง)
        self.student_thumbs_frame = ctk.CTkFrame(self.student_form_frame, fg_color="#101B2B", height=180)
        self.student_thumbs_frame.pack(fill="x", expand=False, padx=20, pady=(5, 10))
        self.student_thumbs_frame.pack_propagate(False)

        ctk.CTkLabel(self.student_thumbs_frame, text="ภาพใบหน้าที่เรียนรู้แล้ว (ตารางภาพ):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#6CA6CD").pack(anchor="w", padx=10, pady=(5, 0))

        self.student_thumbs_scrollable = ctk.CTkScrollableFrame(self.student_thumbs_frame, orientation="vertical", fg_color="transparent", height=140)
        self.student_thumbs_scrollable.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ลบชื่อนักเรียนที่เลือก
        ctk.CTkLabel(self.student_form_frame, text="3. การดำเนินการอื่น ๆ", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E74C3C").pack(anchor="w", padx=20, pady=(15, 5))
        self.btn_delete_student = ctk.CTkButton(
            self.student_form_frame, text="ลบรายชื่อนักเรียน (ลบข้อมูลและภาพทั้งหมด)",
            state="disabled", fg_color="#C0392B", hover_color="#962D22", command=self.delete_selected_student
        )
        self.btn_delete_student.pack(fill="x", padx=20, pady=10)

    def load_student_list(self):
        # ลบวิดเจ็ตใน Scrollable Frame เก่าออก
        for widget in self.student_list_scrollable.winfo_children():
            widget.destroy()

        self.student_buttons = {}
        self.selected_student_id = None
        self.selected_student_name = None
        self.btn_upload_student_photo.configure(state="disabled")
        self.btn_delete_student.configure(state="disabled")
        self.lbl_student_selected_info.configure(text="กรุณาเลือกนักเรียนจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ")
        self.lbl_student_photo_count_detail.configure(text="")

        search_term = ""
        if hasattr(self, 'entry_student_search'):
            search_term = self.entry_student_search.get().strip().lower()

        students = self.db.get_all_students()
        for idx, s in enumerate(students):
            if search_term:
                name_match = search_term in s['name'].lower()
                id_match = s['student_id'] and (search_term in s['student_id'].lower())
                if not (name_match or id_match):
                    continue

            # สร้างเฟรมแถวรายชื่อนักเรียนแต่ละคนเพื่อความเรียบร้อยและใส่ปุ่มลบกากบาท X ได้
            row_frame = ctk.CTkFrame(self.student_list_scrollable, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)

            btn = ctk.CTkButton(
                row_frame,
                text=f"{s['name']} [{s['student_id']}] ({s['photo_count']} รูปภาพ)",
                anchor="w",
                fg_color="transparent",
                text_color="#A2B5CD",
                hover_color="#1F3A60",
                command=lambda sid=s['id'], sname=s['name'], scode=s['student_id'], scnt=s['photo_count']: self.select_student_item(sid, sname, scode, scnt)
            )
            btn.pack(side="left", fill="x", expand=True)
            self.student_buttons[s['id']] = btn

            # ปุ่มกากบาทสีแดงสำหรับการลบข้อมูลนักเรียนอย่างรวดเร็ว (Quick Delete)
            btn_delete_x = ctk.CTkButton(
                row_frame,
                text="❌",
                width=26, height=26,
                fg_color="transparent",
                hover_color="#E74C3C",
                text_color="#E74C3C",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda sid=s['id'], sname=s['name']: self.delete_selected_student_by_id(sid, sname)
            )
            btn_delete_x.pack(side="right", padx=(5, 2))

    def filter_student_list(self):
        self.load_student_list()

    def clear_student_search(self):
        if hasattr(self, 'entry_student_search'):
            self.entry_student_search.delete(0, "end")
            self.load_student_list()

    def select_student_item(self, student_id, student_name, student_code, photo_count):
        self.selected_student_id = student_id
        self.selected_student_name = student_name
        self.selected_student_code = student_code
        self.selected_student_thumb_path = None
        self.selected_student_thumb_widget = None

        # ไฮไลต์ปุ่มที่ถูกเลือก
        for sid, btn in self.student_buttons.items():
            if sid == student_id:
                btn.configure(fg_color="#1F3A60", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#A2B5CD")

        self.lbl_student_selected_info.configure(text=f"นักเรียนที่เลือก: {student_name} (รหัส: {student_code})")
        self.lbl_student_photo_count_detail.configure(text=f"รูปภาพที่ลงทะเบียนแล้วในระบบ: {photo_count} รูป")

        self.btn_upload_student_photo.configure(state="normal")
        self.btn_delete_student.configure(state="normal")
        self.btn_delete_student_photo.configure(state="disabled")

        # ดึงภาพย่อมาแสดงผล
        self.show_student_thumbnails(student_id)

    def add_student_name(self):
        name = self.entry_student_name.get().strip()
        student_code = self.entry_student_id.get().strip()

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

        student_id = self.db.register_member(name, role='student', student_id=student_code)
        if student_id:
            logger.info(f"Registered new student '{name}' (ID: {student_code}) successfully.")
            self.entry_student_name.delete(0, "end")
            self.entry_student_id.delete(0, "end")
            self.load_student_list()
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

        threading.Thread(target=process_upload, daemon=True).start()

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
            img = cv2.imdecode(np.fromfile(original_path, dtype=np.uint8), cv2.IMREAD_COLOR)
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
        """แสดงรูปภาพย่อยของนักเรียนที่เลือกในรูปแบบตารางกริด (Grid)"""
        # ล้างข้อมูลเก่า
        for widget in self.student_thumbs_scrollable.winfo_children():
            widget.destroy()

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (student_id,))
        rows = cursor.fetchall()
        conn.close()

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
        """เลือกรูปภาพย่อของนักเรียน"""
        logger.info(f"[DEBUG] select_student_thumbnail called: path={path}, student_id={self.selected_student_id}")
        # รีเซ็ตสีของ widget เก่า (เหมือนเมนูครู)
        if self.selected_student_thumb_widget:
            try:
                self.selected_student_thumb_widget.configure(fg_color="transparent", border_width=0, border_color="transparent")
            except Exception:
                pass

        self.selected_student_thumb_path = path
        self.selected_student_thumb_widget = widget
        # แสดงไฮไลต์สีแดงรอบขอบเฟรม (เหมือนเมนูครู)
        widget.configure(fg_color="transparent", border_width=3, border_color="#FF5252")
        logger.info(f"[DEBUG] About to enable delete button, hasattr={hasattr(self, 'btn_delete_student_photo')}")
        if hasattr(self, 'btn_delete_student_photo'):
            self.btn_delete_student_photo.configure(state="normal")
            logger.info(f"[DEBUG] Delete button enabled")
        else:
            logger.error(f"[ERROR] btn_delete_student_photo not found!")

    def delete_selected_student_photo(self):
        """ลบรูปภาพใบหน้านักเรียนที่เลือก"""
        if not self.selected_student_thumb_path or not self.selected_student_id:
            return

        confirm = messagebox.askyesno(
            "ยืนยันการลบรูป",
            f"คุณต้องการลบรูปภาพนี้ใช่หรือไม่?"
        )
        if not confirm:
            return

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM staff_embeddings WHERE image_path = ? AND staff_id = ?",
                          (self.selected_student_thumb_path, self.selected_student_id))
            conn.commit()
            conn.close()

            # ลบไฟล์รูปภาพ
            if os.path.exists(self.selected_student_thumb_path):
                os.remove(self.selected_student_thumb_path)

            logger.info(f"Deleted student photo: {self.selected_student_thumb_path}")

            # รีเฟรช
            self.show_student_thumbnails(self.selected_student_id)
            self.load_student_list()

            self.selected_student_thumb_path = None
            self.selected_student_thumb_widget = None
            self.btn_delete_student_photo.configure(state="disabled")

            messagebox.showinfo("ลบสำเร็จ", "ลบรูปภาพเรียบร้อย")
        except Exception as e:
            logger.error(f"Error deleting student photo: {e}")
            messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการลบรูป: {e}")

    def open_sheets_import_dialog(self):
        """เปิด Dialog ตั้งค่าการนำเข้าจาก Google Sheets"""
        SheetsImportDialog(self, callback=self.batch_import_from_sheets)

    def batch_import_from_sheets(self, settings):
        """นำเข้านักเรียนจาก Google Sheets พร้อมตรวจสอบข้อมูลเดิม"""
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
                col_front = col_map.get(settings["col_front"], 2)

                # ข้ามแถวหัวคอลัมน์
                data_rows = sheet_data[1:]

                # จัดกลุ่มข้อมูลตาม รหัส + ชื่อ + รวบรวม URL ภาพทั้งหมด
                student_dict = {}
                for row in data_rows:
                    if len(row) <= max(col_id, col_name, col_front):
                        continue

                    student_code = row[col_id].strip() if col_id < len(row) else ""
                    student_name = row[col_name].strip() if col_name < len(row) else ""

                    if not student_code or not student_name:
                        continue

                    # รวบรวม URL ภาพเริ่มจาก column หน้าตรง ไปเรื่อยๆ จนกว่าจะเจอค่าว่าง
                    photo_urls = []
                    for col_idx in range(col_front, len(row)):
                        url = row[col_idx].strip() if col_idx < len(row) else ""
                        if not url or url == "-":
                            break  # หยุดเมื่อเจอค่าว่าง
                        photo_urls.append((chr(65 + col_idx), url))

                    if not photo_urls:
                        continue

                    key = (student_code, student_name)
                    if key not in student_dict:
                        student_dict[key] = {"photos": photo_urls}

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

                        if existing is None:
                            # กรณีที่ 1: ไม่มีข้อมูล → บันทึกใหม่
                            student_id = self.db.register_member(student_name, role='student', student_id=student_code)
                            is_new = True
                            logger.info(f"New student: {student_name} (ID: {student_code}, DB ID: {student_id})")
                        else:
                            # กรณีที่ 2-3: มีข้อมูลอยู่แล้ว → ใช้ ID เดิม
                            student_id = existing["id"]
                            is_new = False
                            logger.info(f"Existing student: {student_name} (ID: {student_code}, DB ID: {student_id})")

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

    def load_staff_list(self):
        # ลบวิดเจ็ตใน Scrollable Frame เก่าออก
        for widget in self.staff_list_scrollable.winfo_children():
            widget.destroy()
            
        self.staff_buttons = {}
        self.selected_staff_id = None
        self.selected_staff_name = None
        self.btn_upload_photo.configure(state="disabled")
        self.btn_delete_staff.configure(state="disabled")
        self.lbl_selected_info.configure(text="กรุณาเลือกคุณครูจากรายชื่อซ้ายมือเพื่อจัดการรูปภาพ")
        self.lbl_photo_count_detail.configure(text="")

        search_term = ""
        if hasattr(self, 'entry_staff_search'):
            search_term = self.entry_staff_search.get().strip().lower()

        staff = self.db.get_all_teachers()
        for idx, s in enumerate(staff):
            if search_term and search_term not in s['name'].lower():
                continue

            # สร้างเฟรมแถวรายชื่อครูแต่ละคนเพื่อความเรียบร้อยและใส่ปุ่มลบกากบาท X ได้
            row_frame = ctk.CTkFrame(self.staff_list_scrollable, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            
            btn = ctk.CTkButton(
                row_frame, 
                text=f"{s['name']} ({s['photo_count']} รูปภาพ)", 
                anchor="w",
                fg_color="transparent",
                text_color="#A2B5CD",
                hover_color="#1F3A60",
                command=lambda sid=s['id'], sname=s['name'], scnt=s['photo_count']: self.select_staff_item(sid, sname, scnt)
            )
            btn.pack(side="left", fill="x", expand=True)
            self.staff_buttons[s['id']] = btn
            
            # ปุ่มกากบาทสีแดงสำหรับการลบข้อมูลคุณครูอย่างรวดเร็ว (Quick Delete)
            btn_delete_x = ctk.CTkButton(
                row_frame, 
                text="❌", 
                width=26, height=26,
                fg_color="transparent",
                hover_color="#E74C3C",
                text_color="#E74C3C",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda sid=s['id'], sname=s['name']: self.delete_selected_staff_by_id(sid, sname)
            )
            btn_delete_x.pack(side="right", padx=(5, 2))

    def filter_staff_list(self):
        self.load_staff_list()

    def clear_staff_search(self):
        if hasattr(self, 'entry_staff_search'):
            self.entry_staff_search.delete(0, "end")
            self.load_staff_list()

    def select_staff_item(self, staff_id, staff_name, photo_count):
        self.selected_staff_id = staff_id
        self.selected_staff_name = staff_name
        self.selected_thumb_path = None
        self.selected_thumb_widget = None
        
        # ไฮไลต์ปุ่มที่ถูกเลือก
        for sid, btn in self.staff_buttons.items():
            if sid == staff_id:
                btn.configure(fg_color="#1F3A60", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#A2B5CD")

        self.lbl_selected_info.configure(text=f"คุณครูที่เลือก: {staff_name}")
        self.lbl_photo_count_detail.configure(text=f"รูปภาพที่ลงทะเบียนแล้วในระบบ: {photo_count} รูป")
        
        self.btn_upload_photo.configure(state="normal")
        self.btn_delete_staff.configure(state="normal")
        self.btn_delete_photo.configure(state="disabled")

        # ดึงภาพย่อมาแสดงผล
        self.show_staff_thumbnails(staff_id)

    def add_staff_name(self):
        name = self.entry_staff_name.get().strip()
        if not name:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อคุณครู")
            return
            
        staff_id = self.db.register_staff_member(name)
        if staff_id:
            logger.info(f"Registered new teacher '{name}' successfully.")
            self.entry_staff_name.delete(0, "end")
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

            logger.info(f"Registered {success_count} / {len(file_paths)} face templates for {self.selected_staff_name}")
            
            # รีเฟรชรายชื่อและรูปภาพย่อยในหน่วยความจำ
            self.after(0, self.load_staff_list)
            self.after(0, lambda: self.show_staff_thumbnails(self.selected_staff_id))
            self.after(0, lambda: messagebox.showinfo(
                "ลงทะเบียนสำเร็จ", 
                f"ลงทะเบียนใบหน้าของคุณครู {self.selected_staff_name} สำเร็จ {success_count} รูป"
            ))
            
            # โหลดข้อมูลรายชื่อใหม่ใน Thread หลัก
            self.after(0, self.load_staff_list)
            self.after(0, lambda: messagebox.showinfo(
                "ลงทะเบียนสำเร็จ", 
                f"ลงทะเบียนใบหน้าของคุณครู {self.selected_staff_name} สำเร็จ {success_count} รูป"
            ))

        threading.Thread(target=process_upload, daemon=True).start()

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
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 20))

        # โซนตั้งค่าการสแกน (บน)
        self.scan_settings_frame = ctk.CTkFrame(self.frame_scan, fg_color="#101B2B")
        self.scan_settings_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15), padx=2)
        self.scan_settings_frame.grid_columnconfigure((0, 1), weight=1)

        # ลิงก์โฟลเดอร์ Google Drive และชีท พร้อมปุ่มค้นหาดึงจาก API
        ctk.CTkLabel(self.scan_settings_frame, text="ID โถลเดอร์ภาพกิจกรรม (Google Drive):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").grid(row=0, column=0, padx=15, pady=(15, 2), sticky="w")
        
        folder_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        folder_input_frame.grid(row=1, column=0, padx=15, pady=2, sticky="ew")
        folder_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_drive_folder_id = ctk.CTkEntry(folder_input_frame, placeholder_text="ตัวอย่าง: 1a2b3c4d5e6f7g8h9i0j...")
        self.entry_drive_folder_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_pick_folder = ctk.CTkButton(folder_input_frame, text="🔍 เลือกโฟลเดอร์", width=95, fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("folder"))
        btn_pick_folder.pack(side="right")

        ctk.CTkLabel(self.scan_settings_frame, text="ID ของ Google Sheets (ฐานข้อมูลดัชนี):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").grid(row=0, column=1, padx=15, pady=(15, 2), sticky="w")
        
        sheet_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        sheet_input_frame.grid(row=1, column=1, padx=15, pady=2, sticky="ew")
        sheet_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_sheets_id = ctk.CTkEntry(sheet_input_frame, placeholder_text="ตัวอย่าง: 1AbCdEfGhIjKlMnOpQrStUvWxYz...")
        self.entry_sheets_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_pick_sheet = ctk.CTkButton(sheet_input_frame, text="🔍 เลือก Sheets", width=95, fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("sheet"))
        btn_pick_sheet.pack(side="right", padx=(0, 5))
        
        btn_open_sheet = ctk.CTkButton(sheet_input_frame, text="🌐 เปิด Sheets", width=95, fg_color="#107C41", hover_color="#0A5C30", command=self.open_sheets_in_browser)
        btn_open_sheet.pack(side="right")

        # แถวใหม่สำหรับโฟลเดอร์เก็บ JSON
        ctk.CTkLabel(self.scan_settings_frame, text="ID โฟลเดอร์เก็บไฟล์ JSON ดัชนี (Google Drive):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").grid(row=2, column=0, columnspan=2, padx=15, pady=(8, 2), sticky="w")
        
        json_folder_input_frame = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        json_folder_input_frame.grid(row=3, column=0, columnspan=2, padx=15, pady=2, sticky="ew")
        json_folder_input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_json_folder_id = ctk.CTkEntry(json_folder_input_frame, placeholder_text="ระบุ ID โฟลเดอร์หลักที่แชร์ไฟล์ person_index.json และ photo_index.json")
        self.entry_json_folder_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        btn_pick_json_folder = ctk.CTkButton(json_folder_input_frame, text="🔍 เลือกโฟลเดอร์", width=95, fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.open_google_picker("json_folder"))
        btn_pick_json_folder.pack(side="right", padx=(0, 5))
        
        btn_open_json_folder = ctk.CTkButton(json_folder_input_frame, text="🌐 โฟลเดอร์เก็บไฟล์ jason", width=160, fg_color="#E67E22", hover_color="#D35400", text_color="white", command=self.open_json_folder_in_browser)
        btn_open_json_folder.pack(side="right")

        # ปรับค่า Threshold และ CPU/GPU (เลื่อนไป row 4)
        option_panel = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        option_panel.grid(row=4, column=0, columnspan=2, padx=15, pady=10, sticky="ew")
        option_panel.grid_columnconfigure(0, weight=1)
        option_panel.grid_columnconfigure(1, weight=1)

        # สไลเดอร์ Threshold
        thresh_frame = ctk.CTkFrame(option_panel, fg_color="transparent")
        thresh_frame.grid(row=0, column=0, sticky="w")
        self.lbl_threshold = ctk.CTkLabel(thresh_frame, text="ค่า Threshold ความคล้ายใบหน้า: 0.65", text_color="#A2B5CD")
        self.lbl_threshold.pack(anchor="w")
        self.slider_threshold = ctk.CTkSlider(thresh_frame, from_=0.1, to=0.9, number_of_steps=80, command=self.update_thresh_label)
        self.slider_threshold.set(0.65)
        self.slider_threshold.pack(fill="x", pady=5)

        # การประมวลผล (CPU / GPU และ สแกนซ้ำ)
        device_frame = ctk.CTkFrame(option_panel, fg_color="transparent")
        device_frame.grid(row=0, column=1, sticky="e")
        
        self.chk_use_gpu = ctk.CTkCheckBox(device_frame, text="เปิดใช้งานการสแกนด้วย GPU (CUDA)", text_color="#A2B5CD")
        self.chk_use_gpu.pack(anchor="e", pady=(5, 2))

        self.chk_re_scan = ctk.CTkCheckBox(device_frame, text="เปิดฟังก์ชั่นให้แสกนรูปภาพเดิมซ้ำ (Re-scan)", text_color="#A2B5CD")
        self.chk_re_scan.pack(anchor="e", pady=(2, 5))

        # เฟรมเลือกเป้าหมายการจับคู่ใบหน้า (Matching Target Panel v1.7.5)
        self.match_target_box = ctk.CTkFrame(option_panel, fg_color="#101B2B")
        self.match_target_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0), padx=5)
        self.match_target_box.grid_columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkLabel(self.match_target_box, text="เป้าหมายการค้นหาและจับคู่ใบหน้า:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, columnspan=3, sticky="w", padx=15, pady=(5, 2))
        
        self.match_mode = ctk.StringVar(value="all")
        
        # คอลัมน์ 0: ครู + นักเรียน ทั้งหมด
        self.rad_all = ctk.CTkRadioButton(self.match_target_box, text="ครู + นักเรียน ทั้งหมด", variable=self.match_mode, value="all", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_all.grid(row=1, column=0, sticky="w", padx=25, pady=3)
        
        # คอลัมน์ 1: กลุ่มคุณครู
        self.rad_teachers = ctk.CTkRadioButton(self.match_target_box, text="คุณครูทั้งหมด", variable=self.match_mode, value="teachers", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_teachers.grid(row=1, column=1, sticky="w", padx=25, pady=3)
        
        self.rad_sel_teachers = ctk.CTkRadioButton(self.match_target_box, text="เลือกเฉพาะคุณครูบางคน", variable=self.match_mode, value="selected_teachers", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_sel_teachers.grid(row=2, column=1, sticky="w", padx=25, pady=3)
        
        self.btn_select_teachers = ctk.CTkButton(
            self.match_target_box, text="เลือกรายชื่อคุณครู (0 คน)...", 
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            height=24, font=ctk.CTkFont(size=11), state="disabled",
            command=self.show_teachers_selection_popup
        )
        self.btn_select_teachers.grid(row=3, column=1, sticky="w", padx=50, pady=(2, 8))
        
        # คอลัมน์ 2: กลุ่มนักเรียน
        self.rad_students = ctk.CTkRadioButton(self.match_target_box, text="นักเรียนทั้งหมด", variable=self.match_mode, value="students", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_students.grid(row=1, column=2, sticky="w", padx=25, pady=3)
        
        self.rad_sel_students = ctk.CTkRadioButton(self.match_target_box, text="เลือกเฉพาะนักเรียนบางคน", variable=self.match_mode, value="selected_students", command=self.update_match_mode_ui, text_color="#A2B5CD")
        self.rad_sel_students.grid(row=2, column=2, sticky="w", padx=25, pady=3)
        
        self.btn_select_students = ctk.CTkButton(
            self.match_target_box, text="เลือกรายชื่อนักเรียน (0 คน)...", 
            fg_color="#1F3A60", hover_color="#20334F", text_color="white",
            height=24, font=ctk.CTkFont(size=11), state="disabled",
            command=self.show_students_selection_popup
        )
        self.btn_select_students.grid(row=3, column=2, sticky="w", padx=50, pady=(2, 8))

        # ปุ่มกดทำสแกนและ Progress Bar (เลื่อนไป row 5)
        self.action_panel = ctk.CTkFrame(self.scan_settings_frame, fg_color="transparent")
        self.action_panel.grid(row=5, column=0, columnspan=2, padx=15, pady=(10, 15), sticky="ew")
        self.action_panel.grid_columnconfigure(0, weight=1)

        self.btn_start_scan = ctk.CTkButton(
            self.action_panel, text="เริ่มต้นดาวน์โหลดและสแกนใบหน้ากิจกรรม", 
            fg_color="#2ECC71", hover_color="#27AE60", text_color="black",
            font=ctk.CTkFont(size=14, weight="bold"), height=40,
            command=self.toggle_scanning
        )
        self.btn_start_scan.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.btn_pause_scan = ctk.CTkButton(
            self.action_panel, text="⏸️ พักการสแกน (Pause)", 
            fg_color="#F39C12", hover_color="#D68910", text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"), height=40,
            command=self.toggle_pause_scanning,
            state="disabled"
        )
        self.btn_pause_scan.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(self.action_panel)
        self.progress_bar.set(0.0)
        self.progress_bar.grid(row=2, column=0, sticky="ew")
        self.progress_bar.grid_remove() # ซ่อนไว้ก่อนเริ่ม

        self.lbl_progress_text = ctk.CTkLabel(self.action_panel, text="พร้อมสแกน", text_color="#A2B5CD")
        self.lbl_progress_text.grid(row=3, column=0, pady=2)
        self.lbl_progress_text.grid_remove()

        # โซนแสดงผล Console Logs ย้ายไปก้นจอหลักถาวรแล้ว ไม่ต้องกริตเฟรมซ้ำซ้อนที่นี่

    def update_thresh_label(self, val):
        self.lbl_threshold.configure(text=f"ค่า Threshold ความคล้ายใบหน้า: {val:.2f}")

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

    def check_log_queue(self):
        """ดึง Log จากคิวของ Thread ย่อย มาเติมลงในช่อง Console ของ GUI ในเธรดหลัก"""
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                
                # วิเคราะห์หาแท็กประเภทสีตาม Keyword 12 หมวดหมู่
                tag = "white"
                msg_upper = msg.upper()
                
                if "[ERROR]" in msg_upper or "ERROR:" in msg_upper:
                    tag = "red"
                elif "[WARNING]" in msg_upper or "WARNING:" in msg_upper:
                    tag = "orange_red"
                elif "[INIT]" in msg_upper:
                    tag = "orange"
                elif "[DATABASE]" in msg_upper or "SQLITE" in msg_upper or "DB_" in msg_upper:
                    tag = "yellow_orange"
                elif "[GDRIVE]" in msg_upper or "GOOGLE DRIVE" in msg_upper:
                    tag = "yellow"
                elif "[GSHEETS]" in msg_upper or "GOOGLE SHEET" in msg_upper:
                    tag = "yellow_green"
                elif "[MATCH_OK]" in msg_upper or "SUCCESSFULLY" in msg_upper:
                    tag = "green"
                elif "MATCHED WITH TEMPLATE" in msg_upper:
                    # ตรวจวิเคราะห์คะแนน Threshold และแบ่งเป็นสีเขียว/แดงตามจริง
                    if "SCORE:" in msg_upper:
                        try:
                            score_str = msg_upper.split("SCORE:")[1].strip()
                            score_val = float(''.join(c for c in score_str if c.isdigit() or c == '.'))
                            thresh_val = self.slider_threshold.get()
                            if score_val >= thresh_val:
                                tag = "green"
                            else:
                                tag = "red"
                        except Exception:
                            tag = "green"
                    else:
                        tag = "green"
                elif "[SCAN_INFO]" in msg_upper or "SCANNING" in msg_upper:
                    tag = "green_blue"
                elif "[FACE_AI]" in msg_upper or "INSIGHTFACE" in msg_upper or "EMBEDDING" in msg_upper:
                    tag = "blue"
                elif "[SYSTEM]" in msg_upper or "CONNECTED" in msg_upper:
                    tag = "navy"
                elif "[UI]" in msg_upper:
                    tag = "purple"
                elif "FALLBACK" in msg_upper:
                    tag = "magenta"
                
                self.console_text.insert("end", msg + "\n", tag)
                self.console_text.see("end")
                
                # จำกัดจำนวนบรรทัดของ Console เพื่อป้องกันค้าง (เช่น เก็บ 5000 บรรทัดล่าสุด)
                num_lines = float(self.console_text.index('end-1c').split('.')[0])
                if num_lines > 5000:
                    self.console_text.delete('1.0', '100.0')
            except queue.Empty:
                break
        # เช็คซ้ำทุก 100 มิลลิวินาที
        self.after(100, self.check_log_queue)

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
            templates = self.db.get_all_embeddings()
            if len(templates["embeddings"]) == 0:
                logger.warning("[SCHEDULE] No target embeddings found.")
                return
                
            if not self.sync_manager.connect(sheet_id):
                logger.error("[SCHEDULE] Failed to connect to Google Sheets.")
                return
                
            use_gpu = self.chk_use_gpu.get()
            self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if not self.analyzer.initialize():
                logger.error("[SCHEDULE] Could not initialize FaceAnalyzer.")
                return
                
            # วนลูปโฟลเดอร์ย่อยที่ส่งเข้ามา
            for f_id in folder_ids:
                logger.info(f"[SCHEDULE] Processing headless scan for folder ID: {f_id}")
                images_to_scan = []
                query = f"'{f_id}' in parents and (mimeType contains 'image/') and trashed = false"
                try:
                    results = self.sync_manager.drive_service.files().list(
                        q=query, fields="nextPageToken, files(id, name, mimeType)", pageSize=500
                    ).execute()
                    files = results.get("files", [])
                    # (Assume subfolders don't have deeper subfolders for this specific task)
                    for file_info in files:
                        images_to_scan.append({
                            "file_id": file_info['id'],
                            "file_name": file_info['name'],
                            "event": folder_name
                        })
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error listing files in {f_id}: {e}")
                    continue
                    
                # Scan Process
                success_scan_count = 0
                for idx, img_info in enumerate(images_to_scan):
                    if getattr(self.scheduler, 'stop_requested', False):
                        break
                    existing_photo_id = self.db.get_photo_id_by_drive_id(img_info["file_id"])
                    if existing_photo_id and self.db.has_cached_faces(existing_photo_id):
                        # Fast Rescan
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
                                threshold=current_thresh
                            )
                            # Update DB
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
                        img_bytes = self.sync_manager.download_image_bytes(img_info["file_id"])
                        if img_bytes:
                            import cv2
                            nparr = np.frombuffer(img_bytes, np.uint8)
                            img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img_cv is not None:
                                faces = self.analyzer.app.get(img_cv)
                                photo_id = existing_photo_id
                                if not photo_id:
                                    photo_serial = self.get_next_photo_serial()
                                    photo_id = f"P{photo_serial:05d}"
                                self.db.save_scanned_photo(photo_id, img_info["file_id"], img_info["event"], f"https://drive.google.com/file/d/{img_info['file_id']}/view", matches=[])
                                
                                if faces:
                                    self.db.save_photo_face_embeddings(photo_id, faces)
                                        
                                    detected_embeddings = np.array([f.embedding for f in faces])
                                    current_thresh = self.slider_threshold.get()
                                    match_results = self.analyzer.match_faces_matrix(
                                        detected_embeddings,
                                        templates["embeddings"],
                                        templates["names"],
                                        templates["staff_ids"],
                                        threshold=current_thresh
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
        """ทำ Retroactive Match เงียบๆ สำหรับหน้าใหม่ที่เพิ่งเพิ่ม (เทียบกับแคชทั้งหมด)"""
        logger.info(f"[SCHEDULE] Running retroactive match for {len(matched_faces_to_process)} faces...")
        try:
            # ดึงแคชทั้งหมด
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT photo_id, embedding FROM scanned_photo_faces")
                cached_faces = c.fetchall()
            
            for item in matched_faces_to_process:
                staff_id = item["staff_id"]
                target_emb = item["emb"]
                target_norm = target_emb / (np.linalg.norm(target_emb) or 1.0)
                
                for row in cached_faces:
                    photo_id = row[0]
                    emb_blob = row[1]
                    cached_emb = np.frombuffer(emb_blob, dtype=np.float32)
                    c_norm = cached_emb / (np.linalg.norm(cached_emb) or 1.0)
                    
                    sim = np.dot(target_norm, c_norm)
                    if sim >= 0.5: # Threshold
                        self.db.save_detected_face(photo_id, staff_id, sim)
            
            # อัปเดตข้อมูลขึ้น Sheet
            sync_data = self.db.get_all_sync_data()
            self.sync_manager.sync_to_google_sheet(sync_data)
            
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
            self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
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

            # 5. ลุยตรวจจับใบหน้าทีละภาพ
            thresh_val = self.slider_threshold.get()
            success_scan_count = 0
            
            for idx, img_info in enumerate(images_to_scan):
                # ตรวจสอบปุ่ม Pause สลับลูปรอกรณีหยุดพักชั่วคราว
                while self.is_paused and self.is_scanning:
                    time.sleep(0.2)
                    
                if not self.is_scanning:
                    logger.warning("Scan process cancelled by user.")
                    break
                
                # แสดงความก้าวหน้า
                prog_val = (idx / len(images_to_scan))
                self.progress_bar.set(prog_val)
                self.lbl_progress_text.configure(text=f"กำลังสแกนรูปที่ {idx+1}/{len(images_to_scan)}: {img_info['file_name']}")

                logger.info(f"[{idx+1}/{len(images_to_scan)}] Processing image '{img_info['file_name']}' from event '{img_info['event']}'")
                
                # ตรวจสอบว่าสามารถรัน Fast Re-scan ผ่านแคชได้หรือไม่
                is_fast_rescan = False
                if use_re_scan:
                    existing_photo_id = self.db.get_photo_id_by_drive_id(img_info["file_id"])
                    if existing_photo_id and self.db.has_cached_faces(existing_photo_id):
                        is_fast_rescan = True
                        logger.info(f"⚡ [FAST RESCAN] Using cached face embeddings for {img_info['file_name']} (Photo ID: {existing_photo_id})")
                        
                        # โหลดใบหน้าจากแคช
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
                                threshold=current_thresh
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
                        
                        # อัปเดต GUI Summary Log (เฉพาะส่วนข้อความสรุป)
                        def update_summary_only(items=summary_list):
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
                        
                        self.after(0, update_summary_only)
                        
                        # ปรับปรุงผลลัพธ์ลง SQLite (ลบแมตช์เดิมตามเงื่อนไขที่เลือก และเขียนแมตช์ใหม่ลงไป โดยไม่ลบแคช)
                        if self.match_mode.get() != "all":
                            self.db.delete_photo_matches_selective(existing_photo_id, templates["staff_ids"])
                        else:
                            self.db.delete_photo_matches(existing_photo_id)
                        self.db.save_detected_faces(existing_photo_id, matches_in_photo)
                        success_scan_count += 1
                        continue
                
                # หากแอดมินติ๊กสแกนซ้ำ แต่ไม่มีข้อมูลแคช ให้ทำการล้างประวัติใน SQLite ก่อนเพื่อรับการวิเคราะห์ใหม่ (Full Re-scan)
                if use_re_scan:
                    self.db.delete_photo_scan_record(img_info["file_id"])

                # ดาวน์โหลดไบต์รูปภาพ
                img_bytes = self.sync_manager.download_image_bytes(img_info["file_id"])
                if img_bytes is None:
                    logger.error(f"Cannot download image {img_info['file_name']}. Skipping.")
                    continue

                # แปลงเป็นรูปภาพ OpenCV (รองรับเฉพาะไฟล์รูปภาพปกติ เช่น JPG, PNG, WEBP)
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if img is None:
                    logger.error(f"Cannot decode image {img_info['file_name']}. Skipping.")
                    continue

                # รันสแกนหาใบหน้าทั้งหมด
                faces = self.analyzer.app.get(img)
                logger.info(f"Found {len(faces)} faces in '{img_info['file_name']}'")

                matches_in_photo = []
                
                # ดึงค่า Threshold สด ณ วินาทีนี้ (Real-time Threshold!)
                current_thresh = self.slider_threshold.get()
                
                # ดึงพจนานุกรมภาพพรีวิวด้วย PIL เพื่อรองรับตัวอักษรภาษาไทย Tahoma
                from PIL import ImageDraw, ImageFont
                preview_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                preview_pil = Image.fromarray(preview_rgb)
                draw = ImageDraw.Draw(preview_pil)
                
                # พยายามโหลดฟอนต์ Tahoma (ฟอนต์ระบบ Windows มาตรฐาน) เพื่อรองรับอักขระไทย
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

                if len(faces) > 0:
                    # คัดลอกเวกเตอร์ใบหน้าที่พบ
                    detected_embeddings = np.array([f.embedding for f in faces])
                    
                    # ค้นหาในเมทริกซ์ใบหน้าต้นแบบครู
                    match_results = self.analyzer.match_faces_matrix(
                        detected_embeddings,
                        templates["embeddings"],
                        templates["names"],
                        templates["staff_ids"],
                        threshold=current_thresh
                    )
                    
                    # กรองและประมวลผลวาดกรอบผลลัพธ์
                    summary_list = [] # เก็บ tuple (name, confidence, is_matched) เพื่อพ่นขึ้นกล่องข้อความขวา
                    for i, f in enumerate(faces):
                        bbox = f.bbox
                        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                        
                        m_res = match_results[i]
                        if m_res:
                            matches_in_photo.append((m_res["staff_id"], m_res["confidence"]))
                            logger.info(f"🎯 Match: {m_res['name']} ({m_res['confidence']*100:.1f}%) in {img_info['file_name']}")
                            summary_list.append((m_res["name"], m_res["confidence"], True))
                            
                            # วาดกรอบสี่เหลี่ยมสีเขียว (ผ่านเกณฑ์) ลงบน PIL Image
                            draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=4)
                            text_label = f"{m_res['name']} ({m_res['confidence']*100:.0f}%)"
                            draw.text((x1, max(0, y1 - font.getbbox(text_label)[3] - 5)), text_label, fill=(0, 255, 0), font=font)
                        else:
                            # ต่ำกว่าเกณฑ์ -> ค้นหาคนที่ใกล้เคียงสุดเพื่อรายงานคะแนนในวงเล็บและตีกรอบสีแดง
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
                            
                # ปรับรูปพรีวิวย่อขนาดเพื่อแสดงใน GUI
                h_orig, w_orig = preview_pil.height, preview_pil.width
                h_new = 240
                w_new = int(w_orig * (h_new / h_orig))
                if w_new > 380:
                    w_new = 380
                    h_new = int(h_orig * (w_new / w_orig))
                    
                preview_resized = preview_pil.resize((w_new, h_new), Image.Resampling.LANCZOS)
                ctk_preview = ctk.CTkImage(light_image=preview_resized, size=(w_new, h_new))
                
                # ส่งวัตถุพรีวิวและประวัติสรุปรายชื่อแบบเรียลไทม์ขึ้น GUI
                def update_preview_and_summary(img_obj=ctk_preview, items=summary_list):
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

                self.after(0, update_preview_and_summary)

                # 6. สร้าง หรือใช้ รหัส ID เดิมสำหรับรูปภาพนี้
                photo_id = existing_photo_id
                if not photo_id:
                    photo_serial = self.get_next_photo_serial()
                    photo_id = f"P{photo_serial:05d}"
                
                # 7. บันทึกข้อมูลลง SQLite (ส่ง photo_date ไปด้วย)
                self.db.save_scanned_photo(
                    photo_id=photo_id,
                    drive_file_id=img_info["file_id"],
                    event_name=img_info["event"],
                    drive_link=img_info["drive_link"],
                    matches=matches_in_photo,
                    photo_date=img_info.get("date", "")
                )
                
                # บันทึกข้อมูลใบหน้าลงแคชสำหรับภาพสแกนใหม่ (Full Scan)
                self.db.save_photo_face_embeddings(photo_id, faces)
                
                success_scan_count += 1
            
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
        self.btn_start_scan.configure(text="เริ่มต้นดาวน์โหลดและสแกนใบหน้ากิจกรรม", fg_color="#2ECC71", hover_color="#27AE60", text_color="black", state="normal")
        self.btn_pause_scan.configure(state="disabled", text="⏸️ พักการสแกน (Pause)", fg_color="#F39C12", hover_color="#D68910")
        self.progress_bar.grid_remove()
        self.lbl_progress_text.grid_remove()
        # เคลียร์ภาพและคำอธิบายพรีวิว
        self.lbl_realtime_preview.configure(image="", text="[ แสดงภาพเปรียบเทียบการจับคู่ใบหน้าแบบ Real-time ]")
        self.txt_match_summary.configure(state="normal")
        self.txt_match_summary.delete("1.0", "end")
        self.txt_match_summary.configure(state="normal")

    # ==================== (4) หน้าตั้งค่าระบบ (Settings) ====================
    def setup_settings_ui(self):
        self.frame_settings.grid_columnconfigure(0, weight=1)
        
        lbl_title = ctk.CTkLabel(
            self.frame_settings, text="ตั้งค่าระบบการเข้าถึง", 
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 20))

        # โซนไฟล์ Credentials
        cred_frame = ctk.CTkFrame(self.frame_settings, fg_color="#101B2B")
        cred_frame.grid(row=1, column=0, sticky="ew", pady=10, padx=2)
        cred_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(cred_frame, text="ที่อยู่ไฟล์คีย์สิทธิ์ Google (Service Account JSON):", font=ctk.CTkFont(size=13, weight="bold"), text_color="#6CA6CD").grid(row=0, column=0, padx=15, pady=(15, 2), sticky="w")
        
        self.entry_cred_path = ctk.CTkEntry(cred_frame, placeholder_text="ตัวอย่าง: config/service_account.json")
        self.entry_cred_path.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        
        # ปุ่มเลือกไฟล์จากคอมพิวเตอร์
        btn_select_cred = ctk.CTkButton(
            cred_frame, text="เลือกไฟล์คีย์สิทธิ์ JSON จากเครื่อง...", fg_color="#1F3A60", hover_color="#20334F",
            command=self.select_cred_file
        )
        btn_select_cred.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="w")

        # โซนจัดการขยะล้างประวัติ
        db_settings_frame = ctk.CTkFrame(self.frame_settings, fg_color="#101B2B")
        db_settings_frame.grid(row=2, column=0, sticky="ew", pady=10, padx=2)
        db_settings_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(db_settings_frame, text="จัดการฐานข้อมูลสแกน:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#E74C3C").grid(row=0, column=0, padx=15, pady=(15, 2), sticky="w")
        
        btn_clear_history = ctk.CTkButton(
            db_settings_frame, text="ล้างประวัติภาพสแกนกิจกรรมกิจกรรมทั้งหมด (ไม่ลบรายชื่อครูต้นแบบ)", 
            fg_color="#C0392B", hover_color="#962D22",
            command=self.clear_scan_history
        )
        btn_clear_history.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="w")

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
            "re_scan": self.chk_re_scan.get()
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
                    
        except Exception as e:
            logger.error(f"Error loading settings file: {e}")

    # ==================== (5) เมธอดสร้างและจัดการเพิ่มเติม ====================

    def create_global_console(self):
        # โซนแสดงผล Console Logs (ล่างสุดของฝั่งขวา) - แบ่ง 2 คอลัมน์ ซ้าย (Log Text) และ ขวา (Preview Image)
        # ปลด height=185 คงที่ออก เพื่อให้ขยายขอบเต็มพื้นที่ครึ่งล่างตาม Row Weight 1:1 อย่างเป็นธรรมชาติ
        self.console_frame = ctk.CTkFrame(self, fg_color="#101B2B")
        self.console_frame.grid(row=1, column=1, padx=25, pady=(0, 25), sticky="nsew")
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
        log_header.grid(row=0, column=0, pady=(0, 2), sticky="ew")
        log_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_header, text="Console Debug logs (แสดงสถานะ):", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#6CA6CD"
        ).grid(row=0, column=0, sticky="w")

        btn_copy_log = ctk.CTkButton(
            log_header, text="📋 คัดลอก Log", width=90, height=20, 
            font=ctk.CTkFont(size=10), fg_color="#1F3A60", hover_color="#20334F",
            command=self.copy_console_selection
        )
        btn_copy_log.grid(row=0, column=1, padx=(0, 5), sticky="e")

        btn_clear_log = ctk.CTkButton(
            log_header, text="🧹 ล้าง Log", width=75, height=20, 
            font=ctk.CTkFont(size=10), fg_color="#1F3A60", hover_color="#20334F",
            command=self.clear_console_log
        )
        btn_clear_log.grid(row=0, column=2, sticky="e")

        # กล่อง Textbox แสดง Log สีขาวพื้นฐานบนพื้นดำสไตล์ Terminal
        self.console_text = ctk.CTkTextbox(
            left_frame, font=ctk.CTkFont(family="Consolas", size=9), 
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
        tb.tag_config("magenta", foreground="#EC407A")      # 12. ม่วงแดง (Fallback / อื่นๆ)
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
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#2ECC71"
        ).pack(anchor="w")

        # ป้ายสำหรับวาดแปะภาพพรีวิวผลงานการตรวจจับ (ด้านซ้ายของ right_frame)
        self.lbl_realtime_preview = ctk.CTkLabel(
            right_frame, text="[ แสดงภาพเปรียบเทียบการจับคู่ใบหน้าแบบ Real-time ]",
            font=ctk.CTkFont(size=10), text_color="#A2B5CD", fg_color="transparent"
        )
        self.lbl_realtime_preview.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # กล่องสำหรับพ่นรายชื่อครูและผลการแมตช์แบบสีเขียว/แดง (ด้านขวาของ right_frame)
        self.txt_match_summary = ctk.CTkTextbox(
            right_frame, font=ctk.CTkFont(family="Consolas", size=9),
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

    # ==================== (4) หน้าดูฐานข้อมูล SQLite ====================
    def setup_database_ui(self):
        from tkinter import ttk
        
        self.frame_database.grid_columnconfigure(0, weight=1)
        self.frame_database.grid_rowconfigure(4, weight=1)

        # หัวข้อ
        lbl_title = ctk.CTkLabel(
            self.frame_database, text="ดูข้อมูลในฐานข้อมูล SQLite", 
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 15))

        # โซนควบคุม (แถวบน)
        control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        control_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10), padx=2)
        
        ctk.CTkLabel(control_frame, text="เลือกตารางข้อมูล:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=15)
        
        self.option_db_table = ctk.CTkOptionMenu(
            control_frame, 
            values=[
                "รายชื่อคุณครู (staff_members - ครู)", 
                "รายชื่อนักเรียน (staff_members - นักเรียน)", 
                "ประวัติภาพถ่ายกิจกรรม (scanned_photos)", 
                "ผลจับคู่ใบหน้าครู (detected_faces - ครู)",
                "ผลจับคู่ใบหน้านักเรียน (detected_faces - นักเรียน)"
            ],
            command=self.load_db_table_data
        )
        self.option_db_table.pack(side="left", padx=5, pady=15)

        # ปุ่มรีเฟรช
        btn_refresh = ctk.CTkButton(control_frame, text="🔄 รีเฟรช", width=80, fg_color="#1F3A60", hover_color="#20334F", command=lambda: self.load_db_table_data(self.option_db_table.get()))
        btn_refresh.pack(side="left", padx=10, pady=15)

        # ปุ่มรีเซ็ตผลการจับคู่ของบุคคล
        self.btn_reset_matching = ctk.CTkButton(
            control_frame, text="🗑️ รีเซ็ตประวัติจับคู่", width=140, 
            fg_color="#C0392B", hover_color="#962D22", text_color="white",
            font=ctk.CTkFont(weight="bold"),
            command=self.reset_selected_person_matches
        )
        self.btn_reset_matching.pack(side="left", padx=10, pady=15)

        # ปุ่มเปิดโฟลเดอร์ DB
        btn_open_folder = ctk.CTkButton(control_frame, text="📂 เปิดโฟลเดอร์ฐานข้อมูล", width=140, fg_color="#1F3A60", hover_color="#20334F", command=self.open_db_folder)
        btn_open_folder.pack(side="right", padx=15, pady=15)

        # ปุ่มส่งออก CSV
        btn_export = ctk.CTkButton(control_frame, text="📊 ส่งออก CSV", width=100, fg_color="#2ECC71", hover_color="#27AE60", text_color="black", command=self.export_current_table)
        btn_export.pack(side="right", padx=5, pady=15)

        # โซนควบคุมที่สอง: ซิงค์ข้อมูล JSON ขึ้น Google Drive (v1.7.7)
        sync_control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        sync_control_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15), padx=2)
        
        ctk.CTkLabel(sync_control_frame, text="ซิงค์ดัชนี JSON ไป Google Drive:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=10)
        
        self.btn_sync_json_all = ctk.CTkButton(
            sync_control_frame, text="1. ซิงค์ทั้งครูและนักเรียน", width=165, 
            fg_color="#8E44AD", hover_color="#7D3C98", text_color="white",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self.run_manual_json_sync("all")
        )
        self.btn_sync_json_all.pack(side="left", padx=5, pady=10)
        
        self.btn_sync_json_teachers = ctk.CTkButton(
            sync_control_frame, text="2. ซิงค์เฉพาะครู", width=120, 
            fg_color="#2980B9", hover_color="#2471A3", text_color="white",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self.run_manual_json_sync("teachers")
        )
        self.btn_sync_json_teachers.pack(side="left", padx=5, pady=10)
        
        self.btn_sync_json_students = ctk.CTkButton(
            sync_control_frame, text="3. ซิงค์เฉพาะนักเรียน", width=140, 
            fg_color="#D35400", hover_color="#BA4A00", text_color="white",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self.run_manual_json_sync("students")
        )
        self.btn_sync_json_students.pack(side="left", padx=5, pady=10)

        # โซนควบคุมที่สาม: ค้นหาข้อมูลในตารางฐานข้อมูล (v1.8.4)
        search_control_frame = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        search_control_frame.grid(row=3, column=0, sticky="ew", pady=(0, 15), padx=2)
        
        ctk.CTkLabel(search_control_frame, text="🔍 ค้นหาข้อมูล:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD").pack(side="left", padx=15, pady=10)
        
        self.entry_db_search = ctk.CTkEntry(
            search_control_frame, 
            placeholder_text="พิมพ์คำค้นหา (Drive File ID, ลิงก์ Drive, Photo ID, ชื่อ, กิจกรรม, รหัสนักเรียน...)", 
            width=480
        )
        self.entry_db_search.pack(side="left", padx=5, pady=10, fill="x", expand=True)
        self.entry_db_search.bind("<KeyRelease>", lambda e: self.load_db_table_data())

        btn_clear_search = ctk.CTkButton(
            search_control_frame, text="❌ ล้างการค้นหา", width=110,
            fg_color="#34495E", hover_color="#2C3E50", text_color="white",
            command=self.clear_db_search
        )
        btn_clear_search.pack(side="right", padx=15, pady=10)

        # โซนแสดงตาราง (Treeview)
        table_container = ctk.CTkFrame(self.frame_database, fg_color="#101B2B")
        table_container.grid(row=4, column=0, sticky="nsew", padx=2, pady=(0, 5))
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        # สไตล์ตาราง Treeview
        self.style = ttk.Style()
        self.style.theme_use("default")
        self.style.configure(
            "Treeview",
            background="#1C2D42",
            foreground="white",
            rowheight=25,
            fieldbackground="#1C2D42",
            bordercolor="#101B2B",
            borderwidth=0
        )
        self.style.configure("Treeview.Heading", background="#101B2B", foreground="#6CA6CD", font=("Segoe UI", 10, "bold"))
        self.style.map("Treeview", background=[("selected", "#1F3A60")])

        # สร้าง Treeview
        self.db_tree = ttk.Treeview(table_container, show="headings")
        self.db_tree.grid(row=0, column=0, sticky="nsew", padx=(15, 0), pady=15)

        # แถบสกรอลด้านแนวตั้ง
        tree_scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.db_tree.yview)
        tree_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 15), pady=15)
        self.db_tree.configure(yscrollcommand=tree_scrollbar.set)

    def clear_db_search(self):
        if hasattr(self, 'entry_db_search'):
            self.entry_db_search.delete(0, "end")
        self.load_db_table_data()

    def load_db_table_data(self, selected_table_text=None):
        if not selected_table_text:
            selected_table_text = self.option_db_table.get()

        search_query = ""
        if hasattr(self, 'entry_db_search'):
            search_query = self.entry_db_search.get().strip()
        
        # ล้างข้อมูลเดิมใน Treeview
        self.db_tree.delete(*self.db_tree.get_children())
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            if "staff_members" in selected_table_text and "ครู" in selected_table_text:
                # ตาราง staff_members (ครู)
                if search_query:
                    cursor.execute("""
                        SELECT s.id, s.name, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                          AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ?)
                        GROUP BY s.id, s.name
                        ORDER BY s.id DESC
                    """, (f"%{search_query}%", f"%{search_query}%"))
                else:
                    cursor.execute("""
                        SELECT s.id, s.name, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        GROUP BY s.id, s.name
                        ORDER BY s.id DESC
                    """)
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("id", "name", "photos")
                self.db_tree.column("id", width=80, anchor="center")
                self.db_tree.column("name", width=350, anchor="w")
                self.db_tree.column("photos", width=120, anchor="center")
                
                self.db_tree.heading("id", text="ID ครู")
                self.db_tree.heading("name", text="ชื่อ-นามสกุล คุณครู")
                self.db_tree.heading("photos", text="จำนวนรูปที่ลงทะเบียน (รูป)")
                
                for r in rows:
                    self.db_tree.insert("", "end", values=r)
                    
            elif "staff_members" in selected_table_text and "นักเรียน" in selected_table_text:
                # ตาราง staff_members (นักเรียน)
                if search_query:
                    cursor.execute("""
                        SELECT s.id, s.name, s.student_id, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'student'
                          AND (CAST(s.id AS TEXT) LIKE ? OR s.name LIKE ? OR s.student_id LIKE ?)
                        GROUP BY s.id, s.name, s.student_id
                        ORDER BY s.id DESC
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
                else:
                    cursor.execute("""
                        SELECT s.id, s.name, s.student_id, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'student'
                        GROUP BY s.id, s.name, s.student_id
                        ORDER BY s.id DESC
                    """)
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("id", "name", "student_id", "photos")
                self.db_tree.column("id", width=80, anchor="center")
                self.db_tree.column("name", width=250, anchor="w")
                self.db_tree.column("student_id", width=150, anchor="center")
                self.db_tree.column("photos", width=120, anchor="center")
                
                self.db_tree.heading("id", text="ID")
                self.db_tree.heading("name", text="ชื่อ-นามสกุล นักเรียน")
                self.db_tree.heading("student_id", text="รหัสประจำตัว")
                self.db_tree.heading("photos", text="จำนวนรูปที่ลงทะเบียน (รูป)")
                
                for r in rows:
                    self.db_tree.insert("", "end", values=r)
                    
            elif "scanned_photos" in selected_table_text:
                # ตาราง scanned_photos (พร้อมแสดงสถานะแคชใบหน้า v1.8.5)
                query_sql = """
                    SELECT p.photo_id, p.drive_file_id, p.event_name, p.drive_link, COUNT(pf.id) as face_cache_count
                    FROM scanned_photos p
                    LEFT JOIN scanned_photo_faces pf ON p.photo_id = pf.photo_id
                    {where_clause}
                    GROUP BY p.photo_id, p.drive_file_id, p.event_name, p.drive_link
                    ORDER BY p.photo_id DESC
                """
                if search_query:
                    where_clause = "WHERE p.photo_id LIKE ? OR p.drive_file_id LIKE ? OR p.event_name LIKE ? OR p.drive_link LIKE ?"
                    if "มีแคช" in search_query or "cache" in search_query.lower():
                        where_clause += " OR pf.id IS NOT NULL"
                    elif "ไม่มีแคช" in search_query or "no cache" in search_query.lower():
                        where_clause += " OR pf.id IS NULL"
                    
                    cursor.execute(query_sql.format(where_clause=where_clause), (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
                else:
                    cursor.execute(query_sql.format(where_clause=""))
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("photo_id", "file_id", "event", "cache_status", "link")
                self.db_tree.column("photo_id", width=90, anchor="center")
                self.db_tree.column("file_id", width=180, anchor="center")
                self.db_tree.column("event", width=150, anchor="w")
                self.db_tree.column("cache_status", width=140, anchor="center")
                self.db_tree.column("link", width=260, anchor="w")
                
                self.db_tree.heading("photo_id", text="Photo ID")
                self.db_tree.heading("file_id", text="Drive File ID")
                self.db_tree.heading("event", text="ชื่องานกิจกรรม")
                self.db_tree.heading("cache_status", text="สถานะแคชใบหน้า")
                self.db_tree.heading("link", text="ลิงก์ไดรฟ์รูปภาพ")
                
                for r in rows:
                    pid, fid, evt, link, c_count = r
                    c_status = f"✅ มีแคชแล้ว ({c_count} หน้า)" if c_count > 0 else "❌ ยังไม่มีแคช (0)"
                    self.db_tree.insert("", "end", values=(pid, fid, evt, c_status, link))
                    
            elif "detected_faces" in selected_table_text and "ครู" in selected_table_text:
                # ตาราง detected_faces (ครู)
                if search_query:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        WHERE (s.role = 'teacher' OR s.role IS NULL OR s.role = '')
                          AND (df.photo_id LIKE ? OR s.name LIKE ? OR CAST(s.id AS TEXT) LIKE ? OR p.event_name LIKE ? OR p.drive_file_id LIKE ?)
                        ORDER BY df.id DESC
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
                else:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        ORDER BY df.id DESC
                    """)
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("match_id", "photo_id", "name", "conf")
                self.db_tree.column("match_id", width=100, anchor="center")
                self.db_tree.column("photo_id", width=120, anchor="center")
                self.db_tree.column("name", width=250, anchor="w")
                self.db_tree.column("conf", width=150, anchor="center")
                
                self.db_tree.heading("match_id", text="Match ID")
                self.db_tree.heading("photo_id", text="Photo ID")
                self.db_tree.heading("name", text="คุณครูที่ตรวจพบ")
                self.db_tree.heading("conf", text="ระดับความเหมือน (Similarity)")
                
                for r in rows:
                    match_id, pid, name, conf = r
                    self.db_tree.insert("", "end", values=(match_id, pid, name, f"{conf*100:.2f}%"))
                    
            elif "detected_faces" in selected_table_text and "นักเรียน" in selected_table_text:
                # ตาราง detected_faces (นักเรียน)
                if search_query:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, s.student_id, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        LEFT JOIN scanned_photos p ON df.photo_id = p.photo_id
                        WHERE s.role = 'student'
                          AND (df.photo_id LIKE ? OR s.name LIKE ? OR s.student_id LIKE ? OR p.event_name LIKE ? OR p.drive_file_id LIKE ?)
                        ORDER BY df.id DESC
                    """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
                else:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, s.student_id, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'student'
                        ORDER BY df.id DESC
                    """)
                rows = cursor.fetchall()
                
                self.db_tree["columns"] = ("match_id", "photo_id", "name", "student_id", "conf")
                self.db_tree.column("match_id", width=80, anchor="center")
                self.db_tree.column("photo_id", width=100, anchor="center")
                self.db_tree.column("name", width=220, anchor="w")
                self.db_tree.column("student_id", width=120, anchor="center")
                self.db_tree.column("conf", width=120, anchor="center")
                
                self.db_tree.heading("match_id", text="Match ID")
                self.db_tree.heading("photo_id", text="Photo ID")
                self.db_tree.heading("name", text="นักเรียนที่ตรวจพบ")
                self.db_tree.heading("student_id", text="รหัสประจำตัว")
                self.db_tree.heading("conf", text="ระดับความเหมือน (Similarity)")
                
                for r in rows:
                    match_id, pid, name, std_id, conf = r
                    self.db_tree.insert("", "end", values=(match_id, pid, name, std_id, f"{conf*100:.2f}%"))
                    
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
        # เสนอชื่อไฟล์ตั้งต้นตามตาราง
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
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f: # utf-8-sig สำหรับเปิดใน Excel ภาษาไทยไม่เพี้ยน
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
                        SELECT s.id, s.name, s.student_id, COUNT(e.id)
                        FROM staff_members s
                        LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                        WHERE s.role = 'student'
                        GROUP BY s.id, s.name, s.student_id
                        ORDER BY s.id ASC
                    """)
                    writer.writerow(["ID", "ชื่อ-นามสกุล นักเรียน", "รหัสประจำตัว", "จำนวนรูปที่บันทึก"])
                    writer.writerows(cursor.fetchall())
                    
                elif "scanned_photos" in selected_table_text:
                    cursor.execute("SELECT photo_id, drive_file_id, event_name, drive_link FROM scanned_photos ORDER BY photo_id ASC")
                    writer.writerow(["Photo ID", "Drive File ID", "ชื่องานกิจกรรม", "ลิงก์ไดรฟ์รูปภาพ"])
                    writer.writerows(cursor.fetchall())
                    
                elif "detected_faces" in selected_table_text and "ครู" in selected_table_text:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'teacher' OR s.role IS NULL OR s.role = ''
                        ORDER BY df.id ASC
                    """)
                    writer.writerow(["Match ID", "Photo ID", "คุณครูที่ตรวจพบ", "ระดับความเหมือน"])
                    writer.writerows(cursor.fetchall())
                    
                elif "detected_faces" in selected_table_text and "นักเรียน" in selected_table_text:
                    cursor.execute("""
                        SELECT df.id, df.photo_id, s.name, s.student_id, df.confidence
                        FROM detected_faces df
                        JOIN staff_members s ON df.staff_id = s.id
                        WHERE s.role = 'student'
                        ORDER BY df.id ASC
                    """)
                    writer.writerow(["Match ID", "Photo ID", "นักเรียนที่ตรวจพบ", "รหัสประจำตัว", "ระดับความเหมือน"])
                    writer.writerows(cursor.fetchall())
                    
            logger.info("CSV Export completed successfully.")
            messagebox.showinfo("ส่งออกสำเร็จ", "ส่งออกไฟล์ข้อมูล CSV เรียบร้อยแล้ว")
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}", exc_info=True)
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถส่งออกไฟล์ได้: {e}")
            conn.close()

    def reset_selected_person_matches(self):
        selected_table_text = self.option_db_table.get()
        # เช็คว่าอยู่ในตารางครูหรือนักเรียนหรือไม่
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
        
        # ป๊อปอัปยืนยัน
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
                # ลบผลการจับคู่ใน detected_faces ของคนๆ นี้ทั้งหมด
                cursor.execute("DELETE FROM detected_faces WHERE staff_id = ?", (staff_id,))
                conn.commit()
                messagebox.showinfo("รีเซ็ตสำเร็จ", f"รีเซ็ตประวัติการจับคู่ของ '{name}' เรียบร้อยแล้ว")
                
                # โหลดตารางข้อมูลใหม่
                self.load_db_table_data(selected_table_text)
                
                # โหลดสถิติหน้าแรกใหม่ด้วย
                self.refresh_dashboard_stats()
            except Exception as e:
                logger.error(f"Error resetting person matching data: {e}", exc_info=True)
                messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการรีเซ็ตข้อมูล: {e}")
            finally:
                conn.close()

    def run_manual_json_sync(self, mode):
        # 1. ตรวจสอบ Authentication
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

        # 2. ตรวจสอบ JSON Folder ID
        json_folder_id = self.entry_json_folder_id.get().strip()
        if not json_folder_id:
            messagebox.showerror("ข้อผิดพลาด", "กรุณาระบุ ID โฟลเดอร์เก็บไฟล์ JSON ดัชนีก่อนซิงค์")
            return

        # 3. กำหนดป้ายแสดงผล
        mode_th = "ทั้งหมด (ครู+นักเรียน)" if mode == "all" else ("เฉพาะครู" if mode == "teachers" else "เฉพาะนักเรียน")
        
        # ปิดปุ่มควบคุมระหว่างทำ sync เพื่อป้องกันการกดซ้อน
        self.btn_sync_json_all.configure(state="disabled")
        self.btn_sync_json_teachers.configure(state="disabled")
        self.btn_sync_json_students.configure(state="disabled")

        def task():
            try:
                logger.info(f"[GDRIVE] Manual JSON Sync: starting sync for mode={mode}")
                sync_data = self.db.get_all_sync_data()
                
                # เรียกใช้งาน sync manager เพื่ออัพเดต JSON ไฟล์
                self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode=mode)
                
                logger.info(f"[GDRIVE] Manual JSON Sync: mode={mode} completed.")
                self.after(0, lambda: messagebox.showinfo("ซิงค์สำเร็จ", f"อัปเดตไฟล์ JSON ดัชนีกลุ่ม {mode_th} ขึ้น Google Drive สำเร็จ!"))
            except Exception as e:
                logger.error(f"[GDRIVE] Manual JSON Sync Error: {e}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาดในการซิงค์ JSON: {e}"))
            finally:
                # เปิดปุ่มให้ใช้งานได้อีกครั้ง
                self.after(0, lambda: [
                    self.btn_sync_json_all.configure(state="normal"),
                    self.btn_sync_json_teachers.configure(state="normal"),
                    self.btn_sync_json_students.configure(state="normal")
                ])

        import threading
        threading.Thread(target=task, daemon=True).start()

    # --- ฟังก์ชันเพิ่มเติมใหม่เพื่อการใช้งานที่ง่ายขึ้น ---

    def save_cropped_face(self, staff_id, original_path, bbox, count, orig_filename=None):
        """ตัดส่วนใบหน้าคุณครูแล้วเก็บเป็นไฟล์ย่อยลงในแอป ป้องกันไฟล์ต้นฉบับหาย"""
        try:
            # อ่านภาพดึงข้อมูลไบต์แบบรองรับภาษาไทย
            img = cv2.imdecode(np.fromfile(original_path, dtype=np.uint8), cv2.IMREAD_COLOR)
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
        """แสดงรูปภาพย่อยของคุณครูที่เลือกในรูปแบบตารางกริด (Grid)"""
        # ล้างข้อมูลเก่า
        for widget in self.thumbs_scrollable.winfo_children():
            widget.destroy()

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
        rows = cursor.fetchall()
        conn.close()

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
        """เลือกรูปภาพพรีวิวใบหน้าย่อยเพื่อดำเนินการลบ"""
        # รีเซ็ตสีพื้นหลังขอบตัวก่อนหน้าที่เลือกไว้
        if hasattr(self, "selected_thumb_widget") and self.selected_thumb_widget:
            try:
                self.selected_thumb_widget.configure(fg_color="transparent", border_width=0, border_color="transparent")
            except Exception:
                pass
                
        self.selected_thumb_path = path
        self.selected_thumb_widget = frame_widget
        
        # แสดงไฮไลต์สีแดงรอบขอบเฟรม
        frame_widget.configure(fg_color="transparent", border_width=3, border_color="#FF5252")
        self.btn_delete_photo.configure(state="normal")
        logger.info(f"[UI] Selected face template image: {os.path.basename(path)}")

    def delete_selected_photo(self):
        """ทำการลบรูปภาพใบหน้าย่อยคุณครูที่แอดมินเลือกจากระบบ"""
        if not hasattr(self, "selected_thumb_path") or not self.selected_thumb_path:
            return
            
        confirm = messagebox.askyesno(
            "ยืนยันการลบรูปภาพ", 
            "คุณแน่ใจหรือไม่ว่าต้องการลบรูปภาพใบหน้านี้ออกจากฐานข้อมูลระบบ?\n(การกระทำนี้จะลบการเรียนรู้เวกเตอร์ใบหน้าของรูปนี้ออก)"
        )
        if not confirm:
            return
            
        path_to_delete = self.selected_thumb_path
        
        try:
            # 1. ลบจาก SQLite
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM staff_embeddings WHERE image_path = ?", (path_to_delete,))
            conn.commit()
            conn.close()
            logger.info(f"[DATABASE] Deleted embedding row from SQLite: {os.path.basename(path_to_delete)}")
            
            # 2. ลบรูปย่อยที่บันทึกไว้ในโฟลเดอร์แอปย่อยจริงออก
            if os.path.exists(path_to_delete):
                os.remove(path_to_delete)
                logger.info(f"[SYSTEM] Deleted cropped face file from disk: {path_to_delete}")
                
            messagebox.showinfo("ลบสำเร็จ", "ลบรูปภาพใบหน้าและเวกเตอร์ของภาพนี้ออกจากระบบเรียบร้อยแล้ว")
            
            # 3. โหลดและรีเฟรชข้อมูลรายชื่อครูและรูปพรีวิวใหม่
            self.load_staff_list()
            self.show_staff_thumbnails(self.selected_staff_id)
            self.btn_delete_photo.configure(state="disabled")
            self.selected_thumb_path = None
            self.selected_thumb_widget = None
        except Exception as e:
            logger.error(f"[SYSTEM] Error deleting photo: {e}", exc_info=True)
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถลบภาพได้: {e}")

    def batch_import_teachers(self):
        """เลือกโฟลเดอร์หลักแล้วนำเข้าโฟลเดอร์ย่อยเป็นรายชื่อครูและรูปภาพย่อยแบบอัตโนมัติ"""
        main_dir = filedialog.askdirectory(title="เลือกโฟลเดอร์หลักที่มีโฟลเดอร์ย่อยเป็นชื่อครู")
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
        logger.info(f"[INIT] เริ่มนำเข้าข้อมูลใบหน้าครูอัตโนมัติแบบกลุ่ม (Batch Import) จาก: {main_dir}")
        
        try:
            # 1. โหลดระบบวิเคราะห์ใบหน้า AI (ป้องกัน NoneType)
            if self.analyzer is None:
                use_gpu = self.chk_use_gpu.get()
                self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if not self.analyzer.initialize():
                logger.error("[SYSTEM] ไม่สามารถเริ่มระบบ InsightFace AI ได้ การนำเข้าล้มเหลว")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", "ไม่สามารถเปิดระบบตรวจจับใบหน้า AI ได้"))
                return
                
            # 2. กวาดหาโฟลเดอร์ย่อยทั้งหมด
            subdirs = []
            for item in os.listdir(main_dir):
                full_path = os.path.join(main_dir, item)
                if os.path.isdir(full_path):
                    subdirs.append((item, full_path))
                    
            if not subdirs:
                logger.warning(f"[UI] ไม่พบโฟลเดอร์ย่อยในโฟลเดอร์หลักที่เลือก: {main_dir}")
                self.after(0, lambda: messagebox.showwarning("คำเตือน", "ไม่พบโฟลเดอร์ย่อย (โฟลเดอร์ครู) ในโฟลเดอร์ที่เลือก"))
                return
                
            logger.info(f"[SYSTEM] ตรวจพบข้อมูลโฟลเดอร์ครูทั้งหมด {len(subdirs)} คน")
            
            import rawpy
            import cv2
            
            total_imported_photos = 0
            
            for idx, (teacher_name, path) in enumerate(subdirs):
                logger.info(f"[INIT] ({idx+1}/{len(subdirs)}) กำลังตรวจสอบโฟลเดอร์ครู: '{teacher_name}'")
                
                # ตรวจเช็คหรือสร้างชื่อคนในระบบ SQLite (หากชื่อซ้ำจะได้ ID ของคนเดิม)
                staff_id = self.db.register_staff_member(teacher_name)
                
                # ดึงรายชื่อภาพที่บันทึกไว้แล้วทั้งหมดสำหรับครูคนนี้ เพื่อนำมาตรวจไฟล์ซ้ำ
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT image_path FROM staff_embeddings WHERE staff_id = ?", (staff_id,))
                existing_paths = [row[0] for row in cursor.fetchall()]
                conn.close()
                
                # กวาดหาภาพถ่ายทั้งหมดในโฟลเดอร์ครูคนนั้น (อัปเดต v1.7.8: ข้ามไฟล์ RAW)
                valid_extensions = (".jpg", ".jpeg", ".png", ".webp")
                files = [f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in valid_extensions]
                
                if not files:
                    logger.warning(f"[UI] โฟลเดอร์ของ '{teacher_name}' ไม่มีรูปภาพที่เหมาะสม")
                    continue
                    
                logger.info(f"[SCAN_INFO] พบรูปภาพ {len(files)} รูปในโฟลเดอร์ครู '{teacher_name}'")
                
                for f_idx, file in enumerate(files):
                    # ตรวจสอบว่าไฟล์ชื่อนี้เคยถูกนำเข้าแล้วหรือยัง
                    already_imported = False
                    file_base = os.path.splitext(file)[0].lower() # ดึงชื่อไฟล์ตัดนามสกุลออก รองรับการแปลง CR2 -> JPG
                    for ep in existing_paths:
                        ep_base = os.path.basename(ep).lower()
                        # เช็คว่ามีคำว่า _ชื่อไฟล์ดั้งเดิม. ฝังอยู่ในพาธไฟล์ย่อยหรือไม่
                        if f"_{file_base}." in ep_base or ep_base.endswith(f"_{file_base}"):
                            already_imported = True
                            break
                            
                    if already_imported:
                        logger.info(f"[SYSTEM] รูปภาพ '{file}' ของครู '{teacher_name}' เคยนำเข้าแล้ว -> ข้ามการทำงาน")
                        continue
                        
                    filepath = os.path.join(path, file)
                    logger.info(f"[FACE_AI] ({f_idx+1}/{len(files)}) กำลังตรวจหาพิกัดใบหน้าจาก: {file}")
                    
                    process_path = filepath
                            
                    try:
                        # ค้นหาเวกเตอร์ใบหน้าในรูปภาพ
                        faces_in_img = self.analyzer.detect_and_extract_faces(process_path)
                        
                        if not faces_in_img:
                            logger.warning(f"[FACE_AI] ไม่พบใบหน้าเด่นชัดในรูปภาพ: {file}")
                            continue
                            
                        # ดึงใบหน้าที่มีคะแนนดีที่สุด (Best face in photo)
                        best_face = max(faces_in_img, key=lambda x: x["det_score"])
                        
                        # ครอปตัดใบหน้า และบันทึกรูปภาพใบหน้าย่อยลงเครื่อง
                        cropped_path = self.save_cropped_face(
                            staff_id=staff_id,
                            original_path=process_path,
                            bbox=best_face["bbox"],
                            count=len(existing_paths) + total_imported_photos,
                            orig_filename=file
                        )
                        
                        # บันทึกข้อมูลลง SQLite Database
                        self.db.add_staff_embedding(
                            staff_id=staff_id,
                            image_path=cropped_path,
                            embedding_vector=best_face["embedding"]
                        )
                        
                        total_imported_photos += 1
                        logger.info(f"[MATCH_OK] ลงทะเบียนใบหน้าครู '{teacher_name}' จากรูป {file} สำเร็จ!")
                        
                    except Exception as img_err:
                        logger.error(f"[FACE_AI] เกิดข้อผิดพลาดขณะประมวลผลภาพ {file}: {img_err}")
                                
            # 3. นำเข้าจบกระบวนการ -> รีเฟรชหน้า GUI เธรดหลัก
            logger.info(f"[SYSTEM] นำเข้าครูและใบหน้าทั้งหมดเสร็จสิ้น รวมลงทะเบียน {total_imported_photos} รูป")
            self.after(0, lambda: messagebox.showinfo("นำเข้าสำเร็จ", f"นำเข้าข้อมูลครูแบบกลุ่มเสร็จสิ้น!\nลงทะเบียนใบหน้าสำเร็จทั้งหมด {total_imported_photos} ภาพ"))
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

    # ==================== (6) หน้าเฟรมคำขอลบรูปภาพจากไฟล์ JSON (v1.6.7) ====================
    def setup_delete_req_ui(self):
        self.frame_delete_req.grid_columnconfigure(0, weight=1)
        self.frame_delete_req.grid_rowconfigure(3, weight=1)

        # หัวข้อหลัก
        lbl_title = ctk.CTkLabel(
            self.frame_delete_req, text="ระบบจัดการคำขอลบรูปภาพกิจกรรม", 
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        lbl_title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        # แถวป้อนไฟล์ JSON คำขอบนคลาวด์ (Google Drive)
        gdrive_file_frame = ctk.CTkFrame(self.frame_delete_req, fg_color="transparent")
        gdrive_file_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        gdrive_file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            gdrive_file_frame, text="ไฟล์ JSON คำขอลบบน Google Drive:", 
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD"
        ).grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.entry_delete_req_file_id = ctk.CTkEntry(
            gdrive_file_frame, placeholder_text="ระบุ ID ไฟล์ delete_request.json บน Google Drive ของท่าน"
        )
        self.entry_delete_req_file_id.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        btn_pick_file = ctk.CTkButton(
            gdrive_file_frame, text="🔍 เลือกไฟล์ JSON", width=120,
            fg_color="#1F3A60", hover_color="#20334F",
            command=lambda: self.open_google_picker("delete_req_json")
        )
        btn_pick_file.grid(row=0, column=2, padx=(0, 5), sticky="e")

        btn_open_file = ctk.CTkButton(
            gdrive_file_frame, text="🌐 เปิดดูไฟล์", width=100,
            fg_color="#E67E22", hover_color="#D35400", text_color="white",
            command=self.open_delete_req_file_in_browser
        )
        btn_open_file.grid(row=0, column=3, sticky="e")

        # โซนปุ่มควบคุมด้านล่าง (แถวที่ 2)
        action_bar = ctk.CTkFrame(self.frame_delete_req, fg_color="transparent")
        action_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        btn_refresh = ctk.CTkButton(
            action_bar, text="🔄 รีเฟรชตารางคำขอ", 
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.load_delete_requests_table
        )
        btn_refresh.pack(side="left", padx=(0, 10))

        self.btn_approve_delete = ctk.CTkButton(
            action_bar, text="🗑️ อนุมัติการลบรูปภาพที่เลือก", 
            fg_color="#E74C3C", hover_color="#C0392B", text_color="white",
            command=self.approve_delete_requests
        )
        self.btn_approve_delete.pack(side="left")

        # แถบสลับหน้า Pagination คำขอลบ
        self.btn_next_delete_req = ctk.CTkButton(
            action_bar, text="▶️", width=36,
            fg_color="#1F3A60", hover_color="#20334F",
            command=self.next_delete_req_page
        )
        self.btn_next_delete_req.pack(side="right", padx=(5, 0))

        self.lbl_delete_req_page = ctk.CTkLabel(
            action_bar, text="หน้า 1/1",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#A2B5CD"
        )
        self.lbl_delete_req_page.pack(side="right", padx=10)

        self.btn_prev_delete_req = ctk.CTkButton(
            action_bar, text="◀️", width=36,
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
            font=ctk.CTkFont(size=12), text_color="#A2B5CD"
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

if __name__ == "__main__":
    # บังคับระบบควบคุม Windows Scaling เพื่อความคมชัดของวิดเจ็ต
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    app = FaceSearchApp()
    app.mainloop()
