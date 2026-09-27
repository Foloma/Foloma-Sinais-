import os
import logging
import importlib
import pkgutil
import time
import threading
from datetime import datetime
import requests

import strategies
from strategies.base import Strategy


class StrategyEngine:
    """
    Motor de estratégias com cache pré-aquecida em background.

    Notas:
    - Cache em memória por processo. Se correres vários workers gunicorn,
      cada um terá a sua própria cache e a soma das chamadas à API
      multiplica-se pelo nº de workers. Nesse caso: correr 1 worker, ou
      usar Redis como backend de cache partilhada.
    - Todos os acessos a _cache/_cache_time/_last_request_time passam pelo
      self._lock. O sleep para respeitar o rate limit acontece FORA do lock.
    - O endpoint time_series do TwelveData devolve OHLC completo; guardamos
      'closes' (compatibilidade) e 'ohlc' (para padrões de vela).
    """

    CACHE_TTL = 120          # segundos que um valor de cache é válido
    REQUEST_INTERVAL = 7.5   # segundos mínimos entre chamadas à API (8/min)
    WARM_INTERVAL = 60       # segundos entre ciclos de pré-aquecimento
    OUTPUTSIZE_1MIN = 60     # >= 50 para suportar EMA50 (Momentum)
    OUTPUTSIZE_5MIN = 60

    def __init__(self):
        self.ATIVOS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD"]
        self.strategies = []

        self._lock = threading.Lock()
        self._cache = {}          # key -> {"closes": [...], "ohlc": [...]}
        self._cache_time = {}     # key -> timestamp de escrita
        self._last_request_time = 0.0
        self._stop_warm = threading.Event()

        self.load_strategies()
        logging.info(f"Motor carregado com {len(self.strategies)} estratégias.")

        self._warm_thread = threading.Thread(target=self._warm_loop, daemon=True, name="engine-warm")
        self._warm_thread.start()

    # ------------------------------------------------------------------
    # Carregamento
    # ------------------------------------------------------------------
    def load_strategies(self):
        for module_info in pkgutil.iter_modules(strategies.__path__):
            module_name = module_info.name
            if module_name in ['base', '__init__']:
                continue
            try:
                module = importlib.import_module(f"strategies.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, Strategy) and
                            attr is not Strategy):
                        self.strategies.append(attr())
                        logging.info(f"Estratégia carregada: {attr.__name__}")
            except Exception as e:
                logging.error(f"Erro ao carregar estratégia {module_name}: {e}")

    # ------------------------------------------------------------------
    # Fetch de dados com OHLC + cache + lock
    # ------------------------------------------------------------------
    def _fetch_data(self, symbol, interval="1min", outputsize=60):
        """
        Devolve {"closes": [float, ...], "ohlc": [{"open","high","low","close"}, ...]}
        ou None em caso de erro/dados insuficientes.
        """
        api_key = os.environ.get('TWELVE_DATA_API_KEY', '')
        if not api_key:
            logging.error("TWELVE_DATA_API_KEY não configurada.")
            return None

        key = f"{symbol}_{interval}_{outputsize}"
        now = time.time()

        # Cache hit?
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and (now - self._cache_time.get(key, 0)) < self.CACHE_TTL:
                return cached

        # Reservar próximo slot de chamada à API (garante espaçamento global)
        with self._lock:
            next_allowed = self._last_request_time + self.REQUEST_INTERVAL
            if now < next_allowed:
                wait = next_allowed - now
            else:
                wait = 0.0
            self._last_request_time = max(now, next_allowed)

        if wait > 0:
            time.sleep(wait)

        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval={interval}"
            f"&outputsize={outputsize}&apikey={api_key}"
        )
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                logging.error(f"TwelveData 429 (rate limit) para {symbol} {interval}")
                return None
            resp.raise_for_status()
            dados = resp.json()

            if "values" not in dados:
                logging.warning(f"Sem 'values' para {symbol} {interval}: {dados.get('message', 'sem mensagem')}")
                return None

            closes = []
            ohlc = []
            for v in reversed(dados["values"]):
                try:
                    o = float(v["open"])
                    h = float(v["high"])
                    l = float(v["low"])
                    c = float(v["close"])
                except (KeyError, ValueError):
                    continue
                closes.append(c)
                ohlc.append({"open": o, "high": h, "low": l, "close": c})

            if len(closes) < outputsize:
                logging.warning(f"Dados insuficientes {symbol} {interval}: {len(closes)}/{outputsize}")
                return None

            result = {"closes": closes, "ohlc": ohlc}
            with self._lock:
                self._cache[key] = result
                self._cache_time[key] = time.time()
            return result

        except requests.exceptions.Timeout:
            logging.error(f"Timeout TwelveData {symbol} {interval}")
            return None
        except requests.exceptions.HTTPError as e:
            logging.error(f"Erro HTTP {symbol} {interval}: {e}")
            return None
        except Exception as e:
            logging.error(f"Erro ao buscar dados {symbol} {interval}: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Warm loop em background (evita sleeps durante requests)
    # ------------------------------------------------------------------
    def _warm_loop(self):
        while not self._stop_warm.is_set():
            try:
                for symbol in self.ATIVOS:
                    for interval, size in (("1min", self.OUTPUTSIZE_1MIN),
                                           ("5min", self.OUTPUTSIZE_5MIN)):
                        # Força refresh (cache expirou naturalmente ou ainda não existe)
                        self._fetch_data(symbol, interval, size)
            except Exception as e:
                logging.error(f"Warm loop erro: {e}", exc_info=True)
            self._stop_warm.wait(self.WARM_INTERVAL)

    # ------------------------------------------------------------------
    # Decisão
    # ------------------------------------------------------------------
    def get_best_signal(self, score_minimo=1.0):
        dados_1min = {}
        dados_5min = {}
        for symbol in self.ATIVOS:
            dados_1min[symbol] = self._fetch_data(symbol, "1min", self.OUTPUTSIZE_1MIN)
            dados_5min[symbol] = self._fetch_data(symbol, "5min", self.OUTPUTSIZE_5MIN)

        all_results = []
        for symbol in self.ATIVOS:
            d1 = dados_1min.get(symbol)
            d5 = dados_5min.get(symbol)
            if d1 is None or d5 is None:
                continue
            for strategy in self.strategies:
                try:
                    result = strategy.analyze(symbol, d1, d5)
                    if result and result.get("signal") is not None:
                        all_results.append(result)
                except Exception as e:
                    logging.error(
                        f"Erro na estratégia {strategy.__class__.__name__} "
                        f"para {symbol}: {e}", exc_info=True
                    )

        # [1.7] Aplicar threshold aqui — antes era ignorado
        all_results = [r for r in all_results if r.get("score", 0) >= score_minimo]

        if not all_results:
            return {
                "ativo": None, "direcao": None, "score": 0, "confianca": 0,
                "estrategia": None,
                "analise": "Nenhum sinal forte no momento",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "tempo_exp": None,
                "indicators": {},
                "detalhes": []
            }

        return self._decide(all_results)

    def _decide(self, results):
        calls = [r for r in results if r["signal"] == "CALL"]
        puts  = [r for r in results if r["signal"] == "PUT"]

        if not calls and not puts:
            return {
                "ativo": None, "direcao": None, "score": 0, "confianca": 0,
                "estrategia": "Nenhum",
                "analise": "Nenhuma estratégia gerou sinal.",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "tempo_exp": None,
                "indicators": {},
                "detalhes": results
            }

        # [1.3] Desempate por score (escala comum após normalização nas
        #      estratégias). A confidence continua a ser devolvida ao UI,
        #      mas NÃO é usada para comparar entre estratégias.
        if not puts:
            best = max(calls, key=lambda x: x.get("score", 0))
        elif not calls:
            best = max(puts, key=lambda x: x.get("score", 0))
        else:
            best_call = max(calls, key=lambda x: x.get("score", 0))
            best_put  = max(puts,  key=lambda x: x.get("score", 0))
            best = best_call if best_call.get("score", 0) >= best_put.get("score", 0) else best_put

        tempo_exp = best.get("tempo_exp", 3) or 3
        if tempo_exp < 3:
            tempo_exp = 3

        return {
            "ativo": best.get("symbol"),
            "direcao": best["signal"],
            "score": best.get("score", 0),
            "confianca": best.get("confidence", 0),
            "estrategia": best.get("strategy"),
            "analise": best.get("reason", ""),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "tempo_exp": tempo_exp,
            # [Falta 3] propagar indicators do VENCEDOR, não de qualquer estratégia
            "indicators": best.get("indicators", {}),
            "detalhes": results
        }
