from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import mimetypes
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ----------------- Config -----------------
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_NAME = 'uploads.db'

# Expected schema (column name -> SQL type/constraint)
EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "filename": "TEXT NOT NULL",
    "file_type": "TEXT NOT NULL",
    "file_path": "TEXT NOT NULL",
    "geotag": "TEXT",
    "time_sent": "TEXT",
    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    geotag TEXT,
    time_sent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

def table_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]  # row[1] = column name

def ensure_schema(conn):
    cur = conn.cursor()
    # Create table if it doesn't exist
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()

    # Option A: auto-add any missing columns (non-destructive)
    existing = set(table_columns(conn, "uploads"))
    for col, coldef in EXPECTED_COLUMNS.items():
        if col not in existing and col != "id":  # id already exists in any sane table
            cur.execute(f"ALTER TABLE uploads ADD COLUMN {col} {coldef}")
    conn.commit()

def reset_schema(conn):
    """Drop and recreate the uploads table (destructive)."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS uploads")
    conn.commit()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()

# ----------------- Database Initialization -----------------
def init_db():
    reset_requested = os.environ.get("RESET_DB") == "1"

    conn = sqlite3.connect(DB_NAME)
    try:
        if reset_requested:
            reset_schema(conn)
        else:
            ensure_schema(conn)
    finally:
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

    # Sanitize filename
    filename = secure_filename(uploaded_file.filename)

    # Allowed extensions
    allowed_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                    '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv')
    if not filename.lower().endswith(allowed_exts):
        return jsonify({'error': 'File type not allowed'}), 400

    # Save file to disk with timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    timestamped_name = f"{timestamp}_{filename}"
    file_path = os.path.join(UPLOAD_FOLDER, timestamped_name)
    uploaded_file.save(file_path)

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type and mime_type.startswith("video"):
        file_type = "video"
    elif mime_type and mime_type.startswith("image"):
        file_type = "image"
    else:
        os.remove(file_path)  # delete invalid file
        return jsonify({'error': 'Invalid file type'}), 400

    geotag = request.form.get('geotag', 'Not provided')
    time_sent = request.form.get('time', 'Not provided')

    # Save metadata to DB
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO uploads (filename, file_type, file_path, geotag, time_sent)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (filename, file_type, file_path, geotag, time_sent)
    )
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


# POST /location → Save latitude & longitude
@app.route("/location", methods=["POST"])
def save_location():
    data = request.get_json()
    if not data or "latitude" not in data or "longitude" not in data:
        return jsonify({"error": "Latitude and longitude required"}), 400

    latitude = data["latitude"]
    longitude = data["longitude"]

    # Save location to DB (optional)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO uploads (filename, file_type, file_path, geotag, time_sent)
        VALUES (?, ?, ?, ?, ?)
        ''',
        ("location", "location", "N/A", f"{latitude},{longitude}", datetime.now().isoformat())
    )
    conn.commit()
    last_id = c.lastrowid
    conn.close()

    return jsonify({
        "message": "Location saved successfully",
        "id": last_id,
        "latitude": latitude,
        "longitude": longitude
    }), 200


# GET /uploads → List all uploads
@app.route('/uploads', methods=['GET'])
def get_uploads():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, filename, file_type, geotag, time_sent, created_at FROM uploads')
    rows = c.fetchall()
    conn.close()

    uploads_list = [{
        'id': r[0],
        'filename': r[1],
        'file_type': r[2],
        'geotag': r[3],
        'time_sent': r[4],
        'created_at': r[5],
        'file_url': f"{request.host_url}file/{r[0]}"
    } for r in rows]

    return jsonify({'uploads': uploads_list}), 200

# GET /file/<id> → Retrieve a single file
@app.route("/file/<int:file_id>", methods=["GET"])
def get_file(file_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Fetch the actual saved path
        c.execute("SELECT file_path FROM uploads WHERE id=?", (file_id,))
        row = c.fetchone()
        conn.close()

        if row is None:
            return jsonify({"error": f"file not found with id {file_id}"}), 404

        file_path = row[0]

        if not os.path.exists(file_path):
            return jsonify({"error": "File not found on server"}), 404

        return send_file(file_path)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- Root Route -----------------
@app.route("/", methods=["GET"])
def home():
    return "Backend is running successfully 🚀"

# ----------------- Run Server -----------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)



