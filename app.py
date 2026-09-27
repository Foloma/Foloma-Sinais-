import os
import re
import secrets
import logging

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import models
from engine import StrategyEngine

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# [1.9] SECRET_KEY obrigatória em produção
_flask_env = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development'))
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if _flask_env == 'production':
        raise RuntimeError("SECRET_KEY obrigatória em produção. Define a env var.")
    _secret = os.urandom(24).hex()
    logging.warning("SECRET_KEY não definida — usando valor efémero (apenas para dev).")
app.secret_key = _secret

# [Falta 8] Respeitar X-Forwarded-* quando atrás de proxy (Render/Nginx)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# [1.10] CSRF global
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour"]
)

# ---------- Configurações ----------
SCORE_MINIMO = float(os.environ.get('SCORE_MINIMO', '1.0'))
app.config['SCORE_MINIMO'] = SCORE_MINIMO

AFFILIATE_LINK = os.environ.get('AFFILIATE_LINK', 'https://pocket-friends.co/r/br4kbim2pe')
# Defesa em profundidade: garantir que o link é http(s)
if not AFFILIATE_LINK.startswith(('https://', 'http://')):
    raise ValueError("AFFILIATE_LINK inválido: deve começar com https:// ou http://")
app.config['AFFILIATE_LINK'] = AFFILIATE_LINK

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
        # [1.8] NÃO gravar a senha no log
        if os.environ.get('ADMIN_PASS'):
            logging.info("Admin 'admin' criado com ADMIN_PASS definida por env.")
        else:
            logging.warning(
                "Admin 'admin' criado com password ALEATÓRIA. "
                "Define ADMIN_PASS nas env vars para controlar."
            )
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

        # [Falta 5] dummy hash para evitar timing attack
        if not user:
            check_password_hash(
                'pbkdf2:sha256:600000$dummy$' + '0' * 64, password
            )
            flash('Credenciais inválidas ou conta desactivada.', 'error')
            return render_template('login.html')

        if not user.check_password(password) or not user.is_active:
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
@limiter.limit("3 per hour")  # [1.11b]
def register():
    if request.cookies.get('afiliado_confirmado') != '1':
        flash('Precisa de se registar na Pocket Option através do nosso link de afiliado primeiro.', 'error')
        return redirect(url_for('afiliado'))

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm  = request.form.get('confirm_password', '')

        # [1.11c] confirm_password validado no servidor
        if password != confirm:
            flash('As palavras-passe não coincidem.', 'error')
            return render_template('register.html')

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
            resp.set_cookie('afiliado_confirmado', '', expires=0, path='/')
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


# ==============================================
# API
# ==============================================
# NOTA CSRF: as rotas abaixo são JSON-only e o Flask rejeita
# Content-Type diferente de application/json no get_json(), pelo que
# não são exploráveis via form CSRF simples. Exemptamos só elas.
@app.route('/api/sinal')
@login_required
@limiter.limit("1 per minute")
def api_sinal():
    resultado = engine.get_best_signal(app.config['SCORE_MINIMO'])
    return jsonify(resultado)


@app.route('/api/status')
@login_required
@limiter.limit("300 per hour")
def api_status():
    return jsonify({symbol: 30 for symbol in engine.ATIVOS})


@app.route('/api/config', methods=['POST'])
@login_required
@csrf.exempt
def config():
    if not current_user.is_admin:  # [1.6]
        return jsonify({"status": "erro", "msg": "Acesso negado"}), 403

    data = request.get_json(silent=True)
    if not data or 'score_minimo' not in data:
        return jsonify({"status": "erro", "msg": "Dados ausentes"}), 400
    try:
        novo = float(data['score_minimo'])
    except (ValueError, TypeError):
        return jsonify({"status": "erro", "msg": "Valor inválido"}), 400

    # [S5] validação de range
    if not (0.5 <= novo <= 5.0):
        return jsonify({"status": "erro", "msg": "Score deve estar entre 0.5 e 5.0"}), 400

    app.config['SCORE_MINIMO'] = novo
    return jsonify({"status": "ok", "score_minimo": novo})


@app.route('/api/registar_trade', methods=['POST'])
@login_required
@csrf.exempt
def registar_trade():
    data = request.get_json(silent=True)
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
@csrf.exempt
def resultado_trade():
    data = request.get_json(silent=True)
    if not data or 'resultado' not in data:
        return jsonify({"status": "erro", "msg": "Resultado ausente"}), 400
    resultado = data['resultado']
    if resultado not in ('Ganhou', 'Perdeu'):
        return jsonify({"status": "erro", "msg": "Resultado inválido"}), 400

    trade_id = data.get('trade_id')
    if trade_id is not None:
        try:
            trade_id = int(trade_id)
        except (ValueError, TypeError):
            return jsonify({"status": "erro", "msg": "trade_id inválido"}), 400
        ok = models.update_trade_result(trade_id, resultado, user_id=current_user.id)
        if not ok:
            return jsonify({"status": "erro", "msg": "Trade não encontrado"}), 404
        return jsonify({"status": "ok"})

    # Fallback (compatibilidade com o frontend atual)
    trade = models.get_last_unresolved_trade(current_user.id)
    if not trade:
        return jsonify({"status": "erro", "msg": "Nenhum trade pendente encontrado"}), 404
    models.update_trade_result(trade['id'], resultado, user_id=current_user.id)
    return jsonify({"status": "ok"})


@app.route('/api/estatisticas')
@login_required
def api_estatisticas():
    stats = models.get_performance_stats(current_user.id)
    return jsonify(stats)


# ==============================================
# PÁGINAS
# ==============================================
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
