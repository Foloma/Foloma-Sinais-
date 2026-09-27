from strategies.base import Strategy


class SupportResistanceStrategy(Strategy):
    """
    Detecta rejeições e rompimentos em níveis de suporte/resistência
    identificados pelo máximo e mínimo recentes.

    Correção estrutural face à versão anterior:
    - Antes, `high = max(data_1min)` e `low = min(data_1min)` tomavam
      o máximo/mínimo dos CLOSES — não dos preços efectivamente tocados.
      Um "suporte" definido pelo fecho mais baixo é mais fraco do que o
      suporte definido pelo `low` real (o wick). Agora usa OHLC.
    - Input passa a ser dict com "closes" + "ohlc".

    Correções menores:
    - Confidence normalizada (score * 20) para ser comparável às outras.
    - tempo_exp devolvido.
    - `_ema` extraído (era definido duas vezes dentro do método).
    """

    MIN_BARS = 30
    TOLERANCIA = 0.001        # 0.1%
    TEMPO_EXP = 4             # minutos

    def __init__(self):
        self.name = "S&R"

    def analyze(self, symbol, data_1min, data_5min):
        # --- validação ---
        if not isinstance(data_1min, dict):
            return None
        ohlc_1min = data_1min.get("ohlc")
        closes_1min = data_1min.get("closes")
        if not ohlc_1min or not closes_1min:
            return None
        if len(ohlc_1min) < self.MIN_BARS or len(closes_1min) < self.MIN_BARS:
            return None

        # --- níveis de suporte e resistência (usando OHLC real) ---
        resistencia = max(c["high"] for c in ohlc_1min)
        suporte = min(c["low"] for c in ohlc_1min)
        preco_atual = closes_1min[-1]
        preco_anterior = closes_1min[-2] if len(closes_1min) >= 2 else preco_atual

        if resistencia <= 0 or suporte <= 0:
            return None

        # --- filtro de tendência média (para confirmar/negar o sinal) ---
        ema20 = self._ema(closes_1min, 20)
        if ema20 is None:
            return None

        # --- decisão ---
        signal = None
        score = 0.0
        reason = ""

        # Perto da resistência?
        if abs(preco_atual - resistencia) / resistencia < self.TOLERANCIA:
            if preco_anterior < resistencia and preco_atual < resistencia:
                signal = "PUT"
                score = 3.0
                reason = f"Rejeição na resistência {resistencia:.5f}"
            elif preco_anterior < resistencia and preco_atual > resistencia:
                signal = "CALL"
                score = 3.5
                reason = f"Rompeu resistência {resistencia:.5f}"

        # Perto do suporte?
        elif abs(preco_atual - suporte) / suporte < self.TOLERANCIA:
            if preco_anterior > suporte and preco_atual > suporte:
                signal = "CALL"
                score = 3.0
                reason = f"Rejeição no suporte {suporte:.5f}"
            elif preco_anterior > suporte and preco_atual < suporte:
                signal = "PUT"
                score = 3.5
                reason = f"Rompeu suporte {suporte:.5f}"

        if signal is None:
            return None

        # --- validação contra tendência de 5min ---
        if isinstance(data_5min, dict):
            closes_5min = data_5min.get("closes")
            if closes_5min and len(closes_5min) >= 13:
                ema5_5 = self._ema(closes_5min, 5)
                ema13_5 = self._ema(closes_5min, 13)
                if ema5_5 is not None and ema13_5 is not None:
                    tendencia_5 = "CALL" if ema5_5 > ema13_5 else "PUT"
                    if signal != tendencia_5:
                        score -= 1.0
                        reason += " (conflito com tendência de 5min)"

        # Após penalização, exige mínimo
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
                "support": round(suporte, 5),
                "resistance": round(resistencia, 5),
                "ema20": round(ema20, 5),
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
