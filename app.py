import hashlib
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urlparse

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
except ImportError:  # Local SQLite development still works before dependency installation.
    pymysql = None

ROOT = os.path.dirname(__file__)
DB_PATH = os.path.join(ROOT, 'campuslend.sqlite3')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
SESSION_COOKIE = 'campuslend_session'
SESSION_MAX_AGE = 60 * 60 * 24 * 30
app = Flask(__name__, static_folder='public', static_url_path='/assets')


class Database:
    def __init__(self, raw, mysql=False):
        self.raw = raw
        self.mysql = mysql

    def execute(self, sql, params=()):
        if self.mysql:
            sql = sql.replace('?', '%s')
        cursor = self.raw.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def using_mysql():
    return bool(DATABASE_URL.startswith(('mysql://', 'mysql+pymysql://'))) and pymysql is not None


def db():
    if using_mysql():
        parsed = urlparse(DATABASE_URL.replace('mysql+pymysql://', 'mysql://', 1))
        options = {
            'host': parsed.hostname,
            'port': parsed.port or 3306,
            'user': unquote(parsed.username or ''),
            'password': unquote(parsed.password or ''),
            'database': parsed.path.lstrip('/'),
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor,
            'autocommit': False,
            'connect_timeout': 10,
        }
        # Managed MySQL connections require TLS; PyMySQL uses the provider's default CA bundle.
        try:
            raw = pymysql.connect(**options, ssl={'check_hostname': False})
        except Exception:
            raw = pymysql.connect(**options)
        return Database(raw, mysql=True)
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    return Database(raw, mysql=False)


def row_dict(row):
    return dict(row) if row is not None else None


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def parse_day(value, label):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a valid date')


def parse_datetime(value):
    text = str(value or '').replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        raise ValueError('Start time must be a valid date and time')


def table_columns(connection, table):
    if connection.mysql:
        rows = connection.execute(f'DESCRIBE {table}').fetchall()
        return {row['Field'] for row in rows}
    rows = connection.execute(f'PRAGMA table_info({table})').fetchall()
    return {row['name'] for row in rows}


def ensure_column(connection, table, column, definition):
    if column in table_columns(connection, table):
        return
    try:
        connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        connection.commit()
    except Exception:
        connection.rollback()


def init_db():
    connection = db()
    if connection.mysql:
        statements = [
            '''CREATE TABLE IF NOT EXISTS users (id BIGINT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(160) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, college VARCHAR(255) NOT NULL, verified TINYINT DEFAULT 0, role VARCHAR(40) DEFAULT 'student', rating DOUBLE DEFAULT 5.0, created_at VARCHAR(40) NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS sessions (id BIGINT AUTO_INCREMENT PRIMARY KEY, token_hash CHAR(64) UNIQUE NOT NULL, user_id BIGINT NOT NULL, expires_at VARCHAR(40) NOT NULL, created_at VARCHAR(40) NOT NULL, INDEX sessions_user_idx (user_id))''',
            '''CREATE TABLE IF NOT EXISTS devices (id BIGINT AUTO_INCREMENT PRIMARY KEY, owner_id BIGINT NOT NULL, name VARCHAR(255) NOT NULL, category VARCHAR(80) NOT NULL, `condition` VARCHAR(255) NOT NULL, price_per_day DOUBLE DEFAULT 0, available_from VARCHAR(40), available_to VARCHAR(40), status VARCHAR(40) DEFAULT 'available')''',
            '''CREATE TABLE IF NOT EXISTS rental_requests (id BIGINT AUTO_INCREMENT PRIMARY KEY, public_id VARCHAR(32) UNIQUE NOT NULL, device_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, borrower_id BIGINT NOT NULL, pickup_date VARCHAR(20) NOT NULL, return_date VARCHAR(20) NOT NULL, pickup_location VARCHAR(255) NOT NULL, message TEXT, status VARCHAR(40) DEFAULT 'Pending', created_at VARCHAR(40) NOT NULL, decided_at VARCHAR(40))''',
            '''CREATE TABLE IF NOT EXISTS bookings (id BIGINT AUTO_INCREMENT PRIMARY KEY, request_id BIGINT, device_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, borrower_id BIGINT NOT NULL, reason TEXT NOT NULL, start_at VARCHAR(40) NOT NULL, duration_hours INT NOT NULL, return_at VARCHAR(40) NOT NULL, pickup_date VARCHAR(20), return_date VARCHAR(20), pickup_location VARCHAR(255), fee DOUBLE NOT NULL, late_fee DOUBLE DEFAULT 0, purchase_estimate DOUBLE DEFAULT 0, savings DOUBLE DEFAULT 0, status VARCHAR(40) DEFAULT 'pending', payment_status VARCHAR(40) DEFAULT 'unpaid', picked_up_at VARCHAR(40), returned_at VARCHAR(40))''',
            '''CREATE TABLE IF NOT EXISTS payments (id BIGINT AUTO_INCREMENT PRIMARY KEY, booking_id BIGINT NOT NULL, amount DOUBLE NOT NULL, status VARCHAR(80) NOT NULL, created_at VARCHAR(40) NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS savings (id BIGINT AUTO_INCREMENT PRIMARY KEY, booking_id BIGINT UNIQUE NOT NULL, borrower_id BIGINT NOT NULL, amount DOUBLE NOT NULL, created_at VARCHAR(40) NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS requests (id BIGINT AUTO_INCREMENT PRIMARY KEY, requester_id BIGINT NOT NULL, title VARCHAR(255) NOT NULL, category VARCHAR(80) NOT NULL, duration VARCHAR(80) NOT NULL, detail TEXT, status VARCHAR(40) DEFAULT 'open', created_at VARCHAR(40) NOT NULL)''',
        ]
        for statement in statements:
            connection.execute(statement)
            connection.commit()
    else:
        connection.raw.row_factory = sqlite3.Row
        connection.raw.executescript('''
          CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, college TEXT NOT NULL, verified INTEGER DEFAULT 0, role TEXT DEFAULT 'student', rating REAL DEFAULT 5.0, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, condition TEXT NOT NULL, price_per_day REAL DEFAULT 0, available_from TEXT, available_to TEXT, status TEXT DEFAULT 'available');
          CREATE TABLE IF NOT EXISTS rental_requests (id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, device_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, borrower_id INTEGER NOT NULL, pickup_date TEXT NOT NULL, return_date TEXT NOT NULL, pickup_location TEXT NOT NULL, message TEXT, status TEXT DEFAULT 'Pending', created_at TEXT NOT NULL, decided_at TEXT);
          CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY, request_id INTEGER, device_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, borrower_id INTEGER NOT NULL, reason TEXT NOT NULL, start_at TEXT NOT NULL, duration_hours INTEGER NOT NULL, return_at TEXT NOT NULL, pickup_date TEXT, return_date TEXT, pickup_location TEXT, fee REAL NOT NULL, late_fee REAL DEFAULT 0, purchase_estimate REAL DEFAULT 0, savings REAL DEFAULT 0, status TEXT DEFAULT 'pending', payment_status TEXT DEFAULT 'unpaid', picked_up_at TEXT, returned_at TEXT);
          CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS savings (id INTEGER PRIMARY KEY, booking_id INTEGER UNIQUE NOT NULL, borrower_id INTEGER NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, duration TEXT NOT NULL, detail TEXT, status TEXT DEFAULT 'open', created_at TEXT NOT NULL);
        ''')
        connection.commit()

    # Additive migration for databases created by the original CampusLend prototype.
    for column, definition in {
        'owner_id': 'INTEGER' if not connection.mysql else 'BIGINT',
        'request_id': 'INTEGER' if not connection.mysql else 'BIGINT',
        'pickup_date': 'TEXT' if not connection.mysql else 'VARCHAR(20)',
        'return_date': 'TEXT' if not connection.mysql else 'VARCHAR(20)',
        'pickup_location': 'TEXT' if not connection.mysql else 'VARCHAR(255)',
        'purchase_estimate': 'REAL DEFAULT 0' if not connection.mysql else 'DOUBLE DEFAULT 0',
        'savings': 'REAL DEFAULT 0' if not connection.mysql else 'DOUBLE DEFAULT 0',
    }.items():
        ensure_column(connection, 'bookings', column, definition)
    try:
        if connection.mysql:
            connection.execute('ALTER TABLE payments ADD UNIQUE KEY payments_booking_unique (booking_id)')
        else:
            connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS payments_booking_unique ON payments(booking_id)')
        connection.commit()
    except Exception:
        connection.rollback()
    connection.close()


def user_payload(row):
    return {key: row[key] for key in ('id', 'name', 'email', 'college', 'verified', 'role', 'rating')}


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def current_user_id():
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    connection = db()
    row = connection.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?', (hash_token(token), now_iso())).fetchone()
    connection.close()
    return row['user_id'] if row else None


def current_user():
    user_id = current_user_id()
    if not user_id:
        return None
    connection = db()
    row = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    connection.close()
    return row_dict(row)


def require_user():
    user_id = current_user_id()
    if not user_id:
        return None, (jsonify(error='Sign in required'), 401)
    return user_id, None


def auth_response(user_id, status=200):
    token = secrets.token_urlsafe(48)
    connection = db()
    connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
    connection.execute('INSERT INTO sessions (token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)', (hash_token(token), user_id, (datetime.utcnow() + timedelta(seconds=SESSION_MAX_AGE)).isoformat(), now_iso()))
    connection.commit()
    row = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    connection.close()
    response = jsonify(user=user_payload(row))
    response.status_code = status
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True, secure=True, samesite='None', path='/')
    return response


@app.get('/health')
def health():
    return jsonify(ok=True, service='campuslend', database='mysql' if using_mysql() else 'sqlite')


@app.post('/api/auth/register')
def register():
    body = request.get_json(force=True) or {}
    required = ('name', 'email', 'password', 'college')
    if any(not str(body.get(key, '')).strip() for key in required):
        return jsonify(error='Name, college, email, and password are required'), 400
    if len(body['password']) < 8:
        return jsonify(error='Password must be at least 8 characters'), 400
    connection = db()
    try:
        cursor = connection.execute('INSERT INTO users (name,email,password_hash,college,verified,created_at) VALUES (?,?,?,?,?,?)', (body['name'].strip(), body['email'].lower().strip(), generate_password_hash(body['password']), body['college'].strip(), 0, now_iso()))
        connection.commit()
        user_id = cursor.lastrowid
    except Exception as error:
        connection.rollback()
        connection.close()
        if 'duplicate' in str(error).lower() or 'unique' in str(error).lower() or 'integrity' in str(error).lower():
            return jsonify(error='A student with that email already exists'), 409
        raise
    connection.close()
    return auth_response(user_id, 201)


@app.post('/api/auth/login')
def login():
    body = request.get_json(force=True) or {}
    connection = db()
    row = connection.execute('SELECT * FROM users WHERE email=?', (body.get('email', '').lower().strip(),)).fetchone()
    connection.close()
    if not row or not check_password_hash(row['password_hash'], body.get('password', '')):
        return jsonify(error='Invalid student email or password'), 401
    return auth_response(row['id'])


@app.post('/api/auth/logout')
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        connection = db()
        connection.execute('DELETE FROM sessions WHERE token_hash=?', (hash_token(token),))
        connection.commit()
        connection.close()
    response = jsonify(ok=True)
    response.delete_cookie(SESSION_COOKIE, path='/', samesite='None')
    return response


@app.get('/api/auth/me')
def me():
    row = current_user()
    return jsonify(user=user_payload(row) if row else None)


@app.get('/api/devices')
def devices():
    user_id, error = require_user()
    if error:
        return jsonify(devices=[])
    connection = db()
    rows = connection.execute('SELECT devices.*, users.name AS owner_name, users.rating AS owner_rating FROM devices JOIN users ON users.id=devices.owner_id WHERE devices.status=? AND devices.owner_id<>? ORDER BY devices.id DESC', ('available', user_id)).fetchall()
    connection.close()
    return jsonify(devices=[row_dict(row) for row in rows])


@app.post('/api/devices')
def create_device():
    user_id, error = require_user()
    if error:
        return error
    body = request.get_json(force=True) or {}
    if not str(body.get('name', '')).strip() or not str(body.get('category', '')).strip():
        return jsonify(error='Equipment name and category are required'), 400
    connection = db()
    cursor = connection.execute('INSERT INTO devices (owner_id,name,category,`condition`,price_per_day,available_from,available_to,status) VALUES (?,?,?,?,?,?,?,?)', (user_id, body['name'].strip(), body['category'], body.get('condition', 'Good condition'), float(body.get('price_per_day') or 0), body.get('available_from'), body.get('available_to'), 'available'))
    connection.commit()
    device_id = cursor.lastrowid
    connection.close()
    return jsonify(device={'id': device_id, 'owner_id': user_id, 'name': body['name'], 'category': body['category'], 'status': 'available'}), 201


@app.get('/api/tools')
def tools():
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    devices_rows = connection.execute('SELECT devices.*, users.name AS owner_name FROM devices JOIN users ON users.id=devices.owner_id WHERE devices.owner_id=? ORDER BY devices.id DESC', (user_id,)).fetchall()
    request_rows = connection.execute('''SELECT rental_requests.*, devices.name AS device_name, devices.category, borrowers.name AS borrower_name, borrowers.email AS borrower_email
        FROM rental_requests JOIN devices ON devices.id=rental_requests.device_id JOIN users borrowers ON borrowers.id=rental_requests.borrower_id
        WHERE rental_requests.owner_id=? ORDER BY rental_requests.id DESC''', (user_id,)).fetchall()
    booking_rows = connection.execute('''SELECT bookings.*, devices.name AS device_name, devices.category, owners.name AS owner_name, borrowers.name AS borrower_name
        FROM bookings JOIN devices ON devices.id=bookings.device_id JOIN users owners ON owners.id=bookings.owner_id JOIN users borrowers ON borrowers.id=bookings.borrower_id
        WHERE bookings.owner_id=? ORDER BY bookings.id DESC''', (user_id,)).fetchall()
    connection.close()
    return jsonify(tools=[row_dict(row) for row in devices_rows], incoming_requests=[row_dict(row) for row in request_rows], rentals=[row_dict(row) for row in booking_rows])


@app.get('/api/requests')
def get_requests():
    user_id, error = require_user()
    if error:
        return jsonify(requests=[])
    connection = db()
    rows = connection.execute('''SELECT rental_requests.*, devices.name AS device_name, devices.category, owners.name AS owner_name, borrowers.name AS borrower_name
        FROM rental_requests JOIN devices ON devices.id=rental_requests.device_id JOIN users owners ON owners.id=rental_requests.owner_id JOIN users borrowers ON borrowers.id=rental_requests.borrower_id
        WHERE rental_requests.owner_id=? OR rental_requests.borrower_id=? ORDER BY rental_requests.id DESC''', (user_id, user_id)).fetchall()
    connection.close()
    return jsonify(requests=[row_dict(row) for row in rows])


@app.post('/api/rental-requests')
def create_rental_request():
    borrower_id, error = require_user()
    if error:
        return error
    body = request.get_json(force=True) or {}
    required = ('device_id', 'pickup_date', 'return_date', 'pickup_location')
    if any(not str(body.get(key, '')).strip() for key in required):
        return jsonify(error='Pickup date, return date, and pickup location are required'), 400
    try:
        pickup_date = parse_day(body['pickup_date'], 'Pickup date')
        return_date = parse_day(body['return_date'], 'Return date')
    except ValueError as error_message:
        return jsonify(error=str(error_message)), 400
    if return_date < pickup_date:
        return jsonify(error='Return date cannot be before pickup date'), 400
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    device_query = 'SELECT * FROM devices WHERE id=? AND status=?' + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(device_query, (body['device_id'], 'available')).fetchone()
    if not device:
        connection.close()
        return jsonify(error='Equipment is unavailable'), 404
    if device['owner_id'] == borrower_id:
        connection.close()
        return jsonify(error='You cannot request your own equipment'), 400
    conflict_query = "SELECT id FROM rental_requests WHERE device_id=? AND status IN ('Pending','Approved','Active') AND pickup_date <= ? AND return_date >= ?" + (' FOR UPDATE' if connection.mysql else '')
    conflict = connection.execute(conflict_query, (device['id'], return_date.isoformat(), pickup_date.isoformat())).fetchone()
    if conflict:
        connection.close()
        return jsonify(error='This equipment already has a request in those dates'), 409
    public_id = f"RR-{secrets.token_hex(4).upper()}"
    cursor = connection.execute('INSERT INTO rental_requests (public_id,device_id,owner_id,borrower_id,pickup_date,return_date,pickup_location,message,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)', (public_id, device['id'], device['owner_id'], borrower_id, pickup_date.isoformat(), return_date.isoformat(), body['pickup_location'].strip(), body.get('message', '').strip(), 'Pending', now_iso()))
    connection.commit()
    request_id = cursor.lastrowid
    connection.close()
    return jsonify(request={'id': request_id, 'public_id': public_id, 'status': 'Pending'}), 201


@app.post('/api/rental-requests/<int:request_id>/approve')
def approve_rental_request(request_id):
    owner_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    request_query = 'SELECT rental_requests.*, devices.name AS device_name, devices.price_per_day FROM rental_requests JOIN devices ON devices.id=rental_requests.device_id WHERE rental_requests.id=?' + (' FOR UPDATE' if connection.mysql else '')
    rental_request = connection.execute(request_query, (request_id,)).fetchone()
    if not rental_request:
        connection.close()
        return jsonify(error='Request not found'), 404
    if rental_request['owner_id'] != owner_id:
        connection.close()
        return jsonify(error='Only the equipment owner can approve this request'), 403
    if rental_request['status'] != 'Pending':
        connection.close()
        return jsonify(error='This request has already been decided'), 409
    conflict_query = "SELECT id FROM bookings WHERE device_id=? AND status IN ('approved','active') AND pickup_date <= ? AND return_date >= ?" + (' FOR UPDATE' if connection.mysql else '')
    conflict = connection.execute(conflict_query, (rental_request['device_id'], rental_request['return_date'], rental_request['pickup_date'])).fetchone()
    if conflict:
        connection.close()
        return jsonify(error='This equipment already has a confirmed booking in those dates'), 409
    days = max((parse_day(rental_request['return_date'], 'Return date') - parse_day(rental_request['pickup_date'], 'Pickup date')).days, 1)
    fee = round(float(rental_request['price_per_day'] or 0) * days, 2)
    purchase_estimate = round(max(float(rental_request['price_per_day'] or 0) * 30, fee), 2)
    start_at = f"{rental_request['pickup_date']}T09:00:00"
    return_at = f"{rental_request['return_date']}T18:00:00"
    cursor = connection.execute('''INSERT INTO bookings (request_id,device_id,owner_id,borrower_id,reason,start_at,duration_hours,return_at,pickup_date,return_date,pickup_location,fee,purchase_estimate,status,payment_status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (request_id, rental_request['device_id'], owner_id, rental_request['borrower_id'], rental_request['message'] or 'Campus equipment rental', start_at, days * 24, return_at, rental_request['pickup_date'], rental_request['return_date'], rental_request['pickup_location'], fee, purchase_estimate, 'approved', 'unpaid'))
    connection.execute('UPDATE rental_requests SET status=?, decided_at=? WHERE id=?', ('Approved', now_iso(), request_id))
    connection.execute('UPDATE devices SET status=? WHERE id=?', ('rented', rental_request['device_id']))
    connection.commit()
    booking_id = cursor.lastrowid
    connection.close()
    return jsonify(ok=True, status='Approved', booking_id=booking_id)


@app.post('/api/rental-requests/<int:request_id>/reject')
def reject_rental_request(request_id):
    owner_id, error = require_user()
    if error:
        return error
    connection = db()
    rental_request = connection.execute('SELECT owner_id,status FROM rental_requests WHERE id=?', (request_id,)).fetchone()
    if not rental_request:
        connection.close()
        return jsonify(error='Request not found'), 404
    if rental_request['owner_id'] != owner_id:
        connection.close()
        return jsonify(error='Only the equipment owner can reject this request'), 403
    if rental_request['status'] != 'Pending':
        connection.close()
        return jsonify(error='This request has already been decided'), 409
    connection.execute('UPDATE rental_requests SET status=?, decided_at=? WHERE id=?', ('Rejected', now_iso(), request_id))
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='Rejected')


@app.get('/api/bookings')
def bookings():
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    rows = connection.execute('''SELECT bookings.*, devices.name AS device_name, devices.category, owners.name AS owner_name, borrowers.name AS borrower_name
        FROM bookings JOIN devices ON devices.id=bookings.device_id JOIN users owners ON owners.id=bookings.owner_id JOIN users borrowers ON borrowers.id=bookings.borrower_id
        WHERE bookings.borrower_id=? OR bookings.owner_id=? ORDER BY bookings.id DESC''', (user_id, user_id)).fetchall()
    connection.close()
    return jsonify(bookings=[row_dict(row) for row in rows])


@app.post('/api/bookings/<int:booking_id>/simulate-payment')
def simulate_payment(booking_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    booking = connection.execute('SELECT * FROM bookings WHERE id=? AND (borrower_id=? OR owner_id=?)', (booking_id, user_id, user_id)).fetchone()
    if not booking:
        connection.close()
        return jsonify(error='Booking not found or not authorized'), 404
    existing_payment = connection.execute('SELECT id FROM payments WHERE booking_id=? ORDER BY id DESC LIMIT 1', (booking_id,)).fetchone()
    if existing_payment:
        connection.close()
        return jsonify(ok=True, payment_status='DEMO_SIMULATED_PAID', demo=True, already_recorded=True)
    connection.execute('UPDATE bookings SET payment_status=? WHERE id=?', ('DEMO_SIMULATED_PAID', booking_id))
    connection.execute('INSERT INTO payments (booking_id,amount,status,created_at) VALUES (?,?,?,?)', (booking_id, booking['fee'], 'DEMO_SIMULATED_PAID', now_iso()))
    connection.commit()
    connection.close()
    return jsonify(ok=True, payment_status='DEMO_SIMULATED_PAID', demo=True)


@app.post('/api/bookings/<int:booking_id>/return')
def return_booking(booking_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    booking = connection.execute('SELECT * FROM bookings WHERE id=? AND (borrower_id=? OR owner_id=?)', (booking_id, user_id, user_id)).fetchone()
    if not booking:
        connection.close()
        return jsonify(error='Booking not found or not authorized'), 404
    if booking['status'] == 'returned':
        connection.close()
        return jsonify(error='This rental is already closed'), 409
    returned_at = datetime.utcnow()
    deadline = datetime.fromisoformat(booking['return_at'].replace('Z', '+00:00')).replace(tzinfo=None)
    late_hours = max(0, int((returned_at - deadline).total_seconds() // 3600))
    late_fee = round(late_hours * 10, 2)
    savings_amount = round(max(float(booking['purchase_estimate'] or 0) - float(booking['fee'] or 0), 0), 2)
    connection.execute('UPDATE bookings SET status=?, returned_at=?, late_fee=?, savings=? WHERE id=?', ('returned', returned_at.isoformat(), late_fee, savings_amount, booking_id))
    connection.execute('UPDATE devices SET status=? WHERE id=?', ('available', booking['device_id']))
    connection.execute('INSERT IGNORE INTO savings (booking_id,borrower_id,amount,created_at) VALUES (?,?,?,?)', (booking_id, booking['borrower_id'], savings_amount, now_iso())) if connection.mysql else connection.execute('INSERT OR IGNORE INTO savings (booking_id,borrower_id,amount,created_at) VALUES (?,?,?,?)', (booking_id, booking['borrower_id'], savings_amount, now_iso()))
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='returned', late_fee=late_fee, late_hours=late_hours, savings=savings_amount)


@app.post('/api/requests')
def create_generic_request():
    user_id, error = require_user()
    if error:
        return error
    body = request.get_json(force=True) or {}
    if not body.get('title') or not body.get('category') or not body.get('duration'):
        return jsonify(error='Title, category, and duration are required'), 400
    connection = db()
    cursor = connection.execute('INSERT INTO requests (requester_id,title,category,duration,detail,created_at) VALUES (?,?,?,?,?,?)', (user_id, body['title'], body['category'], body['duration'], body.get('detail', ''), now_iso()))
    connection.commit()
    request_id = cursor.lastrowid
    connection.close()
    return jsonify(request={'id': request_id, 'status': 'open'}), 201


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
