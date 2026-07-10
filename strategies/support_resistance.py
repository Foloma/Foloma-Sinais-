from strategies.base import Strategy

class SupportResistanceStrategy(Strategy):
    def __init__(self):
        self.name = "S&R"

    def analyze(self, symbol, data_1min, data_5min):
        if data_1min is None or len(data_1min) < 30:
            return None

        high = max(data_1min)
        low = min(data_1min)
        preco_atual = data_1min[-1]
        resistencia = high
        suporte = low

        def ema(precos, periodo):
            if len(precos) < periodo:
                return None
            mult = 2 / (periodo + 1)
            sma = sum(precos[:periodo]) / periodo
            ema = sma
            for p in precos[periodo:]:
                ema = (p - ema) * mult + ema
            return ema

        ema20 = ema(data_1min, 20)
        if ema20 is None:
            return None

        signal = None
        score = 0
        reason = ""
        tolerancia = 0.001

        if abs(preco_atual - resistencia) / resistencia < tolerancia:
            if len(data_1min) >= 2:
                if data_1min[-2] < resistencia and preco_atual < resistencia:
                    signal = "PUT"
                    score = 3.0
                    reason = f"Rejeição na resistência {resistencia:.5f}"
                elif data_1min[-2] < resistencia and preco_atual > resistencia:
                    signal = "CALL"
                    score = 3.5
                    reason = f"Rompeu resistência {resistencia:.5f}"
        elif abs(preco_atual - suporte) / suporte < tolerancia:
            if len(data_1min) >= 2:
                if data_1min[-2] > suporte and preco_atual > suporte:
                    signal = "CALL"
                    score = 3.0
                    reason = f"Rejeição no suporte {suporte:.5f}"
                elif data_1min[-2] > suporte and preco_atual < suporte:
                    signal = "PUT"
                    score = 3.5
                    reason = f"Rompeu suporte {suporte:.5f}"

        if signal is None:
            return None

        if data_5min is not None and len(data_5min) >= 13:
            def ema5(precos, periodo):
                if len(precos) < periodo:
                    return None
                mult = 2 / (periodo + 1)
                sma = sum(precos[:periodo]) / periodo
                ema = sma
                for p in precos[periodo:]:
                    ema = (p - ema) * mult + ema
                return ema
            ema5_5 = ema5(data_5min, 5)
            ema13_5 = ema5(data_5min, 13)
            if None not in (ema5_5, ema13_5):
                tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"
                if signal != tendencia_5:
                    score -= 1.0
                    reason += " (conflito com tendência de 5min)"

        confidence = min(100, max(0, score * 25))
        if score >= 1.0:
            return {
                "symbol": symbol,
                "signal": signal,
                "confidence": confidence,
                "score": score,
                "reason": reason,
                "strategy": self.name,
                "indicators": {"support": suporte, "resistance": resistencia}
            }
        return None
