from abc import ABC, abstractmethod


class Strategy(ABC):
    """
    Contrato comum a todas as estratégias do motor.

    IMPORTANTE — formato dos dados de entrada:
    O engine._fetch_data() deixou de devolver uma lista de closes e passou a
    devolver um dicionário com duas vistas do mesmo conjunto de candles:

        data = {
            "closes": [c1, c2, ..., cN],                       # float
            "ohlc": [
                {"open": o, "high": h, "low": l, "close": c},
                ...
            ]
        }

    • Estratégias que só precisam de preço de fecho (Breakout, Momentum,
      Reversal, Trend) usam `data["closes"]`.
    • Estratégias que detectam padrões de vela (PriceAction) usam
      `data["ohlc"]` — porque corpo e pavio exigem open/high/low reais.

    IMPORTANTE — escala de confidence:
    Todas as estratégias devem usar a mesma fórmula para que o _decide()
    possa comparar sinais de estratégias diferentes sem viés:

        confidence = min(95, max(20, score * 20))

    Não inventar fórmulas próprias (score*25, score*18+força*5, etc.) —
    isso fazia com que a estratégia com a fórmula mais generosa ganhasse
    desempates que não devia ganhar.
    """

    @abstractmethod
    def analyze(self, symbol: str, data_1min: dict, data_5min: dict) -> dict | None:
        """
        Recebe:
            symbol:    par (ex.: "EUR/USD")
            data_1min: {"closes": [...], "ohlc": [...]}
            data_5min: {"closes": [...], "ohlc": [...]}

        Devolve None (sem sinal) ou:

            {
                "symbol":     str,
                "signal":     "CALL" | "PUT",
                "confidence": float,   # 0-100, escala normalizada
                "score":      float,   # 0-5 aprox.
                "reason":     str,
                "strategy":   str,
                "tempo_exp":  int,     # minutos, mínimo 3
                "indicators": dict,    # opcional; pode incluir "qualidade"
            }
        """
        pass
