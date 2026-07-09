from strategies.base import Strategy

class MomentumStrategy(Strategy):
    def __init__(self):
        self.name = "Momentum"

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

        momentum = data_1min[-1] - data_1min[-10] if len(data_1min) >= 10 else 0
        ema20 = ema(data_1min, 20)
        ema50 = ema(data_1min, 50)
        if None in (ema20, ema50):
            return None

        diff_ema = (ema20 - ema50) / ema50 * 100

        if momentum > 0 and diff_ema > 1.0:
            signal = "CALL"
            score = 3.0
            reason = f"Momentum positivo ({momentum:.5f}), EMA20 > EMA50 ({diff_ema:.2f}%)"
        elif momentum < 0 and diff_ema < -1.0:
            signal = "PUT"
            score = 3.0
            reason = f"Momentum negativo ({momentum:.5f}), EMA20 < EMA50 ({diff_ema:.2f}%)"
        else:
            return None

        ema5_5 = ema(data_5min, 5)
        ema13_5 = ema(data_5min, 13)
        if None not in (ema5_5, ema13_5):
            tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"
            if signal != tendencia_5:
                score -= 1.0
                reason += " (conflito com tendência 5min)"

        confidence = min(100, max(0, score * 25))
        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "score": score,
            "reason": reason,
            "strategy": self.name,
            "indicators": {"momentum": momentum, "ema20": ema20, "ema50": ema50}
        }
