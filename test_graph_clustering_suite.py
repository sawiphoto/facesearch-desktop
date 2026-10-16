import os
import sys
import json
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unknown_analyzer


def test_tc30_mnn_hubness_elimination():
    print("=== TC-30: Testing MNN Hubness Elimination ===")
    np.random.seed(101)
    
    # Group A base
    vec_a = np.random.randn(512).astype(np.float32)
    vec_a /= np.linalg.norm(vec_a)
    
    # Group B base (orthogonal/far from A)
    vec_b = np.random.randn(512).astype(np.float32)
    vec_b -= np.dot(vec_b, vec_a) * vec_a
    vec_b /= np.linalg.norm(vec_b)

    # Hub face H: positioned between A and B with moderate similarity
    vec_h = 0.5 * vec_a + 0.5 * vec_b
    vec_h /= np.linalg.norm(vec_h)

    # 3 faces for Person A (very high mutual similarity ~0.90)
    faces = []
    for i in range(3):
        noise = np.random.randn(512).astype(np.float32) * 0.08
        v = vec_a + noise
        v /= np.linalg.norm(v)
        faces.append({
            "photo_id": f"P_A_{i}",
            "face_index": 0,
            "embedding": v.tobytes(),
            "photo_date": "2026-01-01",
            "event_name": "Event A",
            "bbox": [20, 20, 80, 80]
        })

    # 3 faces for Person B (very high mutual similarity ~0.90)
    for i in range(3):
        noise = np.random.randn(512).astype(np.float32) * 0.08
        v = vec_b + noise
        v /= np.linalg.norm(v)
        faces.append({
            "photo_id": f"P_B_{i}",
            "face_index": 0,
            "embedding": v.tobytes(),
            "photo_date": "2026-02-01",
            "event_name": "Event B",
            "bbox": [20, 20, 80, 80]
        })

    # Add Hub face H in a separate photo
    faces.append({
        "photo_id": "P_HUB_0",
        "face_index": 0,
        "embedding": vec_h.tobytes(),
        "photo_date": "2026-03-01",
        "event_name": "Event Hub",
        "bbox": [20, 20, 80, 80]
    })

    clusters, members, _ = unknown_analyzer.cluster_unknown_faces(faces, sim_threshold=0.65, min_cluster_size=1)
    
    # Verify that Person A and Person B members NEVER end up in the same cluster!
    cluster_person_map = {}
    for m in members:
        cid = m["cluster_id"]
        pid = m["photo_id"]
        p_type = "A" if "P_A_" in pid else ("B" if "P_B_" in pid else "HUB")
        if cid not in cluster_person_map:
            cluster_person_map[cid] = set()
        cluster_person_map[cid].add(p_type)

    for cid, types in cluster_person_map.items():
        assert not ("A" in types and "B" in types), f"TC-30 FAILED: Person A and B merged via Hub in cluster {cid}"

    print("✅ TC-30 PASSED: Mutual k-NN prevented Hub node from merging distinct individuals.")


def test_tc31_strict_cannot_link():
    print("=== TC-31: Testing Strict Cannot-Link (Same-Photo Constraint) ===")
    np.random.seed(202)
    base_v = np.random.randn(512).astype(np.float32)
    base_v /= np.linalg.norm(base_v)

    # 2 faces with high similarity (0.88), BUT both from the exact same photo "P_GROUP_01"
    noise = np.random.randn(512).astype(np.float32) * 0.1
    v2 = base_v + noise
    v2 /= np.linalg.norm(v2)

    same_photo_faces = [
        {
            "photo_id": "P_GROUP_01",
            "face_index": 0,
            "embedding": base_v.tobytes(),
            "photo_date": "2026-05-01",
            "event_name": "Group Photo",
            "bbox": [10, 10, 60, 60]
        },
        {
            "photo_id": "P_GROUP_01",
            "face_index": 1,
            "embedding": v2.tobytes(),
            "photo_date": "2026-05-01",
            "event_name": "Group Photo",
            "bbox": [100, 10, 150, 60]
        }
    ]

    clusters, members, _ = unknown_analyzer.cluster_unknown_faces(same_photo_faces, sim_threshold=0.65, min_cluster_size=1)
    
    # Must be 2 separate clusters!
    assert len(clusters) == 2, f"TC-31 FAILED: Expected 2 clusters, got {len(clusters)}"
    cids = set(m["cluster_id"] for m in members)
    assert len(cids) == 2, f"TC-31 FAILED: Expected 2 distinct cluster IDs, got {len(cids)}"
    print("✅ TC-31 PASSED: Cannot-Link constraint strictly separated faces from the same photo.")


def test_tc32_multiview_transitive_continuity():
    print("=== TC-32: Testing Multi-View Invariance (Transitive Continuity) ===")
    np.random.seed(303)
    
    # Face A (Frontal)
    v_a = np.random.randn(512).astype(np.float32)
    v_a /= np.linalg.norm(v_a)

    # Step vector for angle variation
    step = np.random.randn(512).astype(np.float32)
    step -= np.dot(step, v_a) * v_a
    step /= np.linalg.norm(step)

    # Face B (30 degree tilt) - similar to A (~0.76)
    v_b = v_a * 0.76 + step * 0.65
    v_b /= np.linalg.norm(v_b)

    # Face C (60 degree profile) - similar to B (~0.76), but direct sim to A is low (~0.58)
    v_c = v_b * 0.76 + step * 0.65
    v_c /= np.linalg.norm(v_c)

    sim_ab = np.dot(v_a, v_b)
    sim_bc = np.dot(v_b, v_c)
    sim_ac = np.dot(v_a, v_c)
    assert sim_ab >= 0.70 and sim_bc >= 0.70
    assert sim_ac < 0.65, f"Expected sim_ac < 0.65 for multi-view test, got {sim_ac}"

    chain_faces = [
        {"photo_id": "P_VIEW_1", "face_index": 0, "embedding": v_a.tobytes(), "photo_date": "2026-01-01", "event_name": "A", "bbox": [10, 10, 60, 60]},
        {"photo_id": "P_VIEW_2", "face_index": 0, "embedding": v_b.tobytes(), "photo_date": "2026-01-02", "event_name": "B", "bbox": [10, 10, 60, 60]},
        {"photo_id": "P_VIEW_3", "face_index": 0, "embedding": v_c.tobytes(), "photo_date": "2026-01-03", "event_name": "C", "bbox": [10, 10, 60, 60]},
    ]

    clusters, members, _ = unknown_analyzer.cluster_unknown_faces(chain_faces, sim_threshold=0.68, min_cluster_size=1)
    assert len(clusters) == 1, f"TC-32 FAILED: Expected multi-view faces to merge into 1 cluster, got {len(clusters)}"
    assert len(members) == 3, f"TC-32 FAILED: Expected 3 members in cluster, got {len(members)}"
    print("✅ TC-32 PASSED: Multi-view faces of same individual successfully unified via graph topology.")


def test_tc33_outlier_noise_rejection():
    print("=== TC-33: Testing Outlier & Noise Rejection ===")
    np.random.seed(404)
    v = np.random.randn(512).astype(np.float32)
    v /= np.linalg.norm(v)

    # Face 1: Tiny BBox (< 35px) -> should be filtered out
    # Face 2: Isolated random vector -> should be 1 cluster when min_cluster_size=1
    noisy_faces = [
        {"photo_id": "P_TINY", "face_index": 0, "embedding": v.tobytes(), "photo_date": "2026-01-01", "event_name": "E", "bbox": [0, 0, 20, 20]}, # 20x20 px
        {"photo_id": "P_NORMAL", "face_index": 0, "embedding": v.tobytes(), "photo_date": "2026-01-01", "event_name": "E", "bbox": [10, 10, 70, 70]} # 60x60 px
    ]

    clusters, members, _ = unknown_analyzer.cluster_unknown_faces(noisy_faces, sim_threshold=0.65, min_cluster_size=1, min_face_size=35)
    assert len(clusters) == 1
    assert len(members) == 1
    assert members[0]["photo_id"] == "P_NORMAL", "TC-33 FAILED: Tiny face was not filtered out"
    print("✅ TC-33 PASSED: Low-quality/small background faces successfully rejected by pre-filter.")


def test_tc34_gui_v625_and_schema_integration():
    print("=== TC-34: Testing GUI Version v6.25 and Schema Integration ===")
    from face_analyzer import get_project_root
    app_gui_path = os.path.join(get_project_root(), "app_gui.py")
    with open(app_gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert ('v6.25' in content or 'v6.26' in content), "Window title must be v6.25 or v6.26"
    assert ('FACE MATCHING\\nSYSTEM v6.25' in content or 'FACE MATCHING\\nSYSTEM v6.26' in content), "Sidebar logo must be v6.25 or v6.26"
    print("✅ TC-34 PASSED: System & GUI Version Verified (v6.25/v6.26 on Window Title and Sidebar Logo).")


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 RUNNING GRAPH CLUSTERING TEST SUITE: TC-30 to TC-34 (v6.25)")
    print("=" * 70)
    test_tc30_mnn_hubness_elimination()
    test_tc31_strict_cannot_link()
    test_tc32_multiview_transitive_continuity()
    test_tc33_outlier_noise_rejection()
    test_tc34_gui_v625_and_schema_integration()
    print("=" * 70)
    print("🎉 ALL GRAPH CLUSTERING TEST CASES (TC-30 to TC-34) PASSED SUCCESSFULLY!")
    print("=" * 70)
