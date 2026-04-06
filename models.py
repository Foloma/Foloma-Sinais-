from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime

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

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    # Tabela de utilizadores
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  is_active INTEGER DEFAULT 1,
                  is_admin INTEGER DEFAULT 0)''')
    # Tabela de trades (diário)
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  ativo TEXT NOT NULL,
                  direcao TEXT NOT NULL,
                  score REAL NOT NULL,
                  expiracao INTEGER NOT NULL,
                  resultado TEXT,
                  timestamp TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

# ---------- User functions ----------
def get_user_by_id(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash, is_active, is_admin FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2], row[3], row[4])
    return None

def get_user_by_username(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash, is_active, is_admin FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2], row[3], row[4])
    return None

def create_user(username, password, is_admin=False):
    password_hash = generate_password_hash(password)
    is_admin_flag = 1 if is_admin else 0
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password_hash, is_active, is_admin) VALUES (?, ?, 1, ?)',
                  (username, password_hash, is_admin_flag))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return User(user_id, username, password_hash, 1, is_admin_flag)
    except sqlite3.IntegrityError:
        conn.close()
        return None

def set_user_active(user_id, active):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET is_active = ? WHERE id = ?', (1 if active else 0, user_id))
    conn.commit()
    conn.close()

def list_users():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, username, is_active, is_admin FROM users')
    rows = c.fetchall()
    conn.close()
    return rows

# ---------- Trade functions ----------
def add_trade(user_id, ativo, direcao, score, expiracao, resultado=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO trades (user_id, ativo, direcao, score, expiracao, resultado, timestamp)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, ativo, direcao, score, expiracao, resultado, timestamp))
    conn.commit()
    trade_id = c.lastrowid
    conn.close()
    return trade_id

def update_trade_result(trade_id, resultado):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE trades SET resultado = ? WHERE id = ?', (resultado, trade_id))
    conn.commit()
    conn.close()

def get_user_trades(user_id, limit=50):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''SELECT id, ativo, direcao, score, expiracao, resultado, timestamp
                 FROM trades WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_last_unresolved_trade(user_id):
    """Retorna o último trade sem resultado (para registar depois)"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''SELECT id, ativo, direcao, score, expiracao, timestamp
                 FROM trades WHERE user_id = ? AND resultado IS NULL
                 ORDER BY timestamp DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    return row

init_db()
