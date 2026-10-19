import os
import cv2
import base64
import numpy as np
from config import Config
from database import db

# DeepFace will be imported lazily on the first face scan to enable instant app startup
DeepFace = None
HAS_DEEPFACE = None

def get_deepface():
    global DeepFace, HAS_DEEPFACE
    if HAS_DEEPFACE is None:
        try:
            print("-> Loading DeepFace biometric model...", flush=True)
            from deepface import DeepFace as df
            DeepFace = df
            HAS_DEEPFACE = True
            print("-> DeepFace loaded successfully!", flush=True)
        except Exception as e:
            print(f"DeepFace warning: {e}", flush=True)
            HAS_DEEPFACE = False
    return DeepFace, HAS_DEEPFACE

class FaceRecognitionEngine:
    def __init__(self):
        os.makedirs(Config.FACE_DATA_DIR, exist_ok=True)
        self.face_cascade = None
        try:
            if hasattr(cv2, 'data') and hasattr(cv2, 'CascadeClassifier'):
                self.cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                self.face_cascade = cv2.CascadeClassifier(self.cascade_path)
        except Exception as e:
            print(f"OpenCV Cascade error: {e}")
            self.face_cascade = None

    def decode_base64_image(self, base64_data):
        try:
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]
            img_bytes = base64.b64decode(base64_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            print(f"Error decoding base64 image: {e}")
            return None

    def save_face_image(self, img, regno):
        try:
            filename = f"{regno}.jpg"
            filepath = os.path.join(Config.FACE_DATA_DIR, filename)
            
            # Detect face and crop if possible for better quality, or save resized full frame
            faces = []
            if self.face_cascade is not None and hasattr(self.face_cascade, 'empty') and not self.face_cascade.empty():
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))

            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
                # Add margin
                margin = int(0.2 * max(w, h))
                x_start = max(0, x - margin)
                y_start = max(0, y - margin)
                x_end = min(img.shape[1], x + w + margin)
                y_end = min(img.shape[0], y + h + margin)
                cropped = img[y_start:y_end, x_start:x_end]
                cv2.imwrite(filepath, cropped)
            else:
                cv2.imwrite(filepath, img)

            relative_path = f"uploads/face_data/{filename}"
            return True, relative_path, "Face image saved successfully."
        except Exception as e:
            return False, None, f"Failed to save face image: {str(e)}"

    def recognize_face(self, query_img):
        students = db.get_all_students()
        if not students:
            return {
                'status': 'error',
                'message': 'No registered students found in database. Please register students first.',
                'student': None
            }

        # --- Performance optimisation 1: pre-detect face in the query frame ---
        # If OpenCV can't find a face at all, skip the expensive DeepFace loop.
        if self.face_cascade is not None and hasattr(self.face_cascade, 'empty') and not self.face_cascade.empty():
            gray_q = cv2.cvtColor(query_img, cv2.COLOR_BGR2GRAY)
            faces_q = self.face_cascade.detectMultiScale(gray_q, scaleFactor=1.2, minNeighbors=4, minSize=(50, 50))
            if len(faces_q) == 0:
                return {
                    'status': 'not_found',
                    'message': 'No face detected in the frame. Please face the camera directly and try again.',
                    'student': None
                }

        # --- Performance optimisation 2: resize query image to max 320px ---
        # Smaller input → much faster DeepFace model inference.
        h, w = query_img.shape[:2]
        max_dim = 320
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            query_img = cv2.resize(query_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # Save query image temporarily
        temp_query_path = os.path.join(Config.FACE_DATA_DIR, 'temp_query.jpg')
        cv2.imwrite(temp_query_path, query_img)

        best_match = None
        min_distance = float('inf')

        df_module, has_df = get_deepface()

        for student in students:
            face_rel_path = student['face_image']
            abs_face_path = os.path.join(Config.BASE_DIR, 'static', face_rel_path.replace('/', os.sep))

            if not os.path.exists(abs_face_path):
                continue

            try:
                matched_current = False
                if has_df and df_module:
                    try:
                        # DeepFace verification using Facenet
                        result = df_module.verify(
                            img1_path=temp_query_path,
                            img2_path=abs_face_path,
                            model_name=Config.DEEPFACE_MODEL,
                            distance_metric=Config.DEEPFACE_METRIC,
                            enforce_detection=False
                        )
                        verified = result.get('verified', False)
                        distance = result.get('distance', 1.0)

                        if verified and distance < min_distance:
                            min_distance = distance
                            best_match = student
                            matched_current = True
                    except Exception as df_err:
                        print(f"DeepFace verify error for {student['name']}: {df_err}")

                if not matched_current:
                    # Backup fallback: basic OpenCV structural comparison
                    img1 = cv2.imread(temp_query_path, cv2.IMREAD_GRAYSCALE)
                    img2 = cv2.imread(abs_face_path, cv2.IMREAD_GRAYSCALE)
                    if img1 is not None and img2 is not None:
                        img1_res = cv2.resize(img1, (100, 100))
                        img2_res = cv2.resize(img2, (100, 100))
                        diff = cv2.absdiff(img1_res, img2_res)
                        score = np.mean(diff)
                        if score < 45 and score < min_distance:
                            min_distance = score
                            best_match = student
            except Exception as ex:
                print(f"Comparison error for {student['name']}: {ex}")
                continue

        # Clean temp file
        if os.path.exists(temp_query_path):
            try:
                os.remove(temp_query_path)
            except Exception:
                pass

        if best_match:
            regno = best_match['regno']
            name = best_match['name']

            is_marked = db.check_already_marked(regno)
            if is_marked:
                return {
                    'status': 'already_marked',
                    'message': f"Attendance for {name} ({regno}) is ALREADY marked for today!",
                    'student': best_match
                }

            # Mark attendance
            success, code, msg = db.mark_attendance(name, regno)
            if success:
                return {
                    'status': 'success',
                    'message': f"Welcome {name}! Attendance successfully recorded.",
                    'student': best_match
                }
            else:
                return {
                    'status': 'already_marked' if code == 'ALREADY_MARKED' else 'error',
                    'message': msg,
                    'student': best_match
                }

        return {
            'status': 'not_found',
            'message': 'Face not recognized. Please register first or try scanning again.',
            'student': None
        }

face_engine = FaceRecognitionEngine()
