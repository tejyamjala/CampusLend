import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = os.path.dirname(__file__)
DB_PATH = os.path.join(ROOT, 'campuslend.sqlite3')
app = Flask(__name__, static_folder='public', static_url_path='/assets')
app.secret_key = os.environ.get('SESSION_SECRET', 'campuslend-hackathon-secret')
app.config.update(SESSION_COOKIE_SAMESITE='None', SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True)


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = db()
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, college TEXT NOT NULL, verified INTEGER DEFAULT 0, role TEXT DEFAULT 'student', rating REAL DEFAULT 5.0, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, condition TEXT NOT NULL, price_per_day REAL DEFAULT 0, available_from TEXT, available_to TEXT, status TEXT DEFAULT 'available', FOREIGN KEY(owner_id) REFERENCES users(id));
      CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, borrower_id INTEGER NOT NULL, reason TEXT NOT NULL, start_at TEXT NOT NULL, duration_hours INTEGER NOT NULL, return_at TEXT NOT NULL, fee REAL NOT NULL, late_fee REAL DEFAULT 0, status TEXT DEFAULT 'pending', payment_status TEXT DEFAULT 'unpaid', picked_up_at TEXT, returned_at TEXT, FOREIGN KEY(device_id) REFERENCES devices(id), FOREIGN KEY(borrower_id) REFERENCES users(id));
      CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL, reporter_id INTEGER NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL, status TEXT DEFAULT 'open', created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, duration TEXT NOT NULL, detail TEXT, status TEXT DEFAULT 'open', created_at TEXT NOT NULL, FOREIGN KEY(requester_id) REFERENCES users(id));
    ''')
    connection.commit()
    connection.close()


def user_payload(row):
    return {key: row[key] for key in ('id', 'name', 'email', 'college', 'verified', 'role', 'rating')}


@app.get('/health')
def health():
    return jsonify(ok=True, service='campuslend', database='sqlite')


@app.post('/api/auth/register')
def register():
    body = request.get_json(force=True)
    required = ('name', 'email', 'password', 'college')
    if any(not body.get(key) for key in required):
        return jsonify(error='name, email, password, and college are required'), 400
    connection = db()
    try:
        cursor = connection.execute('INSERT INTO users (name,email,password_hash,college,verified,created_at) VALUES (?,?,?,?,?,?)', (body['name'], body['email'].lower(), generate_password_hash(body['password']), body['college'], 0, datetime.utcnow().isoformat()))
        connection.commit()
        session['user_id'] = cursor.lastrowid
        row = connection.execute('SELECT * FROM users WHERE id=?', (cursor.lastrowid,)).fetchone()
        return jsonify(user=user_payload(row)), 201
    except sqlite3.IntegrityError:
        return jsonify(error='A student with that email already exists'), 409
    finally:
        connection.close()


@app.post('/api/auth/login')
def login():
    body = request.get_json(force=True)
    connection = db()
    row = connection.execute('SELECT * FROM users WHERE email=?', (body.get('email', '').lower(),)).fetchone()
    connection.close()
    if not row or not check_password_hash(row['password_hash'], body.get('password', '')):
        return jsonify(error='Invalid student email or password'), 401
    session['user_id'] = row['id']
    return jsonify(user=user_payload(row))


@app.post('/api/auth/logout')
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get('/api/auth/me')
def me():
    if 'user_id' not in session:
        return jsonify(user=None)
    connection = db()
    row = connection.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    connection.close()
    return jsonify(user=user_payload(row) if row else None)


@app.get('/api/requests')
def get_requests():
    connection = db()
    rows = connection.execute('SELECT requests.*, users.name AS requester_name FROM requests JOIN users ON users.id=requests.requester_id WHERE requests.status=? ORDER BY requests.id DESC', ('open',)).fetchall()
    connection.close()
    return jsonify(requests=[dict(row) for row in rows])


@app.post('/api/requests')
def create_request():
    if 'user_id' not in session:
        return jsonify(error='Sign in required'), 401
    body = request.get_json(force=True)
    if not body.get('title') or not body.get('category') or not body.get('duration'):
        return jsonify(error='Title, category, and duration are required'), 400
    connection = db()
    cursor = connection.execute('INSERT INTO requests (requester_id,title,category,duration,detail,created_at) VALUES (?,?,?,?,?,?)', (session['user_id'], body['title'], body['category'], body['duration'], body.get('detail', ''), datetime.utcnow().isoformat()))
    connection.commit(); connection.close()
    return jsonify(request={'id': cursor.lastrowid, 'status': 'open'}), 201


@app.get('/api/devices')
def devices():
    connection = db()
    rows = connection.execute('SELECT devices.*, users.name AS owner_name, users.rating AS owner_rating FROM devices JOIN users ON users.id=devices.owner_id WHERE devices.status=? ORDER BY devices.id DESC', ('available',)).fetchall()
    connection.close()
    return jsonify(devices=[dict(row) for row in rows])


@app.post('/api/devices')
def create_device():
    if 'user_id' not in session:
        return jsonify(error='Sign in required'), 401
    body = request.get_json(force=True)
    connection = db()
    cursor = connection.execute('INSERT INTO devices (owner_id,name,category,condition,price_per_day,available_from,available_to) VALUES (?,?,?,?,?,?,?)', (session['user_id'], body['name'], body['category'], body.get('condition', 'Good'), body.get('price_per_day', 0), body.get('available_from'), body.get('available_to')))
    connection.commit()
    row = connection.execute('SELECT * FROM devices WHERE id=?', (cursor.lastrowid,)).fetchone()
    connection.close()
    return jsonify(device=dict(row)), 201


@app.post('/api/bookings')
def create_booking():
    if 'user_id' not in session:
        return jsonify(error='Sign in required'), 401
    body = request.get_json(force=True)
    duration = int(body.get('duration_hours', 1))
    start = datetime.fromisoformat(body['start_at'])
    return_at = start + timedelta(hours=duration)
    connection = db()
    device = connection.execute('SELECT * FROM devices WHERE id=? AND status=?', (body['device_id'], 'available')).fetchone()
    if not device:
        connection.close()
        return jsonify(error='Device is unavailable or already booked'), 409
    conflict = connection.execute("SELECT id FROM bookings WHERE device_id=? AND status IN ('pending','approved','active') AND start_at < ? AND return_at > ?", (device['id'], return_at.isoformat(), start.isoformat())).fetchone()
    if conflict:
        connection.close()
        return jsonify(error='This device already has a booking in that time window'), 409
    fee = round(float(device['price_per_day']) * max(duration / 24, 1 / 24), 2)
    cursor = connection.execute('INSERT INTO bookings (device_id,borrower_id,reason,start_at,duration_hours,return_at,fee) VALUES (?,?,?,?,?,?,?)', (device['id'], session['user_id'], body.get('reason', 'Temporary campus use'), start.isoformat(), duration, return_at.isoformat(), fee))
    connection.commit()
    connection.close()
    return jsonify(booking={'id': cursor.lastrowid, 'fee': fee, 'return_at': return_at.isoformat(), 'status': 'pending', 'payment_status': 'unpaid'}), 201


@app.get('/api/bookings')
def bookings():
    if 'user_id' not in session:
        return jsonify(error='Sign in required'), 401
    connection = db()
    rows = connection.execute('SELECT bookings.*, devices.name AS device_name, devices.category, users.name AS borrower_name FROM bookings JOIN devices ON devices.id=bookings.device_id JOIN users ON users.id=bookings.borrower_id WHERE bookings.borrower_id=? OR devices.owner_id=? ORDER BY bookings.id DESC', (session['user_id'], session['user_id'])).fetchall()
    connection.close()
    return jsonify(bookings=[dict(row) for row in rows])


@app.post('/api/bookings/<int:booking_id>/approve')
def approve_booking(booking_id):
    if 'user_id' not in session:
        return jsonify(error='Sign in required'), 401
    connection = db()
    connection.execute('UPDATE bookings SET status="approved" WHERE id=?', (booking_id,))
    connection.execute('UPDATE devices SET status="rented" WHERE id=(SELECT device_id FROM bookings WHERE id=?)', (booking_id,))
    connection.commit(); connection.close()
    return jsonify(ok=True, status='approved')


@app.post('/api/bookings/<int:booking_id>/simulate-payment')
def simulate_payment(booking_id):
    connection = db()
    connection.execute('UPDATE bookings SET payment_status="simulated_paid" WHERE id=?', (booking_id,))
    connection.commit(); connection.close()
    return jsonify(ok=True, payment_status='simulated_paid')


@app.post('/api/bookings/<int:booking_id>/return')
def return_booking(booking_id):
    connection = db()
    row = connection.execute('SELECT * FROM bookings WHERE id=?', (booking_id,)).fetchone()
    if not row:
        connection.close(); return jsonify(error='Booking not found'), 404
    returned_at = datetime.utcnow()
    deadline = datetime.fromisoformat(row['return_at'])
    late_hours = max(0, int((returned_at - deadline).total_seconds() // 3600))
    late_fee = round(late_hours * 10, 2)
    connection.execute('UPDATE bookings SET status="returned", returned_at=?, late_fee=? WHERE id=?', (returned_at.isoformat(), late_fee, booking_id))
    connection.execute('UPDATE devices SET status="available" WHERE id=?', (row['device_id'],))
    connection.commit(); connection.close()
    return jsonify(ok=True, status='returned', late_fee=late_fee, late_hours=late_hours)


@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.get('/<path:path>')
def spa_fallback(path):
    if path.startswith('api/') or path in {'health'}:
        return jsonify(error='Not found'), 404
    requested = os.path.join(app.static_folder, path)
    if os.path.isfile(requested):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '3000')))
