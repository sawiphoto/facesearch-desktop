import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import os
import time
import queue
import threading
import numpy as np
import cv2
from db_manager import DatabaseManager
from face_analyzer import FaceAnalyzer
from gdrive_sync import GoogleSyncManager

def run_benchmark():
    print("=== STARTING SCANNING SPEED BENCHMARK ===")
    db = DatabaseManager()
    sync = GoogleSyncManager()
    sync.connect()
    
    # 1. ค้นหาโฟลเดอร์ทดสอบและดึงรูปตัวอย่าง 10 รูป
    test_year_id = "1Y0GFynJhBzQIyR4XE0X7ABkdM1xEENTQ"
    q_sub = f"'{test_year_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    sub_res = sync.drive_service.files().list(q=q_sub, fields="files(id, name)").execute()
    subfolders = sub_res.get("files", [])
    if not subfolders:
        print("No subfolders found.")
        return
        
    target_folder = subfolders[0]
    folder_id = target_folder["id"]
    folder_name = target_folder["name"]
    print(f"Target Test Folder: {folder_name} (ID: {folder_id})")
    
    q_imgs = f"'{folder_id}' in parents and (mimeType contains 'image/') and trashed = false"
    img_res = sync.drive_service.files().list(q=q_imgs, fields="files(id, name)", pageSize=10).execute()
    test_files = img_res.get("files", [])
    if not test_files:
        print("No image files in target folder.")
        return
        
    print(f"Loaded {len(test_files)} test images from Drive.")
    
    # Init AI Analyzer
    analyzer = FaceAnalyzer(use_gpu=True)
    analyzer.initialize()
    
    # Load Templates
    embeddings_data = db.get_all_embeddings()
    template_embs = embeddings_data["embeddings"]
    template_names = embeddings_data["names"]
    template_ids = embeddings_data["staff_ids"]
    template_thresh = embeddings_data["personal_thresholds"]
    
    # -------------------------------------------------------------
    # 🧪 TEST 1: ORIGINAL SEQUENTIAL PROCESSING
    # -------------------------------------------------------------
    print("\n--- Running Test 1: Original Sequential Processing ---")
    t0_seq = time.time()
    seq_dl_times = []
    seq_ai_times = []
    
    for idx, f in enumerate(test_files):
        f_id = f['id']
        f_name = f['name']
        
        # 1. Download
        t_dl_start = time.time()
        img_bytes, dl_time, _ = sync.download_image_bytes_with_stats(f_id, f_name)
        seq_dl_times.append(time.time() - t_dl_start)
        
        # 2. Decode
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 3. AI Scan
        t_ai_start = time.time()
        faces = analyzer.get_faces_optimized(img)
        if faces and len(faces) > 0:
            det_embs = np.array([fc.embedding for fc in faces])
            analyzer.match_faces_matrix(det_embs, template_embs, template_names, template_ids, threshold=0.50, template_thresholds=template_thresh)
        seq_ai_times.append(time.time() - t_ai_start)
        print(f"[SEQ {idx+1}/{len(test_files)}] {f_name} | DL: {seq_dl_times[-1]:.2f}s | AI: {seq_ai_times[-1]:.2f}s | Faces: {len(faces) if faces else 0}")
        
    total_time_seq = time.time() - t0_seq
    print(f"==> Total Time (Original Sequential): {total_time_seq:.2f}s (Avg: {total_time_seq/len(test_files):.2f}s/image)")
    
    # -------------------------------------------------------------
    # 🧪 TEST 2: PROPOSED PREFETCH PIPELINE (PRODUCER-CONSUMER)
    # -------------------------------------------------------------
    print("\n--- Running Test 2: Proposed Parallel Prefetch Pipeline ---")
    t0_pipe = time.time()
    img_queue = queue.Queue(maxsize=3)
    stop_event = threading.Event()
    
    def download_worker():
        for f in test_files:
            if stop_event.is_set():
                break
            f_id = f['id']
            f_name = f['name']
            t_start = time.time()
            img_bytes, dl_time, _ = sync.download_image_bytes_with_stats(f_id, f_name)
            img = None
            if img_bytes:
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            img_queue.put({"id": f_id, "name": f_name, "image": img, "dl_time": time.time() - t_start})
        img_queue.put(None) # Sentinel
        
    dl_thread = threading.Thread(target=download_worker, daemon=True)
    dl_thread.start()
    
    pipe_count = 0
    while True:
        item = img_queue.get()
        if item is None:
            break
        pipe_count += 1
        f_name = item["name"]
        img = item["image"]
        dl_t = item["dl_time"]
        
        t_ai_start = time.time()
        faces = []
        if img is not None:
            faces = analyzer.get_faces_optimized(img)
            if faces and len(faces) > 0:
                det_embs = np.array([fc.embedding for fc in faces])
                analyzer.match_faces_matrix(det_embs, template_embs, template_names, template_ids, threshold=0.50, template_thresholds=template_thresh)
        ai_t = time.time() - t_ai_start
        print(f"[PIPE {pipe_count}/{len(test_files)}] {f_name} | DL: {dl_t:.2f}s | AI: {ai_t:.2f}s | Faces: {len(faces) if faces else 0}")
        
    dl_thread.join()
    total_time_pipe = time.time() - t0_pipe
    print(f"==> Total Time (Proposed Pipeline): {total_time_pipe:.2f}s (Avg: {total_time_pipe/len(test_files):.2f}s/image)")
    
    # -------------------------------------------------------------
    # 📊 SUMMARY COMPARISON
    # -------------------------------------------------------------
    speedup = total_time_seq / total_time_pipe if total_time_pipe > 0 else 1.0
    pct_faster = ((total_time_seq - total_time_pipe) / total_time_seq) * 100
    print("\n==================================================")
    print(f"📊 BENCHMARK RESULTS ({len(test_files)} Real Photos):")
    print(f"   - Original Sequential: {total_time_seq:.2f}s ({total_time_seq/len(test_files):.2f}s/image)")
    print(f"   - Proposed Pipeline:   {total_time_pipe:.2f}s ({total_time_pipe/len(test_files):.2f}s/image)")
    print(f"   - Speedup Factor:      {speedup:.2f}x Faster! ({pct_faster:.1f}% time reduced)")
    print("==================================================")

if __name__ == "__main__":
    run_benchmark()
