import os
import sqlite3
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin):
    def __init__(self, id, username, password_hash, is_active=1, is_admin=0):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self._is_active = bool(is_active)
        self.is_admin = bool(is_admin)

    @property
    def is_active(self):
        return self._is_active

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ---------- Conexão segura à base de dados ----------
_db_path = os.path.join(os.path.dirname(__file__), 'users.db')

def set_db_path(path):
    global _db_path
    _db_path = path

def get_db_conn():
    """Retorna uma conexão SQLite com row_factory e foreign_keys ativadas."""
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # respeitar FKs
    return conn

# ---------- Inicialização ----------
def init_db():
    with get_db_conn() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         username TEXT UNIQUE NOT NULL,
                         password_hash TEXT NOT NULL,
                         is_active INTEGER DEFAULT 1,
                         is_admin INTEGER DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS trades
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         user_id INTEGER NOT NULL,
                         ativo TEXT NOT NULL,
                         direcao TEXT NOT NULL,
                         score REAL NOT NULL,
                         expiracao INTEGER NOT NULL,
                         resultado TEXT,
                         timestamp TEXT NOT NULL,
                         FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
        # Índice para acelerar queries por user_id
        conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)')
        conn.commit()

# ---------- User functions ----------
def get_user_by_id(user_id):
    with get_db_conn() as conn:
        cursor = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            return User(row['id'], row['username'], row['password_hash'],
                        row['is_active'], row['is_admin'])
    return None

def get_user_by_username(username):
    with get_db_conn() as conn:
        cursor = conn.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        if row:
            return User(row['id'], row['username'], row['password_hash'],
                        row['is_active'], row['is_admin'])
    return None

def create_user(username, password, is_admin=False):
    password_hash = generate_password_hash(password)
    is_admin_flag = 1 if is_admin else 0
    with get_db_conn() as conn:
        try:
            cursor = conn.execute(
                'INSERT INTO users (username, password_hash, is_active, is_admin) VALUES (?, ?, 1, ?)',
                (username, password_hash, is_admin_flag)
            )
            conn.commit()
            user_id = cursor.lastrowid
            return User(user_id, username, password_hash, 1, is_admin_flag)
        except sqlite3.IntegrityError:
            return None

def set_user_active(user_id, active):
    with get_db_conn() as conn:
        conn.execute('UPDATE users SET is_active = ? WHERE id = ?',
                     (1 if active else 0, user_id))
        conn.commit()

def list_users():
    with get_db_conn() as conn:
        cursor = conn.execute('SELECT id, username, is_active, is_admin FROM users')
        return cursor.fetchall()

# ---------- Trade functions ----------
def add_trade(user_id, ativo, direcao, score, expiracao, resultado=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_conn() as conn:
        cursor = conn.execute(
            'INSERT INTO trades (user_id, ativo, direcao, score, expiracao, resultado, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (user_id, ativo, direcao, score, expiracao, resultado, timestamp)
        )
        conn.commit()
        return cursor.lastrowid

def update_trade_result(trade_id, resultado):
    with get_db_conn() as conn:
        conn.execute('UPDATE trades SET resultado = ? WHERE id = ?', (resultado, trade_id))
        conn.commit()

def get_user_trades(user_id, limit=50):
    with get_db_conn() as conn:
        cursor = conn.execute(
            'SELECT id, ativo, direcao, score, expiracao, resultado, timestamp FROM trades WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?',
            (user_id, limit)
        )
        return cursor.fetchall()

def get_last_unresolved_trade(user_id):
    with get_db_conn() as conn:
        cursor = conn.execute(
            'SELECT id, ativo, direcao, score, expiracao, timestamp FROM trades WHERE user_id = ? AND resultado IS NULL ORDER BY timestamp DESC LIMIT 1',
            (user_id,)
        )
        return cursor.fetchone()
