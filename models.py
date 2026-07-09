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
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# ---------- Inicialização (com migração para novas colunas) ----------
def init_db():
    with get_db_conn() as conn:
        # Tabela users
        conn.execute('''CREATE TABLE IF NOT EXISTS users
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         username TEXT UNIQUE NOT NULL,
                         password_hash TEXT NOT NULL,
                         is_active INTEGER DEFAULT 1,
                         is_admin INTEGER DEFAULT 0)''')
        
        # Tabela trades com as novas colunas estrategia e confianca
        conn.execute('''CREATE TABLE IF NOT EXISTS trades
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         user_id INTEGER NOT NULL,
                         ativo TEXT NOT NULL,
                         direcao TEXT NOT NULL,
                         score REAL NOT NULL,
                         expiracao INTEGER NOT NULL,
                         resultado TEXT,
                         estrategia TEXT,
                         confianca REAL,
                         timestamp TEXT NOT NULL,
                         FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
        
        # Índice
        conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)')
        
        # --- MIGRAÇÃO: adicionar colunas se não existirem (para bancos antigos) ---
        # Verifica se a coluna 'estrategia' já existe
        cursor = conn.execute("PRAGMA table_info(trades)")
        colunas = [col[1] for col in cursor.fetchall()]
        if 'estrategia' not in colunas:
            conn.execute('ALTER TABLE trades ADD COLUMN estrategia TEXT')
        if 'confianca' not in colunas:
            conn.execute('ALTER TABLE trades ADD COLUMN confianca REAL')
        
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

# ---------- Trade functions (ATUALIZADAS) ----------
def add_trade(user_id, ativo, direcao, score, expiracao, resultado=None, estrategia=None, confianca=0):
    """Insere um novo trade com campos adicionais (estrategia e confianca)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_conn() as conn:
        cursor = conn.execute(
            '''INSERT INTO trades 
               (user_id, ativo, direcao, score, expiracao, resultado, estrategia, confianca, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, ativo, direcao, score, expiracao, resultado, estrategia, confianca, timestamp)
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
            '''SELECT id, ativo, direcao, score, expiracao, resultado, estrategia, confianca, timestamp 
               FROM trades 
               WHERE user_id = ? 
               ORDER BY timestamp DESC 
               LIMIT ?''',
            (user_id, limit)
        )
        return cursor.fetchall()

def get_last_unresolved_trade(user_id):
    with get_db_conn() as conn:
        cursor = conn.execute(
            '''SELECT id, ativo, direcao, score, expiracao, estrategia, confianca, timestamp 
               FROM trades 
               WHERE user_id = ? AND resultado IS NULL 
               ORDER BY timestamp DESC 
               LIMIT 1''',
            (user_id,)
        )
        return cursor.fetchone()

# ---------- NOVAS FUNÇÕES PARA ESTATÍSTICAS ----------
def get_performance_stats(user_id):
    """Retorna estatísticas de desempenho agregadas por estratégia, ativo, hora e dia da semana."""
    conn = get_db_conn()
    cursor = conn.cursor()
    
    # Por estratégia
    cursor.execute('''
        SELECT estrategia, 
               COUNT(*) as total, 
               SUM(CASE WHEN resultado = 'Ganhou' THEN 1 ELSE 0 END) as ganhos,
               AVG(score) as avg_score,
               AVG(confianca) as avg_confianca
        FROM trades
        WHERE user_id = ? AND resultado IS NOT NULL
        GROUP BY estrategia
    ''', (user_id,))
    estrategias = cursor.fetchall()

    # Por ativo
    cursor.execute('''
        SELECT ativo,
               COUNT(*) as total,
               SUM(CASE WHEN resultado = 'Ganhou' THEN 1 ELSE 0 END) as ganhos
        FROM trades
        WHERE user_id = ? AND resultado IS NOT NULL
        GROUP BY ativo
    ''', (user_id,))
    ativos = cursor.fetchall()

    # Por hora do dia
    cursor.execute('''
        SELECT strftime('%H', timestamp) as hora,
               COUNT(*) as total,
               SUM(CASE WHEN resultado = 'Ganhou' THEN 1 ELSE 0 END) as ganhos
        FROM trades
        WHERE user_id = ? AND resultado IS NOT NULL
        GROUP BY hora
        ORDER BY hora
    ''', (user_id,))
    horas = cursor.fetchall()

    # Por dia da semana (0=Domingo, 6=Sábado)
    cursor.execute('''
        SELECT strftime('%w', timestamp) as dia_semana,
               COUNT(*) as total,
               SUM(CASE WHEN resultado = 'Ganhou' THEN 1 ELSE 0 END) as ganhos
        FROM trades
        WHERE user_id = ? AND resultado IS NOT NULL
        GROUP BY dia_semana
        ORDER BY dia_semana
    ''', (user_id,))
    dias = cursor.fetchall()

    conn.close()
    return {
        "por_estrategia": estrategias,
        "por_ativo": ativos,
        "por_hora": horas,
        "por_dia_semana": dias
    }
