from strategies.base import Strategy


class BreakoutStrategy(Strategy):
    """
    Detecta rompimentos das Bandas de Bollinger em regime de baixa
    volatilidade (squeeze).

    Lógica:
    - Calcula Bandas de Bollinger (20, 2σ) sobre os closes de 1min.
    - Se a largura relativa da banda for > 3%, o mercado está em tendência
      e a estratégia abstém-se (não é regime de breakout).
    - Se o preço rompeu a banda superior  -> CALL
    - Se o preço rompeu a banda inferior  -> PUT
    - Se está dentro das bandas            -> None

    Nota: usa apenas `data_1min["closes"]`. O `data_5min` é aceito por
    contrato mas não é usado — não há aqui informação de 5min relevante.
    """

    BANDWIDTH_MAX = 3.0   # %
    SCORE = 3.5           # fixo: todo o rompimento vale o mesmo
    TEMPO_EXP = 3         # minutos (breakout → rápido, mínimo do engine)

    def __init__(self):
        self.name = "Breakout"

    def analyze(self, symbol, data_1min, data_5min):
        # --- validação de entrada (novo formato: dict) ---
        if not isinstance(data_1min, dict):
            return None
        precos = data_1min.get("closes")
        if not precos or len(precos) < 30:
            return None

        # --- cálculo das bandas ---
        sup, med, inf = self._bollinger(precos, periodo=20, desvios=2)
        if sup is None or inf is None or med == 0:
            return None

        banda_width = (sup - inf) / med * 100.0
        if banda_width > self.BANDWIDTH_MAX:
            # regime de tendência — breakout não é o setup adequado
            return None

        preco_atual = precos[-1]

        if preco_atual > sup:
            signal = "CALL"
            reason = (
                f"Rompeu resistência da banda superior ({sup:.5f}), "
                f"largura da banda: {banda_width:.2f}%"
            )
        elif preco_atual < inf:
            signal = "PUT"
            reason = (
                f"Rompeu suporte da banda inferior ({inf:.5f}), "
                f"largura da banda: {banda_width:.2f}%"
            )
        else:
            return None

        score = self.SCORE
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
                "bollinger_sup": round(sup, 5),
                "bollinger_med": round(med, 5),
                "bollinger_inf": round(inf, 5),
                "bandwidth": round(banda_width, 3),
            },
        }

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    @staticmethod
    def _bollinger(precos, periodo=20, desvios=2):
        """Devolve (superior, media, inferior) ou (None, None, None)."""
        if len(precos) < periodo:
            return None, None, None
        ultimos = precos[-periodo:]
        media = sum(ultimos) / periodo
        var = sum((x - media) ** 2 for x in ultimos) / periodo
        std = var ** 0.5
        return media + desvios * std, media, media - desvios * std

    @staticmethod
    def _score_to_confidence(score):
        """
        Escala comum a todas as estratégias (ver base.py).
        score 0   ->  20
        score 2.5 ->  50
        score 5   ->  95
        """
        return min(95, max(20, score * 20))
