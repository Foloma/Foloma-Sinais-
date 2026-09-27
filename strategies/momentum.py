from strategies.base import Strategy


class MomentumStrategy(Strategy):
    """
    Segue a direção do momentum de curto prazo confirmado por estrutura
    de médias (EMA20 vs EMA50) em 1min, com validação cruzada em 5min.

    Lógica:
    - Momentum = close[-1] - close[-10] (movimento recente).
    - EMA20 e EMA50 em 1min (precisa de >= 50 barras — o engine já
      garante outputsize=60, pelo que esta estratégia deixa de ser código
      morto).
    - CALL se momentum > 0  E  EMA20 > EMA50 (por >= 1%).
    - PUT  se momentum < 0  E  EMA20 < EMA50 (por >= 1%).
    - Se a tendência de 5min (EMA5 vs EMA13) contradiz o sinal de 1min,
      penaliza -1.0 no score.

    Score máximo teórico: 3.0. Com penalização: 2.0.
    """

    EMA_FAST = 20
    EMA_SLOW = 50
    DIFF_EMA_MIN = 1.0     # % mínimo para considerar tendência estabelecida
    MOMENTUM_LOOKBACK = 10
    TEMPO_EXP = 4          # minutos

    def __init__(self):
        self.name = "Momentum"

    def analyze(self, symbol, data_1min, data_5min):
        # --- validação de entrada ---
        if not isinstance(data_1min, dict) or not isinstance(data_5min, dict):
            return None
        precos_1 = data_1min.get("closes")
        precos_5 = data_5min.get("closes")
        if not precos_1 or not precos_5:
            return None
        if len(precos_1) < self.EMA_SLOW:
            return None

        # --- momentum de 1min ---
        momentum = precos_1[-1] - precos_1[-self.MOMENTUM_LOOKBACK]

        # --- estrutura de médias em 1min ---
        ema20 = self._ema(precos_1, self.EMA_FAST)
        ema50 = self._ema(precos_1, self.EMA_SLOW)
        if ema20 is None or ema50 is None or ema50 == 0:
            return None

        diff_ema = (ema20 - ema50) / ema50 * 100.0

        # --- decisão primária ---
        signal = None
        score = 0.0
        reason = ""

        if momentum > 0 and diff_ema > self.DIFF_EMA_MIN:
            signal = "CALL"
            score = 3.0
            reason = (
                f"Momentum positivo ({momentum:.5f}), "
                f"EMA20 > EMA50 ({diff_ema:.2f}%)"
            )
        elif momentum < 0 and diff_ema < -self.DIFF_EMA_MIN:
            signal = "PUT"
            score = 3.0
            reason = (
                f"Momentum negativo ({momentum:.5f}), "
                f"EMA20 < EMA50 ({diff_ema:.2f}%)"
            )
        else:
            return None

        # --- confirmação/invalidação em 5min ---
        ema5_5 = self._ema(precos_5, 5)
        ema13_5 = self._ema(precos_5, 13)
        if ema5_5 is not None and ema13_5 is not None:
            tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"
            if signal != tendencia_5:
                score -= 1.0
                reason += " (conflito com tendência 5min)"

        # Após penalização, exige um mínimo para não devolver ruído
        if score < 1.0:
            return None

        confidence = self._score_to_confidence(score)

        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "score": round(score, 2),
            "reason": reason,
            "strategy": self.name,
            "tempo_exp": self.TEMPO_EXP,
            "indicators": {
                "momentum": round(momentum, 5),
                "ema20": round(ema20, 5),
                "ema50": round(ema50, 5),
                "diff_ema_pct": round(diff_ema, 3),
            },
        }

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    @staticmethod
    def _ema(precos, periodo):
        if len(precos) < periodo:
            return None
        mult = 2 / (periodo + 1)
        ema = sum(precos[:periodo]) / periodo
        for p in precos[periodo:]:
            ema = (p - ema) * mult + ema
        return ema

    @staticmethod
    def _score_to_confidence(score):
        return min(95, max(20, score * 20))
