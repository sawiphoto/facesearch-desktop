import os
import time
import json
import logging
import threading
import concurrent.futures
import queue
import traceback
import schedule
import cv2
import numpy as np
import collections
from datetime import datetime
import re
from face_analyzer import decode_image_bytes, read_image_file, get_project_root
from db_manager import RAW_EXTENSIONS_MAP, get_camera_brand_from_filename
from gdrive_sync import is_generic_folder_name

logger = logging.getLogger("FaceSearchApp")

# เปิดใช้งานโหมด Debug การซิงค์นักเรียน
DEBUG_SYNC_MODE = True


class ScanSessionTracker:
    """
    คลาสติดตามสถิติการสแกนภาพถ่ายในรอบการทำงานแบบ Real-time และสรุปผลรายงาน (v6.24)
    บันทึกรายชื่อโฟลเดอร์, จำนวนรูป, Top 10 บุคคลที่พบ, ปัญหา และส่งออกเป็น Markdown & JSON
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = datetime.now()
        self.end_time = None
        self.duration_seconds = 0
        self.stopped_by_user = False
        self.json_sync_completed = False
        self.current_folder = ""
        self.folders = {}
        self.person_counts = collections.Counter()
        self.skipped_files = []
        self.total_faces_detected = 0
        self.total_ai_photos = 0
        self.total_raw_photos = 0
        self.total_skipped_photos = 0

    def record_folder_start(self, folder_name, year_name, total_files):
        self.current_folder = folder_name
        if folder_name not in self.folders:
            self.folders[folder_name] = {
                "year": year_name,
                "ai_count": 0,
                "raw_count": 0,
                "skipped_count": 0,
                "total_files": total_files,
                "status": "กำลังสแกน (In Progress)"
            }

    def record_raw_photo(self, folder_name, f_name, f_id):
        self.total_raw_photos += 1
        if folder_name in self.folders:
            self.folders[folder_name]["raw_count"] += 1

    def record_ai_photo(self, folder_name, f_name, f_id, faces_count, match_names):
        self.total_ai_photos += 1
        self.total_faces_detected += faces_count
        if folder_name in self.folders:
            self.folders[folder_name]["ai_count"] += 1
        if match_names:
            for name in set(match_names):
                self.person_counts[name] += 1

    def record_skipped(self, folder_name, f_name, f_id, reason, f_link=""):
        self.total_skipped_photos += 1
        if folder_name in self.folders:
            self.folders[folder_name]["skipped_count"] += 1
        self.skipped_files.append({
            "folder": folder_name,
            "file_name": f_name,
            "file_id": f_id,
            "reason": str(reason),
            "drive_link": f_link
        })

    def record_folder_finish(self, folder_name, is_completed):
        if folder_name in self.folders:
            self.folders[folder_name]["status"] = "เสร็จสมบูรณ์ 100%" if is_completed else "สแกนบางส่วน (Partial)"

    def has_scanned_items(self):
        return (self.total_ai_photos > 0 or self.total_raw_photos > 0 or 
                self.total_skipped_photos > 0 or len(self.folders) > 0)

    def finalize(self, stopped_by_user=False, json_synced=True):
        self.end_time = datetime.now()
        self.stopped_by_user = stopped_by_user
        self.json_sync_completed = json_synced
        self.duration_seconds = max(1, int((self.end_time - self.start_time).total_seconds()))
        return self.get_summary()

    def get_summary(self):
        end_time_val = self.end_time or datetime.now()
        duration = self.duration_seconds if self.duration_seconds > 0 else max(1, int((end_time_val - self.start_time).total_seconds()))
        mins, secs = divmod(duration, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            duration_str = f"{hours} ชม. {mins} นาที {secs} วิ"
        elif mins > 0:
            duration_str = f"{mins} นาที {secs} วิ"
        else:
            duration_str = f"{secs} วินาที"

        top_10 = self.person_counts.most_common(10)
        top_10_list = [{"rank": idx + 1, "name": name, "count": count} for idx, (name, count) in enumerate(top_10)]
        total_all_images = self.total_ai_photos + self.total_raw_photos + self.total_skipped_photos

        return {
            "start_time_str": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time_str": end_time_val.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_str": duration_str,
            "duration_seconds": duration,
            "stopped_by_user": self.stopped_by_user,
            "json_sync_completed": self.json_sync_completed,
            "total_folders": len(self.folders),
            "total_all_images": total_all_images,
            "total_ai_photos": self.total_ai_photos,
            "total_raw_photos": self.total_raw_photos,
            "total_skipped_photos": self.total_skipped_photos,
            "total_faces_detected": self.total_faces_detected,
            "total_matched_appearances": sum(self.person_counts.values()),
            "folders_breakdown": self.folders,
            "top_10_people": top_10_list,
            "skipped_files": self.skipped_files
        }

    def generate_markdown(self, summary=None):
        if summary is None:
            summary = self.get_summary()

        status_badge = "🛑 หยุดทำงานตามคำร้องขอ (Stop Requested)" if summary["stopped_by_user"] else "✅ เสร็จสมบูรณ์ (Completed)"
        drive_badge = "✅ อัปเดต Drive JSON สำเร็จเรียบร้อยแล้ว" if summary["json_sync_completed"] else "⚠️ ยังไม่ได้อัปเดต Drive JSON"

        lines = [
            "# 📊 รายงานสรุปผลการสแกนภาพถ่ายกิจกรรม (Scan Session Summary Report)",
            "",
            f"**วัน-เวลาเริ่มสแกน:** {summary['start_time_str']}  ",
            f"**วัน-เวลาสิ้นสุด:** {summary['end_time_str']}  ",
            f"**ระยะเวลาทั้งหมด:** {summary['duration_str']}  ",
            f"**สถานะการทำงาน:** {status_badge}  ",
            f"**สถานะ Drive JSON:** {drive_badge}  ",
            "",
            "---",
            "",
            "## 📈 ภาพรวมตัวเลขสถิติ (Executive Summary)",
            "",
            "| หมวดหมู่สถิติ | จำนวน | หน่วย |",
            "| :--- | :---: | :---: |",
            f"| 📁 โฟลเดอร์ที่สแกน | **{summary['total_folders']}** | โฟลเดอร์ |",
            f"| 📸 ภาพที่ประมวลผลทั้งหมด | **{summary['total_all_images']}** | ภาพ |",
            f"| 🤖 ภาพที่สแกนด้วย AI (InsightFace) | **{summary['total_ai_photos']}** | ภาพ |",
            f"| 📷 ภาพถ่ายไฟล์ดิบ RAW จากกล้อง | **{summary['total_raw_photos']}** | ภาพ |",
            f"| ⚠️ ภาพที่มีปัญหา / ข้าม | **{summary['total_skipped_photos']}** | ภาพ |",
            f"| 👤 จำนวนใบหน้าที่ตรวจพบสะสม | **{summary['total_faces_detected']}** | ใบหน้า |",
            f"| 🎯 ตรวจพบบุคคลในระบบสะสม | **{summary['total_matched_appearances']}** | ครั้ง |",
            "",
            "---",
            "",
            "## 📁 รายละเอียดโฟลเดอร์ที่สแกนไป (Folders Breakdown)",
            "",
            "| ลำดับ | ชื่องาน / โฟลเดอร์ | ปีการศึกษา | สำเร็จ (AI) | ไฟล์ RAW | ปัญหา | รวม | สถานะ |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
        ]

        if summary["folders_breakdown"]:
            for idx, (f_name, f_data) in enumerate(summary["folders_breakdown"].items(), start=1):
                total_f = f_data.get("ai_count", 0) + f_data.get("raw_count", 0) + f_data.get("skipped_count", 0)
                lines.append(
                    f"| {idx} | {f_name} | {f_data.get('year', '-')} | "
                    f"{f_data.get('ai_count', 0)} | {f_data.get('raw_count', 0)} | "
                    f"{f_data.get('skipped_count', 0)} | {total_f} | {f_data.get('status', '-')} |"
                )
        else:
            lines.append("| - | *ไม่พบข้อมูลโฟลเดอร์* | - | 0 | 0 | 0 | 0 | - |")

        lines.extend([
            "",
            "---",
            "",
            "## 🏆 ภาพใครปรากฏเยอะสุด Top 10 (Most Recognized People)",
            "",
            "| อันดับ | ชื่อ-นามสกุล บุคลากร / นักเรียน | จำนวนภาพถ่ายที่พบ |",
            "| :---: | :--- | :---: |"
        ])

        if summary["top_10_people"]:
            for item in summary["top_10_people"]:
                lines.append(f"| {item['rank']} | **{item['name']}** | {item['count']} ภาพ |")
        else:
            lines.append("| - | *ไม่พบบุคคลที่จับคู่ได้ในรอบนี้* | 0 ภาพ |")

        lines.extend([
            "",
            "---",
            "",
            "## ⚠️ รายการภาพที่มีปัญหา / ข้าม (Issues & Skipped Files)",
            ""
        ])

        if summary["skipped_files"]:
            lines.extend([
                "| ลำดับ | โฟลเดอร์ | ชื่อไฟล์ภาพ | สาเหตุที่เกิดปัญหา | รหัส Drive ID |",
                "| :---: | :--- | :--- | :--- | :--- |"
            ])
            for idx, item in enumerate(summary["skipped_files"], start=1):
                lines.append(
                    f"| {idx} | {item.get('folder', '-')} | {item.get('file_name', '-')} | "
                    f"{item.get('reason', '-')} | `{item.get('file_id', '-')}` |"
                )
        else:
            lines.append("✅ **ไม่พบภาพที่มีปัญหาในรอบการสแกนนี้ (ประมวลผลสมบูรณ์ 100%)**")

        lines.append("")
        return "\n".join(lines)

    def save_report_to_disk(self, project_root):
        if self.end_time is None:
            self.finalize()
        summary = self.get_summary()
        report_dir = os.path.join(project_root, "report_summary")
        os.makedirs(report_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_filename = f"scan_report_{timestamp_str}.md"
        json_filename = f"scan_report_{timestamp_str}.json"

        md_path = os.path.join(report_dir, md_filename)
        json_path = os.path.join(report_dir, json_filename)

        md_content = self.generate_markdown(summary)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(f"[REPORT] Saved scan summary report to: {md_path}")
        return md_path


class SchedulerTask:
    def __init__(self, db_manager, sync_manager, face_analyzer, app_gui):
        self.db = db_manager
        self.sync_manager = sync_manager
        self.analyzer = face_analyzer
        self.app_gui = app_gui
        self.is_running = False
        self.stop_requested = False
        self._stopped_json_synced = False
        self.tracker = ScanSessionTracker()
        self.gpu_lock = threading.Lock()
        
        # Schedule midnight trigger
        schedule.every().day.at("00:00").do(self.run_scheduled_tasks)
        
        # Start background thread
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()

    def _safe_sync_json_on_stop(self):
        """ช่วยอัปเดตไฟล์ JSON บน Drive เมื่อหยุดทำงาน โดยป้องกันการรันซ้ำซ้อน (v6.24)"""
        if not self._stopped_json_synced:
            self._sync_all_json_to_drive()
            self._stopped_json_synced = True

    def request_stop(self):
        if self.is_running:
            self.stop_requested = True
            logger.info("[SCHEDULE] ร้องขอการหยุดทำงานชั่วคราว... กำลังสรุปผลในรอบปัจจุบัน")

    def _scheduler_loop(self):
        while True:
            schedule.run_pending()
            time.sleep(60)
            
    def run_scheduled_tasks_manual(self):
        if self.is_running:
            logger.info("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self.run_scheduled_tasks, daemon=True).start()

    def run_task_2_manual(self):
        if self.is_running:
            logger.info("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self._run_task_2_only, daemon=True).start()

    def _run_task_2_only(self):
        self.is_running = True
        self.stop_requested = False
        try:
            logger.info("="*50)
            logger.info("[SCHEDULE] เริ่มทำงาน Task 2 เฉพาะกิจ (v4.0 - Bulk Sync)")
            if not self.sync_manager.connected:
                self.sync_manager.connect()
            self._ensure_analyzer()
            self._task_2_sync_new_students_bulk()
            self._sync_all_json_to_drive()
            from datetime import datetime, timedelta, timezone
            bkk_tz = timezone(timedelta(hours=7))
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[SCHEDULE] Task 2 เสร็จสมบูรณ์ ({bkk_time} BKK)")
            logger.info("="*50)
        except Exception as e:
            logger.error(f"[SCHEDULE Error] {e}", exc_info=True)
        finally:
            self.is_running = False
            self.stop_requested = False

    def run_task_3_manual(self):
        if self.is_running:
            logger.info("[SCHEDULE] Tasks are already running.")
            return
        threading.Thread(target=self._run_task_3_only, daemon=True).start()

    def _run_task_3_only(self):
        self.is_running = True
        self.stop_requested = False
        try:
            logger.info("="*50)
            logger.info("[SCHEDULE] เริ่มทำงาน Task 3 เฉพาะกิจ (v5.30 - Sync New Teachers & Retroactive Matching)")
            if not self.sync_manager.connected:
                self.sync_manager.connect()
            self._ensure_analyzer()
            self._task_3_sync_new_teachers_bulk()
            # ปิดท้ายด้วยการซิงค์ไฟล์ JSON ดัชนีทั้งหมดขึ้น Drive เสมอ (v6.46)
            self._sync_all_json_to_drive()
            from datetime import datetime, timedelta, timezone
            bkk_tz = timezone(timedelta(hours=7))
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[SCHEDULE] Task 3 เสร็จสมบูรณ์ ({bkk_time} BKK)")
            logger.info("="*50)
        except Exception as e:
            logger.error(f"[SCHEDULE Error] {e}", exc_info=True)
        finally:
            self.is_running = False
            self.stop_requested = False

    def run_scheduled_tasks(self):
        if self.is_running:
            return
            
        self.is_running = True
        self.stop_requested = False
        self._stopped_json_synced = False
        if hasattr(self, 'tracker') and self.tracker:
            self.tracker.reset()

        try:
            logger.info("="*50)
            logger.info("[SCHEDULE] เริ่มทำงาน Task อัตโนมัติ (v6.24 - High Speed & Report Summary)")
            logger.info("="*50)
            
            # Ensure Google API is connected
            if not self.sync_manager.connected:
                self.sync_manager.connect()
                
            # Ensure Analyzer is initialized
            self._ensure_analyzer()
            
            # Task 1: Scan New Photos (High-Speed)
            self._task_1_scan_new_photos_fast()
            
            # 1. Sync JSON บน Drive ทันทีหลังจบ Task 1 (ก่อนขึ้น Task 2)
            if not self._stopped_json_synced:
                logger.info("[SCHEDULE] 📤 กำลังอัปเดตไฟล์ JSON 3 โฟลเดอร์หลักขึ้น Google Drive หลังจบ Task 1...")
                self._sync_all_json_to_drive()
                self._stopped_json_synced = True

            if not self.stop_requested:
                # Task 2: Sync New Students (Bulk)
                self._task_2_sync_new_students_bulk()

            if not self.stop_requested:
                # Task 3: Sync New Teachers (Bulk)
                self._task_3_sync_new_teachers_bulk()
            else:
                logger.info("[SCHEDULE] 🛑 มีคำร้องขอหยุดทำงาน (Stop Requested) กำลังบันทึกไฟล์ JSON ปิดท้าย...")
                self._safe_sync_json_on_stop()

            # Final Consistency Sync across all tasks (v6.46)
            if not self.stop_requested:
                logger.info("[SCHEDULE] 📤 กำลังอัปเดตไฟล์ JSON ดัชนีทุกประเภทขึ้น Google Drive (Final Consistency Sync v6.46)...")
                self._sync_all_json_to_drive()
            
            from datetime import datetime, timedelta, timezone
            bkk_tz = timezone(timedelta(hours=7))
            bkk_time = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[SCHEDULE] กระบวนการทำงานอัตโนมัติเสร็จสมบูรณ์ ({bkk_time} BKK)")
            logger.info("="*50)
            
        except Exception as e:
            logger.error(f"[SCHEDULE] เกิดข้อผิดพลาดระหว่างทำงาน: {e}", exc_info=True)
            if self.stop_requested:
                logger.info("[SCHEDULE] 🛑 ปิดท้ายด้วยการอัปเดตไฟล์ JSON ขึ้น Google Drive...")
                self._safe_sync_json_on_stop()
        finally:
            was_stopped = self.stop_requested
            if was_stopped:
                self._safe_sync_json_on_stop()

            # สรุปผลและส่งออกรายงาน พร้อมแจ้งเตือน Popup สรุปผลบน GUI (v6.24)
            if hasattr(self, 'tracker') and self.tracker and (self.tracker.has_scanned_items() or was_stopped):
                try:
                    summary = self.tracker.finalize(stopped_by_user=was_stopped, json_synced=self._stopped_json_synced)
                    project_root = get_project_root()
                    saved_path = self.tracker.save_report_to_disk(project_root)
                    if hasattr(self.app_gui, 'show_scan_report_popup'):
                        self.app_gui.after(0, lambda s=summary, p=saved_path: self.app_gui.show_scan_report_popup(s, p))
                except Exception as rep_err:
                    logger.error(f"[SCHEDULE] ❌ Error generating scan report summary: {rep_err}", exc_info=True)

            self.is_running = False
            self.stop_requested = False
            self._stopped_json_synced = False

    def _sync_all_json_to_drive(self):
        """ช่วยอัปเดตไฟล์ JSON สรุปย่อ 3 ไฟล์ขึ้น Google Drive (ทำงานเหมือนปุ่ม GUI เป๊ะ)"""
        try:
            sync_data = self.db.get_all_sync_data() if hasattr(self, 'db') and self.db else None
            json_folder_id = self.app_gui.entry_json_folder_id.get().strip() if hasattr(self, 'app_gui') and hasattr(self.app_gui, 'entry_json_folder_id') else ""
            if not json_folder_id:
                json_folder_id = "1X0vHO47LMVSxp5wyVQEN7xU6A7lAUq0L"
            self.sync_manager.update_json_indexes_on_drive(sync_data, json_folder_id, scan_mode="all")
            logger.info("[SCHEDULE] ✅ อัปเดตไฟล์ JSON สรุปย่อขึ้น Google Drive สำเร็จเรียบร้อยแล้ว")
        except Exception as e:
            logger.error(f"[SCHEDULE] Error updating JSON to drive: {e}")

    def _get_unscanned_subfolder(self, root_folder_id, force_rescan=False, scanned_in_this_run=None):
        """ค้นหาโฟลเดอร์ย่อยที่มีรูปภาพและต้องการสแกน (หรือ Re-scan)"""
        if scanned_in_this_run is None:
            scanned_in_this_run = set()

        query_dirs = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subdirs = []
        page_token = None
        while True:
            if self.stop_requested: break
            try:
                results = self.sync_manager.drive_service.files().list(
                    q=query_dirs, fields="nextPageToken, files(id, name)", pageToken=page_token, pageSize=100
                ).execute()
                subdirs.extend(results.get("files", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                logger.error(f"Error fetching subdirs for {root_folder_id}: {e}")
                break

        # ถ้า root_folder_id ไม่มีโฟลเดอร์ย่อย ให้คืนค่า root_folder เองหากมีรูป (พร้อมดึงชื่อจริงจาก Drive)
        if not subdirs:
            real_name = "TargetFolder"
            try:
                if hasattr(self.sync_manager, "drive_service") and self.sync_manager.drive_service:
                    f_meta = self.sync_manager.drive_service.files().get(fileId=root_folder_id, fields="name").execute()
                    if f_meta and f_meta.get("name"):
                        real_name = f_meta["name"]
            except Exception:
                pass
            subdirs = [{"id": root_folder_id, "name": real_name}]
                
        # ดึงรายชื่อไฟล์ที่สแกนแล้วจาก DB (เฉพาะรูปที่สแกนสำเร็จจริง v5.80 + RAW files v6.10)
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT drive_file_id FROM scanned_photos 
                WHERE photo_date NOT LIKE 'ERROR%' AND photo_date NOT LIKE 'SKIPPED%' 
                  AND drive_link NOT LIKE 'ERROR%' AND drive_link NOT LIKE 'SKIPPED%'
                UNION
                SELECT drive_file_id FROM raw_camera_photos
            """)
            scanned_ids = set(row[0] for row in c.fetchall())

        total_subdirs = len(subdirs)
        for idx, subdir in enumerate(subdirs):
            if self.stop_requested: break
            subdir_id = subdir['id']
            if subdir_id in scanned_in_this_run:
                continue

            # พ่น Log แสดงสถานะความก้าวหน้าเรียลไทม์
            logger.info(f"[SCHEDULE] กำลังตรวจสอบโฟลเดอร์ย่อย ({idx+1}/{total_subdirs}): {subdir['name']}")

            # เช็คไฟล์รูปในโฟลเดอร์นี้
            query_files = f"'{subdir_id}' in parents and (mimeType contains 'image/') and trashed = false"
            try:
                f_results = self.sync_manager.drive_service.files().list(
                    q=query_files, fields="files(id)", pageSize=500
                ).execute()
                files = f_results.get("files", [])
                if not files:
                    continue

                if force_rescan:
                    # ถ้าเปิด Re-scan ➔ ส่งคืนโฟลเดอร์นี้ไปทำ Re-scan ทันที
                    return subdir

                # ถ้าปิด Re-scan ➔ ตรวจสอบว่ามีรูปไหนยังไม่อยู่ใน DB หรือไม่
                for f in files:
                    if f['id'] not in scanned_ids:
                        return subdir # เจอโฟลเดอร์มีรูปใหม่ยังไม่เคยสแกน
            except Exception:
                pass
                
        return None # สแกนครบถ้วนหมดแล้ว

    def _task_1_scan_new_folders(self):
        logger.info("[SCHEDULE] กำลังทำ task โฟลเดอร์ใหม่...")
        
        # ดึงการตั้งค่าจาก GUI 100% (Threshold, Re-scan, Fast Rescan, Target matching)
        scan_settings = self.app_gui.get_current_scan_settings() if hasattr(self.app_gui, 'get_current_scan_settings') else {}
        rescan = scan_settings.get("rescan", False)
        fast_rescan = scan_settings.get("fast_rescan", False)
        
        target_folders = []
        # 1. เพิ่ม ID โฟลเดอร์กิจกรรมหลักที่ตั้งค่าในช่อง GUI ก่อนเสมอ
        if hasattr(self.app_gui, 'entry_drive_folder_id'):
            gui_folder_id = self.app_gui.entry_drive_folder_id.get().strip()
            if gui_folder_id:
                target_folders.append(("โฟลเดอร์หลักใน GUI", gui_folder_id))

        # 2. เพิ่มโฟลเดอร์ประจำปีการศึกษาจาก config/year_folders.json (v5.60 Dynamic)
        target_folders.extend(self._load_year_folders())
        
        scanned_in_this_run = set()
        for year_name, year_id in target_folders:
            if self.stop_requested: break
            while True:
                if self.stop_requested: break
                red_folder = self._get_unscanned_subfolder(year_id, force_rescan=rescan, scanned_in_this_run=scanned_in_this_run)
                if not red_folder or red_folder['id'] in scanned_in_this_run:
                    break
                scanned_in_this_run.add(red_folder['id'])
                    
                logger.info(f"[SCHEDULE] เริ่มทำการสแกนรูปภาพในโฟลเดอร์: {red_folder['name']}")
                # เรียกใช้กระบวนการสแกนของระบบ (ใช้ background scan logic)
                try:
                    if hasattr(self.app_gui, 'process_scanning_headless'):
                        success = self.app_gui.process_scanning_headless([red_folder['id']], folder_name=red_folder['name'])
                        if not success:
                            logger.error(f"[SCHEDULE] Error: process_scanning_headless aborted for {red_folder['name']}")
                            break # หลุดจาก while เพื่อป้องกัน infinite loop
                        logger.info(f"[SCHEDULE] สแกนโฟลเดอร์ {red_folder['name']} เสร็จสิ้นเรียบร้อย")
                    else:
                        logger.error(f"[SCHEDULE] Error: app_gui does not have process_scanning_headless")
                        break
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error scanning {red_folder['name']}: {e}")
                    break # หลุดจาก while เพื่อไม่ให้ค้าง
                    
    def _extract_drive_id(self, url):
        """ดึง ID จากลิงก์ Google Drive (รองรับ /d/, uc?id=, open?id=, และ raw ID)"""
        if not isinstance(url, str):
            return None
        url = url.strip()
        if not url:
            return None
            
        # 1. ลิงก์รูปแบบ /d/ID หรือ /file/d/ID
        if '/d/' in url:
            parts = url.split('/d/')
            if len(parts) > 1:
                return parts[1].split('/')[0].split('?')[0].split('&')[0]
                
        # 2. ลิงก์รูปแบบ id=ID (เช่น uc?id=..., open?id=...)
        if 'id=' in url:
            parts = url.split('id=')
            if len(parts) > 1:
                return parts[1].split('&')[0].split('/')[0].split('?')[0]
                
        # 3. หากเป็น Raw Google Drive File ID ตรงๆ ( alphanumeric ความยาว >= 25)
        if len(url) >= 25 and '/' not in url and '=' not in url:
            return url
            
        return None

    def _ensure_analyzer(self):
        """ตรวจสอบและอ้างอิง FaceAnalyzer AI Model เพียงอินสแตนซ์เดียวทั้งระบบ"""
        if hasattr(self.app_gui, 'analyzer') and self.app_gui.analyzer is not None:
            self.analyzer = self.app_gui.analyzer
            return True

        if self.analyzer is not None:
            return True

        try:
            logger.info("[SCHEDULE] กำลังโหลด FaceAnalyzer AI Model...")
            from face_analyzer import FaceAnalyzer
            use_gpu = False
            if hasattr(self.app_gui, 'chk_use_gpu'):
                try:
                    use_gpu = bool(self.app_gui.chk_use_gpu.get())
                except Exception:
                    use_gpu = False
            self.analyzer = FaceAnalyzer(use_gpu=use_gpu)
            if self.analyzer.initialize():
                logger.info("[SCHEDULE] โหลด FaceAnalyzer AI Model สำเร็จ")
                if hasattr(self.app_gui, 'analyzer'):
                    self.app_gui.analyzer = self.analyzer
                return True
            else:
                logger.error("[SCHEDULE] ไม่สามารถสร้าง FaceAnalyzer AI Model ได้")
                return False
        except Exception as e:
            logger.error(f"[SCHEDULE] เกิดข้อผิดพลาดในการสร้าง FaceAnalyzer: {e}", exc_info=True)
            return False

    def debug_compare_sheet_vs_db(self, data, col_id, col_name, col_img1, col_img2, col_img3):
        """โหมดสืบสวน: นำข้อมูลจาก Sheet มาเทียบกับ DB แล้วพ่น Log ออกมาทีเดียว"""
        logger.info("[DEBUG] ================= เริ่มโหมดตรวจสอบ Sheet vs DB =================")
        
        not_in_db = []
        no_photo_in_sheet_count = 0
        mismatched_data = []
        invalid_urls = []
        missing_photos_in_db = []
        db_orphans = []
        
        total_in_sheet = 0
        sheet_student_ids = set()
        
        # 1. เช็คข้อมูลจาก Sheet -> DB
        for row in data:
            std_id = str(row.get(col_id, "")).strip()
            if not std_id:
                continue
                
            total_in_sheet += 1
            sheet_student_ids.add(std_id)
            
            std_name = str(row.get(col_name, "")).strip()
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, ""))]
            valid_imgs = [img for img in imgs if img.strip()]
            
            # ตรวจสอบลิงก์ที่ผิดปกติ
            for img in valid_imgs:
                if "drive.google.com" not in img and "google.com" not in img:
                    invalid_urls.append((std_id, std_name, img))
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT id, name FROM staff_members WHERE student_id = ? AND role = 'student'", (std_id,))
                db_row = c.fetchone()
                
                if not db_row:
                    if len(valid_imgs) == 0:
                        no_photo_in_sheet_count += 1
                    else:
                        not_in_db.append(f"{std_name} ({std_id}) - มีรูปใน Sheet {len(valid_imgs)} รูป")
                else:
                    staff_id_check = db_row[0]
                    db_name = db_row[1]
                    
                    if db_name != std_name:
                        mismatched_data.append(f"{std_id}: Sheet(Name='{std_name}') vs DB(Name='{db_name}')")
                    
                    # เช็ครูปภาพ
                    c.execute("SELECT image_path, source_url FROM staff_embeddings WHERE staff_id = ?", (staff_id_check,))
                    existing_records = c.fetchall()
                    existing_file_ids = set()
                    for r in existing_records:
                        img_p, src_u = r[0] or "", r[1] or ""
                        if "drive:" in img_p:
                            existing_file_ids.add(img_p.replace("drive:", "").strip())
                        ext_p = self._extract_drive_id(img_p)
                        if ext_p: existing_file_ids.add(ext_p)
                        ext_u = self._extract_drive_id(src_u)
                        if ext_u: existing_file_ids.add(ext_u)
                    
                    missing_files = []
                    for img in valid_imgs:
                        f_id = self._extract_drive_id(img)
                        if f_id and f_id not in existing_file_ids:
                            missing_files.append(f_id)
                    
                    if missing_files:
                        missing_photos_in_db.append(f"{std_name} ({std_id}): ขาดหายไป {len(missing_files)} รูป (File ID: {', '.join(missing_files)})")

        # 2. เช็คข้อมูลจาก DB -> Sheet (หาคนที่โดนลบจาก Sheet ไปแล้ว)
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT student_id, name FROM staff_members WHERE role = 'student' AND student_id IS NOT NULL")
            db_students = c.fetchall()
            for r in db_students:
                db_std_id = r[0]
                db_std_name = r[1]
                if db_std_id not in sheet_student_ids:
                    db_orphans.append(f"{db_std_name} ({db_std_id})")

        # พ่น Log สรุปทีเดียว
        logger.info(f"[DEBUG] 📊 สรุปผลการเปรียบเทียบ:")
        logger.info(f"[DEBUG] - พบนักเรียนใน Sheet ทั้งหมด: {total_in_sheet} คน")
        
        if no_photo_in_sheet_count > 0:
            logger.info(f"[DEBUG] - พบนักเรียนที่ยังไม่มีรูปใน Sheet (และยังไม่ถูกบันทึก) ทั้งหมด: {no_photo_in_sheet_count} คน")
            
        logger.info(f"[DEBUG] - พบใน DB แต่ไม่มีใน Sheet (Orphans): {len(db_orphans)} คน")
        if db_orphans:
            logger.info(f"[DEBUG]   รายชื่อ Orphans: {', '.join(db_orphans)}")
            
        logger.info(f"[DEBUG] - พบใน Sheet แต่ไม่มีในฐานข้อมูล (รอลงทะเบียน): {len(not_in_db)} คน")
        if not_in_db:
            for n in not_in_db:
                logger.info(f"[DEBUG]   - {n}")
                
        logger.info(f"[DEBUG] - ข้อมูล Name ไม่ตรงกัน: {len(mismatched_data)} คน")
        if mismatched_data:
            for m in mismatched_data:
                logger.info(f"[DEBUG]   - {m}")
                
        logger.info(f"[DEBUG] - ลิงก์รูปภาพใน Sheet ผิดรูปแบบ: {len(invalid_urls)} ลิงก์")
        if invalid_urls:
            for iv in invalid_urls:
                logger.info(f"[DEBUG]   - {iv[1]} ({iv[0]}): {iv[2]}")
                
        logger.info(f"[DEBUG] - มีรูปใน Sheet แต่ไม่มีใน DB (ขาดหาย): {len(missing_photos_in_db)} คน")
        if missing_photos_in_db:
            for mp in missing_photos_in_db:
                logger.info(f"[DEBUG]   - {mp}")
                
        logger.info("[DEBUG] ===============================================================")

    def _task_2_sync_new_students(self):
        logger.info("[SCHEDULE] กำลังทำ task นักเรียนใหม่...")
        sheet_id = "1bz81BDC0NkuX1-jzw_glntYZ1xkmuI9xJSi8op_x7To"
        
        try:
            # เชื่อมต่อเพื่ออ่าน Sheet ข้อมูลนักเรียน (โดยไม่สร้างแท็บ photos/faces ซ้ำซ้อน)
            if not self.sync_manager.connect(sheet_id, ensure_worksheets=False):
                logger.error("[SCHEDULE] ไม่สามารถเชื่อมต่อกับ Google Sheet ข้อมูลนักเรียนได้")
                return
            sheet = self.sync_manager.gspread_client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
            logger.info(f"[SCHEDULE] อ่านข้อมูลจาก Sheet ข้อมูลนักเรียนสำเร็จ พบทั้งหมด {len(data)} แถว")
        except Exception as e:
            logger.error(f"[SCHEDULE] ไม่สามารถอ่าน Sheet ข้อมูลนักเรียนได้: {e}", exc_info=True)
            return

        if not data:
            logger.warning("[SCHEDULE] Sheet ข้อมูลนักเรียน ไม่มีข้อมูลหรือเป็นค่าว่าง")
            return
            
        sample_keys = list(data[0].keys())
        logger.info(f"[SCHEDULE] พบคอลัมน์ใน Sheet ข้อมูลนักเรียน: {sample_keys}")

        # ฟังก์ชันจับคู่ชื่อคอลัมน์แบบยืดหยุ่น
        def find_col(possible_names):
            for k in sample_keys:
                clean_k = str(k).replace(" ", "").replace("-", "").strip()
                for name in possible_names:
                    clean_name = str(name).replace(" ", "").replace("-", "").strip()
                    if clean_k == clean_name:
                        return k
            return None

        col_id = find_col(["รหัสนักเรียน", "รหัสประจำตัว", "รหัส"]) or (sample_keys[0] if len(sample_keys) > 0 else "รหัสนักเรียน")
        col_name = find_col(["ชื่อ สกุล", "ชื่อ-นามสกุล", "ชื่อนามสกุล", "ชื่อสุกล"]) or (sample_keys[1] if len(sample_keys) > 1 else "ชื่อ สกุล")
        col_img1 = find_col(["ภาพใบหน้าตรงตอนเด็ก", "ภาพใบหน้าตรง ตอนเด็ก", "ภาพใบหน้าตรง", "รูปถ่าย", "ภาพถ่าย"]) or (sample_keys[3] if len(sample_keys) > 3 else "ภาพใบหน้าตรง ตอนเด็ก")
        col_img2 = find_col(["ภาพใบหน้าตรงตอนวัยรุ่น", "ภาพใบหน้าตรง ตอนวัยรุ่น", "ภาพใบหน้าตรง2", "ภาพใบหน้าเพิ่มเติม1", "ภาพใบหน้าเพิ่มเติม 1", "ภาพใบหน้าตรงอัปเดต"]) or (sample_keys[4] if len(sample_keys) > 4 else "ภาพใบหน้าตรง ตอนวัยรุ่น")

        logger.info(f"[SCHEDULE] ใช้ชื่อคอลัมน์นักเรียน (A-E) -> ID: '{col_id}', Name: '{col_name}', Img1: '{col_img1}', Img2: '{col_img2}' (รองรับสูงสุด 2 ภาพหน้าตรงต่างช่วงวัย)")

        if DEBUG_SYNC_MODE:
            self.debug_compare_sheet_vs_db(data, col_id, col_name, col_img1, col_img2, None)

        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_sync_temp.json")
        old_data = {}
        if os.path.exists(temp_file):
            try:
                with open(temp_file, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
            except Exception as e:
                logger.warning(f"[SCHEDULE] อ่านไฟล์แคช student_sync_temp.json ไม่สำเร็จ: {e}")
                
        new_data = {}
        matched_faces_to_process = []
        
        valid_rows_count = 0
        for row in data:
            std_id = str(row.get(col_id, "")).strip()
            if not std_id:
                continue
            valid_rows_count += 1
                
            std_name = str(row.get(col_name, "")).strip()
            imgs = [str(row.get(col_img1, "")), str(row.get(col_img2, ""))]
            
            # เก็บ State (เอา PIN ออกแล้ว)
            std_state = {
                "name": std_name,
                "imgs": imgs
            }
            new_data[std_id] = std_state
            
            # เปรียบเทียบไฟล์แคช JSON
            is_new = False
            new_imgs = []
            
            if std_id not in old_data:
                is_new = True
                new_imgs = [img for img in imgs if img.strip()]
            else:
                old_imgs = old_data[std_id].get("imgs", [])
                # หาลิงก์รูปที่เพิ่งเพิ่มมาใหม่หรือเปลี่ยนไป (ตรวจสูงสุด 2 รูปหน้าตรง)
                for i in range(min(2, len(imgs))):
                    if imgs[i].strip() and (i >= len(old_imgs) or imgs[i] != old_imgs[i]):
                        new_imgs.append(imgs[i])

            # ตรวจสอบเพิ่มเติมกับ SQLite DB: หากรูปภาพใดยังไม่มี embedding ใน DB ให้จัดเข้า new_imgs ด้วย
            # ดึง ID มาตรวจสอบโดยไม่บันทึกลง DB ทันที เพื่อป้องกันรายชื่อขยะ
            staff_id_check = None
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM staff_members WHERE student_id = ? AND role = 'student'", (std_id,))
                row = c.fetchone()
                if row:
                    staff_id_check = row[0]
            
            if staff_id_check:
                with self.db.get_connection() as conn:
                    c = conn.cursor()
                    c.execute("SELECT image_path, source_url FROM staff_embeddings WHERE staff_id = ?", (staff_id_check,))
                    existing_records = c.fetchall()
                    existing_file_ids = set()
                    for r in existing_records:
                        img_p, src_u = r[0] or "", r[1] or ""
                        if "drive:" in img_p:
                            existing_file_ids.add(img_p.replace("drive:", "").strip())
                        ext_p = self._extract_drive_id(img_p)
                        if ext_p: existing_file_ids.add(ext_p)
                        ext_u = self._extract_drive_id(src_u)
                        if ext_u: existing_file_ids.add(ext_u)
                    
                    for img_url in imgs:
                        if img_url.strip():
                            f_id = self._extract_drive_id(img_url)
                            if f_id and f_id not in existing_file_ids and img_url not in new_imgs:
                                new_imgs.append(img_url)
            else:
                # กรณีที่ใน DB ไม่มีเลย (อาจถูกลบไปแล้ว) ต้องบังคับ is_new=True
                is_new = True
                for img_url in imgs:
                    if img_url.strip() and img_url not in new_imgs:
                        new_imgs.append(img_url)

            if is_new and new_imgs:
                logger.info(f"[SCHEDULE] พบนักเรียนใหม่: {std_name} ({std_id})")
            elif new_imgs:
                logger.info(f"[SCHEDULE] พบนักเรียนเก่าอัปเดตรูป: {std_name} ({std_id}) [จำนวน {len(new_imgs)} รูปภาพ]")
                
            if new_imgs:
                # ตรวจสอบและโหลด FaceAnalyzer Model หากยังไม่มี
                if not self._ensure_analyzer():
                    logger.error(f"[SCHEDULE] ข้ามการสกัดใบหน้าของ {std_name} เนื่องจากไม่สามารถโหลด AI Model ได้")
                    continue

                # ลงทะเบียน DB (ส่งค่า pin_code เป็นสตริงว่าง)
                staff_id = self.db.register_member(std_name, role='student', student_id=std_id, pin_code="")
                
                # โหลดภาพและสกัดเวกเตอร์
                for img_url in new_imgs:
                    file_id = self._extract_drive_id(img_url)
                    if file_id:
                        try:
                            logger.info(f"[SCHEDULE] กำลังดาวน์โหลดรูปภาพ {file_id} ของ {std_name}...")
                            img_bytes = self.sync_manager.download_image_bytes(file_id)
                            img_cv = decode_image_bytes(img_bytes)
                            if img_cv is not None:
                                faces = self.analyzer.app.get(img_cv)
                                if not faces:
                                    # Fallback สำหรับภาพครอบตัดแน่นชิดใบหน้า (Tight Crop)
                                    h, w = img_cv.shape[:2]
                                    pad = int(max(h, w) * 0.5)
                                    img_padded = cv2.copyMakeBorder(img_cv, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=[128, 128, 128])
                                    faces = self.analyzer.app.get(img_padded)

                                if faces:
                                    # เอาหน้าแรกที่ชัดที่สุด
                                    face = faces[0]
                                    emb = face.embedding
                                    
                                    # ตัดใบหน้าและบันทึกลงเครื่อง
                                    h, w = img_cv.shape[:2]
                                    x1, y1, x2, y2 = face.bbox
                                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                                    pad_x = int(0.15 * (x2 - x1))
                                    pad_y = int(0.15 * (y2 - y1))
                                    x1 = max(0, x1 - pad_x)
                                    y1 = max(0, y1 - pad_y)
                                    x2 = min(w, x2 + pad_x)
                                    y2 = min(h, y2 + pad_y)
                                    cropped = img_cv[y1:y2, x1:x2]
                                    
                                    import time
                                    student_face_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "registered_students")
                                    os.makedirs(student_face_dir, exist_ok=True)
                                    student_filename = f"student_{std_id}_{int(time.time())}_{file_id}.jpg"
                                    local_img_path = os.path.join(student_face_dir, student_filename)
                                    
                                    success, img_encoded = cv2.imencode('.jpg', cropped)
                                    if success:
                                        img_encoded.tofile(local_img_path)
                                        db_img_path = local_img_path
                                    else:
                                        db_img_path = f"drive:{file_id}"
                                    
                                    # เซฟลง staff_embeddings
                                    conn = self.db.get_connection()
                                    c = conn.cursor()
                                    c.execute("INSERT INTO staff_embeddings (staff_id, image_path, embedding, source_url) VALUES (?, ?, ?, ?)",
                                             (staff_id, db_img_path, emb.tobytes(), img_url))
                                    conn.commit()
                                    # เตรียมสำหรับ Retroactive Match
                                    matched_faces_to_process.append({
                                        "staff_id": staff_id,
                                        "name": std_name,
                                        "emb": emb
                                    })
                                    logger.info(f"[SCHEDULE] สกัดเวกเตอร์ใบหน้าสำเร็จสำหรับ {std_name} (File ID: {file_id})")
                                else:
                                    logger.warning(f"[SCHEDULE] ไม่พบใบหน้าในรูปภาพ {file_id} ของ {std_name}")
                            else:
                                logger.warning(f"[SCHEDULE] ไม่สามารถแปลงรูปภาพ {file_id} ของ {std_name} ได้")
                        except Exception as e:
                            logger.error(f"[SCHEDULE] Error processing image {file_id} for {std_name}: {e}")
                    else:
                        logger.error(f"[SCHEDULE] ไม่สามารถดึง Google Drive File ID จาก URL: {img_url}")
                            
        logger.info(f"[SCHEDULE] ตรวจสอบข้อมูลนักเรียนเสร็จสิ้น ({valid_rows_count} แถวมีรหัสนักเรียนถูกต้อง)")

        # Save temp JSON
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SCHEDULE] บันทึกไฟล์แคช student_sync_temp.json ไม่สำเร็จ: {e}")
            
        # Retroactive Matching สำหรับหน้าที่เพิ่มมาใหม่
        if matched_faces_to_process:
            logger.info(f"[SCHEDULE] กำลังทำ task นักเรียนใหม่ -> Retroactive Match จำนวน {len(matched_faces_to_process)} ใบหน้า...")
            if hasattr(self.app_gui, 'process_retroactive_match_headless'):
                self.app_gui.process_retroactive_match_headless(matched_faces_to_process, scan_mode="all")
            else:
                logger.error("[SCHEDULE] Error: app_gui does not have process_retroactive_match_headless")
            logger.info("[SCHEDULE] ซิงค์นักเรียนและอัปเดตใบหน้าเสร็จสิ้น")
        else:
            logger.info("[SCHEDULE] ไม่มีนักเรียนอัปเดตรูปภาพใหม่")

    
    
    def _load_year_folders(self, active_only=True):
        """โหลดรายชื่อโฟลเดอร์หลักปีการศึกษาจากตาราง SQLite root_year_folders หรือ config/year_folders.json (v6.27)"""
        if hasattr(self, 'db') and self.db and hasattr(self.db, 'get_root_year_folders'):
            try:
                rows = self.db.get_root_year_folders(active_only=active_only)
                if rows is not None and len(rows) > 0:
                    return [(r["name"], r["id"]) for r in rows if r.get("name") and r.get("id")]
                elif not active_only and rows == []:
                    pass
                elif active_only and rows == []:
                    # ถ้ารายการทั้งหมดมีแต่ถูกปิด active หมด ให้คืนลิสต์ว่างตามที่ผู้ใช้ตั้งค่า
                    all_rows = self.db.get_root_year_folders(active_only=False)
                    if all_rows:
                        return []
            except Exception as e:
                logger.error(f"[SCHEDULE] Error reading root_year_folders from SQLite: {e}")

        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "year_folders.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return [
                            (item["name"], item["id"])
                            for item in data
                            if "name" in item and "id" in item and (not active_only or item.get("is_active", 1))
                        ]
            except Exception as e:
                logger.error(f"[SCHEDULE] Error reading config/year_folders.json: {e}")
                
        # Default Fallback (6 โฟลเดอร์หลัก)
        return [
            ("ภาพกิจกรรม 2569", "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"),
            ("ภาพกิจกรรม 2568", "1YYkDLsalb0jVM0K876lcejLoiggoJ18N"),
            ("ภาพกิจกรรม 2567", "1ocR4srmu1tA1nYgJOhoM9I0KDVMmbRGF"),
            ("ภาพกิจกรรม 2566", "1ZMhLENv8u-onIhVzwBTxCzjJVQVCriVd"),
            ("ภาพกิจกรรม 2565", "1cN-3d_mz_9CAbAwLOFKil22bBr0xgasL"),
            ("ภาพกิจกรรม 2563", "1uE8wHS5MNxscTIif9TmRLoxd5ptK16_t")
        ]

    def _get_root_folder_year_lookup(self):
        """คืนค่า Dict {folder_id: academic_year} จากตาราง root_year_folders (v6.27)"""
        lookup = {}
        if hasattr(self, 'db') and self.db and hasattr(self.db, 'get_root_year_folders'):
            try:
                for r in self.db.get_root_year_folders(active_only=False):
                    fid = r.get("id", "")
                    yr = str(r.get("academic_year") or "").strip()
                    if not yr:
                        m = re.search(r'25[5-8]\d', r.get("name", ""))
                        yr = m.group(0) if m else ""
                    if fid and yr:
                        lookup[fid] = yr
            except Exception as e:
                logger.warning(f"[SCHEDULE] Could not build root folder year lookup: {e}")
        return lookup

    def _get_all_subfolders_recursive(self, parent_id, parent_name="", main_event_name=None, subfolder_name=None):
        """ดึงรายชื่อทุกระดับแบบ Recursive พร้อมรักษาระดับ Main Event Folder และ Subfolder (v6.24)"""
        all_subfolders = []
        try:
            query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            page_token = None
            subdirs = []
            while True:
                res = self.sync_manager.drive_service.files().list(
                    q=query, fields="nextPageToken, files(id, name)", pageToken=page_token, pageSize=1000
                ).execute()
                subdirs.extend(res.get("files", []))
                page_token = res.get("nextPageToken")
                if not page_token or self.stop_requested: break
                
            for subdir in subdirs:
                if self.stop_requested: break
                s_id = subdir['id']
                s_name = subdir['name']
                
                # ถ้ายังไม่มี main_event_name แสดงว่า subdir นี้คือโฟลเดอร์กิจกรรมหลัก (Level 2 ใต้ปี)
                # Anti-Generic Guard (v6.32): หาก s_name เป็นคำ generic และ parent_name ไม่ใช่ Root Year ให้ใช้ parent_name เป็นชื่อกิจกรรมหลัก
                if main_event_name:
                    cur_event = main_event_name
                    cur_sub = s_name
                elif is_generic_folder_name(s_name) and parent_name and not any(yr in parent_name for yr in ['ภาพกิจกรรม', '256', '255']):
                    cur_event = parent_name
                    cur_sub = s_name
                else:
                    cur_event = s_name
                    cur_sub = None
                
                all_subfolders.append({
                    "id": s_id, 
                    "name": s_name, 
                    "event_name": cur_event, 
                    "subfolder": cur_sub
                })
                
                # มุดลงไปดึงโฟลเดอร์ชั้นในซ้อนชั้นอีก (Recursive)
                inner_subdirs = self._get_all_subfolders_recursive(s_id, s_name, main_event_name=cur_event, subfolder_name=cur_sub)
                all_subfolders.extend(inner_subdirs)
        except Exception as e:
            logger.error(f"[SCHEDULE] Error fetching recursive subfolders for {parent_name}: {e}")
        return all_subfolders

    def fetch_drive_folder_year_mapping(self):
        """
        ดึงโครงสร้างโฟลเดอร์ทั้งหมดจาก Google Drive แบบ Bulk (~4-6 วินาที)
        และสร้างแผนผังจับคู่ชื่อโฟลเดอร์กิจกรรม (event_name) ไปยังปีการศึกษา Root Year (v6.26/v6.27)
        """
        if not self.sync_manager or not self.sync_manager.connected:
            if hasattr(self, 'sync_manager') and self.sync_manager:
                self.sync_manager.connect()
            else:
                return {}

        target_years = self._load_year_folders(active_only=False)
        db_year_lookup = self._get_root_folder_year_lookup()
        root_years = {}
        for y_name, y_id in target_years:
            if y_id in db_year_lookup and db_year_lookup[y_id]:
                root_years[y_id] = db_year_lookup[y_id]
            else:
                m_be = re.search(r'25[5-8]\d', y_name)
                if m_be:
                    root_years[y_id] = m_be.group(0)

        all_folders = {}
        page_token = None
        while True:
            res = self.sync_manager.drive_service.files().list(
                q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                fields="nextPageToken, files(id, name, parents)",
                pageSize=1000,
                pageToken=page_token
            ).execute()
            for f in res.get('files', []):
                all_folders[f['id']] = {'name': f.get('name', ''), 'parents': f.get('parents', [])}
            page_token = res.get('nextPageToken')
            if not page_token or self.stop_requested:
                break

        def _trace_root_year(fid, visited=None):
            if visited is None: visited = set()
            if fid in visited: return None
            visited.add(fid)
            if fid in root_years: return root_years[fid]
            f_info = all_folders.get(fid)
            if not f_info: return None
            for p in f_info.get('parents', []):
                y = _trace_root_year(p, visited)
                if y: return y
            return None

        event_to_years = {}
        for fid, f in all_folders.items():
            y = _trace_root_year(fid)
            if y:
                name = f['name'].strip()
                event_to_years.setdefault(name, set()).add(y)

        logger.info(f"[GDRIVE MAP] Successfully mapped {len(event_to_years)} distinct folder names to academic years.")
        return event_to_years
    
    
    def _task_1_scan_new_photos_fast(self):
        logger.info("[SCHEDULE] 🚀 เริ่มต้น Task 1: สแกนโฟลเดอร์ใหม่เรียงลำดับปีการศึกษา (Single GPU Consumer)")
        
        target_years = self._load_year_folders(active_only=True)
        root_year_lookup = self._get_root_folder_year_lookup()
        
        # 1. โหลดข้อมูลเป้าหมายจากฐานข้อมูลมาไว้ใน Memory
        with self.db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id, name, personal_threshold FROM staff_members")
            staff_data = c.fetchall()
            
            c.execute("SELECT staff_id, embedding FROM staff_embeddings")
            emb_data = c.fetchall()

            c.execute("""
                SELECT drive_file_id FROM scanned_photos 
                WHERE photo_date NOT LIKE 'ERROR%' AND photo_date NOT LIKE 'SKIPPED%' 
                  AND drive_link NOT LIKE 'ERROR%' AND drive_link NOT LIKE 'SKIPPED%'
                UNION
                SELECT drive_file_id FROM raw_camera_photos
            """)
            scanned_ids = set(row[0] for row in c.fetchall())

        if not staff_data or not emb_data:
            logger.warning("[SCHEDULE] ⚠️ ไม่มีข้อมูลนักเรียน/บุคลากรในฐานข้อมูล หรือไม่มีเวกเตอร์ภาพ")
            return
            
        import numpy as np
        template_embeddings = []
        template_staff_ids = []
        template_names = []
        personal_threshold_dict = {row[0]: row[2] for row in staff_data}
        template_thresholds = []

        for staff_id, emb_blob in emb_data:
            try:
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                template_embeddings.append(emb)
                template_staff_ids.append(staff_id)
                name = next((r[1] for r in staff_data if r[0] == staff_id), "Unknown")
                template_names.append(name)
                thresh = personal_threshold_dict.get(staff_id, 0.50)
                template_thresholds.append(thresh)
            except Exception as e:
                logger.error(f"[SCHEDULE] Error loading embedding for staff_id {staff_id}: {e}")

        if not template_embeddings:
            logger.warning("[SCHEDULE] ⚠️ โหลด Template เวกเตอร์ไม่สำเร็จ")
            return

        template_embeddings = np.array(template_embeddings, dtype=np.float32)
        
        import concurrent.futures
        # ดึงประวัติโฟลเดอร์ที่สแกนเสร็จสิ้นแล้วจาก matched_folders.json เพื่อ Fast Skip ระดับ Folder
        completed_folder_ids = set()
        if hasattr(self.app_gui, 'get_matched_folders'):
            completed_folder_ids = set(self.app_gui.get_matched_folders().keys())

        for year_name, year_id in target_years:
            if self.stop_requested: break
            
            # ดึงปีการศึกษา พ.ศ. 4 หลัก จากตาราง root_year_folders หรือสกัดจากชื่อโฟลเดอร์หลัก (v6.26/v6.27)
            current_academic_year = root_year_lookup.get(year_id, "")
            if not current_academic_year:
                m_year = re.search(r'25[5-8]\d', year_name)
                current_academic_year = m_year.group(0) if m_year else ""

            subfolders = self._get_all_subfolders_recursive(year_id, year_name)
            if not subfolders:
                subfolders = [{"id": year_id, "name": year_name}]
                
            logger.info(f"[SCHEDULE] 🔍 กำลังตรวจหาโฟลเดอร์ใหม่ใน '{year_name}' (พบ {len(subfolders)} โฟลเดอร์ย่อย)...")
            
            folders_to_scan = []
            for subdir in subfolders:
                if self.stop_requested: break
                f_id = subdir['id']
                f_name = subdir['name']
                
                # Fast Skip: ถ้าโฟลเดอร์ย่อยนี้ถูกบันทึกว่าสแกนสมบูรณ์แล้ว ให้ข้ามทันทีโดยไม่ต้องส่ง API query รูปข้างใน (v5.10)
                if f_id in completed_folder_ids:
                    continue
                
                try:
                    q_imgs = f"'{f_id}' in parents and (mimeType contains 'image/') and trashed = false"
                    img_res = self.sync_manager.drive_service.files().list(
                        q=q_imgs, fields="files(id, name, webContentLink, createdTime)", pageSize=1000
                    ).execute()
                    imgs = img_res.get("files", [])
                    
                    if not imgs:
                        # หากเป็นโฟลเดอร์เปล่า บันทึกไว้เป็น matched_folder เพื่อไม่ต้องเช็กซ้ำ
                        if hasattr(self.app_gui, 'record_matched_folder'):
                            self.app_gui.record_matched_folder(f_id, f_name)
                            completed_folder_ids.add(f_id)
                        continue
                        
                    unscanned = [img for img in imgs if img['id'] not in scanned_ids]
                    if unscanned:
                        folders_to_scan.append({
                            "folder_id": f_id,
                            "folder_name": f_name,
                            "event_name": subdir.get("event_name", f_name),
                            "subfolder": subdir.get("subfolder"),
                            "academic_year": current_academic_year,
                            "files_to_scan": unscanned
                        })
                    else:
                        # ถ้าภาพทุกภาพในโฟลเดอร์มีสแกนใน DB ครบแล้ว ให้บันทึกสถานะโฟลเดอร์เป็นสีเขียวทันที (v4.14 / v5.10)
                        if hasattr(self.app_gui, 'record_matched_folder'):
                            self.app_gui.record_matched_folder(f_id, f_name)
                            completed_folder_ids.add(f_id)
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error checking folder {f_name}: {e}")

            total_in_year = len(folders_to_scan)
            if total_in_year == 0:
                logger.info(f"[SCHEDULE] ✅ '{year_name}' สแกนสมบูรณ์แล้ว 100% (ไม่พบรูปภาพใหม่)")
                continue
                
            folder_names_summary = [f['folder_name'] for f in folders_to_scan[:5]]
            more_suffix = f" ...และอีก {total_in_year-5} โฟลเดอร์" if total_in_year > 5 else ""
            logger.info(f"[SCHEDULE] 🎯 '{year_name}' พบ {total_in_year} โฟลเดอร์ที่ต้องทำ Full Scan: [{', '.join(folder_names_summary)}{more_suffix}]")

            # 3. สแกนทีละโฟลเดอร์ย่อยของปีนี้ (Sequential Thread-Safe Pattern)
            for idx, target in enumerate(folders_to_scan):
                if self.stop_requested: break
                
                folder_id = target["folder_id"]
                folder_name = target["folder_name"]
                files_to_process = target["files_to_scan"]
                total_files = len(files_to_process)
                
                logger.info(f"[FULLSCAN] 🚀 [{year_name}] ({idx+1}/{total_in_year}) สแกนโฟลเดอร์: {folder_name} ({total_files} รูป)")
                if hasattr(self, 'tracker') and self.tracker:
                    self.tracker.record_folder_start(folder_name, year_name, total_files)
                
                results_data = []
                raw_photos_data = []
                skipped_files = []
                processed_count = 0
                
                # Sequential Loop: โหลดทีละรูป และยิง InsightFace บน Thread เดียวแบบ 100% Thread-Safe
                for file_info in files_to_process:
                    if self.stop_requested: break
                    
                    f_id = file_info['id']
                    f_name = file_info['name']
                    f_link = file_info.get('webContentLink', f"https://drive.google.com/file/d/{f_id}/view")
                    p_date = file_info.get('createdTime', '').split('T')[0] if 'createdTime' in file_info else datetime.now().strftime("%Y-%m-%d")
                    f_ext = os.path.splitext(f_name)[1].lower() if f_name else ""

                    # 📷 ตรวจจับไฟล์ RAW กล้องดิจิทัล (Sony .ARW, Canon .CR2/.CR3, Nikon .NEF, Fuji .RAF, etc.) (v6.10)
                    camera_brand = RAW_EXTENSIONS_MAP.get(f_ext)
                    if camera_brand:
                        logger.info(f"[AI SCAN] [{folder_name}] ({processed_count+1}/{total_files}) 📷 ตรวจพบไฟล์ RAW กล้อง ({camera_brand} {f_ext}): {f_name} (บันทึกลง raw_camera_photos โดยอัตโนมัติ ข้ามการดาวน์โหลด)")
                        if hasattr(self, 'tracker') and self.tracker:
                            self.tracker.record_raw_photo(folder_name, f_name, f_id)
                        raw_photos_data.append({
                            "photo_id": f_id,
                            "drive_file_id": f_id,
                            "event_name": target.get("event_name", folder_name),
                            "drive_link": f_link,
                            "photo_date": p_date,
                            "file_name": f_name,
                            "file_extension": f_ext,
                            "camera_brand": camera_brand
                        })
                        processed_count += 1
                        continue

                    logger.info(f"[AI SCAN] [{folder_name}] ({processed_count+1}/{total_files}) 📥 โหลดรูปภาพจาก Drive: {f_name} (ID: {f_id})")
                    
                    try:
                        # 1. ดาวน์โหลดรูปภาพจาก Drive (Single Thread - Safe Google API Call)
                        t_dl_start = time.time()
                        req = self.sync_manager.drive_service.files().get_media(fileId=f_id)
                        img_bytes = req.execute()
                        t_dl = time.time() - t_dl_start
                        
                        if not img_bytes:
                            logger.warning(f"[AI SCAN] [{folder_name}] ⚠️ ไม่สามารถดาวน์โหลดไฟล์ได้: {f_name} (ข้ามเพื่อรอสแกนซ้ำรอบถัดไป)")
                            skipped_files.append((f_id, f_name, "SKIPPED_DOWNLOAD_EMPTY"))
                            if hasattr(self, 'tracker') and self.tracker:
                                self.tracker.record_skipped(folder_name, f_name, f_id, "ไม่สามารถดาวน์โหลดไฟล์ได้ (Empty Bytes)", f_link)
                            processed_count += 1
                            continue

                        # 2. Decode Multi-Format (v5.90: Full HEIC / JPEG / PNG / WEBP Support)
                        img = decode_image_bytes(img_bytes)
                        
                        if img is None:
                            logger.warning(f"[AI SCAN] [{folder_name}] ⚠️ ไม่สามารถ Decode ไฟล์ภาพได้: {f_name} (ข้ามเพื่อรอสแกนซ้ำรอบถัดไป)")
                            skipped_files.append((f_id, f_name, "SKIPPED_UNREADABLE_IMAGE"))
                            if hasattr(self, 'tracker') and self.tracker:
                                self.tracker.record_skipped(folder_name, f_name, f_id, "ไม่สามารถ Decode ไฟล์ภาพได้ (Unreadable Image)", f_link)
                            processed_count += 1
                            continue

                        # 3. สแกนด้วย InsightFace GPU
                        t0 = time.time()
                        faces = self.analyzer.get_faces_optimized(img)
                        t_ai = time.time() - t0
                        
                        photo_matches = []
                        face_embeddings = []
                        match_names = []
                        
                        if faces and len(faces) > 0:
                            detected_embs = [f.embedding for f in faces if f is not None and hasattr(f, 'embedding')]
                            if detected_embs:
                                detected_embs = np.array(detected_embs, dtype=np.float32)
                                
                                matches = self.analyzer.match_faces_matrix(
                                    detected_embs, template_embeddings, template_names, template_staff_ids, 
                                    threshold=0.50, template_thresholds=template_thresholds
                                )
                                
                                for i, face in enumerate(faces):
                                    if i < len(matches) and matches[i] is not None and isinstance(matches[i], dict):
                                        best_match = matches[i]
                                        if best_match.get('name', 'Unknown') != "Unknown":
                                            photo_matches.append((best_match['staff_id'], best_match['confidence']))
                                            match_names.append(best_match['name'])
                                            
                                    if hasattr(face, 'bbox') and face.bbox is not None:
                                        bbox = face.bbox
                                        face_embeddings.append({
                                            'face_index': i,
                                            'bbox': [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                                            'embedding': face.embedding.astype(np.float32).tobytes()
                                        })

                        match_str = f"-> [MATCH_OK] เจอ: {', '.join(match_names)}" if match_names else "-> ไม่พบคนในระบบ"
                        logger.info(f"[AI SCAN] [{folder_name}] ({processed_count+1}/{total_files}) ✅ {f_name} | DL: {t_dl:.2f}s | AI: {t_ai:.2f}s | พบ {len(faces) if faces else 0} ใบหน้า {match_str}")
                        if hasattr(self, 'tracker') and self.tracker:
                            self.tracker.record_ai_photo(folder_name, f_name, f_id, len(faces) if faces else 0, match_names)
                        
                        # Save Thumbnail Cache (รองรับ Encoding โฟลเดอร์ภาษาไทยบน Windows)
                        try:
                            thumb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "thumbnail_cache")
                            os.makedirs(thumb_dir, exist_ok=True)
                            thumb_path = os.path.join(thumb_dir, f"{f_id}.jpg")
                            if not os.path.exists(thumb_path):
                                h, w = img.shape[:2]
                                scale = 500.0 / max(h, w)
                                thumb_img = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img
                                success, encoded_img = cv2.imencode('.jpg', thumb_img)
                                if success:
                                    encoded_img.tofile(thumb_path)
                        except Exception as thumb_err:
                            logger.error(f"[AI SCAN] [{folder_name}] ⚠️ บันทึก Thumbnail Cache ล้มเหลวสำหรับ {f_id}: {thumb_err}")

                        # สร้าง photo_id รูปแบบ Pxxxxx ต่อเนื่อง (v6.11) หรือใช้ ID เดิมหากมี
                        existing_photo_id = self.db.get_photo_id_by_drive_id(f_id)
                        if existing_photo_id:
                            photo_id = existing_photo_id
                        else:
                            photo_serial = self.db.get_next_photo_serial() + len(results_data)
                            photo_id = f"P{photo_serial:05d}"

                        results_data.append({
                            "photo_id": photo_id,
                            "drive_file_id": f_id,
                            "event_name": target.get("event_name", folder_name),
                            "drive_link": f_link,
                            "photo_date": p_date,
                            "file_name": f_name,
                            "file_extension": f_ext,
                            "academic_year": target.get("academic_year", current_academic_year),
                            "matches": photo_matches,
                            "face_embeddings": face_embeddings
                        })
                        
                        processed_count += 1
                            
                    except Exception as e:
                        logger.error(f"[AI SCAN] [{folder_name}] ❌ Error analyzing faces for {f_name}: {e} (ข้ามเพื่อรอสแกนซ้ำรอบถัดไป)")
                        skipped_files.append((f_id, f_name, f"ERROR_{e}"))
                        if hasattr(self, 'tracker') and self.tracker:
                            self.tracker.record_skipped(folder_name, f_name, f_id, f"เกิดข้อผิดพลาด: {e}", f_link)
                        processed_count += 1

                # Single Transaction Batch Save - บันทึกเฉพาะรูปที่สแกนสำเร็จจริง 100% (v5.80 / v6.00 with file_name & file_extension, v6.26 with academic_year)
                if results_data:
                    with self.db.get_connection() as conn:
                        c = conn.cursor()
                        scanned_rows = [
                            (
                                r["photo_id"],
                                r["drive_file_id"],
                                r["event_name"],
                                r["drive_link"],
                                r["photo_date"],
                                r.get("file_name", ""),
                                r.get("file_extension", ""),
                                len(r.get("face_embeddings", [])),
                                r.get("academic_year", current_academic_year)
                            )
                            for r in results_data
                        ]
                        c.executemany("INSERT OR REPLACE INTO scanned_photos (photo_id, drive_file_id, event_name, drive_link, photo_date, file_name, file_extension, total_faces_detected, academic_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", scanned_rows)
                        
                        photo_ids_batch = [r["photo_id"] for r in results_data]
                        if photo_ids_batch:
                            placeholders_del = ",".join("?" for _ in photo_ids_batch)
                            c.execute(f"DELETE FROM detected_faces WHERE photo_id IN ({placeholders_del})", photo_ids_batch)

                        match_rows = []
                        for r in results_data:
                            for staff_id, conf in r["matches"]: match_rows.append((r["photo_id"], staff_id, conf))
                        if match_rows:
                            c.executemany("INSERT INTO detected_faces (photo_id, staff_id, confidence) VALUES (?, ?, ?)", match_rows)
                            
                        emb_rows = []
                        for r in results_data:
                            for f in r["face_embeddings"]:
                                emb_rows.append((r["photo_id"], f["face_index"], f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3], f["embedding"]))
                        if emb_rows:
                            c.executemany("INSERT INTO scanned_photo_faces (photo_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)", emb_rows)

                        conn.commit()

                # บันทึกไฟล์ภาพดิบ RAW ลงตาราง raw_camera_photos (v6.10)
                if raw_photos_data:
                    self.db.save_raw_photos_batch(raw_photos_data)
                    for r in raw_photos_data:
                        scanned_ids.add(r["photo_id"])

                # เฉพาะโฟลเดอร์ที่สแกนสำเร็จครบ 100% (ไม่มีไฟล์หลุด/Error) จึงบันทึกเป็น Completed Folder (v5.80 / v6.10)
                if (len(results_data) + len(raw_photos_data)) == total_files and len(skipped_files) == 0:
                    if hasattr(self.app_gui, 'record_matched_folder'):
                        self.app_gui.record_matched_folder(folder_id, folder_name)
                        completed_folder_ids.add(folder_id)
                    if hasattr(self, 'tracker') and self.tracker:
                        self.tracker.record_folder_finish(folder_name, is_completed=True)
                else:
                    logger.warning(f"[FULLSCAN] ⚠️ โฟลเดอร์ '{folder_name}' สแกนสำเร็จ {len(results_data) + len(raw_photos_data)}/{total_files} รูป (มี {len(skipped_files)} รูปค้างเนื่องจากเน็ตหลุด/ผิดพลาด จะไม่บันทึกว่าเสร็จเพื่อให้สแกนซ้ำ)")
                    if hasattr(self, 'tracker') and self.tracker:
                        self.tracker.record_folder_finish(folder_name, is_completed=False)

                for r in results_data: scanned_ids.add(r["photo_id"])
                
                if self.stop_requested:
                    logger.info(f"[SCHEDULE] 🛑 หยุดการทำงานในโฟลเดอร์ '{folder_name}' ตามคำร้องขอ (Stop Requested) กำลังบันทึกไฟล์ JSON ปิดท้าย...")
                    self._safe_sync_json_on_stop()
                    break
                
            logger.info(f"[SCHEDULE] 🎉 เสร็จสิ้นการทำ Full Scan สำหรับโฟลเดอร์หลัก: '{year_name}'")



    def _task_2_sync_new_students_bulk(self):
        logger.info("[SCHEDULE] 🚀 เริ่มต้น Task 2: Sync New Students & Bulk Matching")
        sheet_id = "1bz81BDC0NkuX1-jzw_glntYZ1xkmuI9xJSi8op_x7To"
        
        try:
            if not self.sync_manager.connect(sheet_id, ensure_worksheets=False):
                logger.error("[SCHEDULE] ไม่สามารถเชื่อมต่อกับ Google Sheet ได้")
                return
            sheet = self.sync_manager.gspread_client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
            logger.info(f"[SCHEDULE] อ่านข้อมูลจาก Sheet สำเร็จ พบ {len(data)} แถว")
        except Exception as e:
            logger.error(f"[SCHEDULE] ไม่สามารถอ่าน Sheet ได้: {e}", exc_info=True)
            return

        if not data:
            logger.warning("[SCHEDULE] Sheet ไม่มีข้อมูล")
            return
            
        sample_keys = list(data[0].keys())
        def find_col(possible_names):
            for k in sample_keys:
                clean_k = str(k).replace(" ", "").replace("-", "").strip()
                for name in possible_names:
                    if clean_k == str(name).replace(" ", "").replace("-", "").strip(): return k
            return None

        col_id = find_col(["รหัสนักเรียน", "รหัสประจำตัว", "รหัส"]) or (sample_keys[0] if len(sample_keys) > 0 else "รหัสนักเรียน")
        col_name = find_col(["ชื่อ สกุล", "ชื่อ-นามสกุล", "ชื่อนามสกุล"]) or (sample_keys[1] if len(sample_keys) > 1 else "ชื่อ สกุล")
        col_img1 = find_col(["ภาพใบหน้าตรงตอนเด็ก", "ภาพใบหน้าตรง ตอนเด็ก", "ภาพใบหน้าตรง", "รูปถ่าย"]) or (sample_keys[3] if len(sample_keys) > 3 else "ภาพใบหน้าตรง ตอนเด็ก")
        col_img2 = find_col(["ภาพใบหน้าตรงตอนวัยรุ่น", "ภาพใบหน้าตรง ตอนวัยรุ่น", "ภาพใบหน้าตรง2"]) or (sample_keys[4] if len(sample_keys) > 4 else "ภาพใบหน้าตรง ตอนวัยรุ่น")

        # 🌟 DB-Single Source of Truth: ดึงสถานะปัจจุบันของนักเรียนทุกคนที่มีใน SQLite DB มาสร้างเป็น old_data ตั้งต้น
        old_data = {}
        try:
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT s.student_id, s.name, e.source_url 
                    FROM staff_members s
                    LEFT JOIN staff_embeddings e ON s.id = e.staff_id
                    WHERE s.role = 'student' AND s.student_id IS NOT NULL AND s.student_id != ''
                """)
                for sid, sname, surl in cur.fetchall():
                    if sid not in old_data:
                        old_data[sid] = {"name": sname, "urls": []}
                    if surl:
                        clean_u = surl.replace("url:", "").strip()
                        if clean_u and clean_u not in old_data[sid]["urls"]:
                            old_data[sid]["urls"].append(clean_u)
            logger.info(f"[SCHEDULE] 📊 โหลดสถานะตั้งต้นจาก SQLite DB สำเร็จ พบนักเรียนเดิม {len(old_data)} คน")
        except Exception as db_err:
            logger.warning(f"[SCHEDULE] Could not build old_data from DB: {db_err}")

        # อ่านสถานะจาก json สำรอง (ถ้ามี)
        import json
        temp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "student_sync_temp.json")
        new_data = {}
        processed_students = 0
        
        self._ensure_analyzer()
        
        import numpy as np
        import cv2

        for row in data:
            if self.stop_requested: break
            
            s_id = str(row.get(col_id, "")).strip()
            s_name = str(row.get(col_name, "")).strip()
            if not s_id or not s_name:
                continue
                
            url1 = str(row.get(col_img1, "")).strip()
            url2 = str(row.get(col_img2, "")).strip()
            
            # (หากไม่มีรูประบบจะไม่บันทึกและปล่อยผ่าน)
            if not url1 and not url2:
                continue
                
            urls = []
            if url1: urls.append(url1)
            if url2: urls.append(url2)
            
            is_new_or_updated = False
            if s_id not in old_data:
                is_new_or_updated = True
            else:
                old_urls = set(old_data[s_id].get("urls", []))
                new_urls = set(urls)
                # ถ้าไม่มี URL รูปใน DB เลย หรือ URL ใน Sheet ไม่ตรงกับ DB ➔ ให้ Re-sync ใหม่
                if not old_urls or old_urls != new_urls:
                    is_new_or_updated = True

            # 🌟 Auto-Recovery Check: ถ้า DB ถูกลบออกไปแล้ว หรือไม่มี embedding สำหรับนักเรียนคนนี้ ให้ถือว่าต้องทำ Re-sync เสมอ
            staff_id_check = self.db.get_staff_id_by_student_id(s_id) if hasattr(self.db, 'get_staff_id_by_student_id') else None
            if not staff_id_check:
                is_new_or_updated = True
            else:
                with self.db.get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM staff_embeddings WHERE staff_id = ?", (staff_id_check,))
                    emb_count = cur.fetchone()[0]
                    if emb_count == 0:
                        is_new_or_updated = True

            if is_new_or_updated:
                logger.info(f"[SCHEDULE] 🔄 พบการอัปเดตรูปของนักเรียน: {s_name} ({s_id})")
                try:
                    # 1. พยายามดาวน์โหลดรูปและสกัดเวกเตอร์ใบหน้าก่อนบันทึกลง DB
                    pending_embeddings = []
                    for url in urls:
                        try:
                            img_data = self.sync_manager.download_image_from_url(url)
                            if not img_data:
                                logger.warning(f"[SCHEDULE] ⚠️ ดาวน์โหลดรูปไม่ผ่านจาก URL: {url} สำหรับนักเรียน {s_name} ({s_id})")
                                continue
                            
                            if isinstance(img_data, str) and os.path.exists(img_data):
                                img = read_image_file(img_data)
                            elif isinstance(img_data, bytes):
                                img = decode_image_bytes(img_data)
                            else:
                                img = None

                            if img is not None:
                                faces = self.analyzer.get_faces_optimized(img)
                                if faces:
                                    best_face = faces[0]
                                    
                                    # บันทึกไฟล์ภาพแคชต้นแบบลงดิสก์ (ใช้ imencode.tofile เพื่อรองรับ Unicode Path บน Windows)
                                    from face_analyzer import get_project_root
                                    template_dir = os.path.join(get_project_root(), "data", "student_templates")
                                    os.makedirs(template_dir, exist_ok=True)
                                    file_id = self.sync_manager.extract_file_id_from_url(url) or f"{s_id}_{len(pending_embeddings)}"
                                    save_path = os.path.join(template_dir, f"student_{s_id}_{file_id}.jpg")
                                    
                                    ok, img_encoded = cv2.imencode('.jpg', img)
                                    if ok:
                                        img_encoded.tofile(save_path)
                                        pending_embeddings.append((save_path, best_face.embedding.tolist(), url))
                                    else:
                                        logger.error(f"[SCHEDULE] Could not encode image for {s_name} ({s_id})")
                                else:
                                    logger.warning(f"[SCHEDULE] ⚠️ ตรวจไม่พบใบหน้าในรูปของนักเรียน {s_name} ({s_id}) จาก URL: {url}")
                        except Exception as e:
                            logger.error(f"[SCHEDULE] Error embedding for {s_name}: {e}")

                    # 2. ตรวจสอบว่าดาวน์โหลดและสกัดใบหน้าได้สำเร็จอย่างน้อย 1 รูปหรือไม่
                    if pending_embeddings:
                        # ลงทะเบียนบันทึก DB พร้อมกำหนด personal_threshold = 0.60 (60%) อัตโนมัติ
                        staff_id = self.db.register_member(s_name, role='student', student_id=s_id, personal_threshold=0.60)
                        self.db.clear_staff_embeddings(staff_id)
                        
                        for img_ref_path, emb_vector, source_url in pending_embeddings:
                            self.db.add_staff_embedding(staff_id, img_ref_path, emb_vector, source_url=source_url)
                            
                        self.db.set_staff_backfill_status(staff_id, 0)
                        processed_students += 1
                        logger.info(f"[SCHEDULE] ✅ ลงทะเบียนเวกเตอร์และตั้ง Threshold 60% ให้ {s_name} สำเร็จ ({len(pending_embeddings)} รูป)")
                        new_data[s_id] = {"name": s_name, "urls": urls}
                    else:
                        # ❌ หากดาวน์โหลดไม่ผ่าน หรือสแกนไม่พบใบหน้า (0 รูป): ห้ามบันทึก DB และห้ามบันทึก temp JSON
                        logger.warning(f"[SCHEDULE] ❌ [RETRY TASK 2] ไม่สามารถสกัดใบหน้าของนักเรียน {s_name} ({s_id}) ได้ (0 รูป) -> ยกเลิกการบันทึก DB และเตรียม Retry สแกนใหม่อัตโนมัติใน Task 2 รอบถัดไป")
                        new_data.pop(s_id, None)
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error process sync for {s_name}: {e}")
                    new_data.pop(s_id, None)
            else:
                new_data[s_id] = {"name": s_name, "urls": urls}

        # เซฟประวัติเฉพาะรายการที่สแกนสมบูรณ์แล้ว
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
        except: pass
        
        # ----------------------------------------------------
        # Bulk Backfill Matching (ใช้เมธอดเดิมของระบบ 100%)
        # ----------------------------------------------------
        logger.info("[SCHEDULE] 🔍 กำลังค้นหานักเรียน/บุคลากรที่ต้องทำ Bulk Backfill Matching...")
        unbackfilled = self.db.get_unbackfilled_students()
        
        if unbackfilled:
            logger.info(f"[SCHEDULE] พบ {len(unbackfilled)} คน ที่ต้องการทำจับคู่ย้อนหลัง")
            target_staff_ids = [s["staff_id"] for s in unbackfilled]
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT staff_id, embedding FROM staff_embeddings")
                all_embs = c.fetchall()
                
                matched_faces_to_process = []
                for staff_id, emb_blob in all_embs:
                    if staff_id in target_staff_ids and emb_blob:
                        emb = np.frombuffer(emb_blob, dtype=np.float32)
                        matched_faces_to_process.append({"staff_id": staff_id, "emb": emb})
            
            if matched_faces_to_process:
                logger.info(f"[SCHEDULE] กำลังทำ Retroactive Match กับเวกเตอร์ทั้งหมด {len(matched_faces_to_process)} เวกเตอร์...")
                if hasattr(self.app_gui, 'process_retroactive_match_headless'):
                    self.app_gui.process_retroactive_match_headless(matched_faces_to_process, scan_mode="all")
                else:
                    logger.error("[SCHEDULE] Error: app_gui does not have process_retroactive_match_headless")
            
            # Mark backfilled
            self.db.mark_students_backfilled(target_staff_ids)
            logger.info("[SCHEDULE] 🎉 การ Bulk Sync New Students เสร็จสมบูรณ์แล้ว!")
        else:
            logger.info("[SCHEDULE] ✅ ไม่มีนักเรียนใหม่หรือรูปอัปเดตที่ต้องทำ Backfill Matching ในรอบนี้")

    def _task_3_sync_new_teachers_bulk(self):
        """Task 3: ค้นหาคุณครูที่เพิ่มมาใหม่หรืออัปเดตรูปใหม่จาก SQLite DB (is_backfilled = 0) และนำค่า embedding ไป match กับ embedding ที่เก็บไว้ทั้งหมดใน scanned_photo_faces ทันที"""
        logger.info("[SCHEDULE] 🚀 เริ่มต้น Task 3: Sync New Teachers & Bulk Retroactive Matching")
        
        self._ensure_analyzer()
        
        # 1. ค้นหาครูที่ยังไม่ได้ทำการจับคู่ย้อนหลัง (is_backfilled = 0)
        logger.info("[SCHEDULE] 🔍 [TASK 3] กำลังค้นหาคุณครูที่มีการเพิ่มใหม่หรืออัปเดตรูปภาพที่ต้องทำ Retroactive Matching...")
        unbackfilled = self.db.get_unbackfilled_teachers()
        
        if unbackfilled:
            teacher_names = [t["name"] for t in unbackfilled]
            logger.info(f"[SCHEDULE] [TASK 3] พบคุณครู {len(unbackfilled)} ท่าน ที่ต้องการทำจับคู่ย้อนหลัง: {teacher_names}")
            target_staff_ids = [t["staff_id"] for t in unbackfilled]
            
            with self.db.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT staff_id, embedding FROM staff_embeddings")
                all_embs = c.fetchall()
                
                matched_faces_to_process = []
                for staff_id, emb_blob in all_embs:
                    if staff_id in target_staff_ids and emb_blob:
                        emb = np.frombuffer(emb_blob, dtype=np.float32)
                        matched_faces_to_process.append({"staff_id": staff_id, "emb": emb})
            
            if matched_faces_to_process:
                logger.info(f"[SCHEDULE] [TASK 3] กำลังทำ Retroactive Match สำหรับคุณครูกับเวกเตอร์กิจกรรมทั้งหมด ({len(matched_faces_to_process)} เวกเตอร์)...")
                if hasattr(self.app_gui, 'process_retroactive_match_headless'):
                    self.app_gui.process_retroactive_match_headless(matched_faces_to_process, scan_mode="all")
                else:
                    logger.error("[SCHEDULE] Error: app_gui does not have process_retroactive_match_headless")
            
            # ทำเครื่องหมายว่าครูกลุ่มนี้ทำ Backfill สำเร็จแล้ว
            self.db.mark_teachers_backfilled(target_staff_ids)
            logger.info(f"[SCHEDULE] 🎉 [TASK 3] การ Bulk Sync New Teachers เสร็จสมบูรณ์แล้ว ({len(target_staff_ids)} คน)!")
        else:
            logger.info("[SCHEDULE] ✅ [TASK 3] ไม่มีคุณครูใหม่หรือรูปอัปเดตที่ต้องทำ Backfill Matching ในรอบนี้")



