import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    BASE_DIR = BASE_DIR
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'smart_attendance_secret_key_2026_super_secure'
    
    # Upload Folder
    FACE_DATA_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'face_data')
    
    # MySQL Database Configuration
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'smart_attendance_db')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))
    
    # SQLite Fallback Configuration (Used if MySQL service is unreachable)
    SQLITE_DB_PATH = os.path.join(BASE_DIR, 'attendance.db')
    
    # Default Admin Credentials
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'admin123'
    
    # Default Teacher / Faculty Credentials
    TEACHER_USERNAME = os.environ.get('TEACHER_USERNAME', 'teacher')
    TEACHER_PASSWORD = os.environ.get('TEACHER_PASSWORD', 'teacher123')
    
    # DeepFace Configuration
    DEEPFACE_MODEL = 'Facenet'
    DEEPFACE_METRIC = 'cosine'
