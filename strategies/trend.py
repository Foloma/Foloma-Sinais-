from strategies.base import Strategy

class TrendStrategy(Strategy):
    def __init__(self):
        self.name = "Trend"

    def analyze(self, symbol, data_1min, data_5min):
        if data_1min is None or len(data_1min) < 30 or data_5min is None or len(data_5min) < 30:
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

        def rsi(precos, periodo=7):
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

        def macd(precos):
            ema12 = ema(precos, 12)
            ema26 = ema(precos, 26)
            if None in (ema12, ema26):
                return None
            return ema12 - ema26

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
        diff_5 = abs(ema5_5 - ema13_5) / ema13_5 * 100
        tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"

        preco_atual = data_1min[-1]
        rsi_7 = rsi(data_1min, 7)
        macd_val = macd(data_1min)
        sup, med, inf = bollinger(data_1min)

        score = 1 if diff_5 > 0.03 else 0.5

        if tendencia_5 == "CALL":
            if rsi_7 < 55:
                score += 1
            elif rsi_7 < 65:
                score += 0.5
            if macd_val is not None and macd_val > 0:
                score += 0.5
            if sup is not None and preco_atual <= inf * 1.001:
                score += 0.5
            if diff_5 > 0.15:
                score += 0.5
            elif diff_5 > 0.08:
                score += 0.25
        else:
            if rsi_7 > 45:
                score += 1
            elif rsi_7 > 35:
                score += 0.5
            if macd_val is not None and macd_val < 0:
                score += 0.5
            if sup is not None and preco_atual >= sup * 0.999:
                score += 0.5
            if diff_5 > 0.15:
                score += 0.5
            elif diff_5 > 0.08:
                score += 0.25

        confidence = min(100, max(0, score * 20))
        if score >= 1.5:
            return {
                "symbol": symbol,
                "signal": tendencia_5,
                "confidence": confidence,
                "score": score,
                "reason": f"EMA5/EMA13: {diff_5:.2f}%, RSI: {rsi_7:.1f}, MACD: {macd_val:.5f}",
                "strategy": self.name,
                "indicators": {"ema5_5": ema5_5, "ema13_5": ema13_5, "rsi": rsi_7, "macd": macd_val}
            }
        return None
