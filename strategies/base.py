from abc import ABC, abstractmethod

class Strategy(ABC):
    @abstractmethod
    def analyze(self, symbol: str, data_1min: list, data_5min: list) -> dict:
        """
        Retorna:
        {
            "symbol": str,
            "signal": "CALL" or "PUT" or None,
            "confidence": float (0-100),
            "score": float,
            "reason": str,
            "strategy": str,
            "indicators": dict (opcional)
        }
        """
        pass
