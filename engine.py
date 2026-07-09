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
        # Cache por 30 segundos para reduzir chamadas à API
        if key in self._cache and (now - self._cache_time.get(key, 0)) < 30:
            logging.info(f"Usando cache para {symbol} {interval}")
            return self._cache[key]

        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={api_key}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            dados = resp.json()
            if "values" in dados:
                precos = [float(v["close"]) for v in reversed(dados["values"])]
                if len(precos) >= outputsize:
                    self._cache[key] = precos
                    self._cache_time[key] = now
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
        calls = [r for r in results if r["signal"] == "CALL"]
        puts = [r for r in results if r["signal"] == "PUT"]

        if not calls:
            best = max(puts, key=lambda x: x["confidence"])
        elif not puts:
            best = max(calls, key=lambda x: x["confidence"])
        else:
            best_call = max(calls, key=lambda x: x["confidence"])
            best_put = max(puts, key=lambda x: x["confidence"])
            diff = abs(best_call["confidence"] - best_put["confidence"])
            if diff >= 20:
                best = best_call if best_call["confidence"] > best_put["confidence"] else best_put
            else:
                return {
                    "ativo": None,
                    "direcao": None,
                    "score": 0,
                    "confianca": 0,
                    "estrategia": "Conflito",
                    "analise": f"Conflito: CALL ({best_call['confidence']:.0f}%) vs PUT ({best_put['confidence']:.0f}%)",
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "tempo_exp": None,
                    "detalhes": results
                }

        score = best.get("score", 0)
        tempo_exp = 1 if score >= 3.5 else 2 if score >= 2.5 else 3

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
