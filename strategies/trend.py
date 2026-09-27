from strategies.base import Strategy


class TrendStrategy(Strategy):
    """
    Segue tendências estabelecidas em 5min, com filtro de regime e
    confirmação multi-indicador em 1min (RSI-7, MACD, Bollinger).

    Correções face à versão anterior:
    - FILTRO DE REGIME: se |EMA5 - EMA13| em 5min for inferior a 0.05%,
      devolve None. Sem isto, a estratégia disparava sinal em ruído puro
      (base 0.5 + rsi_7 < 55 ≈ quase sempre verdadeiro → score 1.5 → passava).
      Este era o principal contaminador do _decide().
    - Score recalculado com a base mínima mais exigente. Agora o score só
      chega a valores que justificam a inclusão no _decide() quando há
      tendência real E pelo menos uma confirmação.
    - Fórmula de confidence alinhada com as restantes (score * 20).
    - tempo_exp devolvido.

    Score (máximo teórico ≈ 3.5):
    - Tendência 5min com |diff| >= 0.15%   → base 1.0
    - Tendência 5min com |diff| >= 0.05%   → base 0.5
    - RSI-7 em zona favorável              → +1.0  (com gradiente: +0.5 se mais extremo)
    - MACD (EMA12 - EMA26) alinhado        → +0.5
    - Preço na borda oposta da banda       → +0.5
    - |diff| 5min muito forte (>=0.15%)    → +0.5 extra
    """

    DIFF_MINIMO = 0.05       # % — abaixo disto não há tendência, é ruído
    DIFF_FORTE = 0.15        # % — tendência claramente estabelecida
    RSI_PERIOD = 7
    TEMPO_EXP = 4            # minutos

    def __init__(self):
        self.name = "Trend"

    def analyze(self, symbol, data_1min, data_5min):
        if not isinstance(data_1min, dict) or not isinstance(data_5min, dict):
            return None
        precos_1 = data_1min.get("closes")
        precos_5 = data_5min.get("closes")
        if not precos_1 or not precos_5:
            return None
        if len(precos_1) < 30 or len(precos_5) < 30:
            return None

        # --- tendência em 5min ---
        ema5_5 = self._ema(precos_5, 5)
        ema13_5 = self._ema(precos_5, 13)
        if ema5_5 is None or ema13_5 is None or ema13_5 == 0:
            return None

        diff_5 = abs(ema5_5 - ema13_5) / ema13_5 * 100.0

        # [FIX CRÍTICO] filtro de regime — abaixo deste limiar é ruído
        if diff_5 < self.DIFF_MINIMO:
            return None

        tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"

        # --- indicadores em 1min ---
        preco_atual = precos_1[-1]
        rsi_7 = self._rsi(precos_1, self.RSI_PERIOD)
        macd_val = self._macd(precos_1)
        sup, med, inf = self._bollinger(precos_1)

        # --- score composto ---
        # Base: 1.0 para tendência forte, 0.5 para tendência marginal
        score = 1.0 if diff_5 >= self.DIFF_FORTE else 0.5

        if tendencia_5 == "CALL":
            # RSI-7: em CALL queremos que não esteja já sobrecomprado
            if rsi_7 < 55:
                score += 1.0
            elif rsi_7 < 65:
                score += 0.5

            if macd_val is not None and macd_val > 0:
                score += 0.5

            # pullback para a banda inferior durante tendência CALL = entrada
            if sup is not None and preco_atual <= inf * 1.001:
                score += 0.5

            if diff_5 >= self.DIFF_FORTE:
                score += 0.5

        else:  # tendencia_5 == "PUT"
            if rsi_7 > 45:
                score += 1.0
            elif rsi_7 > 35:
                score += 0.5

            if macd_val is not None and macd_val < 0:
                score += 0.5

            if sup is not None and preco_atual >= sup * 0.999:
                score += 0.5

            if diff_5 >= self.DIFF_FORTE:
                score += 0.5

        # Nota: com a base mínima de 0.5 e o filtro de regime, o score
        # apenas chega a 1.0+ quando há tendência real + pelo menos uma
        # confirmação. Já não há o caso "ruído + rsi<55 = 1.5 → passa".

        confidence = self._score_to_confidence(score)

        reason_parts = [
            f"EMA5/EMA13 5min: {diff_5:.2f}%",
            f"RSI-7: {rsi_7:.1f}",
        ]
        if macd_val is not None:
            reason_parts.append(f"MACD: {macd_val:.5f}")

        return {
            "symbol": symbol,
            "signal": tendencia_5,
            "confidence": confidence,
            "score": round(score, 2),
            "reason": ", ".join(reason_parts),
            "strategy": self.name,
            "tempo_exp": self.TEMPO_EXP,
            "indicators": {
                "ema5_5": round(ema5_5, 5),
                "ema13_5": round(ema13_5, 5),
                "diff_5min_pct": round(diff_5, 3),
                "rsi": round(rsi_7, 2),
                "macd": round(macd_val, 6) if macd_val is not None else None,
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
    def _rsi(precos, periodo=7):
        if len(precos) < periodo + 1:
            return 50.0
        deltas = [precos[i] - precos[i - 1] for i in range(1, len(precos))]
        ult = deltas[-periodo:]
        ganhos = sum(d for d in ult if d > 0)
        perdas = sum(-d for d in ult if d < 0)
        avg_gain = ganhos / periodo
        avg_loss = perdas / periodo
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @classmethod
    def _macd(cls, precos):
        ema12 = cls._ema(precos, 12)
        ema26 = cls._ema(precos, 26)
        if ema12 is None or ema26 is None:
            return None
        return ema12 - ema26

    @staticmethod
    def _bollinger(precos, periodo=20, desvios=2):
        if len(precos) < periodo:
            return None, None, None
        ult = precos[-periodo:]
        media = sum(ult) / periodo
        var = sum((x - media) ** 2 for x in ult) / periodo
        std = var ** 0.5
        return media + desvios * std, media, media - desvios * std

    @staticmethod
    def _score_to_confidence(score):
        return min(95, max(20, score * 20))
