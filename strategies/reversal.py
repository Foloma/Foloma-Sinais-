from strategies.base import Strategy


class ReversalStrategy(Strategy):
    """
    Detecta exaustão de movimentos nas extremidades das Bandas de Bollinger
    confirmada por RSI em zona extrema, e valida contra a tendência de 5min.

    Lógica:
    - Preço toca/ultrapassa a banda inferior + RSI-14 < 30  -> potencial CALL
    - Preço toca/ultrapassa a banda superior + RSI-14 > 70 -> potencial PUT
    - Se a tendência de 5min (EMA5 vs EMA13) concordar com a reversão,
      score = 3.0 (setup limpo).
    - Se a tendência de 5min estiver contra, score = 1.5 (reversão contra
      tendência — setup fraco, mas ainda assim reportado).

    Nota de design: o score continua a ser binário (3.0 / 1.5). Não há
    gradiente para "quão extrema é a exaustão" (RSI 25 vs RSI 29, ou preço
    no limite vs 0.5% além da banda). Isto é intencional — evita inventar
    coeficientes sem evidência empírica. A Fase 3 pode introduzir gradiente
    com base numa amostra pré-registada.
    """

    RSI_PERIOD = 14
    RSI_LOW = 30
    RSI_HIGH = 70
    BOLLINGER_PERIOD = 20
    BOLLINGER_DEV = 2
    TOLERANCIA = 0.001        # 0.1% de folga nas bandas
    TEMPO_EXP = 4             # minutos

    def __init__(self):
        self.name = "Reversal"

    def analyze(self, symbol, data_1min, data_5min):
        if not isinstance(data_1min, dict) or not isinstance(data_5min, dict):
            return None
        precos_1 = data_1min.get("closes")
        precos_5 = data_5min.get("closes")
        if not precos_1 or not precos_5:
            return None
        if len(precos_1) < 30 or len(precos_5) < 13:
            return None

        # --- tendência de 5min (só para validar a reversão) ---
        ema5_5 = self._ema(precos_5, 5)
        ema13_5 = self._ema(precos_5, 13)
        if ema5_5 is None or ema13_5 is None:
            return None
        tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"

        # --- indicadores em 1min ---
        preco_atual = precos_1[-1]
        rsi_14 = self._rsi(precos_1, self.RSI_PERIOD)
        sup, med, inf = self._bollinger(
            precos_1, self.BOLLINGER_PERIOD, self.BOLLINGER_DEV
        )
        if sup is None or inf is None:
            return None

        # --- decisão ---
        signal = None
        score = 0.0
        reason = ""

        if preco_atual <= inf * (1 + self.TOLERANCIA) and rsi_14 < self.RSI_LOW:
            signal = "CALL"
            if tendencia_5 != "PUT":
                score = 3.0
                reason = (
                    f"Preço na banda inferior ({inf:.5f}), "
                    f"RSI extremo ({rsi_14:.1f})"
                )
            else:
                score = 1.5
                reason = (
                    f"Reversão potencial, mas tendência de 5min é PUT. "
                    f"Conflito."
                )

        elif preco_atual >= sup * (1 - self.TOLERANCIA) and rsi_14 > self.RSI_HIGH:
            signal = "PUT"
            if tendencia_5 != "CALL":
                score = 3.0
                reason = (
                    f"Preço na banda superior ({sup:.5f}), "
                    f"RSI extremo ({rsi_14:.1f})"
                )
            else:
                score = 1.5
                reason = (
                    f"Reversão potencial, mas tendência de 5min é CALL. "
                    f"Conflito."
                )

        if signal is None:
            return None

        confidence = self._score_to_confidence(score)

        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "score": score,
            "reason": reason,
            "strategy": self.name,
            "tempo_exp": self.TEMPO_EXP,
            "indicators": {
                "rsi": round(rsi_14, 2),
                "bollinger_sup": round(sup, 5),
                "bollinger_inf": round(inf, 5),
                "tendencia_5min": tendencia_5,
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
    def _rsi(precos, periodo=14):
        if len(precos) < periodo + 1:
            return 50.0
        deltas = [precos[i] - precos[i - 1] for i in range(1, len(precos))]
        ult_deltas = deltas[-periodo:]
        ganhos = sum(d for d in ult_deltas if d > 0)
        perdas = sum(-d for d in ult_deltas if d < 0)
        avg_gain = ganhos / periodo
        avg_loss = perdas / periodo
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _bollinger(precos, periodo=20, desvios=2):
        if len(precos) < periodo:
            return None, None, None
        ultimos = precos[-periodo:]
        media = sum(ultimos) / periodo
        var = sum((x - media) ** 2 for x in ultimos) / periodo
        std = var ** 0.5
        return media + desvios * std, media, media - desvios * std

    @staticmethod
    def _score_to_confidence(score):
        return min(95, max(20, score * 20))
