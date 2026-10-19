import sqlite3
import pymysql
import os
import socket
from datetime import datetime
from config import Config

class DatabaseManager:
    def __init__(self):
        self._checked_mysql = False
        self._mysql_available = False
        self.use_mysql = False
        self.init_db()

    def _test_mysql_once(self):
        if not self._checked_mysql:
            self._checked_mysql = True
            host = Config.MYSQL_HOST
            if host == 'localhost':
                host = '127.0.0.1'
            s = None
            try:
                # Instant 0.15s socket test - takes 1 millisecond if port 3306 is not open
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.15)
                s.connect((host, Config.MYSQL_PORT))
                s.close()
                s = None

                # If port is open, test login
                conn = pymysql.connect(
                    host=host,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    port=Config.MYSQL_PORT,
                    connect_timeout=1
                )
                conn.close()
                self._mysql_available = True
                print("-> Connected to MySQL database server.", flush=True)
            except Exception:
                self._mysql_available = False
                print("-> Using local SQLite database (instant & standalone).", flush=True)
            finally:
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass
        return self._mysql_available

    def get_connection(self):
        if self._test_mysql_once():
            try:
                conn = pymysql.connect(
                    host=Config.MYSQL_HOST,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    database=Config.MYSQL_DB,
                    port=Config.MYSQL_PORT,
                    cursorclass=pymysql.cursors.DictCursor,
                    connect_timeout=2
                )
                self.use_mysql = True
                return conn, True
            except Exception:
                pass

        # Fast local SQLite
        conn = sqlite3.connect(Config.SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        self.use_mysql = False
        return conn, False

    def init_db(self):
        if self._test_mysql_once():
            try:
                temp_conn = pymysql.connect(
                    host=Config.MYSQL_HOST,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    port=Config.MYSQL_PORT,
                    connect_timeout=1
                )
                cursor = temp_conn.cursor()
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{Config.MYSQL_DB}`")
                temp_conn.commit()
                temp_conn.close()
            except Exception:
                pass

        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()

        if is_mysql:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    regno VARCHAR(100) NOT NULL UNIQUE,
                    course VARCHAR(255) NOT NULL,
                    face_image VARCHAR(550) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    student_name VARCHAR(255) NOT NULL,
                    regno VARCHAR(100) NOT NULL,
                    date DATE NOT NULL,
                    time TIME NOT NULL,
                    UNIQUE KEY unique_daily_attendance (regno, date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS teachers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    department VARCHAR(255) DEFAULT 'General'
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            # Check and seed default teacher
            cursor.execute("SELECT COUNT(*) as cnt FROM teachers WHERE username = %s", (Config.TEACHER_USERNAME,))
            teacher_count = cursor.fetchone()
            if not teacher_count or teacher_count['cnt'] == 0:
                cursor.execute(
                    "INSERT INTO teachers (name, username, password, department) VALUES (%s, %s, %s, %s)",
                    ('Prof. Sarah Jenkins', Config.TEACHER_USERNAME, Config.TEACHER_PASSWORD, 'Computer Applications')
                )
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    regno TEXT NOT NULL UNIQUE,
                    course TEXT NOT NULL,
                    face_image TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT NOT NULL,
                    regno TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    UNIQUE (regno, date)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    department TEXT DEFAULT 'General'
                )
            """)
            # Check and seed default teacher
            cursor.execute("SELECT COUNT(*) as cnt FROM teachers WHERE username = ?", (Config.TEACHER_USERNAME,))
            teacher_count = cursor.fetchone()
            if not teacher_count or teacher_count['cnt'] == 0:
                cursor.execute(
                    "INSERT INTO teachers (name, username, password, department) VALUES (?, ?, ?, ?)",
                    ('Prof. Sarah Jenkins', Config.TEACHER_USERNAME, Config.TEACHER_PASSWORD, 'Computer Applications')
                )

        conn.commit()
        conn.close()

    def get_all_students(self):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students ORDER BY id DESC")
        rows = cursor.fetchall()

        # Fetch attendance counts per student in one shot
        cursor.execute("SELECT regno, COUNT(*) as cnt FROM attendance GROUP BY regno")
        att_rows = cursor.fetchall()
        conn.close()

        att_map = {r['regno']: r['cnt'] for r in att_rows}

        # Calculate total school days (distinct dates with any attendance)
        all_att = self.get_all_attendance()
        distinct_dates = len(set(r['date'] for r in all_att)) if all_att else 0

        students = []
        for r in rows:
            regno = r['regno']
            att_count = att_map.get(regno, 0)
            pct = round((att_count / distinct_dates * 100), 1) if distinct_dates > 0 else 0.0
            students.append({
                'id': r['id'],
                'name': r['name'],
                'regno': regno,
                'course': r['course'],
                'face_image': r['face_image'],
                'attendance_count': att_count,
                'total_days': distinct_dates,
                'attendance_percentage': pct
            })
        return students


    def get_student_by_regno(self, regno):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        if is_mysql:
            cursor.execute("SELECT * FROM students WHERE regno = %s", (regno,))
        else:
            cursor.execute("SELECT * FROM students WHERE regno = ?", (regno,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'regno': row['regno'],
                'course': row['course'],
                'face_image': row['face_image']
            }
        return None

    def add_student(self, name, regno, course, face_image):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute(
                    "INSERT INTO students (name, regno, course, face_image) VALUES (%s, %s, %s, %s)",
                    (name, regno, course, face_image)
                )
            else:
                cursor.execute(
                    "INSERT INTO students (name, regno, course, face_image) VALUES (?, ?, ?, ?)",
                    (name, regno, course, face_image)
                )
            conn.commit()
            conn.close()
            return True, "Student added successfully!"
        except Exception as e:
            conn.close()
            if "UNIQUE" in str(e) or "1062" in str(e):
                return False, f"Register number '{regno}' is already registered."
            return False, f"Database error: {str(e)}"

    def get_student_by_id(self, student_id):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        if is_mysql:
            cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        else:
            cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'regno': row['regno'],
                'course': row['course'],
                'face_image': row['face_image']
            }
        return None

    def delete_student(self, student_id):
        student = self.get_student_by_id(student_id)
        if not student:
            return False, "Student not found."
        
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute("DELETE FROM students WHERE id = %s", (student_id,))
            else:
                cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
            conn.commit()
            conn.close()

            # Clean up face photo file if exists
            try:
                face_rel_path = student['face_image']
                abs_face_path = os.path.join(Config.BASE_DIR, 'static', face_rel_path.replace('/', os.sep))
                if os.path.exists(abs_face_path):
                    os.remove(abs_face_path)
            except Exception as fe:
                print(f"Failed to remove face image file: {fe}")

            return True, f"Student '{student['name']}' deleted successfully."
        except Exception as e:
            conn.close()
            return False, f"Database error while deleting: {str(e)}"

    def delete_attendance_log(self, log_id):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute("DELETE FROM attendance WHERE id = %s", (log_id,))
            else:
                cursor.execute("DELETE FROM attendance WHERE id = ?", (log_id,))
            conn.commit()
            conn.close()
            return True, "Attendance record deleted."
        except Exception as e:
            conn.close()
            return False, f"Database error: {str(e)}"

    def check_already_marked(self, regno, date_str=None):
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        if is_mysql:
            cursor.execute(
                "SELECT * FROM attendance WHERE regno = %s AND date = %s",
                (regno, date_str)
            )
        else:
            cursor.execute(
                "SELECT * FROM attendance WHERE regno = ? AND date = ?",
                (regno, date_str)
            )
        row = cursor.fetchone()
        conn.close()
        return row is not None

    def mark_attendance(self, student_name, regno):
        today = datetime.now().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')

        if self.check_already_marked(regno, today):
            return False, "ALREADY_MARKED", "Attendance already marked for today!"

        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute(
                    "INSERT INTO attendance (student_name, regno, date, time) VALUES (%s, %s, %s, %s)",
                    (student_name, regno, today, now_time)
                )
            else:
                cursor.execute(
                    "INSERT INTO attendance (student_name, regno, date, time) VALUES (?, ?, ?, ?)",
                    (student_name, regno, today, now_time)
                )
            conn.commit()
            conn.close()
            return True, "SUCCESS", "Attendance marked successfully!"
        except Exception as e:
            conn.close()
            return False, "ERROR", f"Failed to mark attendance: {str(e)}"

    def get_all_attendance(self):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attendance ORDER BY date DESC, time DESC")
        rows = cursor.fetchall()
        conn.close()

        records = []
        for r in rows:
            records.append({
                'id': r['id'],
                'student_name': r['student_name'],
                'regno': r['regno'],
                'date': str(r['date']),
                'time': str(r['time'])
            })
        return records

    def get_attendance_grouped_by_date(self):
        records = self.get_all_attendance()
        grouped = {}
        for r in records:
            d = r['date']
            if d not in grouped:
                grouped[d] = []
            grouped[d].append(r)
        
        # Sort dates descending
        sorted_dates = sorted(grouped.keys(), reverse=True)
        return {d: grouped[d] for d in sorted_dates}

    def get_dashboard_stats(self):
        students = self.get_all_students()
        total_students = len(students)
        
        today = datetime.now().strftime('%Y-%m-%d')
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        
        if is_mysql:
            cursor.execute("SELECT COUNT(DISTINCT regno) as count FROM attendance WHERE date = %s", (today,))
        else:
            cursor.execute("SELECT COUNT(DISTINCT regno) as count FROM attendance WHERE date = ?", (today,))
        
        result = cursor.fetchone()
        today_attendance = result['count'] if result else 0
        conn.close()

        percentage = round((today_attendance / total_students * 100), 1) if total_students > 0 else 0.0

        # Recent 5 attendance logs
        all_logs = self.get_all_attendance()
        recent_logs = all_logs[:5]

        return {
            'total_students': total_students,
            'today_attendance': today_attendance,
            'attendance_percentage': percentage,
            'recent_logs': recent_logs
        }

    def get_all_teachers(self):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        teachers = []
        for r in rows:
            teachers.append({
                'id': r['id'],
                'name': r['name'],
                'username': r['username'],
                'department': r['department'] if 'department' in r.keys() else 'General'
            })
        return teachers

    def add_teacher(self, name, username, password, department='General'):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute(
                    "INSERT INTO teachers (name, username, password, department) VALUES (%s, %s, %s, %s)",
                    (name, username, password, department)
                )
            else:
                cursor.execute(
                    "INSERT INTO teachers (name, username, password, department) VALUES (?, ?, ?, ?)",
                    (name, username, password, department)
                )
            conn.commit()
            conn.close()
            return True, "Teacher added successfully!"
        except Exception as e:
            conn.close()
            if "UNIQUE" in str(e) or "1062" in str(e):
                return False, f"Username '{username}' is already taken."
            return False, f"Database error: {str(e)}"

    def delete_teacher(self, teacher_id):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute("SELECT name, username FROM teachers WHERE id = %s", (teacher_id,))
            else:
                cursor.execute("SELECT name, username FROM teachers WHERE id = ?", (teacher_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False, "Teacher not found."
            name = row['name']
            if is_mysql:
                cursor.execute("DELETE FROM teachers WHERE id = %s", (teacher_id,))
            else:
                cursor.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))
            conn.commit()
            conn.close()
            return True, f"Teacher '{name}' deleted successfully."
        except Exception as e:
            conn.close()
            return False, f"Database error: {str(e)}"

    def verify_teacher(self, username, password):
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        teacher = None
        try:
            if is_mysql:
                cursor.execute("SELECT * FROM teachers WHERE username = %s AND password = %s", (username, password))
            else:
                cursor.execute("SELECT * FROM teachers WHERE username = ? AND password = ?", (username, password))
            row = cursor.fetchone()
            if row:
                teacher = {
                    'id': row['id'],
                    'name': row['name'],
                    'username': row['username'],
                    'department': row['department'] if 'department' in row else 'General'
                }
        except Exception as e:
            print(f"Error verifying teacher from DB: {e}")
        finally:
            conn.close()

        if teacher:
            return teacher

        # Fallback check against config credentials
        if username == Config.TEACHER_USERNAME and password == Config.TEACHER_PASSWORD:
            return {
                'id': 1,
                'name': 'Prof. Sarah Jenkins',
                'username': username,
                'department': 'Computer Applications'
            }
        return None

    def get_daily_attendance_breakdown(self, date_str=None):
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
            
        students = self.get_all_students()
        
        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        if is_mysql:
            cursor.execute("SELECT * FROM attendance WHERE date = %s ORDER BY time ASC", (date_str,))
        else:
            cursor.execute("SELECT * FROM attendance WHERE date = ? ORDER BY time ASC", (date_str,))
        attendance_rows = cursor.fetchall()
        conn.close()

        attendance_map = {}
        for r in attendance_rows:
            attendance_map[r['regno']] = {
                'id': r['id'],
                'student_name': r['student_name'],
                'regno': r['regno'],
                'date': str(r['date']),
                'time': str(r['time'])
            }

        present_students = []
        absent_students = []
        all_students_with_status = []

        for s in students:
            regno = s['regno']
            s_data = {
                'id': s['id'],
                'name': s['name'],
                'regno': s['regno'],
                'course': s['course'],
                'face_image': s['face_image']
            }
            if regno in attendance_map:
                att = attendance_map[regno]
                s_data['status'] = 'Present'
                s_data['time'] = att['time']
                s_data['attendance_id'] = att['id']
                present_students.append(s_data)
                all_students_with_status.append(s_data)
            else:
                s_data['status'] = 'Absent'
                s_data['time'] = None
                s_data['attendance_id'] = None
                absent_students.append(s_data)
                all_students_with_status.append(s_data)

        # Sort present by time, absent by name
        present_students.sort(key=lambda x: str(x['time'] or ''))
        absent_students.sort(key=lambda x: x['name'].lower())

        total_students = len(students)
        present_count = len(present_students)
        absent_count = len(absent_students)
        percentage = round((present_count / total_students * 100), 1) if total_students > 0 else 0.0

        return {
            'date': date_str,
            'total_students': total_students,
            'present_count': present_count,
            'absent_count': absent_count,
            'attendance_percentage': percentage,
            'present_students': present_students,
            'absent_students': absent_students,
            'all_students': all_students_with_status
        }

    def mark_attendance_manual(self, regno, date_str=None, time_str=None):
        student = self.get_student_by_regno(regno)
        if not student:
            return False, "Student not found with this register number."
        
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
        if not time_str:
            time_str = datetime.now().strftime('%H:%M:%S')

        if self.check_already_marked(regno, date_str):
            return False, f"Attendance already marked for {student['name']} on {date_str}."

        conn, is_mysql = self.get_connection()
        cursor = conn.cursor()
        try:
            if is_mysql:
                cursor.execute(
                    "INSERT INTO attendance (student_name, regno, date, time) VALUES (%s, %s, %s, %s)",
                    (student['name'], regno, date_str, time_str)
                )
            else:
                cursor.execute(
                    "INSERT INTO attendance (student_name, regno, date, time) VALUES (?, ?, ?, ?)",
                    (student['name'], regno, date_str, time_str)
                )
            conn.commit()
            conn.close()
            return True, f"Attendance for {student['name']} marked successfully!"
        except Exception as e:
            conn.close()
            return False, f"Error marking attendance: {str(e)}"

db = DatabaseManager()

