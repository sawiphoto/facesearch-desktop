import os
import sys
import zipfile
import requests
import numpy as np
import cv2
import logging
import warnings
from tqdm import tqdm
from insightface.app import FaceAnalysis

# ลงทะเบียนโฟลเดอร์ CUDA และ python nvidia package bin เข้า DLL Search Path สำหรับ Python 3.8+
cuda_path = os.environ.get("CUDA_PATH")
if cuda_path:
    cuda_bin = os.path.join(cuda_path, "bin")
    if os.path.exists(cuda_bin) and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(cuda_bin)
        except Exception:
            pass

# ค้นหาและลงทะเบียนโฟลเดอร์ของแพ็คเกจ nvidia (cudnn, cublas, etc.) ใน venv
project_root = os.path.dirname(os.path.abspath(__file__))
site_packages = os.path.join(project_root, "venv", "Lib", "site-packages")
if os.path.exists(site_packages) and hasattr(os, "add_dll_directory"):
    nvidia_dirs = [
        os.path.join(site_packages, "nvidia", "cudnn", "bin"),
        os.path.join(site_packages, "nvidia", "cublas", "bin"),
        os.path.join(site_packages, "nvidia", "cuda_nvrtc", "bin"),
        os.path.join(site_packages, "nvidia", "cuda_runtime", "bin"),
        os.path.join(site_packages, "nvidia", "cufft", "bin")
    ]
    for n_dir in nvidia_dirs:
        if os.path.exists(n_dir):
            try:
                os.add_dll_directory(n_dir)
            except Exception:
                pass

# พรีโหลด DLL ของ CUDA และ cuDNN เพื่อแก้บั๊ก Unicode Path ของ Windows (โฟลเดอร์ภาษาไทย)
try:
    import ctypes
    import onnxruntime as ort
    
    # 1. พรีโหลด CUDA Runtime
    cudart_dll = os.path.join(site_packages, "nvidia", "cuda_runtime", "bin", "cudart64_110.dll")
    if os.path.exists(cudart_dll):
        ctypes.CDLL(cudart_dll)

    # 2. พรีโหลด CUDA NVRTC
    nvrtc_dll = os.path.join(site_packages, "nvidia", "cuda_nvrtc", "bin", "nvrtc64_112_0.dll")
    nvrtc_builtins_dll = os.path.join(site_packages, "nvidia", "cuda_nvrtc", "bin", "nvrtc-builtins64_118.dll")
    if os.path.exists(nvrtc_dll):
        ctypes.CDLL(nvrtc_dll)
    if os.path.exists(nvrtc_builtins_dll):
        ctypes.CDLL(nvrtc_builtins_dll)

    # 3. พรีโหลด cuBLAS
    cublas_lt_dll = os.path.join(site_packages, "nvidia", "cublas", "bin", "cublasLt64_11.dll")
    cublas_dll = os.path.join(site_packages, "nvidia", "cublas", "bin", "cublas64_11.dll")
    if os.path.exists(cublas_lt_dll):
        ctypes.CDLL(cublas_lt_dll)
    if os.path.exists(cublas_dll):
        ctypes.CDLL(cublas_dll)

    # 4. พรีโหลด cuFFT
    cufft_dll = os.path.join(site_packages, "nvidia", "cufft", "bin", "cufft64_10.dll")
    if os.path.exists(cufft_dll):
        ctypes.CDLL(cufft_dll)

    # 5. พรีโหลด cuDNN
    cudnn_ops_dll = os.path.join(site_packages, "nvidia", "cudnn", "bin", "cudnn_ops_infer64_8.dll")
    cudnn_cnn_dll = os.path.join(site_packages, "nvidia", "cudnn", "bin", "cudnn_cnn_infer64_8.dll")
    cudnn_dll = os.path.join(site_packages, "nvidia", "cudnn", "bin", "cudnn64_8.dll")
    if os.path.exists(cudnn_ops_dll):
        ctypes.CDLL(cudnn_ops_dll)
    if os.path.exists(cudnn_cnn_dll):
        ctypes.CDLL(cudnn_cnn_dll)
    if os.path.exists(cudnn_dll):
        ctypes.CDLL(cudnn_dll)

    # 6. พรีโหลด ONNX Runtime GPU Shared และ CUDA Provider
    capi_dir = os.path.join(os.path.dirname(ort.__file__), "capi")
    shared_dll = os.path.join(capi_dir, "onnxruntime_providers_shared.dll")
    cuda_provider_dll = os.path.join(capi_dir, "onnxruntime_providers_cuda.dll")
    if os.path.exists(shared_dll):
        ctypes.CDLL(shared_dll)
    if os.path.exists(cuda_provider_dll):
        ctypes.CDLL(cuda_provider_dll)
except Exception:
    pass

# ซ่อนข้อความแจ้งเตือนเตือน CUDA/Execution Provider ของ ONNX Runtime ที่กวนสายตา
warnings.filterwarnings("ignore", category=UserWarning, module="onnxruntime")

logger = logging.getLogger("FaceSearchApp")

MODEL_ZIP_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip"

def get_project_root():
    return os.path.dirname(os.path.abspath(__file__))

def get_models_dir():
    return os.path.join(get_project_root(), "models")

def get_antelopev2_dir():
    return os.path.join(get_models_dir(), "antelopev2")

def check_and_download_model():
    """ตรวจสอบว่ามีไฟล์โมเดล antelopev2 หรือยัง ถ้าไม่มีจะดาวน์โหลดและแตกไฟล์โดยอัตโนมัติ"""
    model_dir = get_antelopev2_dir()
    os.makedirs(model_dir, exist_ok=True)
    
    # ไฟล์หลักๆ ที่จำเป็นสำหรับ antelopev2
    required_files = ["scrfd_10g_bnkps.onnx", "glintr100.onnx"]
    model_exists = all(os.path.exists(os.path.join(model_dir, f)) for f in required_files)
    
    if model_exists:
        logger.info("InsightFace antelopev2 model files are already present.")
        return True

    logger.warning("InsightFace antelopev2 model files not found. Starting automatic download...")
    zip_path = os.path.join(get_models_dir(), "antelopev2.zip")
    
    # 1. ดาวน์โหลดไฟล์ Zip
    try:
        response = requests.get(MODEL_ZIP_URL, stream=True, timeout=25)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        logger.info(f"Downloading model zip from: {MODEL_ZIP_URL}")
        logger.info(f"Total size: {total_size / (1024*1024):.2f} MB")
        
        with open(zip_path, 'wb') as f, tqdm(
            desc="Downloading antelopev2.zip",
            total=total_size,
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024*1024):
                size = f.write(data)
                bar.update(size)
                # ส่ง log ความคืบหน้าแบบร้อยละ
                if total_size > 0:
                    percent = (f.tell() / total_size) * 100
                    logger.info(f"Download progress: {percent:.1f}%")
        
        logger.info("Download completed successfully.")
    except Exception as e:
        logger.error(f"Error downloading model zip: {e}")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return False

    # 2. แตกไฟล์ Zip
    try:
        logger.info("Extracting model files...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # แตกไฟล์ชั่วคราวลงใน models/
            zip_ref.extractall(get_models_dir())
        
        # จัดโครงสร้างไดเรกทอรี
        # บางที zip อาจจะมีโฟลเดอร์ซ้อน (เช่น models/antelopev2/antelopev2/*)
        # เราจะกวาดหาไฟล์ .onnx ทั้งหมดในโฟลเดอร์ที่แตกมา แล้วย้ายมาไว้ที่ models/antelopev2/ โดยตรง
        temp_extracted_dir = os.path.join(get_models_dir(), "antelopev2")
        if os.path.exists(temp_extracted_dir):
            for root, dirs, files in os.walk(temp_extracted_dir):
                for file in files:
                    if file.endswith(".onnx"):
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(model_dir, file)
                        if src_file != dst_file:
                            if os.path.exists(dst_file):
                                os.remove(dst_file)
                            os.rename(src_file, dst_file)
                            logger.debug(f"Moved model file: {file} to {model_dir}")
        
        # ลบไฟล์ zip และโฟลเดอร์ชั่วคราวที่ไม่ได้ใช้งาน
        if os.path.exists(zip_path):
            os.remove(zip_path)
        logger.info("Model extraction and setup completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Error extracting model zip: {e}")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return False

import threading

class FaceAnalyzer:
    def __init__(self, use_gpu=False):
        """
        use_gpu: True (ใช้ CUDA) / False (ใช้ CPU)
        """
        self.app = None
        self.use_gpu = use_gpu
        self.initialized = False
        self.lock = threading.Lock()

    def initialize(self):
        """ดาวน์โหลดโมเดลและเริ่มทำงาน InsightFace"""
        if self.initialized:
            return True

        # ตรวจสอบและดาวน์โหลดโมเดล
        if not check_and_download_model():
            logger.error("Failed to ensure antelopev2 model files.")
            return False

        # ตรวจสอบความพร้อมของ GPU (CUDA) ใน ONNX Runtime
        import onnxruntime as ort
        available_providers = ort.get_available_providers()
        logger.info(f"[SYSTEM] Available ONNX Runtime execution providers: {available_providers}")

        if self.use_gpu:
            if "CUDAExecutionProvider" not in available_providers:
                logger.error(
                    f"[SYSTEM] ERROR: GPU (CUDA) was selected, but CUDAExecutionProvider is NOT available in ONNX Runtime.\n"
                    f"  - คอมพิวเตอร์นี้อาจยังไม่ได้ติดตั้งตัวเร่งการ์ดจอ หรือไม่มี CUDA Toolkit\n"
                    f"  - ระบบจะทำการสลับกลับไปประมวลผลด้วย CPU อัตโนมัติ (CPU Fallback)..."
                )
                self.use_gpu = False
            else:
                logger.info("[SYSTEM] GPU (CUDA) is available and successfully enabled! USING GPU ACCELERATION.")

        ctx_id = 0 if self.use_gpu else -1
        provider_str = "GPU (CUDA)" if self.use_gpu else "CPU"
        providers_list = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if self.use_gpu else ['CPUExecutionProvider']
        logger.info(f"Initializing InsightFace with provider: {provider_str} (ctx_id={ctx_id})")
        
        try:
            # root: ไดเรกทอรีของโปรเจกต์ (InsightFace จะวิ่งไปหาที่ root/models/antelopev2)
            self.app = FaceAnalysis(
                name='antelopev2', 
                root=get_project_root(), 
                allowed_modules=['detection', 'recognition'],
                providers=providers_list
            )
            # ctx_id >= 0 คือ GPU, ctx_id < 0 คือ CPU
            self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))
            self.initialized = True
            # Warmup inference
            try:
                import numpy as np
                dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
                self.app.get(dummy_img)
                logger.info("[SYSTEM] GPU Warmup inference completed.")
            except Exception as w_err:
                logger.debug(f"Warmup inference skipped: {w_err}")
            logger.info("InsightFace initialized successfully.")
            return True
        except Exception as e:
            if self.use_gpu:
                logger.error(
                    f"[SYSTEM] ERROR: Failed to initialize GPU (CUDA) even though CUDAExecutionProvider was found: {e}\n"
                    f"  - ปัญหานี้เกิดจากไฟล์ประสานงานการ์ดจอ NVIDIA cuDNN (เช่น `cudnn64_8.dll`) หายไปจากระบบ\n"
                    f"  - วิธีแก้ไข:\n"
                    f"    1) ไปดาวน์โหลด cuDNN v8.x สำหรับ CUDA 11.x จากหน้าเว็บ NVIDIA\n"
                    f"    2) แตกไฟล์แล้วคัดลอกไฟล์ DLL ทั้งหมดในโฟลเดอร์ bin (เช่น `cudnn64_8.dll` และผองเพื่อน)\n"
                    f"       ไปวางไว้ที่โฟลเดอร์เครื่องมือ CUDA Toolkit:\n"
                    f"       C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v11.8\\bin\n"
                    f"  - ระบบจะทำการสลับกลับไปประมวลผลด้วย CPU แทนอัตโนมัติ..."
                )
                try:
                    self.app = FaceAnalysis(
                        name='antelopev2', 
                        root=get_project_root(), 
                        allowed_modules=['detection', 'recognition'],
                        providers=['CPUExecutionProvider']
                    )
                    self.app.prepare(ctx_id=-1, det_size=(640, 640))
                    self.use_gpu = False
                    self.initialized = True
                    logger.info("InsightFace initialized successfully with CPU (Fallback).")
                    return True
                except Exception as fallback_err:
                    logger.error(f"CPU Fallback failed as well: {fallback_err}")
            else:
                logger.error(f"Failed to initialize InsightFace using CPU: {e}")
            return False

    def get_faces_optimized(self, img, max_size=1280):
        """
        ปรับย่อขนาดรูปภาพความละเอียดสูง (เช่น 42MP / 6000x4000) ก่อนส่งเข้า InsightFace
        เพื่อเร่งความเร็วในการประมวลผลบน GPU/CPU จาก 1-2 นาทีเหลือเพียงไม่กี่มิลลิวินาที
        พร้อมสเกลพิกัด bbox และ kps กลับสู่ขนาดดั้งเดิมโดยอัตโนมัติ
        """
        if img is None:
            return []
            
        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim > max_size:
            scale = max_size / float(max_dim)
            new_w, new_h = int(w * scale), int(h * scale)
            img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
            img_resized = img

        with self.lock:
            faces = self.app.get(img_resized)
            if not faces:
                # Fallback สำหรับรูปที่ตัดชิดใบหน้าแน่นเกินไป (Tight Crop): เติมขอบภาพ 50%
                pad = int(max(h, w) * 0.5)
                img_padded = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=[128, 128, 128])
                faces_padded = self.app.get(img_padded)
                if faces_padded:
                    for face in faces_padded:
                        if hasattr(face, 'bbox') and face.bbox is not None:
                            face.bbox = face.bbox - pad
                        if hasattr(face, 'kps') and face.kps is not None:
                            face.kps = face.kps - pad
                    return faces_padded

            if scale != 1.0:
                for face in faces:
                    if hasattr(face, 'bbox') and face.bbox is not None:
                        face.bbox = face.bbox / scale
                    if hasattr(face, 'kps') and face.kps is not None:
                        face.kps = face.kps / scale
            return faces

    def detect_and_extract_faces(self, image_path):
        """
        ตรวจจับใบหน้าทั้งหมดในรูปภาพและแปลงเป็น Embedding เวกเตอร์
        คืนค่า: รายการของ dict ที่มีคีย์ {'bbox', 'kps', 'det_score', 'embedding'}
        """
        if not self.initialized:
            if not self.initialize():
                raise RuntimeError("FaceAnalyzer is not initialized.")

        logger.debug(f"Reading image: {image_path}")
        # รองรับชื่อไฟล์ภาษาไทย (cv2.imread ปกติจะอ่านภาษาไทยไม่ได้)
        try:
            img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:
            logger.error(f"Failed to read image {image_path} with Thai characters support: {e}")
            img = None
            
        if img is None:
            logger.error(f"Image not found or unreadable: {image_path}")
            return []

        # สแกนใบหน้าด้วย get_faces_optimized
        try:
            faces = self.get_faces_optimized(img)
            logger.debug(f"Detected {len(faces)} faces in image.")
            
            results = []
            for face in faces:
                results.append({
                    "bbox": face.bbox,
                    "kps": face.kps,
                    "det_score": face.det_score,
                    "embedding": face.embedding  # numpy array 512 มิติ
                })
            return results
        except Exception as e:
            logger.error(f"Error during face detection/recognition on {image_path}: {e}")
            return []

    @staticmethod
    def compute_similarity(embedding1, embedding2):
        """คำนวณความคล้ายคลึงระหว่าง 2 เวกเตอร์ใบหน้า ด้วย Cosine Similarity"""
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        similarity = dot_product / (norm1 * norm2)
        return float(similarity)

    def match_faces_matrix(self, detected_embeddings, template_embeddings, template_names, template_staff_ids, threshold=0.65, template_thresholds=None):
        """
        เปรียบเทียบชุดใบหน้าที่ตรวจจับได้กับใบหน้าต้นแบบพร้อมกันโดยใช้ Numpy Matrix Operation
        detected_embeddings: numpy array ขนาด (M, 512)
        template_embeddings: numpy array ขนาด (N, 512)
        template_thresholds: list/array ของ threshold แยกรายบุคคล (ถ้ามี)
        คืนค่า: รายชื่อของครู/นักเรียนที่จับคู่ได้สำหรับแต่ละใบหน้าตรวจพบ
        """
        if len(detected_embeddings) == 0 or len(template_embeddings) == 0:
            return []

        # ทำ L2 Normalization เพื่อให้การทำ Dot Product กลายเป็นการคำนวณ Cosine Similarity ทันที
        detected_norms = np.linalg.norm(detected_embeddings, axis=1, keepdims=True)
        detected_norms[detected_norms == 0] = 1.0  # ป้องกันการหารด้วยศูนย์
        norm_detected = detected_embeddings / detected_norms

        template_norms = np.linalg.norm(template_embeddings, axis=1, keepdims=True)
        template_norms[template_norms == 0] = 1.0
        norm_templates = template_embeddings / template_norms

        # Matrix Multiplication: (M, 512) x (512, N) -> (M, N)
        # similarity_matrix[i, j] คือความคล้ายระหว่างใบหน้าที่พบตัวที่ i กับรูปครูต้นแบบตัวที่ j
        similarity_matrix = np.dot(norm_detected, norm_templates.T)

        results = []
        for i in range(len(detected_embeddings)):
            scores = similarity_matrix[i]
            max_idx = np.argmax(scores)
            max_score = scores[max_idx]

            # ตรวจสอบ threshold เฉพาะบุคคล (ถ้าไม่มีให้สลับไปใช้ threshold กลาง)
            target_thresh = template_thresholds[max_idx] if (template_thresholds is not None and max_idx < len(template_thresholds)) else threshold

            if max_score >= target_thresh:
                results.append({
                    "staff_id": template_staff_ids[max_idx],
                    "name": template_names[max_idx],
                    "confidence": float(max_score)
                })
            else:
                results.append(None)  # ไม่ผ่าน Threshold หรือไม่พบคู่ที่คล้าย

        return results
