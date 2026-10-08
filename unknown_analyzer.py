import re
import time
import logging
import numpy as np
from datetime import datetime

logger = logging.getLogger("FaceSearchApp")

def extract_thai_year(photo_date, event_name=""):
    """
    สกัดปี พ.ศ. จากวันที่ photo_date หรือ event_name
    คืนค่าเป็นสตริงปี พ.ศ. เช่น '2569', '2568'
    """
    # 1. พยายามดึงจาก photo_date (เช่น '2026-05-12' -> 2026 + 543 = 2569)
    if photo_date and isinstance(photo_date, str):
        match = re.match(r'^(\d{4})', photo_date.strip())
        if match:
            year_int = int(match.group(1))
            if 1950 <= year_int <= 2100: # ปี ค.ศ.
                return str(year_int + 543)
            elif 2500 <= year_int <= 2650: # ถ้าเป็นปี พ.ศ. อยู่แล้ว
                return str(year_int)

    # 2. พยายามดึงจาก event_name (เช่น 'ภาพกิจกรรม 2568' หรือ 'เฉลิมพระชนมพรรษา 2563')
    if event_name and isinstance(event_name, str):
        match = re.search(r'(25\d{2})', event_name)
        if match:
            return match.group(1)
        # กรณีระบุเป็น ค.ศ. ในชื่อโฟลเดอร์ เช่น 2026
        match_ad = re.search(r'(20\d{2})', event_name)
        if match_ad:
            return str(int(match_ad.group(1)) + 543)

    return "ไม่ระบุปี"

def cluster_unknown_faces(face_items, sim_threshold=0.65, min_cluster_size=1, progress_callback=None):
    """
    จัดกลุ่มใบหน้านิรนามด้วย High-Performance Vectorized C/BLAS Clustering
    face_items: ลิสต์ของดิกชันนารี [{photo_id, face_index, embedding, photo_date, event_name, bbox}]
    sim_threshold: ค่าความคล้ายคลึงขั้นต่ำสำหรับรวมกลุ่ม (แนะนำ 0.65 ขึ้นไปเพื่อป้องกัน Drift)
    min_cluster_size: ขนาดกลุ่มขั้นต่ำที่จะนำไปบันทึก
    progress_callback: ฟังก์ชัน callback รายงานความคืบหน้า (current, total, num_clusters, speed, eta_sec)
    คืนค่า: (clusters_data, members_data, year_stats_data)
    """
    if not face_items:
        return [], [], []

    t_start = time.time()
    logger.info(f"[UNKNOWN ANALYTICS] 🚀 เริ่มต้นวิเคราะห์จัดกลุ่ม {len(face_items):,} ใบหน้านิรนาม (Threshold: {sim_threshold})...")

    # แปลง embedding bytes เป็น numpy matrix
    embeddings = []
    valid_items = []
    for item in face_items:
        emb_raw = item.get("embedding")
        if isinstance(emb_raw, bytes) and len(emb_raw) == 512 * 4:
            emb = np.frombuffer(emb_raw, dtype=np.float32)
            # Normalize เวกเตอร์ล่วงหน้าเพื่อให้ dot product กลายเป็น Cosine Similarity ทันที
            norm = np.linalg.norm(emb)
            if norm > 0:
                embeddings.append(emb / norm)
                valid_items.append(item)

    if not embeddings:
        logger.warning("[UNKNOWN ANALYTICS] ⚠️ ไม่พบเวกเตอร์ใบหน้าที่ถูกต้อง")
        return [], [], []

    emb_matrix = np.ascontiguousarray(np.array(embeddings, dtype=np.float32)) # Shape: (N, 512)
    num_faces = len(valid_items)
    logger.info(f"[UNKNOWN ANALYTICS] Matrix Shape: {emb_matrix.shape} | พร้อมเริ่มกระบวนการจัดกลุ่มด้วย Vectorized C-Engine...")

    # Fast Vectorized Pre-allocated Centroid Matrix
    # จองพื้นที่ล่วงหน้าเพื่อหลีกเลี่ยงการ allocate ใหม่ในลูป
    init_capacity = min(max(num_faces // 10, 2048), 65536)
    centroids_matrix = np.zeros((init_capacity, 512), dtype=np.float32)
    centroids_sums = np.zeros((init_capacity, 512), dtype=np.float32)
    cluster_members = [] # list of lists of (face_idx, sim)
    num_clusters = 0

    log_interval = 10000
    last_log_time = time.time()

    for idx in range(num_faces):
        emb = emb_matrix[idx]
        best_cluster_idx = -1
        best_sim = -1.0

        if num_clusters > 0:
            # คำนวณ Cosine Similarity ผ่าน BLAS Matrix-Vector Dot Product โดยตรง
            sims = np.dot(centroids_matrix[:num_clusters], emb)
            max_idx = int(np.argmax(sims))
            if sims[max_idx] >= sim_threshold:
                best_cluster_idx = max_idx
                best_sim = float(sims[max_idx])

        if best_cluster_idx >= 0:
            cluster_members[best_cluster_idx].append((idx, best_sim))
            # อัปเดต running sum และ normalize centroid ใหม่
            centroids_sums[best_cluster_idx] += emb
            s = centroids_sums[best_cluster_idx]
            s_norm = np.linalg.norm(s)
            centroids_matrix[best_cluster_idx] = s / (s_norm if s_norm > 0 else 1.0)
        else:
            # ตรวจสอบว่าต้องขยายความจุ Matrix หรือไม่
            if num_clusters >= centroids_matrix.shape[0]:
                new_cap = centroids_matrix.shape[0] * 2
                new_centroids = np.zeros((new_cap, 512), dtype=np.float32)
                new_centroids[:num_clusters] = centroids_matrix
                centroids_matrix = new_centroids

                new_sums = np.zeros((new_cap, 512), dtype=np.float32)
                new_sums[:num_clusters] = centroids_sums
                centroids_sums = new_sums

            centroids_matrix[num_clusters] = emb
            centroids_sums[num_clusters] = emb.copy()
            cluster_members.append([(idx, 1.0)])
            num_clusters += 1

        # รายงานความคืบหน้า (Real-time Progress Logging)
        now = time.time()
        if (idx + 1) % log_interval == 0 or (idx + 1) == num_faces or (now - last_log_time >= 5.0):
            last_log_time = now
            elapsed = now - t_start
            speed = (idx + 1) / elapsed if elapsed > 0 else 0
            rem_faces = num_faces - (idx + 1)
            eta_sec = rem_faces / speed if speed > 0 else 0
            pct = ((idx + 1) / num_faces) * 100.0

            logger.info(
                f"[UNKNOWN ANALYTICS] ⏳ ความคืบหน้า: {idx+1:,} / {num_faces:,} ใบหน้า ({pct:.1f}%) "
                f"| กลุ่มที่พบ: {num_clusters:,} กลุ่ม | ความเร็ว: {speed:,.0f} หน้า/วินาที | ETA: {eta_sec:.0f}s"
            )
            if progress_callback:
                try:
                    progress_callback(idx + 1, num_faces, num_clusters, speed, eta_sec)
                except Exception:
                    pass

    clustering_time = max(time.time() - t_start, 0.001)
    avg_speed = num_faces / clustering_time
    logger.info(
        f"[UNKNOWN ANALYTICS] ⚡ จัดกลุ่มเสร็จสิ้นใน {clustering_time:.2f}s "
        f"ได้ทั้งหมด {num_clusters:,} กลุ่ม (ความเร็วเฉลี่ย: {avg_speed:,.0f} หน้า/วินาที)"
    )

    # กรองเฉพาะ Cluster ที่มีขนาดตามเงื่อนไข และจัดทำโครงสร้างข้อมูลสำหรับบันทึก DB
    clusters_data = []
    members_data = []
    year_stats_data = []

    # เรียงลำดับกลุ่มจากคนที่รูปเยอะสุดไปหาน้อยสุด
    cluster_members.sort(key=len, reverse=True)

    cluster_serial = 1
    for members_indices in cluster_members:
        if len(members_indices) < min_cluster_size:
            continue

        cid = f"UNK_{cluster_serial:05d}"
        cluster_serial += 1

        # สรุปข้อมูลสมาชิกในคลัสเตอร์
        seen_photos = set()
        seen_events = set()
        years_count = {} # {year: count}
        year_rep = {} # {year: (photo_id, face_idx, max_area)}

        best_rep_photo = ""
        best_rep_face_idx = 0
        best_rep_bbox = []
        max_rep_area = -1.0

        for f_idx_local, conf in members_indices:
            item = valid_items[f_idx_local]
            pid = item["photo_id"]
            f_idx = item["face_index"]
            bbox = item.get("bbox", [0, 0, 0, 0])
            p_date = item.get("photo_date", "")
            e_name = item.get("event_name", "")

            thai_year = extract_thai_year(p_date, e_name)
            seen_photos.add(pid)
            if e_name:
                seen_events.add(e_name)

            years_count[thai_year] = years_count.get(thai_year, 0) + 1

            # คำนวณขนาด Bounding Box เพื่อหารูปหน้าตัวแทนที่คมชัดที่สุด
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) if len(bbox) == 4 else 0
            if area > max_rep_area:
                max_rep_area = area
                best_rep_photo = pid
                best_rep_face_idx = f_idx
                best_rep_bbox = bbox

            if thai_year not in year_rep or area > year_rep[thai_year][2]:
                year_rep[thai_year] = (pid, f_idx, area)

            members_data.append({
                "cluster_id": cid,
                "photo_id": pid,
                "face_index": f_idx,
                "year": thai_year,
                "event_name": e_name,
                "confidence": round(conf, 4)
            })

        # สรุปสถิติปี
        valid_years = sorted([y for y in years_count.keys() if y != "ไม่ระบุปี"])
        first_year = valid_years[0] if valid_years else "ไม่ระบุปี"
        last_year = valid_years[-1] if valid_years else "ไม่ระบุปี"
        active_years_str = ", ".join(sorted(years_count.keys(), reverse=True))

        for y, count in years_count.items():
            rep_p, rep_fi, _ = year_rep.get(y, ("", 0, 0))
            year_stats_data.append({
                "cluster_id": cid,
                "year": y,
                "photo_count": count,
                "rep_photo_id": rep_p,
                "rep_face_index": rep_fi
            })

        clusters_data.append({
            "cluster_id": cid,
            "photo_count": len(seen_photos),
            "event_count": len(seen_events),
            "rep_photo_id": best_rep_photo,
            "rep_face_index": best_rep_face_idx,
            "rep_bbox": best_rep_bbox,
            "first_seen_year": first_year,
            "last_seen_year": last_year,
            "active_years": active_years_str
        })

    logger.info(f"[UNKNOWN ANALYTICS] ✅ จัดทำผลวิเคราะห์สำเร็จ: {len(clusters_data)} กลุ่มบุคคลนิรนาม, {len(members_data)} รายการสมาชิก, {len(year_stats_data)} สถิติรายปี")
    return clusters_data, members_data, year_stats_data
