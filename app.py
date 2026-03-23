from flask import Flask, request, jsonify, session
from flask_cors import CORS
import pymysql
from datetime import datetime
import os
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
CORS(app, supports_credentials=True)

# Admin password (store hashed in production, use env var)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# Default time slots
DEFAULT_TIME_SLOTS = ['07-10', '10-13', '13-16', '16-19', '19-22']

def connect_db():
    return pymysql.connect(
        host='biblioteks-db.c74qek6ikkuc.eu-north-1.rds.amazonaws.com',
        user='admin',
        password='4RhQLjYY9bSH4QG',
        database='laundry_booking',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def init_db():
    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                apartment VARCHAR(20) NOT NULL,
                date DATE NOT NULL,
                time VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM information_schema.statistics 
            WHERE table_schema = DATABASE() 
            AND table_name = 'bookings' 
            AND index_name = 'unique_booking'
        ''')
        result = cursor.fetchone()
        if result['count'] == 0:
            cursor.execute('''
                ALTER TABLE bookings 
                ADD UNIQUE KEY unique_booking (date, time)
            ''')

        # Table for configurable time slots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_slots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                slot VARCHAR(10) NOT NULL UNIQUE,
                is_active BOOLEAN DEFAULT TRUE,
                sort_order INT DEFAULT 0
            )
        ''')

        # Insert default slots if empty
        cursor.execute('SELECT COUNT(*) as count FROM time_slots')
        if cursor.fetchone()['count'] == 0:
            for i, slot in enumerate(DEFAULT_TIME_SLOTS):
                cursor.execute(
                    'INSERT INTO time_slots (slot, is_active, sort_order) VALUES (%s, TRUE, %s)',
                    (slot, i)
                )

        conn.commit()
        cursor.close()
        conn.close()
        print("Databas initierad!")
    except Exception as e:
        print(f"Databasfel: {e}")


# ── Auth ────────────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Set user identity (name + apartment). No password needed."""
    data = request.get_json()
    name = (data.get('name') or '').strip()
    apartment = (data.get('apartment') or '').strip()
    if not name or not apartment:
        return jsonify({'error': 'Namn och lägenhetsnummer krävs'}), 400
    session['user_name'] = name
    session['user_apartment'] = apartment
    session['is_admin'] = False
    return jsonify({'message': 'Inloggad', 'name': name, 'apartment': apartment, 'is_admin': False}), 200


@app.route('/api/auth/admin', methods=['POST'])
def admin_login():
    data = request.get_json()
    if data.get('password') == ADMIN_PASSWORD:
        session['is_admin'] = True
        session['user_name'] = 'Admin'
        session['user_apartment'] = ''
        return jsonify({'message': 'Admin inloggad', 'is_admin': True}), 200
    return jsonify({'error': 'Fel lösenord'}), 401


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Utloggad'}), 200


@app.route('/api/auth/me', methods=['GET'])
def me():
    if 'user_name' not in session:
        return jsonify({'logged_in': False}), 200
    return jsonify({
        'logged_in': True,
        'name': session.get('user_name'),
        'apartment': session.get('user_apartment'),
        'is_admin': session.get('is_admin', False)
    }), 200


# ── Bookings ────────────────────────────────────────────────────────────────

@app.route('/api/bookings', methods=['GET'])
def get_bookings():
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, apartment, 
                   DATE_FORMAT(date, '%Y-%m-%d') as date, 
                   time
            FROM bookings 
            ORDER BY date, time
        ''')
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(bookings), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookings', methods=['POST'])
def create_booking():
    if 'user_name' not in session:
        return jsonify({'error': 'Du måste vara inloggad för att boka'}), 401
    try:
        data = request.get_json()
        required_fields = ['date', 'time']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field} är obligatoriskt'}), 400

        # Use session identity
        name = session['user_name']
        apartment = session['user_apartment']

        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        if booking_date < datetime.now().date():
            return jsonify({'error': 'Kan inte boka datum i det förflutna'}), 400

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT id FROM bookings WHERE date = %s AND time = %s',
            (data['date'], data['time'])
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Denna tid är redan bokad'}), 400

        cursor.execute('''
            INSERT INTO bookings (name, apartment, date, time)
            VALUES (%s, %s, %s, %s)
        ''', (name, apartment, data['date'], data['time']))

        conn.commit()
        booking_id = cursor.lastrowid
        cursor.close()
        conn.close()

        return jsonify({'message': 'Bokning skapad', 'id': booking_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
def delete_booking(booking_id):
    if 'user_name' not in session:
        return jsonify({'error': 'Du måste vara inloggad'}), 401
    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM bookings WHERE id = %s', (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Bokning hittades inte'}), 404

        # Admin can delete anything; users only their own
        is_admin = session.get('is_admin', False)
        is_own = (
            booking['name'] == session.get('user_name') and
            booking['apartment'] == session.get('user_apartment')
        )
        if not is_admin and not is_own:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Du kan bara ta bort dina egna bokningar'}), 403

        cursor.execute('DELETE FROM bookings WHERE id = %s', (booking_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Bokning borttagen'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookings/date/<date>', methods=['GET'])
def get_bookings_by_date(date):
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, apartment, time
            FROM bookings WHERE date = %s ORDER BY time
        ''', (date,))
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(bookings), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Time Slots (admin only) ──────────────────────────────────────────────────

@app.route('/api/timeslots', methods=['GET'])
def get_timeslots():
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT slot, is_active FROM time_slots ORDER BY sort_order')
        slots = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(slots), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/timeslots', methods=['PUT'])
def update_timeslots():
    if not session.get('is_admin'):
        return jsonify({'error': 'Endast admin'}), 403
    try:
        data = request.get_json()  # [{"slot": "07-10", "is_active": true}, ...]
        conn = connect_db()
        cursor = conn.cursor()
        for item in data:
            cursor.execute(
                'UPDATE time_slots SET is_active = %s WHERE slot = %s',
                (item['is_active'], item['slot'])
            )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Tidsluckor uppdaterade'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/timeslots', methods=['POST'])
def add_timeslot():
    if not session.get('is_admin'):
        return jsonify({'error': 'Endast admin'}), 403
    try:
        data = request.get_json()
        slot = (data.get('slot') or '').strip()
        if not slot:
            return jsonify({'error': 'Slot krävs'}), 400
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(sort_order) as m FROM time_slots')
        row = cursor.fetchone()
        next_order = (row['m'] or 0) + 1
        cursor.execute(
            'INSERT INTO time_slots (slot, is_active, sort_order) VALUES (%s, TRUE, %s)',
            (slot, next_order)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Tidslucka tillagd'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/timeslots/<slot>', methods=['DELETE'])
def delete_timeslot(slot):
    if not session.get('is_admin'):
        return jsonify({'error': 'Endast admin'}), 403
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM time_slots WHERE slot = %s', (slot,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Tidslucka borttagen'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    init_db()
    print("Server startar på http://localhost:5000")
    app.run(debug=True)

