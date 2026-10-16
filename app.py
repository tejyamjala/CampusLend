import hashlib
import math
import os
import re
import secrets
import sqlite3
import ssl
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
except ImportError:  # Local SQLite development still works before dependency installation.
    pymysql = None

ROOT = os.path.dirname(__file__)
DB_PATH = os.environ.get('CAMPUSLEND_DB_PATH', os.path.join(ROOT, 'campuslend.sqlite3'))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
SESSION_COOKIE = 'campuslend_session'
SESSION_MAX_AGE = 60 * 60 * 24 * 30
EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
UTC_TIMESTAMP_FIELDS = {'created_at', 'decided_at', 'expires_at', 'start_at', 'return_at', 'picked_up_at', 'returned_at'}
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
    return DATABASE_URL.startswith(('mysql://', 'mysql+pymysql://'))


def db():
    if DATABASE_URL:
        if not using_mysql():
            raise RuntimeError('DATABASE_URL must use mysql:// or mysql+pymysql://')
        if pymysql is None:
            raise RuntimeError('PyMySQL is required when DATABASE_URL is configured')
        parsed = urlparse(DATABASE_URL.replace('mysql+pymysql://', 'mysql://', 1))
        if not parsed.hostname or not parsed.path.strip('/') or not parsed.username:
            raise RuntimeError('DATABASE_URL is missing a database host, name, or username')
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
        # Fail closed: verify the managed MySQL server certificate and hostname.
        raw = pymysql.connect(**options, ssl=ssl.create_default_context())
        return Database(raw, mysql=True)
    if os.environ.get('APP_ENV', '').lower() == 'production':
        raise RuntimeError('DATABASE_URL is required in production; refusing ephemeral SQLite storage')
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute('PRAGMA foreign_keys = ON')
    return Database(raw, mysql=False)


def row_dict(row):
    if row is None:
        return None
    result = dict(row)
    for field in UTC_TIMESTAMP_FIELDS:
        value = result.get(field)
        if not isinstance(value, str) or not value or 'T' not in value or value.endswith('Z') or re.search(r'[+-]\d\d:\d\d$', value):
            continue
        try:
            datetime.fromisoformat(value)
        except ValueError:
            continue
        result[field] = f'{value}Z'
    return result


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


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


def json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def parse_nonnegative_amount(value, label):
    try:
        amount = float(value if value not in (None, '') else 0)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a valid amount')
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f'{label} must be zero or greater')
    return round(amount, 2)


def validated_device_fields(body):
    name = body.get('name')
    category = body.get('category')
    condition = body.get('condition', 'Good condition')
    if not isinstance(name, str) or not name.strip() or not isinstance(category, str) or not category.strip():
        raise ValueError('Equipment name and category are required')
    if len(name.strip()) > 255 or len(category.strip()) > 80 or not isinstance(condition, str) or len(condition.strip()) > 255:
        raise ValueError('Equipment details exceed the allowed length')
    price_per_day = parse_nonnegative_amount(body.get('price_per_day'), 'Daily rate')
    available_from = body.get('available_from') or None
    available_to = body.get('available_to') or None
    if available_from:
        available_from = parse_day(available_from, 'Available-from date').isoformat()
    if available_to:
        available_to = parse_day(available_to, 'Available-to date').isoformat()
    if available_from and available_to and available_to < available_from:
        raise ValueError('Available-to date cannot be before available-from date')
    return {
        'name': name.strip(),
        'category': category.strip(),
        'condition': condition.strip() or 'Good condition',
        'price_per_day': price_per_day,
        'available_from': available_from,
        'available_to': available_to,
    }


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
    except Exception as error:
        connection.rollback()
        if column not in table_columns(connection, table):
            raise RuntimeError(f'Could not add required database column {table}.{column}') from error


def mysql_constraint_exists(connection, table, constraint):
    row = connection.execute('''SELECT COUNT(*) AS count FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME=? AND CONSTRAINT_NAME=? AND CONSTRAINT_TYPE='FOREIGN KEY' ''', (table, constraint)).fetchone()
    return bool(row['count'])


def ensure_foreign_key(connection, table, constraint, column, parent_table):
    if not connection.mysql or mysql_constraint_exists(connection, table, constraint):
        return
    orphan = connection.execute(f'''SELECT COUNT(*) AS count FROM `{table}` AS child
        LEFT JOIN `{parent_table}` AS parent ON child.`{column}`=parent.id
        WHERE child.`{column}` IS NOT NULL AND parent.id IS NULL''').fetchone()
    if orphan['count']:
        raise RuntimeError(f'Cannot add required relationship {table}.{column} → {parent_table}.id: legacy orphan rows exist')
    try:
        connection.execute(f'ALTER TABLE `{table}` ADD CONSTRAINT `{constraint}` FOREIGN KEY (`{column}`) REFERENCES `{parent_table}` (`id`)')
        connection.commit()
    except Exception as error:
        connection.rollback()
        if not mysql_constraint_exists(connection, table, constraint):
            raise RuntimeError(f'Could not install required database relationship {table}.{column}') from error


def unique_index_exists(connection, table, index_name):
    if connection.mysql:
        row = connection.execute('''SELECT COUNT(*) AS count FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND INDEX_NAME=? AND NON_UNIQUE=0''', (table, index_name)).fetchone()
        return bool(row['count'])
    indexes = connection.execute(f'PRAGMA index_list({table})').fetchall()
    return any(index['name'] == index_name and index['unique'] for index in indexes)


def ensure_unique_index(connection, table, index_name, columns):
    if unique_index_exists(connection, table, index_name):
        return
    try:
        if connection.mysql:
            connection.execute(f'ALTER TABLE `{table}` ADD UNIQUE INDEX `{index_name}` ({columns})')
        else:
            connection.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})')
        connection.commit()
    except Exception as error:
        connection.rollback()
        if not unique_index_exists(connection, table, index_name):
            raise RuntimeError(f'Could not install required unique index {table}.{index_name}') from error


def init_db():
    connection = db()
    if connection.mysql:
        statements = [
            '''CREATE TABLE IF NOT EXISTS users (id BIGINT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(160) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, college VARCHAR(255) NOT NULL, verified TINYINT DEFAULT 0, role VARCHAR(40) DEFAULT 'student', rating DOUBLE DEFAULT 5.0, created_at VARCHAR(40) NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS sessions (id BIGINT AUTO_INCREMENT PRIMARY KEY, token_hash CHAR(64) UNIQUE NOT NULL, user_id BIGINT NOT NULL, expires_at VARCHAR(40) NOT NULL, created_at VARCHAR(40) NOT NULL, INDEX sessions_user_idx (user_id), CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id))''',
            '''CREATE TABLE IF NOT EXISTS devices (id BIGINT AUTO_INCREMENT PRIMARY KEY, owner_id BIGINT NOT NULL, name VARCHAR(255) NOT NULL, category VARCHAR(80) NOT NULL, `condition` VARCHAR(255) NOT NULL, price_per_day DOUBLE DEFAULT 0, available_from VARCHAR(40), available_to VARCHAR(40), status VARCHAR(40) DEFAULT 'available', CONSTRAINT fk_devices_owner FOREIGN KEY (owner_id) REFERENCES users(id))''',
            '''CREATE TABLE IF NOT EXISTS rental_requests (id BIGINT AUTO_INCREMENT PRIMARY KEY, public_id VARCHAR(32) UNIQUE NOT NULL, device_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, borrower_id BIGINT NOT NULL, pickup_date VARCHAR(20) NOT NULL, return_date VARCHAR(20) NOT NULL, pickup_location VARCHAR(255) NOT NULL, message TEXT, status VARCHAR(40) DEFAULT 'Pending', created_at VARCHAR(40) NOT NULL, decided_at VARCHAR(40), CONSTRAINT fk_rental_requests_device FOREIGN KEY (device_id) REFERENCES devices(id), CONSTRAINT fk_rental_requests_owner FOREIGN KEY (owner_id) REFERENCES users(id), CONSTRAINT fk_rental_requests_borrower FOREIGN KEY (borrower_id) REFERENCES users(id))''',
            '''CREATE TABLE IF NOT EXISTS bookings (id BIGINT AUTO_INCREMENT PRIMARY KEY, request_id BIGINT, device_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, borrower_id BIGINT NOT NULL, reason TEXT NOT NULL, start_at VARCHAR(40) NOT NULL, duration_hours INT NOT NULL, return_at VARCHAR(40) NOT NULL, pickup_date VARCHAR(20), return_date VARCHAR(20), pickup_location VARCHAR(255), fee DOUBLE NOT NULL, late_fee DOUBLE DEFAULT 0, purchase_estimate DOUBLE DEFAULT 0, savings DOUBLE DEFAULT 0, status VARCHAR(40) DEFAULT 'pending', payment_status VARCHAR(40) DEFAULT 'unpaid', picked_up_at VARCHAR(40), returned_at VARCHAR(40), CONSTRAINT fk_bookings_request FOREIGN KEY (request_id) REFERENCES rental_requests(id), CONSTRAINT fk_bookings_device FOREIGN KEY (device_id) REFERENCES devices(id), CONSTRAINT fk_bookings_owner FOREIGN KEY (owner_id) REFERENCES users(id), CONSTRAINT fk_bookings_borrower FOREIGN KEY (borrower_id) REFERENCES users(id))''',
            '''CREATE TABLE IF NOT EXISTS payments (id BIGINT AUTO_INCREMENT PRIMARY KEY, booking_id BIGINT NOT NULL, amount DOUBLE NOT NULL, status VARCHAR(80) NOT NULL, created_at VARCHAR(40) NOT NULL, CONSTRAINT fk_payments_booking FOREIGN KEY (booking_id) REFERENCES bookings(id))''',
            '''CREATE TABLE IF NOT EXISTS savings (id BIGINT AUTO_INCREMENT PRIMARY KEY, booking_id BIGINT UNIQUE NOT NULL, borrower_id BIGINT NOT NULL, amount DOUBLE NOT NULL, created_at VARCHAR(40) NOT NULL, CONSTRAINT fk_savings_booking FOREIGN KEY (booking_id) REFERENCES bookings(id), CONSTRAINT fk_savings_borrower FOREIGN KEY (borrower_id) REFERENCES users(id))''',
            '''CREATE TABLE IF NOT EXISTS requests (id BIGINT AUTO_INCREMENT PRIMARY KEY, requester_id BIGINT NOT NULL, title VARCHAR(255) NOT NULL, category VARCHAR(80) NOT NULL, duration VARCHAR(80) NOT NULL, detail TEXT, status VARCHAR(40) DEFAULT 'open', created_at VARCHAR(40) NOT NULL, CONSTRAINT fk_requests_requester FOREIGN KEY (requester_id) REFERENCES users(id))''',
        ]
        for statement in statements:
            connection.execute(statement)
            connection.commit()
    else:
        connection.raw.row_factory = sqlite3.Row
        connection.raw.executescript('''
          CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, college TEXT NOT NULL, verified INTEGER DEFAULT 0, role TEXT DEFAULT 'student', rating REAL DEFAULT 5.0, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id));
          CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, condition TEXT NOT NULL, price_per_day REAL DEFAULT 0, available_from TEXT, available_to TEXT, status TEXT DEFAULT 'available', FOREIGN KEY (owner_id) REFERENCES users(id));
          CREATE TABLE IF NOT EXISTS rental_requests (id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, device_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, borrower_id INTEGER NOT NULL, pickup_date TEXT NOT NULL, return_date TEXT NOT NULL, pickup_location TEXT NOT NULL, message TEXT, status TEXT DEFAULT 'Pending', created_at TEXT NOT NULL, decided_at TEXT, FOREIGN KEY (device_id) REFERENCES devices(id), FOREIGN KEY (owner_id) REFERENCES users(id), FOREIGN KEY (borrower_id) REFERENCES users(id));
          CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY, request_id INTEGER, device_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, borrower_id INTEGER NOT NULL, reason TEXT NOT NULL, start_at TEXT NOT NULL, duration_hours INTEGER NOT NULL, return_at TEXT NOT NULL, pickup_date TEXT, return_date TEXT, pickup_location TEXT, fee REAL NOT NULL, late_fee REAL DEFAULT 0, purchase_estimate REAL DEFAULT 0, savings REAL DEFAULT 0, status TEXT DEFAULT 'pending', payment_status TEXT DEFAULT 'unpaid', picked_up_at TEXT, returned_at TEXT, FOREIGN KEY (request_id) REFERENCES rental_requests(id), FOREIGN KEY (device_id) REFERENCES devices(id), FOREIGN KEY (owner_id) REFERENCES users(id), FOREIGN KEY (borrower_id) REFERENCES users(id));
          CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (booking_id) REFERENCES bookings(id));
          CREATE TABLE IF NOT EXISTS savings (id INTEGER PRIMARY KEY, booking_id INTEGER UNIQUE NOT NULL, borrower_id INTEGER NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (booking_id) REFERENCES bookings(id), FOREIGN KEY (borrower_id) REFERENCES users(id));
          CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, duration TEXT NOT NULL, detail TEXT, status TEXT DEFAULT 'open', created_at TEXT NOT NULL, FOREIGN KEY (requester_id) REFERENCES users(id));
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
    if connection.mysql:
        connection.execute("UPDATE bookings SET pickup_date=SUBSTRING(start_at,1,10) WHERE pickup_date IS NULL AND start_at IS NOT NULL")
        connection.execute("UPDATE bookings SET return_date=SUBSTRING(return_at,1,10) WHERE return_date IS NULL AND return_at IS NOT NULL")
        connection.execute("UPDATE sessions SET expires_at=CONCAT(expires_at,'Z') WHERE expires_at LIKE '%T%' AND expires_at NOT LIKE '%Z' AND expires_at NOT LIKE '%+%'")
    else:
        connection.execute("UPDATE bookings SET pickup_date=SUBSTR(start_at,1,10) WHERE pickup_date IS NULL AND start_at IS NOT NULL")
        connection.execute("UPDATE bookings SET return_date=SUBSTR(return_at,1,10) WHERE return_date IS NULL AND return_at IS NOT NULL")
        connection.execute("UPDATE sessions SET expires_at=expires_at || 'Z' WHERE expires_at LIKE '%T%' AND expires_at NOT LIKE '%Z' AND expires_at NOT LIKE '%+%'")
    connection.commit()
    for table, constraint, column, parent_table in (
        ('sessions', 'fk_sessions_user', 'user_id', 'users'),
        ('devices', 'fk_devices_owner', 'owner_id', 'users'),
        ('rental_requests', 'fk_rental_requests_device', 'device_id', 'devices'),
        ('rental_requests', 'fk_rental_requests_owner', 'owner_id', 'users'),
        ('rental_requests', 'fk_rental_requests_borrower', 'borrower_id', 'users'),
        ('bookings', 'fk_bookings_request', 'request_id', 'rental_requests'),
        ('bookings', 'fk_bookings_device', 'device_id', 'devices'),
        ('bookings', 'fk_bookings_owner', 'owner_id', 'users'),
        ('bookings', 'fk_bookings_borrower', 'borrower_id', 'users'),
        ('payments', 'fk_payments_booking', 'booking_id', 'bookings'),
        ('savings', 'fk_savings_booking', 'booking_id', 'bookings'),
        ('savings', 'fk_savings_borrower', 'borrower_id', 'users'),
        ('requests', 'fk_requests_requester', 'requester_id', 'users'),
    ):
        ensure_foreign_key(connection, table, constraint, column, parent_table)
    ensure_unique_index(connection, 'payments', 'payments_booking_unique', 'booking_id')
    ensure_unique_index(connection, 'bookings', 'bookings_request_unique', 'request_id')
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


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if request.path.startswith('/api/'):
        return jsonify(error=error.description), error.code
    return error


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception('Unhandled CampusLend request error')
    return jsonify(error='We could not complete that action. Refresh the page and try again.'), 500


@app.before_request
def enforce_same_origin_api_writes():
    if not request.path.startswith('/api/') or request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    source = request.headers.get('Origin') or request.headers.get('Referer')
    if not source:
        return jsonify(error='Request origin is required for this action'), 403
    parsed = urlparse(source)
    if parsed.scheme not in {'http', 'https'} or parsed.netloc.lower() != request.host.lower():
        return jsonify(error='Cross-origin requests are not allowed'), 403
    return None


@app.after_request
def prevent_api_caching(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Pragma'] = 'no-cache'
    return response


def auth_response(user_id, status=200):
    token = secrets.token_urlsafe(48)
    connection = db()
    connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    connection.execute('INSERT INTO sessions (token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)', (hash_token(token), user_id, expires_at, now_iso()))
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
    body = json_body()
    required = ('name', 'email', 'password', 'college')
    if any(not isinstance(body.get(key), str) or not body[key].strip() for key in required):
        return jsonify(error='Name, college, email, and password are required'), 400
    name = body['name'].strip()
    email = body['email'].strip().lower()
    college = body['college'].strip()
    if len(name) > 160 or len(email) > 255 or len(college) > 255:
        return jsonify(error='Name, email, or college exceeds the allowed length'), 400
    if not EMAIL_PATTERN.fullmatch(email):
        return jsonify(error='Enter a valid email address'), 400
    if len(body['password']) < 8:
        return jsonify(error='Password must be at least 8 characters'), 400
    if len(body['password']) > 256:
        return jsonify(error='Password must be 256 characters or fewer'), 400
    connection = db()
    try:
        cursor = connection.execute('INSERT INTO users (name,email,password_hash,college,verified,created_at) VALUES (?,?,?,?,?,?)', (name, email, generate_password_hash(body['password']), college, 0, now_iso()))
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
    body = json_body()
    email = body.get('email')
    password = body.get('password')
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error='Enter your student email and password'), 400
    connection = db()
    row = connection.execute('SELECT * FROM users WHERE email=?', (email.lower().strip(),)).fetchone()
    connection.close()
    if not row or not check_password_hash(row['password_hash'], password):
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
        return error
    connection = db()
    rows = connection.execute("SELECT devices.*, users.name AS owner_name, users.rating AS owner_rating FROM devices JOIN users ON users.id=devices.owner_id WHERE devices.status IN ('available','rented') AND devices.owner_id<>? ORDER BY devices.id DESC", (user_id,)).fetchall()
    connection.close()
    return jsonify(devices=[row_dict(row) for row in rows])


@app.post('/api/devices')
def create_device():
    user_id, error = require_user()
    if error:
        return error
    try:
        fields = validated_device_fields(json_body())
    except ValueError as error_message:
        return jsonify(error=str(error_message)), 400
    connection = db()
    cursor = connection.execute('INSERT INTO devices (owner_id,name,category,`condition`,price_per_day,available_from,available_to,status) VALUES (?,?,?,?,?,?,?,?)', (user_id, fields['name'], fields['category'], fields['condition'], fields['price_per_day'], fields['available_from'], fields['available_to'], 'available'))
    connection.commit()
    device_id = cursor.lastrowid
    connection.close()
    return jsonify(device={'id': device_id, 'owner_id': user_id, **fields, 'status': 'available'}), 201


@app.put('/api/devices/<int:device_id>')
def update_device(device_id):
    user_id, error = require_user()
    if error:
        return error
    try:
        fields = validated_device_fields(json_body())
    except ValueError as error_message:
        return jsonify(error=str(error_message)), 400
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    lock_query = 'SELECT * FROM devices WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(lock_query, (device_id,)).fetchone()
    if not device or device['owner_id'] != user_id:
        connection.close()
        return jsonify(error='Listing not found'), 404
    pending = connection.execute("SELECT pickup_date,return_date FROM rental_requests WHERE device_id=? AND status='Pending'", (device_id,)).fetchall()
    confirmed = connection.execute("SELECT pickup_date,return_date FROM bookings WHERE device_id=? AND status IN ('approved','active')", (device_id,)).fetchall()
    for reservation in [*pending, *confirmed]:
        pickup = str(reservation['pickup_date'] or '')[:10]
        return_day = str(reservation['return_date'] or '')[:10]
        if ((fields['available_from'] and pickup and pickup < fields['available_from']) or
                (fields['available_to'] and return_day and return_day > fields['available_to'])):
            connection.close()
            return jsonify(error='Availability dates cannot exclude a pending request or confirmed rental'), 409
    connection.execute('''UPDATE devices SET name=?,category=?,`condition`=?,price_per_day=?,available_from=?,available_to=? WHERE id=?''',
        (fields['name'], fields['category'], fields['condition'], fields['price_per_day'], fields['available_from'], fields['available_to'], device_id))
    connection.commit()
    connection.close()
    return jsonify(ok=True, device={'id': device_id, 'owner_id': user_id, **fields, 'status': device['status']})


@app.post('/api/devices/<int:device_id>/deactivate')
def deactivate_device(device_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    lock_query = 'SELECT id,owner_id,status FROM devices WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(lock_query, (device_id,)).fetchone()
    if not device or device['owner_id'] != user_id:
        connection.close()
        return jsonify(error='Listing not found'), 404
    if device['status'] == 'inactive':
        connection.close()
        return jsonify(ok=True, status='inactive', already_inactive=True)
    pending = connection.execute("SELECT id FROM rental_requests WHERE device_id=? AND status='Pending' LIMIT 1", (device_id,)).fetchone()
    confirmed = connection.execute("SELECT id FROM bookings WHERE device_id=? AND status IN ('approved','active') LIMIT 1", (device_id,)).fetchone()
    if pending or confirmed:
        connection.close()
        return jsonify(error='Resolve pending requests and complete confirmed rentals before unlisting'), 409
    connection.execute('UPDATE devices SET status=? WHERE id=?', ('inactive', device_id))
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='inactive')


@app.post('/api/devices/<int:device_id>/reactivate')
def reactivate_device(device_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    lock_query = 'SELECT id,owner_id,status,available_to FROM devices WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(lock_query, (device_id,)).fetchone()
    if not device or device['owner_id'] != user_id:
        connection.close()
        return jsonify(error='Listing not found'), 404
    if device['status'] != 'inactive':
        connection.close()
        return jsonify(error='Only an unlisted item can be reactivated'), 409
    if device['available_to'] and str(device['available_to'])[:10] < date.today().isoformat():
        connection.close()
        return jsonify(error='Edit the expired availability window before reactivating this listing'), 409
    connection.execute('UPDATE devices SET status=? WHERE id=?', ('available', device_id))
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='available')


@app.delete('/api/devices/<int:device_id>')
def delete_device(device_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    lock_query = 'SELECT id,owner_id FROM devices WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(lock_query, (device_id,)).fetchone()
    if not device or device['owner_id'] != user_id:
        connection.close()
        return jsonify(error='Listing not found'), 404
    has_requests = connection.execute('SELECT id FROM rental_requests WHERE device_id=? LIMIT 1', (device_id,)).fetchone()
    has_bookings = connection.execute('SELECT id FROM bookings WHERE device_id=? LIMIT 1', (device_id,)).fetchone()
    if has_requests or has_bookings:
        connection.close()
        return jsonify(error='This listing has request or rental history. Unlist it to preserve those records.'), 409
    connection.execute('DELETE FROM devices WHERE id=?', (device_id,))
    connection.commit()
    connection.close()
    return jsonify(ok=True, deleted=True)


@app.get('/api/tools')
def tools():
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    devices_rows = connection.execute('SELECT devices.*, users.name AS owner_name FROM devices JOIN users ON users.id=devices.owner_id WHERE devices.owner_id=? ORDER BY devices.id DESC', (user_id,)).fetchall()
    request_rows = connection.execute('''SELECT rental_requests.*, devices.name AS device_name, devices.category, borrowers.name AS borrower_name,
        CASE WHEN rental_requests.status='Approved' THEN borrowers.email ELSE NULL END AS borrower_email
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
        return error
    connection = db()
    rows = connection.execute('''SELECT rental_requests.*, devices.name AS device_name, devices.category, owners.name AS owner_name, borrowers.name AS borrower_name,
        CASE WHEN rental_requests.status='Approved' THEN owners.email ELSE NULL END AS owner_email,
        CASE WHEN rental_requests.status='Approved' THEN borrowers.email ELSE NULL END AS borrower_email
        FROM rental_requests JOIN devices ON devices.id=rental_requests.device_id JOIN users owners ON owners.id=rental_requests.owner_id JOIN users borrowers ON borrowers.id=rental_requests.borrower_id
        WHERE rental_requests.owner_id=? OR rental_requests.borrower_id=? ORDER BY rental_requests.id DESC''', (user_id, user_id)).fetchall()
    community_rows = connection.execute('''SELECT requests.*, users.name AS requester_name
        FROM requests JOIN users ON users.id=requests.requester_id
        WHERE requests.status='open' ORDER BY requests.id DESC''').fetchall()
    connection.close()
    return jsonify(requests=[row_dict(row) for row in rows], community_requests=[row_dict(row) for row in community_rows])


@app.post('/api/rental-requests')
def create_rental_request():
    borrower_id, error = require_user()
    if error:
        return error
    body = json_body()
    required = ('device_id', 'pickup_date', 'return_date', 'pickup_location')
    if any(not str(body.get(key, '')).strip() for key in required):
        return jsonify(error='Pickup date, return date, and pickup location are required'), 400
    if isinstance(body.get('device_id'), bool):
        return jsonify(error='Equipment ID must be a valid positive integer'), 400
    try:
        device_id = int(body['device_id'])
    except (TypeError, ValueError):
        return jsonify(error='Equipment ID must be a valid positive integer'), 400
    if device_id <= 0:
        return jsonify(error='Equipment ID must be a valid positive integer'), 400
    pickup_location = body.get('pickup_location')
    message = body.get('message', '')
    if not isinstance(pickup_location, str) or len(pickup_location.strip()) > 255:
        return jsonify(error='Pickup location must be 255 characters or fewer'), 400
    if not isinstance(message, str) or len(message) > 2000:
        return jsonify(error='Message must be 2000 characters or fewer'), 400
    try:
        pickup_date = parse_day(body['pickup_date'], 'Pickup date')
        return_date = parse_day(body['return_date'], 'Return date')
    except ValueError as error_message:
        return jsonify(error=str(error_message)), 400
    if pickup_date < date.today():
        return jsonify(error='Pickup date cannot be in the past'), 400
    if return_date < pickup_date:
        return jsonify(error='Return date cannot be before pickup date'), 400
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    device_query = "SELECT * FROM devices WHERE id=? AND status IN ('available','rented')" + (' FOR UPDATE' if connection.mysql else '')
    device = connection.execute(device_query, (device_id,)).fetchone()
    if not device:
        connection.close()
        return jsonify(error='Equipment is unavailable'), 404
    if device['owner_id'] == borrower_id:
        connection.close()
        return jsonify(error='You cannot request your own equipment'), 400
    if device['available_from'] and pickup_date.isoformat() < str(device['available_from'])[:10]:
        connection.close()
        return jsonify(error=f"This equipment is not available until {str(device['available_from'])[:10]}"), 409
    if device['available_to'] and return_date.isoformat() > str(device['available_to'])[:10]:
        connection.close()
        return jsonify(error=f"This equipment is available only through {str(device['available_to'])[:10]}"), 409
    duplicate = connection.execute('''SELECT id, public_id FROM rental_requests
        WHERE device_id=? AND borrower_id=? AND pickup_date=? AND return_date=?
          AND pickup_location=? AND COALESCE(message,'')=? AND status='Pending'
        ORDER BY id DESC LIMIT 1''', (device['id'], borrower_id, pickup_date.isoformat(), return_date.isoformat(), pickup_location.strip(), message.strip())).fetchone()
    if duplicate:
        connection.close()
        return jsonify(request={'id': duplicate['id'], 'public_id': duplicate['public_id'], 'status': 'Pending', 'duplicate': True}), 200
    conflict_query = "SELECT id FROM rental_requests WHERE device_id=? AND status IN ('Pending','Approved','Active') AND pickup_date <= ? AND return_date >= ?" + (' FOR UPDATE' if connection.mysql else '')
    conflict = connection.execute(conflict_query, (device['id'], return_date.isoformat(), pickup_date.isoformat())).fetchone()
    if conflict:
        connection.close()
        return jsonify(error='This equipment already has a request in those dates'), 409
    booking_conflict_query = "SELECT id FROM bookings WHERE device_id=? AND status IN ('approved','active') AND pickup_date <= ? AND return_date >= ? LIMIT 1" + (' FOR UPDATE' if connection.mysql else '')
    booking_conflict = connection.execute(booking_conflict_query, (device['id'], return_date.isoformat(), pickup_date.isoformat())).fetchone()
    if booking_conflict:
        connection.close()
        return jsonify(error='This equipment already has a confirmed booking in those dates'), 409
    public_id = f"RR-{secrets.token_hex(4).upper()}"
    cursor = connection.execute('INSERT INTO rental_requests (public_id,device_id,owner_id,borrower_id,pickup_date,return_date,pickup_location,message,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)', (public_id, device['id'], device['owner_id'], borrower_id, pickup_date.isoformat(), return_date.isoformat(), pickup_location.strip(), message.strip(), 'Pending', now_iso()))
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
    device_lock = 'SELECT id FROM devices WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    if not connection.execute(device_lock, (rental_request['device_id'],)).fetchone():
        connection.close()
        return jsonify(error='Equipment is no longer available'), 409
    conflict_query = "SELECT id FROM bookings WHERE device_id=? AND status IN ('approved','active') AND pickup_date <= ? AND return_date >= ?" + (' FOR UPDATE' if connection.mysql else '')
    conflict = connection.execute(conflict_query, (rental_request['device_id'], rental_request['return_date'], rental_request['pickup_date'])).fetchone()
    if conflict:
        connection.close()
        return jsonify(error='This equipment already has a confirmed booking in those dates'), 409
    days = max((parse_day(rental_request['return_date'], 'Return date') - parse_day(rental_request['pickup_date'], 'Pickup date')).days, 1)
    fee = round(float(rental_request['price_per_day'] or 0) * days, 2)
    purchase_estimate = round(max(float(rental_request['price_per_day'] or 0) * 30, fee), 2)
    start_at = f"{rental_request['pickup_date']}T09:00:00Z"
    return_at = f"{rental_request['return_date']}T18:00:00Z"
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
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    request_query = 'SELECT owner_id,status FROM rental_requests WHERE id=?' + (' FOR UPDATE' if connection.mysql else '')
    rental_request = connection.execute(request_query, (request_id,)).fetchone()
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
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    booking_query = 'SELECT * FROM bookings WHERE id=? AND borrower_id=?' + (' FOR UPDATE' if connection.mysql else '')
    booking = connection.execute(booking_query, (booking_id, user_id)).fetchone()
    if not booking:
        connection.close()
        return jsonify(error='Booking not found or you are not the borrower'), 404
    if booking['status'] not in ('approved', 'active'):
        connection.close()
        return jsonify(error='Only an approved or active rental can be paid'), 409
    existing_payment = connection.execute('SELECT id FROM payments WHERE booking_id=? ORDER BY id DESC LIMIT 1', (booking_id,)).fetchone()
    if existing_payment:
        connection.execute('UPDATE bookings SET payment_status=? WHERE id=?', ('DEMO_SIMULATED_PAID', booking_id))
        connection.commit()
        connection.close()
        return jsonify(ok=True, payment_status='DEMO_SIMULATED_PAID', demo=True, already_recorded=True)
    insert_sql = 'INSERT IGNORE INTO payments (booking_id,amount,status,created_at) VALUES (?,?,?,?)' if connection.mysql else 'INSERT OR IGNORE INTO payments (booking_id,amount,status,created_at) VALUES (?,?,?,?)'
    inserted = connection.execute(insert_sql, (booking_id, booking['fee'], 'DEMO_SIMULATED_PAID', now_iso())).rowcount
    connection.execute('UPDATE bookings SET payment_status=? WHERE id=?', ('DEMO_SIMULATED_PAID', booking_id))
    connection.commit()
    connection.close()
    return jsonify(ok=True, payment_status='DEMO_SIMULATED_PAID', demo=True, already_recorded=not bool(inserted))


@app.post('/api/bookings/<int:booking_id>/pickup')
def pickup_booking(booking_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    booking_query = 'SELECT * FROM bookings WHERE id=? AND (borrower_id=? OR owner_id=?)' + (' FOR UPDATE' if connection.mysql else '')
    booking = connection.execute(booking_query, (booking_id, user_id, user_id)).fetchone()
    if not booking:
        connection.close()
        return jsonify(error='Booking not found or not authorized'), 404
    if booking['status'] != 'approved':
        connection.close()
        return jsonify(error='Only an approved rental can record a handoff'), 409
    picked_up_at = now_iso()
    changed = connection.execute('UPDATE bookings SET status=?, picked_up_at=? WHERE id=? AND status=?', ('active', picked_up_at, booking_id, 'approved')).rowcount
    if not changed:
        connection.rollback()
        connection.close()
        return jsonify(error='This rental has already moved to another state'), 409
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='active', picked_up_at=picked_up_at)


@app.post('/api/bookings/<int:booking_id>/return')
def return_booking(booking_id):
    user_id, error = require_user()
    if error:
        return error
    connection = db()
    if not connection.mysql:
        connection.raw.execute('BEGIN IMMEDIATE')
    booking_query = 'SELECT * FROM bookings WHERE id=? AND (borrower_id=? OR owner_id=?)' + (' FOR UPDATE' if connection.mysql else '')
    booking = connection.execute(booking_query, (booking_id, user_id, user_id)).fetchone()
    if not booking:
        connection.close()
        return jsonify(error='Booking not found or not authorized'), 404
    if booking['status'] == 'returned':
        connection.close()
        return jsonify(error='This rental is already closed'), 409
    if booking['status'] != 'active' or not booking['picked_up_at']:
        connection.close()
        return jsonify(error='Record the equipment handoff before completing the rental'), 409
    returned_at = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    deadline = datetime.fromisoformat(booking['return_at'].replace('Z', '+00:00')).replace(tzinfo=None)
    late_hours = max(0, int((returned_at - deadline).total_seconds() // 3600))
    late_fee = round(late_hours * 10, 2)
    savings_amount = round(max(float(booking['purchase_estimate'] or 0) - float(booking['fee'] or 0), 0), 2)
    changed = connection.execute('UPDATE bookings SET status=?, returned_at=?, late_fee=?, savings=? WHERE id=? AND status=?', ('returned', returned_at.isoformat() + 'Z', late_fee, savings_amount, booking_id, 'active')).rowcount
    if not changed:
        connection.rollback()
        connection.close()
        return jsonify(error='This rental has already moved to another state'), 409
    other_booking = connection.execute("SELECT id FROM bookings WHERE device_id=? AND id<>? AND status IN ('approved','active') LIMIT 1", (booking['device_id'], booking_id)).fetchone()
    connection.execute('UPDATE devices SET status=? WHERE id=?', ('rented' if other_booking else 'available', booking['device_id']))
    connection.execute('INSERT IGNORE INTO savings (booking_id,borrower_id,amount,created_at) VALUES (?,?,?,?)', (booking_id, booking['borrower_id'], savings_amount, now_iso())) if connection.mysql else connection.execute('INSERT OR IGNORE INTO savings (booking_id,borrower_id,amount,created_at) VALUES (?,?,?,?)', (booking_id, booking['borrower_id'], savings_amount, now_iso()))
    connection.commit()
    connection.close()
    return jsonify(ok=True, status='returned', late_fee=late_fee, late_hours=late_hours, savings=savings_amount)


@app.post('/api/requests')
def create_generic_request():
    user_id, error = require_user()
    if error:
        return error
    body = json_body()
    if any(not isinstance(body.get(key), str) or not body[key].strip() for key in ('title', 'category', 'duration')):
        return jsonify(error='Title, category, and duration are required'), 400
    if len(body['title'].strip()) > 255 or len(body['category'].strip()) > 80 or len(body['duration'].strip()) > 80:
        return jsonify(error='Title, category, or duration exceeds the allowed length'), 400
    detail = body.get('detail', '')
    if not isinstance(detail, str) or len(detail) > 4000:
        return jsonify(error='Details must be 4000 characters or fewer'), 400
    connection = db()
    cursor = connection.execute('INSERT INTO requests (requester_id,title,category,duration,detail,created_at) VALUES (?,?,?,?,?,?)', (user_id, body['title'].strip(), body['category'].strip(), body['duration'].strip(), detail.strip(), now_iso()))
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
