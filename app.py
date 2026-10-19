import sys
print("-> Starting Smart Attendance System backend... Please wait...", flush=True)

import os
import io
import csv
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, 
    session, jsonify, flash, Response, make_response
)

from config import Config
from database import db
from face_engine import face_engine

app = Flask(__name__)
app.config.from_object(Config)

# Helper decorator for Admin authentication
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please log in as Admin to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper decorator for Teacher authentication (allows either teacher or admin)
def teacher_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('teacher_logged_in') and not session.get('admin_logged_in'):
            flash('Please log in to the Teacher Portal to access this page.', 'warning')
            return redirect(url_for('teacher_login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper decorator for general authentication (either admin or teacher)
def any_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in') and not session.get('teacher_logged_in'):
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('teacher_login'))
        return f(*args, **kwargs)
    return decorated_function

# Context processor to pass current time and user to all templates
@app.context_processor
def inject_globals():
    return {
        'now': datetime.now(),
        'admin_username': session.get('admin_username', 'Admin'),
        'teacher_name': session.get('teacher_name', 'Faculty Member'),
        'teacher_username': session.get('teacher_username', 'teacher'),
        'is_teacher': session.get('teacher_logged_in', False),
        'is_admin': session.get('admin_logged_in', False)
    }

# -------------------------------------------------------------
# AUTHENTICATION ROUTES
# -------------------------------------------------------------
@app.route('/')
def index():
    if 'admin_logged_in' in session:
        return redirect(url_for('dashboard'))
    if 'teacher_logged_in' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_logged_in' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session['user_role'] = 'admin'
            flash('Welcome back! Admin login successful.', 'success')
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid Username or Password. Please contact your administrator.'

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('login'))

# Teacher Portal Authentication
@app.route('/teacher')
def teacher_root():
    if 'teacher_logged_in' in session or 'admin_logged_in' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('teacher_login'))

@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if 'teacher_logged_in' in session:
        return redirect(url_for('teacher_dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        teacher = db.verify_teacher(username, password)
        if teacher:
            session['teacher_logged_in'] = True
            session['teacher_username'] = teacher['username']
            session['teacher_name'] = teacher.get('name', 'Faculty Member')
            session['user_role'] = 'teacher'
            flash(f"Welcome back, {session['teacher_name']}! Teacher login successful.", 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            error = 'Invalid Teacher Username or Password. Please contact your administrator.'

    return render_template('teacher_login.html', error=error)

@app.route('/teacher/logout')
def teacher_logout():
    session.pop('teacher_logged_in', None)
    session.pop('teacher_username', None)
    session.pop('teacher_name', None)
    if session.get('user_role') == 'teacher':
        session.pop('user_role', None)
    flash('You have been logged out from the Teacher Portal safely.', 'info')
    return redirect(url_for('teacher_login'))

# -------------------------------------------------------------
# DASHBOARD ROUTE
# -------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    stats = db.get_dashboard_stats()
    return render_template('dashboard.html', stats=stats)

@app.route('/api/dashboard/chart_data')
@login_required
def chart_data():
    all_attendance = db.get_all_attendance()
    # Count attendance per date for the last 7 days
    date_counts = {}
    for log in all_attendance:
        d = log['date']
        date_counts[d] = date_counts.get(d, 0) + 1

    sorted_dates = sorted(date_counts.keys())[-7:]
    counts = [date_counts[d] for d in sorted_dates]

    return jsonify({
        'labels': sorted_dates,
        'data': counts
    })

# -------------------------------------------------------------
# STUDENT MANAGEMENT ROUTES
# -------------------------------------------------------------
@app.route('/students')
@login_required
def students():
    search_query = request.args.get('q', '').strip().lower()
    all_students = db.get_all_students()

    if search_query:
        all_students = [
            s for s in all_students 
            if search_query in s['name'].lower() 
            or search_query in s['regno'].lower() 
            or search_query in s['course'].lower()
        ]

    return render_template('students.html', students=all_students, search_query=search_query)

@app.route('/api/students/add', methods=['POST'])
@login_required
def add_student():
    name = request.form.get('name', '').strip()
    regno = request.form.get('regno', '').strip()
    course = request.form.get('course', '').strip()
    face_image_base64 = request.form.get('face_image_base64', '')

    if not name or not regno or not course:
        return jsonify({'success': False, 'message': 'All fields (Name, Register Number, Course) are required.'}), 400

    if not face_image_base64:
        return jsonify({'success': False, 'message': 'Face capture is required before adding student.'}), 400

    # Check duplicate regno first
    existing = db.get_student_by_regno(regno)
    if existing:
        return jsonify({'success': False, 'message': f"Register Number '{regno}' already exists."}), 400

    # Save image
    img = face_engine.decode_base64_image(face_image_base64)
    if img is None:
        return jsonify({'success': False, 'message': 'Invalid image data received.'}), 400

    save_success, rel_path, save_msg = face_engine.save_face_image(img, regno)
    if not save_success:
        return jsonify({'success': False, 'message': save_msg}), 500

    # Insert into Database
    db_success, db_msg = db.add_student(name, regno, course, rel_path)
    if db_success:
        return jsonify({'success': True, 'message': f"Student {name} registered successfully!"})
    else:
        return jsonify({'success': False, 'message': db_msg}), 400

@app.route('/api/students/delete/<int:student_id>', methods=['POST', 'DELETE'])
@login_required
def delete_student(student_id):
    try:
        success, message = db.delete_student(student_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f"Server error: {str(e)}"}), 500

# -------------------------------------------------------------
# TEACHER MANAGEMENT ROUTES (ADMIN ONLY)
# -------------------------------------------------------------
@app.route('/teachers')
@login_required
def teachers():
    search_query = request.args.get('q', '').strip().lower()
    all_teachers = db.get_all_teachers()
    if search_query:
        all_teachers = [
            t for t in all_teachers
            if search_query in t['name'].lower()
            or search_query in t['username'].lower()
            or search_query in t['department'].lower()
        ]
    return render_template('teachers.html', teachers=all_teachers, search_query=search_query)

@app.route('/api/teachers/add', methods=['POST'])
@login_required
def add_teacher():
    name = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    department = request.form.get('department', 'General').strip()

    if not name or not username or not password:
        return jsonify({'success': False, 'message': 'Name, Username, and Password are required.'}), 400

    success, msg = db.add_teacher(name, username, password, department)
    return jsonify({'success': success, 'message': msg}), (200 if success else 400)

@app.route('/api/teachers/delete/<int:teacher_id>', methods=['POST', 'DELETE'])
@login_required
def delete_teacher(teacher_id):
    try:
        success, message = db.delete_teacher(teacher_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f"Server error: {str(e)}"}), 500

# -------------------------------------------------------------
# FACE RECOGNITION ROUTES (ACCESSIBLE TO ADMIN & TEACHERS)
# -------------------------------------------------------------
@app.route('/recognize')
@any_login_required
def recognize():
    return render_template('recognize.html')

@app.route('/api/recognize_frame', methods=['POST'])
@any_login_required
def recognize_frame():
    try:
        data = request.get_json(silent=True) or {}
        image_data = data.get('image', '')

        if not image_data:
            return jsonify({'success': False, 'message': 'No image frame provided for recognition'}), 400

        img = face_engine.decode_base64_image(image_data)
        if img is None:
            return jsonify({'success': False, 'message': 'Failed to decode image frame data'}), 400

        res = face_engine.recognize_face(img)
        session['last_result'] = res

        return jsonify({
            'success': True,
            'result': res,
            'redirect_url': url_for('result')
        })
    except Exception as e:
        print(f"Server error during face recognition: {e}")
        error_res = {
            'status': 'error',
            'message': f'Recognition process error: {str(e)}',
            'student': None
        }
        session['last_result'] = error_res
        return jsonify({
            'success': True,
            'result': error_res,
            'redirect_url': url_for('result')
        })

@app.route('/result')
@any_login_required
def result():
    last_res = session.get('last_result', {
        'status': 'error',
        'message': 'No recent recognition scan available.',
        'student': None
    })
    return render_template('result.html', result=last_res)

# -------------------------------------------------------------
# ATTENDANCE ROUTES
# -------------------------------------------------------------
@app.route('/attendance')
@any_login_required
def attendance():
    search_query = request.args.get('q', '').strip().lower()
    grouped_data = db.get_attendance_grouped_by_date()

    if search_query:
        filtered_grouped = {}
        for date_str, records in grouped_data.items():
            matching_records = [
                r for r in records 
                if search_query in r['student_name'].lower() 
                or search_query in r['regno'].lower() 
                or search_query in r['date'].lower()
            ]
            if matching_records:
                filtered_grouped[date_str] = matching_records
        grouped_data = filtered_grouped

    return render_template('attendance.html', grouped_attendance=grouped_data, search_query=search_query)

@app.route('/export_csv')
@any_login_required
def export_csv():
    records = db.get_all_attendance()
    
    si = io.StringIO()
    writer = csv.writer(si)
    # Write CSV Header
    writer.writerow(['ID', 'Student Name', 'Register Number', 'Date', 'Time'])
    
    # Write Data Rows
    for r in records:
        writer.writerow([r['id'], r['student_name'], r['regno'], r['date'], r['time']])

    output = make_response(si.getvalue())
    today_str = datetime.now().strftime('%Y-%m-%d')
    output.headers["Content-Disposition"] = f"attachment; filename=attendance_report_{today_str}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# -------------------------------------------------------------
# TEACHER PORTAL & ABSENTEE ROUTES
# -------------------------------------------------------------
@app.route('/teacher/dashboard')
@app.route('/teacher/attendance')
@teacher_login_required
def teacher_dashboard():
    today_str = datetime.now().strftime('%Y-%m-%d')
    selected_date = request.args.get('date', today_str).strip() or today_str
    search_query = request.args.get('q', '').strip().lower()

    breakdown = db.get_daily_attendance_breakdown(selected_date)

    if search_query:
        breakdown['absent_students'] = [
            s for s in breakdown['absent_students']
            if search_query in s['name'].lower() 
            or search_query in s['regno'].lower() 
            or search_query in s['course'].lower()
        ]
        breakdown['present_students'] = [
            s for s in breakdown['present_students']
            if search_query in s['name'].lower() 
            or search_query in s['regno'].lower() 
            or search_query in s['course'].lower()
        ]
        breakdown['all_students'] = [
            s for s in breakdown['all_students']
            if search_query in s['name'].lower() 
            or search_query in s['regno'].lower() 
            or search_query in s['course'].lower()
        ]

    return render_template(
        'teacher_dashboard.html',
        breakdown=breakdown,
        selected_date=selected_date,
        today_str=today_str,
        is_today=(selected_date == today_str),
        search_query=search_query
    )

@app.route('/teacher/export_absentees')
@teacher_login_required
def teacher_export_absentees():
    today_str = datetime.now().strftime('%Y-%m-%d')
    selected_date = request.args.get('date', today_str).strip() or today_str
    breakdown = db.get_daily_attendance_breakdown(selected_date)

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Register Number', 'Student Name', 'Course', 'Status', 'Date'])
    for s in breakdown['absent_students']:
        writer.writerow([s['regno'], s['name'], s['course'], 'ABSENT', selected_date])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=absent_students_{selected_date}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/teacher/export_daily_report')
@teacher_login_required
def teacher_export_daily_report():
    today_str = datetime.now().strftime('%Y-%m-%d')
    selected_date = request.args.get('date', today_str).strip() or today_str
    breakdown = db.get_daily_attendance_breakdown(selected_date)

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Register Number', 'Student Name', 'Course', 'Status', 'Check-in Time', 'Date'])
    for s in breakdown['all_students']:
        writer.writerow([s['regno'], s['name'], s['course'], s['status'], s['time'] or 'N/A', selected_date])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=daily_roster_{selected_date}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/api/teacher/mark_manual', methods=['POST'])
@teacher_login_required
def teacher_mark_manual():
    data = request.get_json(silent=True) or request.form
    regno = (data.get('regno') or '').strip()
    date_str = (data.get('date') or '').strip() or datetime.now().strftime('%Y-%m-%d')

    if not regno:
        return jsonify({'success': False, 'message': 'Register number is required.'}), 400

    success, msg = db.mark_attendance_manual(regno, date_str)
    return jsonify({'success': success, 'message': msg}), (200 if success else 400)

if __name__ == '__main__':
    print("=========================================================")
    print(" Smart Attendance System -> http://127.0.0.1:5000")
    print(" Admin Portal Login:   admin   / admin123   (http://127.0.0.1:5000/login)")
    print(" Teacher Portal Login: teacher / teacher123 (http://127.0.0.1:5000/teacher/login)")
    print("=========================================================")
    app.run(debug=True, host='0.0.0.0', port=5000)

