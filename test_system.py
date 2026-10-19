import unittest
import os
import json
from datetime import datetime

class SmartAttendanceTestCase(unittest.TestCase):
    def setUp(self):
        import app
        from database import db
        app.app.config['TESTING'] = True
        app.app.config['SECRET_KEY'] = 'test_secret'
        self.client = app.app.test_client()
        self.db = db

    def test_01_login_logout(self):
        # Invalid login
        res = self.client.post('/login', data={'username': 'admin', 'password': 'wrongpassword'}, follow_redirects=True)
        self.assertIn(b'Invalid Username or Password', res.data)

        # Valid login
        res = self.client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        self.assertIn(b'Overview Dashboard', res.data)

        # Logout
        res = self.client.get('/logout', follow_redirects=True)
        self.assertIn(b'Admin Portal Login', res.data)

    def test_02_dashboard_access(self):
        # Unauthenticated access should redirect to login
        res = self.client.get('/dashboard', follow_redirects=True)
        self.assertIn(b'Admin Portal Login', res.data)

    def test_03_student_addition(self):
        # Login first
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        
        # Test student list route
        res = self.client.get('/students')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Student Directory', res.data)

    def test_04_export_csv(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.get('/export_csv')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        self.assertIn(b'Student Name,Register Number,Date,Time', res.data)

    def test_05_config_and_face_engine(self):
        from config import Config
        from face_engine import face_engine
        import numpy as np
        self.assertTrue(hasattr(Config, 'BASE_DIR'))
        self.assertIsNotNone(Config.BASE_DIR)
        
        # Test recognition with empty frame
        dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        res = face_engine.recognize_face(dummy_frame)
        self.assertIn('status', res)

    def test_06_teacher_login_and_logout(self):
        # Invalid teacher credentials
        res = self.client.post('/teacher/login', data={'username': 'teacher', 'password': 'wrongpassword'}, follow_redirects=True)
        self.assertIn(b'Invalid Teacher Username or Password', res.data)

        # Valid teacher credentials
        res = self.client.post('/teacher/login', data={'username': 'teacher', 'password': 'teacher123'}, follow_redirects=True)
        self.assertIn(b"Today's Attendance", res.data)
        self.assertIn(b"Faculty Portal", res.data)

        # Logout teacher
        res = self.client.get('/teacher/logout', follow_redirects=True)
        self.assertIn(b'Faculty / Teacher Login', res.data)

    def test_07_teacher_dashboard_and_absentee_list(self):
        # Login as teacher
        self.client.post('/teacher/login', data={'username': 'teacher', 'password': 'teacher123'})

        # Visit teacher dashboard
        res = self.client.get('/teacher/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Students NOT Present', res.data)
        self.assertIn(b'Total Registered Students', res.data)

        # Test date query parameter (e.g. past date 2026-09-09)
        res_date = self.client.get('/teacher/dashboard?date=2026-09-09')
        self.assertEqual(res_date.status_code, 200)
        self.assertIn(b'2026-09-09', res_date.data)

    def test_08_teacher_export_absentees_csv(self):
        self.client.post('/teacher/login', data={'username': 'teacher', 'password': 'teacher123'})
        res = self.client.get('/teacher/export_absentees')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        self.assertIn(b'Register Number,Student Name,Course,Status,Date', res.data)

if __name__ == '__main__':
    unittest.main()

