import os
import re
import secrets
import logging
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import models
from engine import StrategyEngine

# ---------- Configuração de logging ----------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24).hex()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour"]
)

# ---------- Configurações ----------
# Score mínimo reduzido para 1.0 (antes 1.5)
SCORE_MINIMO = float(os.environ.get('SCORE_MINIMO', '1.0'))
app.config['SCORE_MINIMO'] = SCORE_MINIMO

AFFILIATE_LINK = os.environ.get('AFFILIATE_LINK', 'https://pocket-friends.co/r/br4kbim2pe')
app.config['AFFILIATE_LINK'] = AFFILIATE_LINK

# Inicializa o motor de estratégias
engine = StrategyEngine()

# ---------- Banco de dados ----------
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
models.set_db_path(db_path)
models.init_db()

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

create_admin_if_not_exists()

@login_manager.user_loader
def load_user(user_id):
    try:
        return models.get_user_by_id(int(user_id))
    except (ValueError, TypeError):
        return None

# ==============================================
# ROTAS
# ==============================================
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user = models.get_user_by_username(username)

        if not user or not user.check_password(password) or not user.is_active:
            flash('Credenciais inválidas ou conta desactivada.', 'error')
            return render_template('login.html')

        login_user(user)
        flash('Login efectuado com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/afiliado')
def afiliado():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('afiliado.html', affiliate_link=app.config['AFFILIATE_LINK'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if not request.cookies.get('afiliado_confirmado'):
        flash('Precisa de se registar na Pocket Option através do nosso link de afiliado primeiro.', 'error')
        return redirect(url_for('afiliado'))

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if not re.match(r'^[A-Za-z0-9]{3,20}$', username):
            flash('Nome de utilizador inválido (apenas letras e números, 3 a 20 caracteres).', 'error')
            return render_template('register.html')
        if len(password) < 8:
            flash('A palavra-passe deve ter pelo menos 8 caracteres.', 'error')
            return render_template('register.html')

        user = models.create_user(username, password)
        if user:
            login_user(user)
            resp = make_response(redirect(url_for('index')))
            resp.set_cookie('afiliado_confirmado', '', expires=0)
            flash('Conta criada com sucesso!', 'success')
            return resp
        else:
            flash('Nome de utilizador já existe', 'error')

    return render_template('register.html')

@app.route('/')
@login_required
def index():
    trades = models.get_user_trades(current_user.id, limit=50)
    return render_template('index.html', trades=trades)

# ---------- API ----------
@app.route('/api/sinal')
@login_required
@limiter.limit("1 per minute")
def api_sinal():
    resultado = engine.get_best_signal()
    return jsonify(resultado)

@app.route('/api/status')
@login_required
@limiter.limit("300 per hour")
def api_status():
    return jsonify({symbol: 30 for symbol in engine.ATIVOS})

@app.route('/api/config', methods=['POST'])
@login_required
def config():
    data = request.get_json()
    if 'score_minimo' in data:
        try:
            novo = float(data['score_minimo'])
            app.config['SCORE_MINIMO'] = novo
            return jsonify({"status": "ok", "score_minimo": novo})
        except (ValueError, TypeError):
            return jsonify({"status": "erro", "msg": "Valor inválido"}), 400
    return jsonify({"status": "erro"}), 400

@app.route('/api/registar_trade', methods=['POST'])
@login_required
def registar_trade():
    data = request.get_json()
    if not data:
        return jsonify({"status": "erro", "msg": "Dados ausentes"}), 400
    ativo = data.get('ativo')
    direcao = data.get('direcao')
    score = data.get('score')
    expiracao = data.get('expiracao')
    estrategia = data.get('estrategia', 'Desconhecida')
    confianca = data.get('confianca', 0)
    if not all([ativo, direcao, score is not None, expiracao is not None]):
        return jsonify({"status": "erro", "msg": "Campos obrigatórios em falta"}), 400
    try:
        trade_id = models.add_trade(
            current_user.id, ativo, direcao, float(score), int(expiracao),
            estrategia=estrategia, confianca=float(confianca)
        )
        return jsonify({"status": "ok", "trade_id": trade_id})
    except Exception as e:
        logging.error(f"Erro ao registar trade: {e}", exc_info=True)
        return jsonify({"status": "erro", "msg": "Erro interno"}), 500

@app.route('/api/resultado_trade', methods=['POST'])
@login_required
def resultado_trade():
    data = request.get_json()
    if not data or 'resultado' not in data:
        return jsonify({"status": "erro", "msg": "Resultado ausente"}), 400
    resultado = data['resultado']
    if resultado not in ('Ganhou', 'Perdeu'):
        return jsonify({"status": "erro", "msg": "Resultado inválido"}), 400
    trade = models.get_last_unresolved_trade(current_user.id)
    if not trade:
        return jsonify({"status": "erro", "msg": "Nenhum trade pendente encontrado"}), 404
    models.update_trade_result(trade['id'], resultado)
    return jsonify({"status": "ok"})

@app.route('/api/estatisticas')
@login_required
def api_estatisticas():
    stats = models.get_performance_stats(current_user.id)
    return jsonify(stats)

# ---------- PÁGINAS ----------
@app.route('/estatisticas')
@login_required
def estatisticas():
    stats = models.get_performance_stats(current_user.id)
    return render_template('estatisticas.html', stats=stats)

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
    if user_id == current_user.id:
        flash('Não pode alterar o estado da sua própria conta.', 'error')
        return redirect(url_for('admin'))
    user = models.get_user_by_id(user_id)
    if user:
        new_state = not user.is_active
        models.set_user_active(user_id, new_state)
        estado = "activo" if new_state else "desactivado"
        flash(f'Utilizador {user.username} {estado} com sucesso.', 'success')
    else:
        flash('Utilizador não encontrado.', 'error')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
