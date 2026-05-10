import os
import time
import threading
import logging
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests

import models

# ---------- Configuração inicial ----------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24).hex()  # não regenera se SECRET_KEY definida

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Rate limiter: máximo 1 pedido por minuto na rota do sinal
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour"]
)

# ---------- Configurações (Twelve Data) ----------
API_KEY = os.environ.get('TWELVE_DATA_KEY', '')
ATIVOS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD"]
SCORE_MINIMO = float(os.environ.get('SCORE_MINIMO', '1.5'))
score_lock = threading.Lock()
app.config['SCORE_MINIMO'] = SCORE_MINIMO

# ---------- Inicialização da base de dados ----------
# Garantir que users.db é criada na mesma pasta do app.py
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
models.set_db_path(db_path)
models.init_db()

# Criação do admin (se não existir)
def create_admin_if_not_exists():
    admin = models.get_user_by_username('admin')
    if not admin:
        admin_pass = os.environ.get('ADMIN_PASS') or secrets.token_urlsafe(10)
        models.create_user('admin', admin_pass, is_admin=True)
        logging.info("=" * 60)
        logging.info(f"Admin criado: admin / {admin_pass}")
        logging.info("Guarde esta senha! Ela não será mostrada novamente.")
        logging.info("=" * 60)
    else:
        logging.info("Administrador já existe.")

import secrets
create_admin_if_not_exists()

# ---------- Funções de trading ----------
def obter_velas(par, intervalo="1min", n=30):
    """Obtém as últimas n velas da Twelve Data (fechos em ordem cronológica)."""
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={par}&interval={intervalo}&outputsize={n}&apikey={API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        if "values" in dados:
            # API retorna da mais recente para a mais antiga
            precos = [float(v["close"]) for v in reversed(dados["values"])]
            if len(precos) == n:
                return precos
            else:
                logging.warning(f"Dados insuficientes para {par}: obtidos {len(precos)} de {n}")
                return None
        else:
            logging.error(f"Resposta inesperada Twelve Data para {par}: {dados}")
    except Exception as e:
        logging.error(f"Erro ao obter velas para {par}: {e}", exc_info=True)
    return None

def calcular_ema(precos, periodo):
    """EMA correta: SMA inicial + iteração por todos os preços restantes."""
    if len(precos) < periodo:
        return None
    mult = 2 / (periodo + 1)
    sma = sum(precos[:periodo]) / periodo
    ema = sma
    for p in precos[periodo:]:
        ema = (p - ema) * mult + ema
    return ema

def calcular_rsi(precos, periodo=7):
    if len(precos) < periodo + 1:
        return 50
    deltas = [precos[i] - precos[i-1] for i in range(1, len(precos))]
    ult_deltas = deltas[-periodo:]
    ganhos = sum(d for d in ult_deltas if d > 0)
    perdas = sum(-d for d in ult_deltas if d < 0)
    avg_gain = ganhos / periodo
    avg_loss = perdas / periodo
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calcular_macd(precos):
    ema12 = calcular_ema(precos, 12)
    ema26 = calcular_ema(precos, 26)
    if None in (ema12, ema26):
        return None
    return ema12 - ema26

def calcular_bollinger(precos, periodo=20, desvios=2):
    if len(precos) < periodo:
        return None, None, None
    ultimos = precos[-periodo:]
    media = sum(ultimos) / periodo
    var = sum((x - media) ** 2 for x in ultimos) / periodo
    std = var ** 0.5
    superior = media + desvios * std
    inferior = media - desvios * std
    return superior, media, inferior

def analisar_ativo(par):
    precos = obter_velas(par, intervalo="1min", n=30)
    if precos is None or len(precos) < 30:
        return None, 0, f"Erro ao obter preços para {par}"

    ema5 = calcular_ema(precos, 5)
    ema13 = calcular_ema(precos, 13)
    if None in (ema5, ema13):
        return None, 0, "Erro no cálculo das EMAs"

    diff_percent = abs(ema5 - ema13) / ema13 * 100

    # Tendência básica (threshold de 0.03% para pontuar)
    if ema5 > ema13:
        tendencia = "CALL"
        score = 1 if diff_percent > 0.03 else 0
    else:
        tendencia = "PUT"
        score = 1 if diff_percent > 0.03 else 0

    rsi = calcular_rsi(precos, 7)
    macd = calcular_macd(precos)
    superior, media, inferior = calcular_bollinger(precos)
    preco_atual = precos[-1]

    if tendencia == "CALL" and rsi < 55:
        score += 1
    elif tendencia == "PUT" and rsi > 45:
        score += 1
    elif tendencia == "CALL" and rsi < 65:
        score += 0.5
    elif tendencia == "PUT" and rsi > 35:
        score += 0.5

    if macd is not None:
        if tendencia == "CALL" and macd > 0:
            score += 0.5
        elif tendencia == "PUT" and macd < 0:
            score += 0.5

    if superior is not None:
        if tendencia == "CALL" and preco_atual <= inferior * 1.001:
            score += 0.5
        elif tendencia == "PUT" and preco_atual >= superior * 0.999:
            score += 0.5

    if diff_percent > 0.15:
        score += 0.5
    elif diff_percent > 0.08:
        score += 0.25

    macd_str = f"{macd:.5f}" if macd is not None else "N/A"
    just = (f"EMA5:{ema5:.5f} EMA13:{ema13:.5f} | RSI:{rsi:.1f} | "
            f"MACD:{macd_str} | Dif:{diff_percent:.2f}% | Score:{score:.1f}")

    if score >= app.config['SCORE_MINIMO']:
        return tendencia, score, just
    return None, score, just

def obter_melhor_sinal():
    melhores = []
    for par in ATIVOS:
        sinal, score, just = analisar_ativo(par)
        if sinal is not None:
            melhores.append((par, sinal, score, just))
    if not melhores:
        return {
            "ativo": None,
            "direcao": None,
            "score": 0,
            "analise": "Nenhum sinal forte no momento",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "tempo_exp": None
        }
    melhores.sort(key=lambda x: x[2], reverse=True)
    ativo, sinal, score, just = melhores[0]
    tempo_exp = 1 if score >= 3.5 else 2 if score >= 2.5 else 3
    return {
        "ativo": ativo,
        "direcao": sinal,
        "score": score,
        "analise": just,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "tempo_exp": tempo_exp
    }

# ---------- Rotas ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = models.get_user_by_username(username)
        if user and user.check_password(password):
            if not user.is_active:
                flash('Conta desactivada. Contacte o administrador.')
            else:
                login_user(user)
                return redirect(url_for('index'))
        else:
            flash('Credenciais inválidas')
    return render_template('login.html')

@app.route('/afiliado')
def afiliado():
    return render_template('afiliado.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if len(password) < 4:
            flash('A palavra-passe deve ter pelo menos 4 caracteres')
        else:
            user = models.create_user(username, password)
            if user:
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('Nome de utilizador já existe')
    return render_template('register.html')

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/sinal')
@login_required
@limiter.limit("1 per minute")  # 🔒 rate limit
def api_sinal():
    return jsonify(obter_melhor_sinal())

@app.route('/api/status')
@login_required
def api_status():
    # Simulação removida: agora retorna estado real (todos os ativos com dados disponíveis)
    # Como obtemos sob demanda, todos têm 30 velas se a API funcionar
    # Mas mantemos compatibilidade: simulamos 'pronto' para não quebrar o frontend.
    # Numa versão mais realista, poderias verificar cache ou última coleta.
    return jsonify({par: 30 for par in ATIVOS})

@app.route('/api/config', methods=['POST'])
@login_required
def config():
    data = request.get_json()
    if 'score_minimo' in data:
        try:
            novo = float(data['score_minimo'])
            with score_lock:
                app.config['SCORE_MINIMO'] = novo
            return jsonify({"status": "ok", "score_minimo": novo})
        except (ValueError, TypeError):
            return jsonify({"status": "erro", "msg": "Valor inválido"}), 400
    return jsonify({"status": "erro"}), 400

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return "Acesso negado", 403
    users = models.list_users()
    return render_template('admin.html', users=users)

@app.route('/admin/toggle/<int:user_id>', methods=['POST'])
@login_required
def admin_toggle(user_id):
    if not current_user.is_admin:
        return "Acesso negado", 403
    user = models.get_user_by_id(user_id)
    if user:
        new_state = not user.is_active
        models.set_user_active(user_id, new_state)
    return redirect(url_for('admin'))

@login_manager.user_loader
def load_user(user_id):
    try:
        return models.get_user_by_id(int(user_id))
    except (ValueError, TypeError):
        return None

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
