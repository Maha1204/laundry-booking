from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Databasanslutning
def connect_db():
    return pymysql.connect(
        host='biblioteks-db.c74qek6ikkuc.eu-north-1.rds.amazonaws.com',  # Fyll i din host (t.ex. 'localhost')
        user='admin',  # Fyll i ditt användarnamn
        password='4RhQLjYY9bSH4QG',  # Fyll i ditt lösenord
        database='laundry_booking',  # Fyll i ditt databasnamn
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# Skapa tabellen om den inte finns
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
        
        # Lägg till UNIQUE constraint om den inte finns
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
        
        conn.commit()
        cursor.close()
        conn.close()
        print("Databas initierad!")
    except Exception as e:
        print(f"Databasfel: {e}")

# Hämta alla bokningar
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

# Skapa ny bokning
@app.route('/api/bookings', methods=['POST'])
def create_booking():
    try:
        data = request.get_json()
        
        # Validering
        required_fields = ['name', 'apartment', 'date', 'time']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field} är obligatoriskt'}), 400
        
        # Kontrollera att datum inte är i det förflutna
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        if booking_date < datetime.now().date():
            return jsonify({'error': 'Kan inte boka datum i det förflutna'}), 400
        
        conn = connect_db()
        cursor = conn.cursor()
        
        # Kontrollera om tiden redan är bokad
        cursor.execute(
            'SELECT id FROM bookings WHERE date = %s AND time = %s',
            (data['date'], data['time'])
        )
        
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Denna tid är redan bokad'}), 400
        
        # Skapa bokning
        cursor.execute('''
            INSERT INTO bookings (name, apartment, date, time)
            VALUES (%s, %s, %s, %s)
        ''', (data['name'], data['apartment'], data['date'], data['time']))
        
        conn.commit()
        booking_id = cursor.lastrowid
        cursor.close()
        conn.close()
        
        return jsonify({
            'message': 'Bokning skapad',
            'id': booking_id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Ta bort bokning
@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
def delete_booking(booking_id):
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM bookings WHERE id = %s', (booking_id,))
        
        if cursor.rowcount == 0:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Bokning hittades inte'}), 404
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'message': 'Bokning borttagen'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Hämta bokningar för specifikt datum
@app.route('/api/bookings/date/<date>', methods=['GET'])
def get_bookings_by_date(date):
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, apartment, time
            FROM bookings 
            WHERE date = %s
            ORDER BY time
        ''', (date,))
        
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify(bookings), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    print("Server startar på http://localhost:5000")
    app.run(debug=True, port=5000)