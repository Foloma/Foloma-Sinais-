from strategies.base import Strategy
import math

class PriceActionStrategy(Strategy):
    """
    Estratégia de Price Action V2 com:
    - Engulfing com pullback + corpo >1.5x
    - Pin Bar com wick >2x corpo + pullback 3 candles
    - Filtro de tendência multi-timeframe (1min e 5min)
    - Score dinâmico com classificação A+ a F
    - ATR para filtro de volatilidade
    - Confiança realista e expiração sugerida (mínimo 3min)
    """
    def __init__(self):
        self.name = "PriceAction"
        self.MIN_BARS = 21
        self.ATR_PERIOD = 14
        self.EMA_FAST = 8
        self.EMA_SLOW = 21

    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================

    def _validate_data(self, data_1min, data_5min):
        if data_1min is None or len(data_1min) < self.MIN_BARS:
            return False
        if data_5min is None or len(data_5min) < self.MIN_BARS:
            return False
        return True

    def _calculate_ema(self, precos, periodo):
        if len(precos) < periodo:
            return None
        mult = 2 / (periodo + 1)
        sma = sum(precos[:periodo]) / periodo
        ema = sma
        for p in precos[periodo:]:
            ema = (p - ema) * mult + ema
        return ema

    def _calculate_atr(self, precos, periodo=14):
        if len(precos) < periodo + 1:
            return None
        ranges = [abs(precos[i] - precos[i-1]) for i in range(1, len(precos))]
        if len(ranges) < periodo:
            return None
        return sum(ranges[-periodo:]) / periodo

    def _analyze_trend(self, data_5min):
        ema8 = self._calculate_ema(data_5min, self.EMA_FAST)
        ema21 = self._calculate_ema(data_5min, self.EMA_SLOW)
        if None in (ema8, ema21):
            return "NEUTRO", 0.0
        diff_percent = (ema8 - ema21) / ema21 * 100
        if abs(diff_percent) < 0.2:
            return "NEUTRO", 0.0
        elif diff_percent > 0:
            return "CALL", min(1.0, diff_percent / 1.5)
        else:
            return "PUT", min(1.0, abs(diff_percent) / 1.5)

    def _check_engulfing(self, data_1min, tendencia_5):
        if len(data_1min) < 5:
            return None, 0, "", {}
        c1 = data_1min[-1]
        c2 = data_1min[-2]
        c3 = data_1min[-3]
        c4 = data_1min[-4]
        c5 = data_1min[-5]
        corpo_atual = abs(c1 - c2)
        corpo_anterior = abs(c2 - c3)
        if corpo_atual < corpo_anterior * 1.5:
            return None, 0, "", {}
        if c2 < c3 and c1 > c2:
            if c3 < c4 and c4 < c5:
                if tendencia_5 == "CALL":
                    return "CALL", 2.5, f"Bullish Engulfing com pullback (corpo {corpo_atual:.5f})", {"corpo": corpo_atual, "anterior": corpo_anterior}
                else:
                    return "CALL", 1.5, f"Bullish Engulfing (conflito com tendência 5min)", {"corpo": corpo_atual, "anterior": corpo_anterior}
        if c2 > c3 and c1 < c2:
            if c3 > c4 and c4 > c5:
                if tendencia_5 == "PUT":
                    return "PUT", 2.5, f"Bearish Engulfing com pullback (corpo {corpo_atual:.5f})", {"corpo": corpo_atual, "anterior": corpo_anterior}
                else:
                    return "PUT", 1.5, f"Bearish Engulfing (conflito com tendência 5min)", {"corpo": corpo_atual, "anterior": corpo_anterior}
        return None, 0, "", {}

    def _check_pin_bar(self, data_1min, tendencia_5):
        if len(data_1min) < 5:
            return None, 0, "", {}
        c1 = data_1min[-1]
        c2 = data_1min[-2]
        c3 = data_1min[-3]
        c4 = data_1min[-4]
        c5 = data_1min[-5]
        maximo = max(data_1min[-5:])
        minimo = min(data_1min[-5:])
        range_total = maximo - minimo
        if range_total == 0:
            return None, 0, "", {}
        dist_max = (maximo - c1) / range_total
        dist_min = (c1 - minimo) / range_total
        if dist_max < 0.2 and dist_min > 0.3:
            if c3 > c4 > c5:
                if tendencia_5 == "PUT":
                    return "PUT", 2.5, f"Shooting Star (wick superior {dist_max:.2f})", {"dist_max": dist_max, "dist_min": dist_min}
                else:
                    return "PUT", 1.5, f"Shooting Star (conflito com tendência 5min)", {"dist_max": dist_max, "dist_min": dist_min}
        if dist_min < 0.2 and dist_max > 0.3:
            if c3 < c4 < c5:
                if tendencia_5 == "CALL":
                    return "CALL", 2.5, f"Hammer (wick inferior {dist_min:.2f})", {"dist_max": dist_max, "dist_min": dist_min}
                else:
                    return "CALL", 1.5, f"Hammer (conflito com tendência 5min)", {"dist_max": dist_max, "dist_min": dist_min}
        return None, 0, "", {}

    def _multi_timeframe_confirm(self, data_1min, data_5min, sinal):
        ema8_1 = self._calculate_ema(data_1min, self.EMA_FAST)
        ema21_1 = self._calculate_ema(data_1min, self.EMA_SLOW)
        ema8_5 = self._calculate_ema(data_5min, self.EMA_FAST)
        ema21_5 = self._calculate_ema(data_5min, self.EMA_SLOW)
        if None in (ema8_1, ema21_1, ema8_5, ema21_5):
            return False, 0.0
        tend_1 = "CALL" if ema8_1 > ema21_1 else "PUT"
        tend_5 = "CALL" if ema8_5 > ema21_5 else "PUT"
        if tend_1 == tend_5 == sinal:
            diff_1 = abs(ema8_1 - ema21_1) / ema21_1 * 100
            diff_5 = abs(ema8_5 - ema21_5) / ema21_5 * 100
            forca = min(1.0, (diff_1 + diff_5) / 3.0)
            return True, forca
        elif tend_1 == sinal:
            return False, 0.2
        else:
            return False, 0.0

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

    def _adjust_score(self, score_ajustado, qualidade, confianca):
        bonus_qualidade = {"A+": 0.5, "A": 0.3, "B": 0.1, "C": 0.0, "D": -0.2, "F": -0.5}.get(qualidade, 0.0)
        bonus_confianca = 0.2 if confianca > 60 else 0.0
        return max(0.5, score_ajustado + bonus_qualidade + bonus_confianca)

    def _calculate_confidence(self, score, forca_tendencia, qualidade):
        penalidade = {"F": 15, "D": 8, "C": 3}.get(qualidade, 0)
        conf = score * 18 + forca_tendencia * 5 - penalidade
        return max(20, min(95, conf))

    def _calculate_expiry(self, qualidade, forca_tendencia):
        """
        Expiração mais realista:
        - Mínimo 3 minutos para dar tempo ao utilizador.
        - A+/A → 3 min (antes 1 min)
        - B/C → 4 min
        - D/F → 5 min (mas D/F já são rejeitados)
        """
        base = {
            "A+": 3,
            "A": 3,
            "B": 4,
            "C": 4,
            "D": 5,
            "F": 5
        }.get(qualidade, 4)
        # Se tendência for muito forte e base > 3, reduz ligeiramente (mas nunca abaixo de 3)
        if forca_tendencia > 0.7 and base > 3:
            base -= 1
        return max(3, base)  # mínimo 3 minutos

    def _no_signal(self, symbol, motivo):
        return {
            "symbol": symbol,
            "signal": None,
            "confidence": 0,
            "score": 0,
            "reason": motivo,
            "strategy": self.name,
            "indicators": {}
        }

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def analyze(self, symbol, data_1min, data_5min):
        if not self._validate_data(data_1min, data_5min):
            return self._no_signal(symbol, "Dados insuficientes")

        atr = self._calculate_atr(data_1min, self.ATR_PERIOD)
        tendencia_5, forca_tendencia = self._analyze_trend(data_5min)

        sinal_eng, score_eng, razao_eng, metrica_eng = self._check_engulfing(data_1min, tendencia_5)
        sinal_pin, score_pin, razao_pin, metrica_pin = self._check_pin_bar(data_1min, tendencia_5)

        if sinal_eng is not None:
            sinal = sinal_eng
            score_base = score_eng
            razao = razao_eng
            metrica = metrica_eng
        elif sinal_pin is not None:
            sinal = sinal_pin
            score_base = score_pin
            razao = razao_pin
            metrica = metrica_pin
        else:
            return self._no_signal(symbol, "Nenhum padrão Price Action identificado")

        confirmado, forca_confirmacao = self._multi_timeframe_confirm(data_1min, data_5min, sinal)
        qualidade, score_ajustado = self._calculate_quality(score_base, confirmado, forca_tendencia, atr)

        # Rejeita qualidade D/E/F
        if qualidade in ["D", "E", "F"]:
            return self._no_signal(symbol, f"Qualidade {qualidade} – setup fraco")

        confianca = self._calculate_confidence(score_ajustado, forca_tendencia, qualidade)
        score_final = self._adjust_score(score_ajustado, qualidade, confianca)
        expiry = self._calculate_expiry(qualidade, forca_tendencia)

        return {
            "symbol": symbol,
            "signal": sinal,
            "confidence": round(confianca, 1),
            "score": round(score_final, 2),
            "reason": f"{razao} | Qualidade: {qualidade} | MTF: {'✓' if confirmado else '✗'} | ATR: {atr:.5f}",
            "strategy": self.name,
            "indicators": {
                "tendencia_5min": tendencia_5,
                "forca_tendencia": round(forca_tendencia, 2),
                "atr": round(atr, 5) if atr else None,
                "confirmado_mtf": confirmado,
                "qualidade": qualidade,
                "score_bruto": round(score_base, 2),
                "score_ajustado": round(score_ajustado, 2),
                **metrica
            }
        }
