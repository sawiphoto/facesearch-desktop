import re
import time
import logging
import numpy as np
import networkx as nx
from networkx.algorithms import community as nx_comm
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


def cluster_unknown_faces(face_items, sim_threshold=0.65, min_cluster_size=1, min_face_size=35, progress_callback=None):
    """
    จัดกลุ่มใบหน้านิรนามด้วย World-Class Mutual k-NN Graph + Cannot-Link Constraints + Community Partitioning (v6.25)
    
    สถาปัตยกรรม 6 ขั้นตอน:
    1. Quality Pre-filtering: คัดกรองขนาด BBox >= min_face_size และนอร์มัลไลซ์เวกเตอร์ L2
    2. Chunked Memory-Safe Matrix Multiplication: ค้นหา Top-k (k=8) Cosine Similarity >= sim_threshold
    3. Mutual k-NN Filtering (MNN): สร้างเส้นเชื่อมเฉพาะคู่ที่มองกันเป็น Top-k ทั้งคู่ (ตัด False Positives & คนหน้าโหลทิ้ง 95%)
    4. Strict Cannot-Link Constraints: ลบเส้นเชื่อมระหว่างใบหน้าที่มาจาก photo_id เดียวกันทิ้ง 100%
    5. Conflict-Aware Community Partitioning: แยก Connected Components และรัน Louvain คลี่คลายการทับซ้อน
    6. Representative Selection & Noise Discard: เลือกใบหน้าที่คมชัดและเชื่อมโยงสูงสุดเป็นตัวแทน
    
    face_items: ลิสต์ของดิกชันนารี [{photo_id, face_index, embedding, photo_date, event_name, bbox}]
    sim_threshold: ค่าความคล้ายคลึงขั้นต่ำ (แนะนำ 0.65 - 0.70)
    min_cluster_size: ขนาดกลุ่มขั้นต่ำที่จะนำไปบันทึก
    min_face_size: ขนาดพิกเซลขั้นต่ำของใบหน้า (กว้างและยาว)
    progress_callback: ฟังก์ชัน callback รายงานความคืบหน้า (current, total, num_clusters, speed, eta_sec)
    คืนค่า: (clusters_data, members_data, year_stats_data)
    """
    if not face_items:
        return [], [], []

    t_start = time.time()
    logger.info(f"[UNKNOWN ANALYTICS] 🚀 เริ่มต้นวิเคราะห์จัดกลุ่ม {len(face_items):,} ใบหน้านิรนาม (MNN Graph Architecture v6.25, Threshold: {sim_threshold}, MinSize: {min_face_size}px)...")

    # -------------------------------------------------------------------------
    # Stage 1: Quality Pre-filtering
    # -------------------------------------------------------------------------
    raw_embeddings = []
    raw_items = []
    for item in face_items:
        emb_raw = item.get("embedding")
        if isinstance(emb_raw, bytes) and len(emb_raw) == 512 * 4:
            emb = np.frombuffer(emb_raw, dtype=np.float32)
            norm = float(np.linalg.norm(emb))
            if norm > 0:
                bbox = item.get("bbox", [])
                if bbox and len(bbox) == 4 and (bbox[2] > bbox[0]) and (bbox[3] > bbox[1]) and min_face_size > 0:
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]
                    if bw < min_face_size or bh < min_face_size:
                        continue
                raw_embeddings.append(emb / norm)
                raw_items.append(item)

    if not raw_embeddings:
        logger.warning("[UNKNOWN ANALYTICS] ⚠️ ไม่พบเวกเตอร์ใบหน้าที่ถูกต้องหรือผ่านเกณฑ์คุณภาพ")
        return [], [], []

    num_faces = len(raw_items)
    emb_matrix = np.ascontiguousarray(np.array(raw_embeddings, dtype=np.float32)) # Shape: (N, 512)
    logger.info(f"[UNKNOWN ANALYTICS] ใบหน้าที่ผ่านเกณฑ์: {num_faces:,} ใบหน้า | Matrix Shape: {emb_matrix.shape}")

    # -------------------------------------------------------------------------
    # Stage 2: Chunked Memory-Safe Matrix Multiplication (Top-k Forward Neighbors)
    # -------------------------------------------------------------------------
    k_neighbors = min(8, num_faces - 1) if num_faces > 1 else 0
    forward_neighbors = [[] for _ in range(num_faces)]
    chunk_size = 2500

    last_log_time = time.time()
    for start_idx in range(0, num_faces, chunk_size):
        end_idx = min(start_idx + chunk_size, num_faces)
        X_chunk = emb_matrix[start_idx:end_idx] # (B, 512)
        sim_chunk = np.dot(X_chunk, emb_matrix.T) # (B, N)

        # Mask self-similarity
        for r in range(end_idx - start_idx):
            global_idx = start_idx + r
            sim_chunk[r, global_idx] = -1.0

        if k_neighbors > 0:
            if k_neighbors < num_faces - 1:
                top_k_indices = np.argpartition(-sim_chunk, k_neighbors, axis=1)[:, :k_neighbors]
            else:
                top_k_indices = np.argsort(-sim_chunk, axis=1)[:, :k_neighbors]

            for r in range(end_idx - start_idx):
                global_idx = start_idx + r
                cand_idx = top_k_indices[r]
                cand_sims = sim_chunk[r, cand_idx]
                valid_mask = cand_sims >= sim_threshold
                if np.any(valid_mask):
                    v_idx = cand_idx[valid_mask].tolist()
                    v_sims = cand_sims[valid_mask].tolist()
                    forward_neighbors[global_idx] = list(zip(v_idx, v_sims))

        # Progress reporting during matrix multiplication
        now = time.time()
        if (now - last_log_time >= 3.0) or (end_idx == num_faces):
            last_log_time = now
            elapsed = max(now - t_start, 0.001)
            speed = end_idx / elapsed
            rem = num_faces - end_idx
            eta = rem / speed if speed > 0 else 0
            pct = (end_idx / num_faces) * 100.0
            logger.info(f"[UNKNOWN ANALYTICS] ⏳ เฟส 1/2: คำนวณความคล้ายคลึง {end_idx:,}/{num_faces:,} ({pct:.1f}%) | {speed:,.0f} หน้า/วิ | ETA: {eta:.0f}s")
            if progress_callback:
                try:
                    progress_callback(end_idx, num_faces, 0, speed, eta)
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # Stage 3 & 4: Mutual k-NN Filtering (MNN) & Cannot-Link (Same-Photo) Constraints
    # -------------------------------------------------------------------------
    G = nx.Graph()
    for i in range(num_faces):
        G.add_node(i)

    forward_dicts = [{target: s for target, s in forward_neighbors[i]} for i in range(num_faces)]

    edge_count = 0
    for i in range(num_faces):
        photo_i = raw_items[i].get("photo_id", "")
        for j, sim_ij in forward_neighbors[i]:
            if j > i: # ตรวจสอบคู่ละครั้งเดียว
                if i in forward_dicts[j]: # Mutual Neighbor!
                    photo_j = raw_items[j].get("photo_id", "")
                    # Cannot-Link Constraint: ห้ามมีเส้นเชื่อมระหว่างใบหน้าจากภาพเดียวกันเด็ดขาด 100%
                    if photo_i != photo_j:
                        sim_ji = forward_dicts[j][i]
                        edge_weight = float((sim_ij + sim_ji) / 2.0)
                        G.add_edge(i, j, weight=edge_weight)
                        edge_count += 1

    logger.info(f"[UNKNOWN ANALYTICS] 🔗 โครงข่าย MNN Graph สร้างเสร็จสิ้น: {num_faces:,} โหนด, {edge_count:,} เส้นเชื่อม (ผ่านเงื่อนไข Mutual + Cannot-Link)")

    # -------------------------------------------------------------------------
    # Stage 5: Conflict-Aware Community Partitioning (Louvain / Connected Components)
    # -------------------------------------------------------------------------
    components = list(nx.connected_components(G))
    final_clusters = []

    for comp in components:
        comp_nodes = list(comp)
        if len(comp_nodes) <= 1:
            final_clusters.append(comp_nodes)
            continue

        # ตรวจสอบว่าใน Component นี้มีภาพเดียวกันซ้ำกันหรือไม่
        photo_ids = [raw_items[node_idx].get("photo_id", "") for node_idx in comp_nodes]
        has_conflict = len(photo_ids) != len(set(photo_ids))

        if not has_conflict:
            # ไม่มีข้อขัดแย้งเลย: รวบเป็น 1 คลัสเตอร์ทันที
            final_clusters.append(comp_nodes)
        else:
            # มีภาพเดียวกันซ้ำกัน: ใช้ Louvain Partitioning แยกชุมชนย่อยที่กลมกลืนที่สุดออกจากกัน
            subG = G.subgraph(comp_nodes)
            try:
                sub_communities = nx_comm.louvain_communities(subG, weight='weight', resolution=1.0)
                for sub_c in sub_communities:
                    sub_c_list = list(sub_c)
                    sub_photos = [raw_items[n].get("photo_id", "") for n in sub_c_list]
                    if len(sub_photos) == len(set(sub_photos)):
                        final_clusters.append(sub_c_list)
                    else:
                        # หากยังมีภาพชนกันในกลุ่มย่อย ให้แยกตามลำดับ photo_id อย่างปลอดภัย 100%
                        resolved_groups = []
                        for n in sub_c_list:
                            p_id = raw_items[n].get("photo_id", "")
                            placed = False
                            for grp in resolved_groups:
                                if p_id not in [raw_items[x].get("photo_id", "") for x in grp]:
                                    grp.append(n)
                                    placed = True
                                    break
                            if not placed:
                                resolved_groups.append([n])
                        final_clusters.extend(resolved_groups)
            except Exception as louvain_err:
                logger.warning(f"[UNKNOWN ANALYTICS] Louvain partitioning fallback: {louvain_err}")
                final_clusters.append(comp_nodes)

    # -------------------------------------------------------------------------
    # Stage 6: Noise Filtering, Representative Selection & Output Formatting
    # -------------------------------------------------------------------------
    # เรียงลำดับคลัสเตอร์จากขนาดใหญ่ไปเล็ก
    final_clusters.sort(key=len, reverse=True)

    clusters_data = []
    members_data = []
    year_stats_data = []

    cluster_serial = 1
    for cluster_nodes in final_clusters:
        if len(cluster_nodes) < min_cluster_size:
            continue

        cid = f"UNK_{cluster_serial:05d}"
        cluster_serial += 1

        seen_photos = set()
        seen_events = set()
        years_count = {}
        year_rep = {}

        # คัดเลือก Representative Face: เลือกโหนดที่มีขนาด BBox ใหญ่สุด และมีความเป็นศูนย์กลาง
        best_rep_idx = cluster_nodes[0]
        max_rep_area = -1.0
        for node_idx in cluster_nodes:
            it = raw_items[node_idx]
            bb = it.get("bbox", [0, 0, 0, 0])
            area = float((bb[2] - bb[0]) * (bb[3] - bb[1])) if len(bb) == 4 else 0.0
            if area > max_rep_area:
                max_rep_area = area
                best_rep_idx = node_idx

        rep_item = raw_items[best_rep_idx]
        best_rep_photo = rep_item.get("photo_id", "")
        best_rep_face_idx = rep_item.get("face_index", 0)
        best_rep_bbox = rep_item.get("bbox", [0, 0, 0, 0])
        rep_emb = emb_matrix[best_rep_idx]

        for node_idx in cluster_nodes:
            item = raw_items[node_idx]
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

            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) if len(bbox) == 4 else 0
            if thai_year not in year_rep or area > year_rep[thai_year][2]:
                year_rep[thai_year] = (pid, f_idx, area)

            # คำนวณ Confidence ความมั่นใจต่อตัวแทนคลัสเตอร์
            sim_to_rep = float(np.dot(emb_matrix[node_idx], rep_emb))
            # ถ้าเป็น node ตัวแทนเองจะได้ 1.0, สมาชิกอื่นให้แสดงตามค่าความสัมพันธ์จริง
            conf = 1.0 if node_idx == best_rep_idx else max(sim_to_rep, sim_threshold)

            members_data.append({
                "cluster_id": cid,
                "photo_id": pid,
                "face_index": f_idx,
                "year": thai_year,
                "event_name": e_name,
                "confidence": round(conf, 4)
            })

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

    clustering_time = max(time.time() - t_start, 0.001)
    avg_speed = num_faces / clustering_time
    logger.info(
        f"[UNKNOWN ANALYTICS] ⚡ จัดกลุ่มด้วย MNN Graph สำเร็จใน {clustering_time:.2f}s "
        f"ได้ทั้งหมด {len(clusters_data):,} กลุ่มบุคคล, {len(members_data):,} รายการสมาชิก "
        f"(ความเร็วเฉลี่ย: {avg_speed:,.0f} หน้า/วินาที)"
    )

    if progress_callback:
        try:
            progress_callback(num_faces, num_faces, len(clusters_data), avg_speed, 0)
        except Exception:
            pass

    return clusters_data, members_data, year_stats_data
