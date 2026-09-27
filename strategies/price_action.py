from strategies.base import Strategy


class PriceActionStrategy(Strategy):
    """
    Detecção de padrões de vela (Engulfing e Pin Bar) usando OHLC real.

    Correção estrutural face à versão anterior:
    - A versão antiga recebia só closes e usava `abs(close[i]-close[i-1])`
      como proxy de "corpo" e `max(closes[-5:])` como proxy de "pavio".
      Isso não corresponde a Engulfing nem a Pin Bar — são padrões
      definidos por open/high/low/close do MESMO candle.
    - Agora usa `data_1min["ohlc"]` (lista de dicts com open/high/low/close)
      para corpo, pavios e ATR reais.

    Correção lógica:
    - Tendência NEUTRO em 5min deixa de ser tratada como conflito.
      Antes, `if tendencia_5 == "CALL" ... else ...` colapsava NEUTRO
      no ramo do conflito, penalizando o score. Agora há três ramos:
      a favor, neutro, contra.

    Correções menores:
    - `tempo_exp` devolvido (a `_calculate_expiry` já existia mas o
      resultado era descartado antes do `return`).
    - `confidence` normalizada (score * 20) para ser comparável às
      outras estratégias no `_decide()`.
    - `atr` devolvido como float ou None (usava `if atr else None` que
      tratava `0.0` como falsy — agora `is not None`).
    """

    MIN_BARS = 21
    ATR_PERIOD = 14
    EMA_FAST = 8
    EMA_SLOW = 21

    def __init__(self):
        self.name = "PriceAction"

    # ============================================================
    # VALIDAÇÃO
    # ============================================================
    def _validate_data(self, data_1min, data_5min):
        if not isinstance(data_1min, dict) or not isinstance(data_5min, dict):
            return False
        ohlc = data_1min.get("ohlc")
        closes_5 = data_5min.get("closes")
        if not ohlc or not closes_5:
            return False
        if len(ohlc) < self.MIN_BARS or len(closes_5) < self.MIN_BARS:
            return False
        return True

    # ============================================================
    # INDICADORES
    # ============================================================
    @staticmethod
    def _calculate_ema(precos, periodo):
        if len(precos) < periodo:
            return None
        mult = 2 / (periodo + 1)
        ema = sum(precos[:periodo]) / periodo
        for p in precos[periodo:]:
            ema = (p - ema) * mult + ema
        return ema

    @staticmethod
    def _calculate_atr(ohlc, periodo=14):
        """
        True Range real: max(high-low, |high-prev_close|, |low-prev_close|).
        Não é a diferença entre closes — é o verdadeiro range de cada candle.
        """
        if len(ohlc) < periodo + 1:
            return None
        trs = []
        for i in range(1, len(ohlc)):
            h = ohlc[i]["high"]
            l = ohlc[i]["low"]
            pc = ohlc[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < periodo:
            return None
        return sum(trs[-periodo:]) / periodo

    def _analyze_trend(self, closes_5min):
        """
        Devolve (direcção, força):
            ("CALL",  0.0–1.0)  se EMA8 > EMA21 por > 0.2%
            ("PUT",   0.0–1.0)  se EMA8 < EMA21 por > 0.2%
            ("NEUTRO", 0.0)      caso contrário
        """
        ema8 = self._calculate_ema(closes_5min, self.EMA_FAST)
        ema21 = self._calculate_ema(closes_5min, self.EMA_SLOW)
        if ema8 is None or ema21 is None or ema21 == 0:
            return "NEUTRO", 0.0
        diff_percent = (ema8 - ema21) / ema21 * 100.0
        if abs(diff_percent) < 0.2:
            return "NEUTRO", 0.0
        if diff_percent > 0:
            return "CALL", min(1.0, diff_percent / 1.5)
        return "PUT", min(1.0, abs(diff_percent) / 1.5)

    # ============================================================
    # PADRÕES DE VELA (com OHLC real)
    # ============================================================
    def _check_engulfing(self, ohlc, tendencia_5):
        """
        Bullish Engulfing: candle anterior bearish, candle actual bullish,
        corpo do actual engole o corpo do anterior (open <= prev.close e
        close >= prev.open). Exige pullback nos 3 candles anteriores.

        Bearish Engulfing: espelho.
        """
        if len(ohlc) < 5:
            return None, 0, "", {}

        c1 = ohlc[-1]   # candle actual
        c2 = ohlc[-2]   # candle anterior
        c3 = ohlc[-3]
        c4 = ohlc[-4]
        c5 = ohlc[-5]

        corpo_atual = abs(c1["close"] - c1["open"])
        corpo_anterior = abs(c2["close"] - c2["open"])
        if corpo_anterior == 0:
            return None, 0, "", {}
        if corpo_atual < corpo_anterior * 1.5:
            return None, 0, "", {}

        c2_bear = c2["close"] < c2["open"]
        c1_bull = c1["close"] > c1["open"]
        # Corpo de c1 engole o corpo de c2
        if c2_bear and c1_bull and c1["open"] <= c2["close"] and c1["close"] >= c2["open"]:
            # pullback: 3 candles anteriores em queda
            pullback = c3["close"] < c4["close"] < c5["close"]
            if pullback:
                if tendencia_5 == "CALL":
                    return "CALL", 2.5, (
                        f"Bullish Engulfing com pullback "
                        f"(corpo {corpo_atual:.5f})"
                    ), {"corpo": corpo_atual, "anterior": corpo_anterior}
                if tendencia_5 == "PUT":
                    return "CALL", 1.5, (
                        "Bullish Engulfing (conflito com tendência 5min)"
                    ), {"corpo": corpo_atual, "anterior": corpo_anterior}
                # NEUTRO
                return "CALL", 2.0, (
                    f"Bullish Engulfing com pullback "
                    f"(tendência 5min neutra)"
                ), {"corpo": corpo_atual, "anterior": corpo_anterior}

        c2_bull = c2["close"] > c2["open"]
        c1_bear = c1["close"] < c1["open"]
        if c2_bull and c1_bear and c1["open"] >= c2["close"] and c1["close"] <= c2["open"]:
            pullback = c3["close"] > c4["close"] > c5["close"]
            if pullback:
                if tendencia_5 == "PUT":
                    return "PUT", 2.5, (
                        f"Bearish Engulfing com pullback "
                        f"(corpo {corpo_atual:.5f})"
                    ), {"corpo": corpo_atual, "anterior": corpo_anterior}
                if tendencia_5 == "CALL":
                    return "PUT", 1.5, (
                        "Bearish Engulfing (conflito com tendência 5min)"
                    ), {"corpo": corpo_atual, "anterior": corpo_anterior}
                return "PUT", 2.0, (
                    f"Bearish Engulfing com pullback "
                    f"(tendência 5min neutra)"
                ), {"corpo": corpo_atual, "anterior": corpo_anterior}

        return None, 0, "", {}

    def _check_pin_bar(self, ohlc, tendencia_5):
        """
        Hammer: pavio inferior >= 2x corpo, pavio superior pequeno.
        Shooting Star: pavio superior >= 2x corpo, pavio inferior pequeno.
        Ambos com pullback nos 3 candles anteriores.
        """
        if len(ohlc) < 5:
            return None, 0, "", {}

        c1 = ohlc[-1]
        c3 = ohlc[-3]
        c4 = ohlc[-4]
        c5 = ohlc[-5]

        high = c1["high"]
        low = c1["low"]
        op = c1["open"]
        cl = c1["close"]

        total_range = high - low
        if total_range <= 0:
            return None, 0, "", {}

        corpo = abs(cl - op)
        if corpo == 0:
            return None, 0, "", {}

        pavio_sup = high - max(op, cl)
        pavio_inf = min(op, cl) - low

        # Shooting Star → PUT
        if pavio_sup >= 2 * corpo and pavio_inf <= corpo * 0.5:
            pullback_alta = c3["close"] > c4["close"] > c5["close"]
            if pullback_alta:
                if tendencia_5 == "PUT":
                    return "PUT", 2.5, (
                        f"Shooting Star (pavio superior {pavio_sup:.5f})"
                    ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}
                if tendencia_5 == "CALL":
                    return "PUT", 1.5, (
                        "Shooting Star (conflito com tendência 5min)"
                    ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}
                return "PUT", 2.0, (
                    f"Shooting Star (tendência 5min neutra)"
                ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}

        # Hammer → CALL
        if pavio_inf >= 2 * corpo and pavio_sup <= corpo * 0.5:
            pullback_baixa = c3["close"] < c4["close"] < c5["close"]
            if pullback_baixa:
                if tendencia_5 == "CALL":
                    return "CALL", 2.5, (
                        f"Hammer (pavio inferior {pavio_inf:.5f})"
                    ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}
                if tendencia_5 == "PUT":
                    return "CALL", 1.5, (
                        "Hammer (conflito com tendência 5min)"
                    ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}
                return "CALL", 2.0, (
                    f"Hammer (tendência 5min neutra)"
                ), {"pavio_sup": pavio_sup, "pavio_inf": pavio_inf}

        return None, 0, "", {}

    # ============================================================
    # CONFIRMAÇÃO MULTI-TIMEFRAME
    # ============================================================
    def _multi_timeframe_confirm(self, closes_1min, closes_5min, sinal):
        """
        Confirma se EMA8/EMA21 concordam com o sinal nos dois timeframes.
        Devolve (confirmado, força) onde força está em [0, 1].
        """
        ema8_1 = self._calculate_ema(closes_1min, self.EMA_FAST)
        ema21_1 = self._calculate_ema(closes_1min, self.EMA_SLOW)
        ema8_5 = self._calculate_ema(closes_5min, self.EMA_FAST)
        ema21_5 = self._calculate_ema(closes_5min, self.EMA_SLOW)
        if None in (ema8_1, ema21_1, ema8_5, ema21_5):
            return False, 0.0
        if ema21_1 == 0 or ema21_5 == 0:
            return False, 0.0

        tend_1 = "CALL" if ema8_1 > ema21_1 else "PUT"
        tend_5 = "CALL" if ema8_5 > ema21_5 else "PUT"

        if tend_1 == tend_5 == sinal:
            diff_1 = abs(ema8_1 - ema21_1) / ema21_1 * 100.0
            diff_5 = abs(ema8_5 - ema21_5) / ema21_5 * 100.0
            forca = min(1.0, (diff_1 + diff_5) / 3.0)
            return True, forca
        if tend_1 == sinal:
            return False, 0.2
        return False, 0.0

    # ============================================================
    # QUALIDADE E AJUSTES DE SCORE
    # ============================================================
    def _calculate_quality(self, score_base, confirmado, forca_tendencia, atr):
        ajuste = 0.0
        if confirmado:
            ajuste += 0.5
        else:
            ajuste -= 0.3
        ajuste += forca_tendencia * 0.5
        if atr is not None and atr > 0.0005:
            ajuste += 0.3
        elif atr is not None and atr < 0.0002:
            ajuste -= 0.3

        score_final = max(0.5, score_base + ajuste)

        if score_final >= 3.8:
            classificacao = "A+"
        elif score_final >= 3.2:
            classificacao = "A"
        elif score_final >= 2.6:
            classificacao = "B"
        elif score_final >= 2.0:
            classificacao = "C"
        elif score_final >= 1.5:
            classificacao = "D"
        else:
            classificacao = "F"

        return classificacao, score_final

    @staticmethod
    def _adjust_score(score_ajustado, qualidade, confianca_bruta):
        bonus_q = {"A+": 0.5, "A": 0.3, "B": 0.1, "C": 0.0, "D": -0.2, "F": -0.5}
        bonus = bonus_q.get(qualidade, 0.0)
        if confianca_bruta > 60:
            bonus += 0.2
        return max(0.5, score_ajustado + bonus)

    @staticmethod
    def _score_to_confidence(score):
        """Escala comum a todas as estratégias (ver base.py)."""
        return min(95, max(20, score * 20))

    def _calculate_expiry(self, qualidade, forca_tendencia):
        base = {"A+": 3, "A": 3, "B": 4, "C": 4, "D": 5, "F": 5}.get(qualidade, 4)
        if forca_tendencia > 0.7 and base > 3:
            base -= 1
        return max(3, base)

    def _no_signal(self, symbol, motivo):
        return {
            "symbol": symbol,
            "signal": None,
            "confidence": 0,
            "score": 0,
            "reason": motivo,
            "strategy": self.name,
            "tempo_exp": None,
            "indicators": {},
        }

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    def analyze(self, symbol, data_1min, data_5min):
        if not self._validate_data(data_1min, data_5min):
            return self._no_signal(symbol, "Dados insuficientes")

        ohlc_1min = data_1min["ohlc"]
        closes_1min = data_1min.get("closes") or [c["close"] for c in ohlc_1min]
        closes_5min = data_5min["closes"]

        atr = self._calculate_atr(ohlc_1min, self.ATR_PERIOD)
        tendencia_5, forca_tendencia = self._analyze_trend(closes_5min)

        sinal_eng, score_eng, razao_eng, met_eng = self._check_engulfing(ohlc_1min, tendencia_5)
        sinal_pin, score_pin, razao_pin, met_pin = self._check_pin_bar(ohlc_1min, tendencia_5)

        if sinal_eng is not None:
            sinal = sinal_eng
            score_base = score_eng
            razao = razao_eng
            metrica = met_eng
        elif sinal_pin is not None:
            sinal = sinal_pin
            score_base = score_pin
            razao = razao_pin
            metrica = met_pin
        else:
            return self._no_signal(symbol, "Nenhum padrão Price Action identificado")

        confirmado, forca_confirmacao = self._multi_timeframe_confirm(
            closes_1min, closes_5min, sinal
        )
        qualidade, score_ajustado = self._calculate_quality(
            score_base, confirmado, forca_tendencia, atr
        )

        if qualidade in ("D", "F"):
            return self._no_signal(symbol, f"Qualidade {qualidade} – setup fraco")

        confianca_bruta = score_ajustado * 18 + forca_tendencia * 5
        score_final = self._adjust_score(score_ajustado, qualidade, confianca_bruta)
        expiry = self._calculate_expiry(qualidade, forca_tendencia)

        # Fórmula final de confidence — normalizada com as outras estratégias
        confidence = self._score_to_confidence(score_final)

        atr_display = round(atr, 5) if atr is not None else None

        return {
            "symbol": symbol,
            "signal": sinal,
            "confidence": round(confidence, 1),
            "score": round(score_final, 2),
            "reason": (
                f"{razao} | Qualidade: {qualidade} | "
                f"MTF: {'✓' if confirmado else '✗'} | "
                f"ATR: {atr_display if atr_display is not None else 'n/d'}"
            ),
            "strategy": self.name,
            "tempo_exp": expiry,
            "indicators": {
                "tendencia_5min": tendencia_5,
                "forca_tendencia": round(forca_tendencia, 2),
                "atr": atr_display,
                "confirmado_mtf": confirmado,
                "qualidade": qualidade,
                "score_bruto": round(score_base, 2),
                "score_ajustado": round(score_ajustado, 2),
                **metrica,
            },
        }
