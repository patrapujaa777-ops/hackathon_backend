from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import io

app = Flask(__name__)
CORS(app)

# Limit uploads to 100 MB
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

DB_NAME = 'uploads.db'

# ----------------- Database Initialization -----------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_data BLOB NOT NULL,
            geotag TEXT,
            time_sent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----------------- API Endpoints -----------------

# POST /upload → Upload image or video
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file found in request'}), 400

    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = uploaded_file.filename
    allowed_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                    '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv')
    
    if not filename.lower().endswith(allowed_exts):
        return jsonify({'error': 'File type not allowed'}), 400

    file_bytes = uploaded_file.read()
    file_type = 'video' if filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv')) else 'image'
    geotag = request.form.get('geotag', 'Not provided')
    time_sent = request.form.get('time', 'Not provided')

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO uploads (filename, file_type, file_data, geotag, time_sent)
        VALUES (?, ?, ?, ?, ?)
    ''', (filename, file_type, file_bytes, geotag, time_sent))
    conn.commit()
    last_id = c.lastrowid
    conn.close()

    return jsonify({
        'message': f'{file_type.capitalize()} uploaded successfully',
        'id': last_id,
        'filename': filename,
        'file_type': file_type,
        'geotag': geotag,
        'time_sent': time_sent,
        'file_url': f"{request.host_url}file/{last_id}"
    }), 200

# GET /uploads → List all uploads
@app.route('/uploads', methods=['GET'])
def get_uploads():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, filename, file_type, geotag, time_sent, created_at FROM uploads')
    rows = c.fetchall()
    conn.close()

    uploads_list = []
    for row in rows:
        uploads_list.append({
            'id': row[0],
            'filename': row[1],
            'file_type': row[2],
            'geotag': row[3],
            'time_sent': row[4],
            'created_at': row[5],
            'file_url': f"{request.host_url}file/{row[0]}"
        })

    return jsonify({'uploads': uploads_list}), 200

# GET /file/<id> → Retrieve a single file
@app.route('/file/<int:file_id>', methods=['GET'])
def get_file(file_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT filename, file_data FROM uploads WHERE id=?', (file_id,))
    row = c.fetchone()
    conn.close()

    if row is None:
        return jsonify({'error': 'File not found'}), 404

    filename, file_data = row
    return send_file(io.BytesIO(file_data), download_name=filename, as_attachment=False)

# ----------------- Run Server -----------------
if __name__ == '__main__':
    app.run(debug=True)