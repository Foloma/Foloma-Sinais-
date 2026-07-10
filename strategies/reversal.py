from strategies.base import Strategy

class ReversalStrategy(Strategy):
    def __init__(self):
        self.name = "Reversal"

    def analyze(self, symbol, data_1min, data_5min):
        if data_1min is None or len(data_1min) < 30 or data_5min is None:
            return None

        def ema(precos, periodo):
            if len(precos) < periodo:
                return None
            mult = 2 / (periodo + 1)
            sma = sum(precos[:periodo]) / periodo
            ema = sma
            for p in precos[periodo:]:
                ema = (p - ema) * mult + ema
            return ema

        def rsi(precos, periodo=14):
            if len(precos) < periodo + 1:
                return 50
            deltas = [precos[i] - precos[i-1] for i in range(1, len(precos))]
            ult_deltas = deltas[-periodo:]
            ganhos = sum(d for d in ult_deltas if d > 0)
            perdas = sum(-d for d in ult_deltas if d < 0)
            avg_gain = ganhos / periodo
            avg_loss = perdas / periodo
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))

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

        ema5_5 = ema(data_5min, 5)
        ema13_5 = ema(data_5min, 13)
        if None in (ema5_5, ema13_5):
            return None
        tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"

        preco_atual = data_1min[-1]
        rsi_14 = rsi(data_1min, 14)
        sup, med, inf = bollinger(data_1min, 20, 2)
        if None in (sup, inf):
            return None

        signal = None
        score = 0
        reason = ""

        if preco_atual <= inf * 1.001 and rsi_14 < 30:
            if tendencia_5 != "PUT":
                signal = "CALL"
                score = 3.0
                reason = f"Preço na banda inferior ({inf:.5f}), RSI extremo ({rsi_14:.1f})"
            else:
                signal = "CALL"
                score = 1.5
                reason = f"Reversão potencial, mas tendência de 5min é PUT. Conflito."
        elif preco_atual >= sup * 0.999 and rsi_14 > 70:
            if tendencia_5 != "CALL":
                signal = "PUT"
                score = 3.0
                reason = f"Preço na banda superior ({sup:.5f}), RSI extremo ({rsi_14:.1f})"
            else:
                signal = "PUT"
                score = 1.5
                reason = f"Reversão potencial, mas tendência de 5min é CALL. Conflito."

        if signal is None:
            return None

        confidence = min(100, max(0, score * 25))
        # Limiar reduzido de 1.5 para 1.0 (já que score mínimo é 1.5)
        if score >= 1.0:
            return {
                "symbol": symbol,
                "signal": signal,
                "confidence": confidence,
                "score": score,
                "reason": reason,
                "strategy": self.name,
                "indicators": {"rsi": rsi_14, "bollinger_sup": sup, "bollinger_inf": inf}
            }
        return None
