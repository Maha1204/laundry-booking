from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
from datetime import datetime, timedelta
import os

app = Flask(__name__)
CORS(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
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

def get_week_bounds(date_obj):
    """Return Monday and Sunday for the week containing date_obj."""
    monday = date_obj - timedelta(days=date_obj.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

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
        if cursor.fetchone()['count'] == 0:
            cursor.execute('ALTER TABLE bookings ADD UNIQUE KEY unique_booking (date, time)')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_slots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                slot VARCHAR(10) NOT NULL UNIQUE,
                is_active BOOLEAN DEFAULT TRUE,
                sort_order INT DEFAULT 0
            )
        ''')

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

init_db()


def is_admin():
    return request.headers.get('X-Admin-Password') == ADMIN_PASSWORD


# ── Bookings ──────────────────────────────────────────────────────────

@app.route('/api/bookings', methods=['GET'])
def get_bookings():
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, apartment,
                   DATE_FORMAT(date, '%Y-%m-%d') as date,
                   time
            FROM bookings ORDER BY date, time
        ''')
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(bookings), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookings', methods=['POST'])
def create_booking():
    try:
        data = request.get_json()
        for field in ['name', 'apartment', 'date', 'time']:
            if not data.get(field):
                return jsonify({'error': f'{field} är obligatoriskt'}), 400

        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        today = datetime.now().date()

        if booking_date < today:
            return jsonify({'error': 'Kan inte boka datum i det förflutna'}), 400

        # Get week bounds for the requested booking date
        week_monday, week_sunday = get_week_bounds(booking_date)

        # Check if this person already has a booking in that same week
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id FROM bookings
            WHERE name = %s AND apartment = %s
            AND date BETWEEN %s AND %s
        ''', (data['name'], data['apartment'], week_monday, week_sunday))

        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Du har redan en bokning denna vecka. Du kan max boka en gång per vecka.'}), 400

        # Check if the time slot itself is already taken
        cursor.execute(
            'SELECT id FROM bookings WHERE date = %s AND time = %s',
            (data['date'], data['time'])
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Denna tid är redan bokad'}), 400

        cursor.execute(
            'INSERT INTO bookings (name, apartment, date, time) VALUES (%s, %s, %s, %s)',
            (data['name'], data['apartment'], data['date'], data['time'])
        )
        conn.commit()
        booking_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return jsonify({'message': 'Bokning skapad', 'id': booking_id}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
def delete_booking(booking_id):
    try:
        name      = request.headers.get('X-User-Name', '')
        apartment = request.headers.get('X-User-Apartment', '')
        admin     = is_admin()

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bookings WHERE id = %s', (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Bokning hittades inte'}), 404

        is_own = (booking['name'] == name and booking['apartment'] == apartment)
        if not admin and not is_own:
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
        cursor.execute('SELECT id, name, apartment, time FROM bookings WHERE date = %s ORDER BY time', (date,))
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(bookings), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Check if user has booking in a given week ─────────────────────────

@app.route('/api/bookings/week-check', methods=['POST'])
def week_check():
    """Returns any existing booking for a person in a given week."""
    try:
        data = request.get_json()
        date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
        week_monday, week_sunday = get_week_bounds(date_obj)

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, DATE_FORMAT(date, '%Y-%m-%d') as date, time
            FROM bookings
            WHERE name = %s AND apartment = %s
            AND date BETWEEN %s AND %s
        ''', (data['name'], data['apartment'], week_monday, week_sunday))
        existing = cursor.fetchone()
        cursor.close()
        conn.close()

        return jsonify({'has_booking': existing is not None, 'booking': existing}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Time Slots ────────────────────────────────────────────────────────

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
    if not is_admin():
        return jsonify({'error': 'Endast admin'}), 403
    try:
        data = request.get_json()
        conn = connect_db()
        cursor = conn.cursor()
        for i, item in enumerate(data):
            cursor.execute('SELECT slot FROM time_slots WHERE slot = %s', (item['slot'],))
            if cursor.fetchone():
                cursor.execute('UPDATE time_slots SET is_active = %s, sort_order = %s WHERE slot = %s',
                               (item['is_active'], i, item['slot']))
            else:
                cursor.execute('INSERT INTO time_slots (slot, is_active, sort_order) VALUES (%s, %s, %s)',
                               (item['slot'], item['is_active'], i))
        new_slots = [item['slot'] for item in data]
        cursor.execute('SELECT slot FROM time_slots')
        existing = [row['slot'] for row in cursor.fetchall()]
        for slot in existing:
            if slot not in new_slots:
                cursor.execute('DELETE FROM time_slots WHERE slot = %s', (slot,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Tidsluckor uppdaterade'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/verify', methods=['POST'])
def verify_admin():
    if is_admin():
        return jsonify({'ok': True}), 200
    return jsonify({'error': 'Fel lösenord'}), 401


if __name__ == '__main__':
    print("Server startar på http://localhost:5000")
    app.run(debug=True)

