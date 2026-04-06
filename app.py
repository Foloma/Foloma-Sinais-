from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import requests
import secrets
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
# CONFIGURAÇÕES DOS SINAIS (CoinCap)
# ==============================================
# Mapeamento: símbolo CoinCap -> nome amigável (Pocket Option)
ATIVOS = {
    "bitcoin": "BTCUSD",
    "ethereum": "ETHUSD",
    "binance-coin": "BNBUSD",
    "cardano": "ADAUSD",
    "solana": "SOLUSD",
    "litecoin": "LTCUSD",
    "chainlink": "LINKUSD",
    "polkadot": "DOTUSD",
    "tron": "TRXUSD",
    "avalanche": "AVAXUSD"
}
JANELA_TICKS = 30
SCORE_MINIMO = 1.5
# ==============================================

def obter_precos_coincap(simbolo_coincap, limite=30):
    """
    Obtém os preços históricos (candles de 1 minuto) da CoinCap.
    Nota: A CoinCap não fornece candles históricos gratuitamente.
    Para contornar, obtemos o preço atual e simulamos uma pequena variação?
    Não é ideal. Melhor usar o endpoint /assets para preço atual e acumular ticks.
    Vamos usar uma abordagem de ticks: cada chamada obtém o preço atual e guardamos numa lista.
    Mas como a API é chamada apenas quando o utilizador clica, precisamos de um acumulador persistente.
    Solução mais simples: usar o preço atual e gerar uma pequena variação aleatória para formar a janela.
    Isso é aceitável para demonstração, mas para produção real, uma fonte de candles é melhor.
    Como o CoinCap não fornece candles, vamos usar a **Binance** novamente, mas com um truque: 
    usar o domínio 'https://api1.binance.com' que costuma funcionar melhor.
    Vou optar por uma solução híbrida: usar a Binance com um domínio que geralmente não é bloqueado.
    """
    # Domínios alternativos da Binance (tentar vários)
    dominios = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com"
    ]
    for dominio in dominios:
        try:
            url = f"{dominio}/api/v3/klines?symbol={simbolo_coincap.upper()}USDT&interval=1m&limit={limite}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                dados = resp.json()
                precos = [float(candle[4]) for candle in dados]
                return precos
        except:
            continue
    # Se todos falharem, retorna None
    return None

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

def analisar_ativo(simbolo, nome_pocket, precos):
    if len(precos) < JANELA_TICKS:
        return None, 0, f"Acumulando: {len(precos)}/{JANELA_TICKS} candles"

    ema5 = calcular_ema(precos, 5)
    ema13 = calcular_ema(precos, 13)
    if None in (ema5, ema13):
        return None, 0, "Erro EMAs"

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

    if upper is not None:
        if tendencia == "CALL" and preco_atual <= lower * 1.001:
            score += 0.5
        elif tendencia == "PUT" and preco_atual >= upper * 0.999:
            score += 0.5

    diff_percent = abs(ema5 - ema13) / ema13 * 100
    if diff_percent > 0.15:
        score += 0.5
    elif diff_percent > 0.08:
        score += 0.25

    macd_str = f"{macd:.2f}" if macd is not None else "N/A"
    just = (f"EMA5:{ema5:.2f} EMA13:{ema13:.2f} | RSI:{rsi:.1f} | "
            f"MACD:{macd_str} | Dif:{diff_percent:.2f}%")

    if score >= SCORE_MINIMO:
        return tendencia, score, just
    else:
        return None, score, just

def obter_melhor_sinal():
    melhores = []
    for simbolo, nome_pocket in ATIVOS.items():
        # Mapeia o símbolo da CoinCap para o símbolo da Binance (com USDT)
        # Ex: bitcoin -> BTCUSDT
        simbolo_binance = simbolo.upper().replace("-", "") + "USDT"
        precos = obter_precos_coincap(simbolo_binance, JANELA_TICKS)
        if precos is None:
            continue
        sinal, score, just = analisar_ativo(simbolo_binance, nome_pocket, precos)
        if sinal is not None:
            melhores.append((nome_pocket, sinal, score, just))
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

    if score >= 3.5:
        tempo_exp = 1
    elif score >= 2.5:
        tempo_exp = 2
    else:
        tempo_exp = 3

    return {
        "ativo": ativo,
        "direcao": sinal,
        "score": score,
        "analise": just,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "tempo_exp": tempo_exp
    }

# ==============================================
# CRIA ADMIN SE NÃO EXISTIR
# ==============================================
def create_admin_if_not_exists():
    admin = models.get_user_by_username('admin')
    if not admin:
        models.create_user('admin', 'admin123', is_admin=True)
        print("Administrador criado: admin / admin123")

create_admin_if_not_exists()

# ==============================================
# ROTAS PÚBLICAS
# ==============================================
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

# ==============================================
# ROTAS PROTEGIDAS
# ==============================================
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
    status = {}
    for simbolo, nome_pocket in ATIVOS.items():
        simbolo_binance = simbolo.upper().replace("-", "") + "USDT"
        precos = obter_precos_coincap(simbolo_binance, JANELA_TICKS)
        status[nome_pocket] = len(precos) if precos else 0
    return jsonify(status)

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
