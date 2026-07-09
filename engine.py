import os
import logging
import importlib
import pkgutil
from datetime import datetime
import requests

# Importa a classe base e as estratégias (serão carregadas dinamicamente)
import strategies
from strategies.base import Strategy

class StrategyEngine:
    def __init__(self):
        self.ATIVOS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD"]
        self.strategies = []
        self.load_strategies()
        logging.info(f"Motor carregado com {len(self.strategies)} estratégias.")

    def load_strategies(self):
        """Carrega dinamicamente todas as classes que herdam de Strategy dentro do pacote strategies."""
        for module_info in pkgutil.iter_modules(strategies.__path__):
            module_name = module_info.name
            # Ignora base.py e __init__.py
            if module_name in ['base', '__init__']:
                continue
            try:
                module = importlib.import_module(f"strategies.{module_name}")
                # Procura classes que são subclasses de Strategy (exceto a própria Strategy)
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
        """Busca dados da Twelve Data (centralizado para reuso)."""
        api_key = os.environ.get('TWELVE_DATA_API_KEY', '')
        if not api_key:
            logging.error("TWELVE_DATA_API_KEY não configurada.")
            return None
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={api_key}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            dados = resp.json()
            if "values" in dados:
                # Retorna lista de preços de fecho (do mais antigo para o mais recente)
                precos = [float(v["close"]) for v in reversed(dados["values"])]
                if len(precos) >= outputsize:
                    return precos
            return None
        except Exception as e:
            logging.error(f"Erro ao buscar dados para {symbol}: {e}")
            return None

    def get_best_signal(self):
        """Executa todas as estratégias para todos os ativos e decide o melhor sinal."""
        # Dados multi-timeframe: 1min e 5min
        dados_1min = {}
        dados_5min = {}
        for symbol in self.ATIVOS:
            dados_1min[symbol] = self._fetch_data(symbol, "1min", 30)
            dados_5min[symbol] = self._fetch_data(symbol, "5min", 30)

        # Coletar resultados de todas as estratégias para todos os ativos
        all_results = []
        for symbol in self.ATIVOS:
            data_1min = dados_1min.get(symbol)
            data_5min = dados_5min.get(symbol)
            if data_1min is None or data_5min is None:
                continue
            for strategy in self.strategies:
                try:
                    # Cada estratégia recebe ambos os timeframes
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

        # Aplicar gestão de conflitos e escolher o melhor
        decision = self._decide(all_results)
        return decision

    def _decide(self, results):
        """
        Gerencia conflitos e retorna o melhor sinal.
        Critérios:
        - Se houver sinais opostos (CALL vs PUT) de estratégias diferentes, 
          verifica se alguma tem confiança significativamente maior (>20% de diferença).
        - Se não, não gera sinal (conflito).
        - Caso contrário, escolhe a de maior confiança.
        """
        calls = [r for r in results if r["signal"] == "CALL"]
        puts = [r for r in results if r["signal"] == "PUT"]

        # Se só houver sinais de um lado, pega o de maior confiança
        if not calls:
            best = max(puts, key=lambda x: x["confidence"])
        elif not puts:
            best = max(calls, key=lambda x: x["confidence"])
        else:
            # Há conflito: compara a maior confiança de cada lado
            best_call = max(calls, key=lambda x: x["confidence"])
            best_put = max(puts, key=lambda x: x["confidence"])
            diff = abs(best_call["confidence"] - best_put["confidence"])
            # Se a diferença for maior que 20%, escolhe o de maior confiança
            if diff >= 20:
                best = best_call if best_call["confidence"] > best_put["confidence"] else best_put
            else:
                # Conflito, não opera
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

        # Se chegou aqui, best é o melhor sinal
        # Calcula tempo de expiração baseado no score
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
            "detalhes": results  # para debug/transparência
        }
