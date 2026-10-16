import atexit
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_TEST_DIR = tempfile.TemporaryDirectory(prefix='campuslend-tests-')
os.environ.pop('DATABASE_URL', None)
os.environ['APP_ENV'] = 'test'
os.environ['CAMPUSLEND_DB_PATH'] = str(Path(_TEST_DIR.name) / 'campuslend-test.sqlite3')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as service  # noqa: E402

atexit.register(_TEST_DIR.cleanup)


class CampusLendApiTests(unittest.TestCase):
    def setUp(self):
        db_path = Path(service.DB_PATH)
        if db_path.exists():
            db_path.unlink()
        service.init_db()
        service.app.config.update(TESTING=True)
        self.owner = service.app.test_client()
        self.borrower = service.app.test_client()
        self.other = service.app.test_client()

    def post(self, client, path, body=None):
        return client.post(path, json=body, headers={'Origin': 'http://localhost'})

    def put(self, client, path, body):
        return client.put(path, json=body, headers={'Origin': 'http://localhost'})

    def delete(self, client, path):
        return client.delete(path, headers={'Origin': 'http://localhost'})

    def register(self, client, name, email):
        return self.post(client, '/api/auth/register', {
            'name': name,
            'email': email,
            'password': 'a-safe-test-password',
            'college': 'Isolated Test Campus',
        })

    @staticmethod
    def json(response):
        return response.get_json()

    def create_listing(self, owner=None, **overrides):
        client = owner or self.owner
        body = {
            'name': 'Regression Laptop',
            'category': 'Laptop',
            'condition': 'Good condition',
            'price_per_day': 50,
        }
        body.update(overrides)
        return self.post(client, '/api/devices', body)

    def valid_rental_request(self, device_id, **overrides):
        body = {
            'device_id': device_id,
            'pickup_date': (date.today() + timedelta(days=2)).isoformat(),
            'return_date': (date.today() + timedelta(days=4)).isoformat(),
            'pickup_location': 'Library desk',
            'message': 'Regression test request',
        }
        body.update(overrides)
        return body

    def test_authentication_validation_session_and_private_reads(self):
        invalid = self.register(self.owner, 'Test Student', 'not-an-email')
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('valid email', self.json(invalid)['error'].lower())

        created = self.register(self.owner, 'Test Student', 'student@example.test')
        self.assertEqual(created.status_code, 201)
        self.assertNotIn('password', self.json(created)['user'])
        cookie = created.headers.get('Set-Cookie', '')
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Secure', cookie)
        self.assertIn('SameSite=None', cookie)
        session_me = self.owner.get('/api/auth/me')
        self.assertEqual(session_me.headers['Cache-Control'], 'no-store, private')
        self.assertEqual(self.json(session_me)['user']['email'], 'student@example.test')

        duplicate = self.register(self.borrower, 'Duplicate Student', 'STUDENT@example.test')
        self.assertEqual(duplicate.status_code, 409)
        bad_login = self.post(self.borrower, '/api/auth/login', {'email': 'student@example.test', 'password': 'wrong-password'})
        self.assertEqual(bad_login.status_code, 401)
        missing_login = self.post(self.borrower, '/api/auth/login', {'email': 'student@example.test'})
        self.assertEqual(missing_login.status_code, 400)
        valid_login = self.post(self.borrower, '/api/auth/login', {'email': 'student@example.test', 'password': 'a-safe-test-password'})
        self.assertEqual(valid_login.status_code, 200)
        self.assertEqual(self.json(self.borrower.get('/api/auth/me'))['user']['email'], 'student@example.test')

        anonymous = service.app.test_client()
        self.assertEqual(anonymous.get('/api/devices').status_code, 401)
        self.assertEqual(anonymous.get('/api/tools').status_code, 401)
        self.assertEqual(anonymous.get('/api/requests').status_code, 401)
        self.assertEqual(anonymous.get('/api/bookings').status_code, 401)
        logout = self.post(self.owner, '/api/auth/logout')
        self.assertEqual(logout.status_code, 200)
        self.assertIsNone(self.json(self.owner.get('/api/auth/me'))['user'])

    def test_listing_validation_and_owner_scoping(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        self.assertEqual(self.create_listing(price_per_day=-10).status_code, 400)
        self.assertEqual(self.create_listing(price_per_day='not-a-number').status_code, 400)
        self.assertEqual(self.create_listing(price_per_day='NaN').status_code, 400)
        self.assertEqual(self.create_listing(available_from='not-a-date').status_code, 400)
        self.assertEqual(self.create_listing(available_from='2026-10-25', available_to='2026-10-20').status_code, 400)

        listed = self.create_listing()
        self.assertEqual(listed.status_code, 201)
        device_id = self.json(listed)['device']['id']
        self.assertEqual(self.json(self.owner.get('/api/devices'))['devices'], [])
        borrower_devices = self.json(self.borrower.get('/api/devices'))['devices']
        self.assertEqual([item['id'] for item in borrower_devices], [device_id])
        owner_tools = self.json(self.owner.get('/api/tools'))['tools']
        self.assertEqual([item['id'] for item in owner_tools], [device_id])
        self.assertEqual(self.json(self.borrower.get('/api/tools'))['tools'], [])

    def test_owner_can_edit_listing_without_invalidating_a_pending_window(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        available_from = date.today() + timedelta(days=1)
        available_to = date.today() + timedelta(days=14)
        listing = self.create_listing(available_from=available_from.isoformat(), available_to=available_to.isoformat())
        device_id = self.json(listing)['device']['id']
        window = {
            'pickup_date': (date.today() + timedelta(days=3)).isoformat(),
            'return_date': (date.today() + timedelta(days=4)).isoformat(),
        }
        self.assertEqual(self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(device_id, **window)).status_code, 201)
        fields = {
            'name': 'Updated Regression Laptop',
            'category': 'Laptop',
            'condition': 'Battery tested',
            'price_per_day': 75,
            'available_from': available_from.isoformat(),
            'available_to': (date.today() + timedelta(days=3)).isoformat(),
        }
        self.assertEqual(self.put(self.owner, f'/api/devices/{device_id}', {**fields, 'price_per_day': -1}).status_code, 400)
        excluded_window = self.put(self.owner, f'/api/devices/{device_id}', fields)
        self.assertEqual(excluded_window.status_code, 409)
        self.assertEqual(self.put(self.borrower, f'/api/devices/{device_id}', {**fields, 'available_to': available_to.isoformat()}).status_code, 404)
        fields['available_to'] = available_to.isoformat()
        saved = self.put(self.owner, f'/api/devices/{device_id}', fields)
        self.assertEqual(saved.status_code, 200)
        updated = self.json(self.owner.get('/api/tools'))['tools'][0]
        self.assertEqual(updated['name'], 'Updated Regression Laptop')
        self.assertEqual(updated['condition'], 'Battery tested')
        self.assertEqual(updated['price_per_day'], 75)

    def test_unlisting_preserves_history_and_only_unused_listings_can_be_deleted(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        self.assertEqual(self.register(self.other, 'Other Student', 'other@example.test').status_code, 201)
        listing = self.create_listing()
        device_id = self.json(listing)['device']['id']
        request = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(device_id))
        request_id = self.json(request)['request']['id']
        self.assertEqual(self.post(self.other, f'/api/devices/{device_id}/deactivate').status_code, 404)
        self.assertEqual(self.delete(self.owner, f'/api/devices/{device_id}').status_code, 409)
        self.assertEqual(self.post(self.owner, f'/api/devices/{device_id}/deactivate').status_code, 409)
        self.assertEqual(self.post(self.owner, f'/api/rental-requests/{request_id}/reject').status_code, 200)

        deactivated = self.post(self.owner, f'/api/devices/{device_id}/deactivate')
        self.assertEqual(deactivated.status_code, 200)
        self.assertEqual(self.json(deactivated)['status'], 'inactive')
        self.assertEqual(self.json(self.owner.get('/api/tools'))['tools'][0]['status'], 'inactive')
        self.assertEqual(self.json(self.borrower.get('/api/devices'))['devices'], [])
        self.assertEqual(self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(device_id)).status_code, 404)
        self.assertEqual(self.post(self.owner, f'/api/devices/{device_id}/reactivate').status_code, 200)
        self.assertEqual(self.delete(self.owner, f'/api/devices/{device_id}').status_code, 409)

        unused = self.create_listing(name='Unused Webcam')
        unused_id = self.json(unused)['device']['id']
        self.assertEqual(self.delete(self.other, f'/api/devices/{unused_id}').status_code, 404)
        deleted = self.delete(self.owner, f'/api/devices/{unused_id}')
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(self.json(deleted)['deleted'])
        remaining_ids = [item['id'] for item in self.json(self.owner.get('/api/tools'))['tools']]
        self.assertEqual(remaining_ids, [device_id])

    def test_two_user_borrow_approval_payment_handoff_return_and_savings(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        self.assertEqual(self.register(self.other, 'Other Student', 'other@example.test').status_code, 201)

        listing = self.create_listing()
        self.assertEqual(listing.status_code, 201)
        device_id = self.json(listing)['device']['id']
        request_body = self.valid_rental_request(device_id)

        missing = self.post(self.borrower, '/api/rental-requests', {'device_id': device_id})
        self.assertEqual(missing.status_code, 400)
        invalid_dates = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(
            device_id,
            pickup_date=(date.today() - timedelta(days=1)).isoformat(),
        ))
        self.assertEqual(invalid_dates.status_code, 400)
        reversed_dates = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(
            device_id,
            pickup_date=(date.today() + timedelta(days=3)).isoformat(),
            return_date=(date.today() + timedelta(days=2)).isoformat(),
        ))
        self.assertEqual(reversed_dates.status_code, 400)
        own_request = self.post(self.owner, '/api/rental-requests', self.valid_rental_request(device_id))
        self.assertEqual(own_request.status_code, 400)
        unknown_device = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(99999))
        self.assertEqual(unknown_device.status_code, 404)

        session_cookie = self.borrower.get_cookie(service.SESSION_COOKIE)
        self.assertIsNotNone(session_cookie)

        def submit_same_request():
            client = service.app.test_client()
            client.set_cookie(service.SESSION_COOKIE, session_cookie.value)
            response = self.post(client, '/api/rental-requests', request_body)
            return response.status_code, self.json(response)

        with ThreadPoolExecutor(max_workers=4) as executor:
            submissions = list(executor.map(lambda _: submit_same_request(), range(4)))
        self.assertEqual(sorted(status for status, _ in submissions), [200, 200, 200, 201])
        request_ids = {body['request']['id'] for _, body in submissions}
        self.assertEqual(len(request_ids), 1)
        request_id = request_ids.pop()
        self.assertTrue(all(body['request'].get('duplicate') for status, body in submissions if status == 200))
        collision = self.post(self.other, '/api/rental-requests', self.valid_rental_request(device_id))
        self.assertEqual(collision.status_code, 409)

        self.assertEqual(len(self.json(self.borrower.get('/api/requests'))['requests']), 1)
        owner_tools = self.json(self.owner.get('/api/tools'))
        self.assertEqual(len(owner_tools['incoming_requests']), 1)
        self.assertIsNone(owner_tools['incoming_requests'][0]['borrower_email'])
        unauthorized_approval = self.post(self.other, f'/api/rental-requests/{request_id}/approve')
        self.assertEqual(unauthorized_approval.status_code, 403)
        approval = self.post(self.owner, f'/api/rental-requests/{request_id}/approve')
        self.assertEqual(approval.status_code, 200)
        booking_id = self.json(approval)['booking_id']
        self.assertEqual(self.post(self.owner, f'/api/devices/{device_id}/deactivate').status_code, 409)
        self.assertEqual(self.delete(self.owner, f'/api/devices/{device_id}').status_code, 409)
        approved_tool_request = self.json(self.owner.get('/api/tools'))['incoming_requests'][0]
        self.assertEqual(approved_tool_request['borrower_email'], 'borrower@example.test')
        approved_borrower_request = self.json(self.borrower.get('/api/requests'))['requests'][0]
        self.assertEqual(approved_borrower_request['owner_email'], 'owner@example.test')
        approved_booking = self.json(self.borrower.get('/api/bookings'))['bookings'][0]
        self.assertTrue(approved_booking['start_at'].endswith('Z'))
        self.assertTrue(approved_booking['return_at'].endswith('Z'))
        self.assertEqual(self.post(self.owner, f'/api/rental-requests/{request_id}/approve').status_code, 409)
        overlap_after_approval = self.post(self.other, '/api/rental-requests', self.valid_rental_request(device_id))
        self.assertEqual(overlap_after_approval.status_code, 409)
        future_request = self.post(self.other, '/api/rental-requests', self.valid_rental_request(
            device_id,
            pickup_date=(date.today() + timedelta(days=7)).isoformat(),
            return_date=(date.today() + timedelta(days=8)).isoformat(),
        ))
        self.assertEqual(future_request.status_code, 201)
        self.assertEqual(len(self.json(self.borrower.get('/api/bookings'))['bookings']), 1)

        premature_return = self.post(self.borrower, f'/api/bookings/{booking_id}/return')
        self.assertEqual(premature_return.status_code, 409)
        owner_payment = self.post(self.owner, f'/api/bookings/{booking_id}/simulate-payment')
        self.assertEqual(owner_payment.status_code, 404)
        payment_one = self.post(self.borrower, f'/api/bookings/{booking_id}/simulate-payment')
        payment_two = self.post(self.borrower, f'/api/bookings/{booking_id}/simulate-payment')
        self.assertEqual(payment_one.status_code, 200)
        self.assertTrue(self.json(payment_one)['demo'])
        self.assertEqual(payment_two.status_code, 200)
        self.assertTrue(self.json(payment_two)['already_recorded'])

        pickup = self.post(self.borrower, f'/api/bookings/{booking_id}/pickup')
        self.assertEqual(pickup.status_code, 200)
        self.assertEqual(self.json(pickup)['status'], 'active')
        self.assertEqual(self.post(self.owner, f'/api/bookings/{booking_id}/pickup').status_code, 409)
        returned = self.post(self.owner, f'/api/bookings/{booking_id}/return')
        self.assertEqual(returned.status_code, 200)
        self.assertGreater(self.json(returned)['savings'], 0)
        self.assertEqual(self.post(self.borrower, f'/api/bookings/{booking_id}/return').status_code, 409)

        connection = service.db()
        payment_count = connection.execute('SELECT COUNT(*) AS count FROM payments WHERE booking_id=?', (booking_id,)).fetchone()['count']
        savings_count = connection.execute('SELECT COUNT(*) AS count FROM savings WHERE booking_id=?', (booking_id,)).fetchone()['count']
        booking = connection.execute('SELECT status,savings,payment_status FROM bookings WHERE id=?', (booking_id,)).fetchone()
        connection.close()
        self.assertEqual(payment_count, 1)
        self.assertEqual(savings_count, 1)
        self.assertEqual(booking['status'], 'returned')
        self.assertGreater(booking['savings'], 0)
        self.assertEqual(booking['payment_status'], 'DEMO_SIMULATED_PAID')
        self.assertEqual(self.json(self.borrower.get('/api/devices'))['devices'][0]['status'], 'available')

    def test_http_errors_keep_real_status_codes_and_json_shape(self):
        not_found = service.app.test_client().get('/api/no-such-route')
        self.assertEqual(not_found.status_code, 404)
        self.assertIn('error', self.json(not_found))
        self.assertEqual(not_found.headers.get('Cache-Control'), 'no-store, private')
        method_not_allowed = service.app.test_client().post('/api/auth/me', headers={'Origin': 'http://localhost'})
        self.assertEqual(method_not_allowed.status_code, 405)
        self.assertIn('error', self.json(method_not_allowed))

    def test_mutating_api_routes_reject_missing_or_cross_origin_source(self):
        payload = {'name': 'CSRF Student', 'email': 'csrf@example.test', 'password': 'a-safe-test-password', 'college': 'Test Campus'}
        anonymous = service.app.test_client()
        missing_origin = anonymous.post('/api/auth/register', json=payload)
        self.assertEqual(missing_origin.status_code, 403)
        cross_origin = anonymous.post('/api/auth/register', json=payload, headers={'Origin': 'https://evil.example'})
        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(self.json(anonymous.get('/api/auth/me'))['user'], None)

    def test_fresh_schema_enforces_foreign_keys_and_unique_business_indexes(self):
        connection = service.db()
        self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute('INSERT INTO devices (owner_id,name,category,condition) VALUES (?,?,?,?)', (99999, 'Orphan', 'Laptop', 'Good'))
        self.assertTrue(service.unique_index_exists(connection, 'payments', 'payments_booking_unique'))
        self.assertTrue(service.unique_index_exists(connection, 'bookings', 'bookings_request_unique'))
        connection.close()

    def test_community_request_posts_are_saved_and_visible_without_private_email(self):
        self.assertEqual(self.register(self.owner, 'Requester Student', 'requester@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Reader Student', 'reader@example.test').status_code, 201)
        posted = self.post(self.owner, '/api/requests', {
            'title': 'Projector for demo day',
            'category': 'Accessories',
            'duration': '1 afternoon',
            'detail': 'Need a classroom projector for a student pitch.',
        })
        self.assertEqual(posted.status_code, 201)
        board = self.json(self.borrower.get('/api/requests'))['community_requests']
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0]['title'], 'Projector for demo day')
        self.assertEqual(board[0]['requester_name'], 'Requester Student')
        self.assertNotIn('email', board[0])

    def test_rental_request_must_fit_listing_availability(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        available_from = date.today() + timedelta(days=5)
        available_to = date.today() + timedelta(days=10)
        listing = self.create_listing(available_from=available_from.isoformat(), available_to=available_to.isoformat())
        device_id = self.json(listing)['device']['id']
        too_early = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(
            device_id,
            pickup_date=(available_from - timedelta(days=1)).isoformat(),
            return_date=(available_from + timedelta(days=1)).isoformat(),
        ))
        self.assertEqual(too_early.status_code, 409)
        valid = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(
            device_id,
            pickup_date=available_from.isoformat(),
            return_date=(available_from + timedelta(days=1)).isoformat(),
        ))
        self.assertEqual(valid.status_code, 201)

    def test_owner_can_reject_once_without_creating_a_booking(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        listing = self.create_listing()
        device_id = self.json(listing)['device']['id']
        created = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(device_id))
        request_id = self.json(created)['request']['id']
        self.assertEqual(self.post(self.borrower, f'/api/rental-requests/{request_id}/reject').status_code, 403)
        rejected = self.post(self.owner, f'/api/rental-requests/{request_id}/reject')
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(self.post(self.owner, f'/api/rental-requests/{request_id}/reject').status_code, 409)
        self.assertEqual(self.json(self.borrower.get('/api/bookings'))['bookings'], [])
        saved_request = self.json(self.borrower.get('/api/requests'))['requests'][0]
        self.assertEqual(saved_request['status'], 'Rejected')

    def test_approval_rejects_a_conflict_with_an_existing_confirmed_booking(self):
        self.assertEqual(self.register(self.owner, 'Owner Student', 'owner@example.test').status_code, 201)
        self.assertEqual(self.register(self.borrower, 'Borrower Student', 'borrower@example.test').status_code, 201)
        self.assertEqual(self.register(self.other, 'Other Student', 'other@example.test').status_code, 201)
        listing = self.create_listing()
        device_id = self.json(listing)['device']['id']
        first_window = {
            'pickup_date': (date.today() + timedelta(days=2)).isoformat(),
            'return_date': (date.today() + timedelta(days=3)).isoformat(),
        }
        second_window = {
            'pickup_date': (date.today() + timedelta(days=5)).isoformat(),
            'return_date': (date.today() + timedelta(days=6)).isoformat(),
        }
        first = self.post(self.borrower, '/api/rental-requests', self.valid_rental_request(device_id, **first_window))
        second = self.post(self.other, '/api/rental-requests', self.valid_rental_request(device_id, **second_window))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        first_id = self.json(first)['request']['id']
        second_id = self.json(second)['request']['id']
        self.assertEqual(self.post(self.owner, f'/api/rental-requests/{first_id}/approve').status_code, 200)

        connection = service.db()
        connection.execute('UPDATE rental_requests SET pickup_date=?,return_date=? WHERE id=?', (first_window['pickup_date'], first_window['return_date'], second_id))
        connection.commit()
        connection.close()
        conflict = self.post(self.owner, f'/api/rental-requests/{second_id}/approve')
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.json(self.owner.get('/api/tools'))['rentals']), 1)

    def test_legacy_booking_dates_are_backfilled_additively(self):
        connection = service.db()
        connection.execute('INSERT INTO users (name,email,password_hash,college,created_at) VALUES (?,?,?,?,?)', ('Owner', 'owner@example.test', 'test-hash', 'Test Campus', service.now_iso()))
        connection.execute('INSERT INTO users (name,email,password_hash,college,created_at) VALUES (?,?,?,?,?)', ('Borrower', 'borrower@example.test', 'test-hash', 'Test Campus', service.now_iso()))
        connection.execute('INSERT INTO devices (owner_id,name,category,`condition`,status) VALUES (?,?,?,?,?)', (1, 'Legacy Laptop', 'Laptop', 'Good', 'rented'))
        connection.execute('''INSERT INTO bookings (device_id,owner_id,borrower_id,reason,start_at,duration_hours,return_at,fee,status,pickup_date,return_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (1, 1, 2, 'Legacy booking', '2026-10-20T09:00:00', 24, '2026-10-21T18:00:00', 50, 'approved', None, None))
        connection.commit()
        connection.close()

        service.init_db()
        connection = service.db()
        legacy = connection.execute('SELECT pickup_date,return_date FROM bookings WHERE id=1').fetchone()
        connection.close()
        self.assertEqual(legacy['pickup_date'], '2026-10-20')
        self.assertEqual(legacy['return_date'], '2026-10-21')

    def test_production_refuses_to_fall_back_to_ephemeral_sqlite(self):
        previous_database_url = service.DATABASE_URL
        previous_app_env = os.environ.get('APP_ENV')
        try:
            service.DATABASE_URL = ''
            os.environ['APP_ENV'] = 'production'
            with self.assertRaisesRegex(RuntimeError, 'DATABASE_URL is required'):
                service.db()
        finally:
            service.DATABASE_URL = previous_database_url
            if previous_app_env is None:
                os.environ.pop('APP_ENV', None)
            else:
                os.environ['APP_ENV'] = previous_app_env


if __name__ == '__main__':
    unittest.main()
