from strategies.base import Strategy

class PriceActionStrategy(Strategy):
    def __init__(self):
        self.name = "PriceAction"

    def analyze(self, symbol, data_1min, data_5min):
        if data_1min is None or len(data_1min) < 5:
            return None

        preco_atual = data_1min[-1]
        preco_anterior = data_1min[-2]
        preco_3 = data_1min[-3] if len(data_1min) >= 3 else None
        preco_4 = data_1min[-4] if len(data_1min) >= 4 else None

        if preco_3 is None or preco_4 is None:
            return None

        sinal = None
        score = 0
        razao = ""

        # Bullish Engulfing (simplificado)
        if preco_anterior < preco_3 and preco_atual > preco_anterior and (preco_atual - preco_anterior) > (preco_anterior - preco_3) * 1.5:
            sinal = "CALL"
            score = 3.0
            razao = "Bullish Engulfing detectado"
        # Bearish Engulfing
        elif preco_anterior > preco_3 and preco_atual < preco_anterior and (preco_anterior - preco_atual) > (preco_3 - preco_anterior) * 1.5:
            sinal = "PUT"
            score = 3.0
            razao = "Bearish Engulfing detectado"
        else:
            # Pin bar / Hammer: preço perto do máximo ou mínimo das últimas 5 velas
            ultimos = data_1min[-5:]
            maximo = max(ultimos)
            minimo = min(ultimos)
            if preco_atual >= maximo * 0.99:
                sinal = "CALL"
                score = 2.5
                razao = "Hammer / Pin Bar (próximo do máximo)"
            elif preco_atual <= minimo * 1.01:
                sinal = "PUT"
                score = 2.5
                razao = "Shooting Star / Pin Bar (próximo do mínimo)"

        if sinal is None:
            return None

        confidence = min(100, max(0, score * 25))
        return {
            "symbol": symbol,
            "signal": sinal,
            "confidence": confidence,
            "score": score,
            "reason": razao,
            "strategy": self.name,
            "indicators": {"last_5": data_1min[-5:]}
        }
