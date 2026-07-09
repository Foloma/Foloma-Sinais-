from strategies.base import Strategy

class BreakoutStrategy(Strategy):
    def __init__(self):
        self.name = "Breakout"

    def analyze(self, symbol, data_1min, data_5min):
        if data_1min is None or len(data_1min) < 30:
            return None

        def bollinger(precos, periodo=20, desvios=2):
            if len(precos) < periodo:
                return None, None, None
            ultimos = precos[-periodo:]
            media = sum(ultimos) / periodo
            var = sum((x - media) ** 2 for x in ultimos) / periodo
            std = var ** 0.5
            superior = media + desvios * std
            inferior = media - desvios * std
            return superior, media, inferior

        sup, med, inf = bollinger(data_1min, 20, 2)
        if None in (sup, inf):
            return None
        banda_width = (sup - inf) / med * 100

        if banda_width > 3:
            return None

        preco_atual = data_1min[-1]
        signal = None
        score = 0
        reason = ""

        if preco_atual > sup:
            signal = "CALL"
            score = 3.5
            reason = f"Rompeu resistência da banda superior ({sup:.5f}), largura da banda: {banda_width:.2f}%"
        elif preco_atual < inf:
            signal = "PUT"
            score = 3.5
            reason = f"Rompeu suporte da banda inferior ({inf:.5f}), largura da banda: {banda_width:.2f}%"
        else:
            return None

        confidence = min(100, max(0, score * 25))
        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "score": score,
            "reason": reason,
            "strategy": self.name,
            "indicators": {"bollinger_sup": sup, "bollinger_inf": inf, "bandwidth": banda_width}
        }
