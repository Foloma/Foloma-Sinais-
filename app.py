from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import requests
import secrets
import time
from datetime import datetime
import models

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return models.get_user_by_id(int(user_id))

# ==============================================
# CONFIGURAÇÕES (FOREX)
# ==============================================
ATIVOS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD"]
SCORE_MINIMO = 1.0          # Reduzido para 1.0 para gerar mais sinais
# ==============================================

def obter_preco(par):
    """Obtém o preço atual do par forex usando exchangerate.host"""
    try:
        if par == "EURUSD":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD"
            resp = requests.get(url, timeout=10)   # timeout aumentado
            if resp.status_code == 200:
                return float(resp.json()['rates']['USD'])
        elif par == "GBPUSD":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD,GBP"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                rates = resp.json()['rates']
                return rates['USD'] / rates['GBP']
        elif par == "USDJPY":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD,JPY"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                rates = resp.json()['rates']
                return rates['JPY'] / rates['USD']
        elif par == "USDCAD":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD,CAD"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                rates = resp.json()['rates']
                return rates['CAD'] / rates['USD']
        elif par == "AUDUSD":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD,AUD"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                rates = resp.json()['rates']
                return rates['USD'] / rates['AUD']
        elif par == "NZDUSD":
            url = "https://api.exchangerate.host/latest?base=EUR&symbols=USD,NZD"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                rates = resp.json()['rates']
                return rates['USD'] / rates['NZD']
    except Exception as e:
        print(f"Erro ao obter {par}: {e}")
    return None

def obter_precos_sequencia(par, n=30):
    """Obtém n preços consecutivos (simula candles de 1 minuto com pequeno atraso)"""
    precos = []
    for _ in range(n):
        p = obter_preco(par)
        if p is None:
            return None
        precos.append(p)
        time.sleep(0.2)   # pausa curta para não sobrecarregar a API
    return precos

def calcular_ema(precos, periodo):
    if len(precos) < periodo:
        return None
    mult = 2 / (periodo + 1)
    ema = precos[0]
    for p in precos[1:periodo]:
        ema = (p - ema) * mult + ema
    return ema

def calcular_rsi(precos, periodo=7):
    if len(precos) < periodo + 1:
        return 50
    ganhos, perdas = [], []
    for i in range(1, periodo+1):
        diff = precos[-i] - precos[-i-1]
        if diff > 0:
            ganhos.append(diff)
            perdas.append(0)
        else:
            ganhos.append(0)
            perdas.append(abs(diff))
    avg_gain = sum(ganhos) / periodo
    avg_loss = sum(perdas) / periodo
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))

def calcular_macd(precos):
    if len(precos) < 26:
        return None
    ema12 = calcular_ema(precos, 12)
    ema26 = calcular_ema(precos, 26)
    if ema12 is None or ema26 is None:
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
    """Versão mais sensível para gerar sinais com scores mais altos"""
    precos = obter_precos_sequencia(par, 30)
    if precos is None or len(precos) < 30:
        print(f"ERRO: não obteve preços para {par}")
        return None, 0, "Erro ao obter preços"

    print(f"{par}: primeiro preço={precos[0]:.5f}, último={precos[-1]:.5f}")

    ema5 = calcular_ema(precos, 5)
    ema13 = calcular_ema(precos, 13)
    if None in (ema5, ema13):
        print(f"ERRO EMAs {par}: ema5={ema5}, ema13={ema13}")
        return None, 0, "Erro nas EMAs"

    rsi = calcular_rsi(precos, 7)
    macd = calcular_macd(precos)
    upper, middle, lower = calcular_bollinger(precos)
    preco_atual = precos[-1]

    score = 0
    if ema5 > ema13:
        tendencia = "CALL"
        score += 1
    else:
        tendencia = "PUT"
        score += 1

    # Limiares mais baixos para gerar sinais
    if tendencia == "CALL" and rsi < 65:
        score += 1
    elif tendencia == "PUT" and rsi > 35:
        score += 1
    elif tendencia == "CALL" and rsi < 75:
        score += 0.5
    elif tendencia == "PUT" and rsi > 25:
        score += 0.5

    if macd is not None:
        if tendencia == "CALL" and macd > -0.0001:
            score += 0.5
        elif tendencia == "PUT" and macd < 0.0001:
            score += 0.5

    if upper is not None:
        if tendencia == "CALL" and preco_atual <= lower * 1.01:
            score += 0.5
        elif tendencia == "PUT" and preco_atual >= upper * 0.99:
            score += 0.5

    diff_percent = abs(ema5 - ema13) / ema13 * 100
    if diff_percent > 0.05:
        score += 0.5
    elif diff_percent > 0.02:
        score += 0.25

    macd_str = f"{macd:.5f}" if macd is not None else "N/A"
    just = (f"EMA5:{ema5:.5f} EMA13:{ema13:.5f} | RSI:{rsi:.1f} | "
            f"MACD:{macd_str} | Dif:{diff_percent:.2f}% | Score:{score:.1f}")

    print(f"{par} -> Score: {score:.1f}, Tendência: {tendencia}")

    if score >= SCORE_MINIMO:
        return tendencia, score, just
    else:
        # Se o score for baixo, mesmo assim retorna sinal de teste (para debug)
        # Comente as 3 linhas abaixo após confirmar que os sinais aparecem
        if score > 0.5:
            return tendencia, 1.0, just + " (Sinal de teste)"
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

# ==============================================
# ADMIN E ROTAS
# ==============================================
def create_admin_if_not_exists():
    admin = models.get_user_by_username('admin')
    if not admin:
        models.create_user('admin', 'admin123', is_admin=True)
        print("Administrador criado: admin / admin123")

create_admin_if_not_exists()

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
def api_sinal():
    return jsonify(obter_melhor_sinal())

@app.route('/api/status')
@login_required
def api_status():
    # Retorna sempre 30 para todos os ativos (simula que estão prontos)
    return jsonify({par: 30 for par in ATIVOS})

@app.route('/api/config', methods=['POST'])
@login_required
def config():
    global SCORE_MINIMO
    data = request.get_json()
    if 'score_minimo' in data:
        try:
            SCORE_MINIMO = float(data['score_minimo'])
            return jsonify({"status": "ok", "score_minimo": SCORE_MINIMO})
        except:
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

@app.route('/admin/toggle/<int:user_id>')
@login_required
def admin_toggle(user_id):
    if not current_user.is_admin:
        return "Acesso negado", 403
    user = models.get_user_by_id(user_id)
    if user:
        new_state = not user.is_active
        models.set_user_active(user_id, new_state)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
