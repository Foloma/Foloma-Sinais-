import os
import logging
import importlib
import pkgutil
import time
from datetime import datetime
import requests

import strategies
from strategies.base import Strategy

class StrategyEngine:
    # Cache partilhado entre instâncias (em memória)
    _cache = {}
    _cache_time = {}
    _last_request_time = 0  # para controlar taxa de chamadas

    def __init__(self):
        self.ATIVOS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD"]
        self.strategies = []
        self.load_strategies()
        logging.info(f"Motor carregado com {len(self.strategies)} estratégias.")

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
                        strategy_instance = attr()
                        self.strategies.append(strategy_instance)
                        logging.info(f"Estratégia carregada: {strategy_instance.__class__.__name__}")
            except Exception as e:
                logging.error(f"Erro ao carregar estratégia {module_name}: {e}")

    def _fetch_data(self, symbol, interval="1min", outputsize=30):
        api_key = os.environ.get('TWELVE_DATA_API_KEY', '')
        if not api_key:
            logging.error("TWELVE_DATA_API_KEY não configurada.")
            return None

        key = f"{symbol}_{interval}_{outputsize}"
        now = time.time()
        
        # Cache aumentado para 120 segundos (antes 30/60)
        if key in self._cache and (now - self._cache_time.get(key, 0)) < 120:
            logging.info(f"Usando cache para {symbol} {interval}")
            return self._cache[key]

        # Controlo de taxa: respeita 8 chamadas/minuto (~7.5s entre chamadas)
        # Para garantir, esperamos pelo menos 2 segundos entre chamadas
        elapsed = now - self._last_request_time
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)
        
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={api_key}"
        try:
            self._last_request_time = time.time()
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            dados = resp.json()
            if "values" in dados:
                precos = [float(v["close"]) for v in reversed(dados["values"])]
                if len(precos) >= outputsize:
                    self._cache[key] = precos
                    self._cache_time[key] = time.time()
                    return precos
            return None
        except Exception as e:
            logging.error(f"Erro ao buscar dados para {symbol} ({interval}): {e}")
            return None

    def get_best_signal(self):
        dados_1min = {}
        dados_5min = {}
        for symbol in self.ATIVOS:
            dados_1min[symbol] = self._fetch_data(symbol, "1min", 30)
            dados_5min[symbol] = self._fetch_data(symbol, "5min", 30)

        all_results = []
        for symbol in self.ATIVOS:
            data_1min = dados_1min.get(symbol)
            data_5min = dados_5min.get(symbol)
            if data_1min is None or data_5min is None:
                continue
            for strategy in self.strategies:
                try:
                    result = strategy.analyze(symbol, data_1min, data_5min)
                    if result and result.get("signal") is not None:
                        all_results.append(result)
                except Exception as e:
                    logging.error(f"Erro na estratégia {strategy.__class__.__name__} para {symbol}: {e}")

        if not all_results:
            return {
                "ativo": None,
                "direcao": None,
                "score": 0,
                "confianca": 0,
                "estrategia": None,
                "analise": "Nenhum sinal forte no momento",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "tempo_exp": None,
                "detalhes": []
            }

        decision = self._decide(all_results)
        return decision

    def _decide(self, results):
        """
        Versão melhorada com decisão menos restritiva.
        - Se diferença de confiança >= 10%, escolhe a de maior confiança.
        - Se diferença de score >= 1.0, escolhe a de maior score.
        - Caso contrário, força decisão pela de maior score (ou maior confiança).
        """
        calls = [r for r in results if r["signal"] == "CALL"]
        puts = [r for r in results if r["signal"] == "PUT"]

        if not calls and not puts:
            return {
                "ativo": None,
                "direcao": None,
                "score": 0,
                "confianca": 0,
                "estrategia": "Nenhum",
                "analise": "Nenhuma estratégia gerou sinal.",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "tempo_exp": None,
                "detalhes": results
            }

        if not calls:
            best = max(puts, key=lambda x: x["confidence"])
        elif not puts:
            best = max(calls, key=lambda x: x["confidence"])
        else:
            best_call = max(calls, key=lambda x: x["confidence"])
            best_put = max(puts, key=lambda x: x["confidence"])
            
            diff_conf = abs(best_call["confidence"] - best_put["confidence"])
            diff_score = abs(best_call.get("score", 0) - best_put.get("score", 0))
            
            if diff_conf >= 10:
                best = best_call if best_call["confidence"] > best_put["confidence"] else best_put
            elif diff_score >= 1.0:
                best = best_call if best_call.get("score", 0) > best_put.get("score", 0) else best_put
            else:
                if best_call.get("score", 0) > best_put.get("score", 0):
                    best = best_call
                elif best_call.get("score", 0) < best_put.get("score", 0):
                    best = best_put
                else:
                    best = best_call if best_call["confidence"] > best_put["confidence"] else best_put
                logging.info(f"Decisão forçada: {best['strategy']} ({best['signal']}) com confiança {best['confidence']}%")

        score = best.get("score", 0)
        # Expiração dinâmica: usa a sugerida pela estratégia, ou fallback
        tempo_exp = best.get("tempo_exp", 3)  # se a estratégia não fornecer, usa 3
        # Garante que nunca seja inferior a 3 minutos
        if tempo_exp < 3:
            tempo_exp = 3

        return {
            "ativo": best.get("symbol"),
            "direcao": best["signal"],
            "score": score,
            "confianca": best["confidence"],
            "estrategia": best["strategy"],
            "analise": best.get("reason", ""),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "tempo_exp": tempo_exp,
            "detalhes": results
        }
