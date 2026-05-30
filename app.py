from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_bcrypt import Bcrypt
import sqlite3
import os
from datetime import datetime, date, timedelta
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)
bcrypt = Bcrypt(app)

# ─── Config ────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'habits.db'))
PASSWORD_HASH = None  # set on first run

# ─── DB Init ───────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (habit_id) REFERENCES habits(id),
            UNIQUE(habit_id, date)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    # Seed habits
    seeds = [
        ('No alcohol', 1),
        ('Exercise', 1),
        ('Stretch', 1),
        ('Elbow rehab', 1),
    ]
    for name, active in seeds:
        try:
            conn.execute(
                'INSERT INTO habits (name, created_at, active) VALUES (?, ?, ?)',
                (name, datetime.utcnow().isoformat(), active)
            )
        except sqlite3.IntegrityError:
            pass  # already exists
    conn.commit()
    conn.close()

# ─── Auth helpers ──────────────────────────────────────────────────────────
def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─── Routes ────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        conn = get_db()
        row = conn.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone()
        conn.close()
        if row and bcrypt.check_password_hash(row['value'], pwd):
            session['authenticated'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='Wrong password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/')
@require_auth
def index():
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    conn.close()

    today = date.today().isoformat()
    logged_ids = set()
    conn = get_db()
    rows = conn.execute("SELECT habit_id FROM log WHERE date=?", (today,)).fetchall()
    conn.close()
    for r in rows:
        logged_ids.add(r['habit_id'])

    habits_list = []
    for h in habits:
        habits_list.append({
            'id': h['id'],
            'name': h['name'],
            'checked': h['id'] in logged_ids,
        })

    return render_template('index.html', habits=habits_list, today=today)

@app.route('/toggle', methods=['POST'])
@require_auth
def toggle():
    data = request.get_json()
    habit_id = data['habit_id']
    date_str = data.get('date', date.today().isoformat())
    comment = data.get('comment', '')
    now = datetime.utcnow().isoformat()

    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM log WHERE habit_id=? AND date=?", (habit_id, date_str)
    ).fetchone()

    if existing:
        conn.execute("DELETE FROM log WHERE id=?", (existing['id'],))
        done = False
    else:
        conn.execute(
            "INSERT INTO log (habit_id, date, comment, created_at) VALUES (?, ?, ?, ?)",
            (habit_id, date_str, comment, now)
        )
        done = True

    conn.commit()
    conn.close()
    return jsonify({'done': done})

@app.route('/add_habit', methods=['POST'])
@require_auth
def add_habit():
    name = request.form.get('name', '').strip()
    if not name:
        return redirect(url_for('index'))
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO habits (name, created_at) VALUES (?, ?)",
            (name, datetime.utcnow().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete_habit/<int:habit_id>', methods=['POST'])
@require_auth
def delete_habit(habit_id):
    conn = get_db()
    # soft delete
    conn.execute("UPDATE habits SET active=0 WHERE id=?", (habit_id,))
    conn.execute("DELETE FROM log WHERE habit_id=?", (habit_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/dashboard_data')
@require_auth
def dashboard_data():
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    today = date.today()
    data = []
    for h in habits:
        rows = conn.execute(
            "SELECT date FROM log WHERE habit_id=? ORDER BY date", (h['id'],)
        ).fetchall()
        current_streak = 0
        streak = 0
        d = today
        for r in sorted(rows, key=lambda x: x['date'], reverse=True):
            if r['date'] == d.isoformat():
                streak += 1
                current_streak = streak
                d -= timedelta(days=1)
            else:
                break
        data.append({'id': h['id'], 'current_streak': current_streak})
    conn.close()
    return jsonify(data)

@app.route('/dashboard')
@require_auth
def dashboard():
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    today = date.today()

    dashboard_data = []
    all_logs = []
    weekly_counts = {}

    for h in habits:
        rows = conn.execute(
            "SELECT date, comment FROM log WHERE habit_id=? ORDER BY date", (h['id'],)
        ).fetchall()

        dates = [r['date'] for r in rows]
        comments = {r['date']: r['comment'] for r in rows if r['comment']}

        # ── Streaks ──
        current_streak = 0
        longest_streak = 0
        streak = 0
        d = today
        for r in sorted(rows, key=lambda x: x['date'], reverse=True):
            if r['date'] == d.isoformat():
                streak += 1
                current_streak = streak
                d -= timedelta(days=1)
            else:
                break

        # Longest streak (scan all)
        sorted_dates = sorted(set(r['date'] for r in rows))
        temp_streak = 0
        prev = None
        for d_str in sorted_dates:
            d_parsed = date.fromisoformat(d_str)
            if prev is None or (d_parsed - prev).days == 1:
                temp_streak += 1
            else:
                temp_streak = 1
            longest_streak = max(longest_streak, temp_streak)
            prev = d_parsed

        # Monthly bar chart data
        monthly = {}
        for r in rows:
            month_key = r['date'][:7]  # YYYY-MM
            monthly[month_key] = monthly.get(month_key, 0) + 1
        sorted_months = sorted(monthly.keys())
        monthly_dates = sorted_months
        monthly_counts = [monthly[m] for m in sorted_months]

        dashboard_data.append({
            'id': h['id'],
            'name': h['name'],
            'current_streak': current_streak,
            'longest_streak': longest_streak,
            'total_logs': len(rows),
            'monthly_dates': monthly_dates,
            'monthly_counts': monthly_counts,
            'has_comment': h['name'] == 'Exercise',
            'comments': comments,
        })

        for r in rows:
            all_logs.append({
                'name': h['name'],
                'date': r['date'],
                'comment': r['comment'],
            })

    conn.close()
    return render_template('dashboard.html', habits=dashboard_data)

@app.route('/history')
@require_auth
def history():
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    logs = conn.execute('''
        SELECT l.date, l.comment, h.name
        FROM log l
        JOIN habits h ON h.id = l.habit_id
        WHERE h.active=1
        ORDER BY l.date DESC
        LIMIT 200
    ''').fetchall()
    conn.close()
    return render_template('history.html', logs=logs, habits=habits)

@app.route('/edit_comment/<int:habit_id>/<date_str>', methods=['POST'])
@require_auth
def edit_comment(habit_id, date_str):
    comment = request.form.get('comment', '')
    conn = get_db()
    conn.execute("UPDATE log SET comment=? WHERE habit_id=? AND date=?", (comment, habit_id, date_str))
    conn.commit()
    conn.close()
    return redirect(url_for('history'))

# ─── Setup first password ──────────────────────────────────────────────────
@app.before_request
def check_setup():
    if request.path == '/setup' or request.path.startswith('/static'):
        return
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone()
    conn.close()
    if not row and request.path != '/login':
        return redirect(url_for('setup'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone()
    conn.close()
    if row and request.method == 'GET':
        return redirect(url_for('login'))

    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if len(pwd) < 4:
            return render_template('setup.html', error='Password must be at least 4 characters')
        pw_hash = bcrypt.generate_password_hash(pwd).decode('utf-8')
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('password_hash', ?)", (pw_hash,))
        conn.commit()
        conn.close()
        session['authenticated'] = True
        return redirect(url_for('index'))
    return render_template('setup.html')

# ─── Start ─────────────────────────────────────────────────────────────────
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
