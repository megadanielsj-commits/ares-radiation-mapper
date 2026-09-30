"""Radiacode through the independent USB service, using ARES's WS contract."""
import math
import time

from .fs5000 import ClienteFS5000


class ClienteRadiacode(ClienteFS5000):
    def __init__(self, url="ws://127.0.0.1:1098/ws", aparelho=None, **kwargs):
        super().__init__(url=url, aparelho=aparelho, **kwargs)
        self._last_session = None
        self._last_sequence = 0
        self.descartadas = 0

    def estado(self):
        return dict(super().estado(), modelo="Radiacode 110", source="radiacode_usb",
                    dose_conversion_verified=False, descartadas=self.descartadas)

    def _processar_leitura(self, evento):
        dados = evento.get("dados")
        try:
            if not isinstance(dados, dict) or evento.get("aparelho_id") != self._aparelho_id:
                return
            ts = float(dados["ts"])
            if not math.isfinite(ts) or not -.1 <= time.time()-ts <= 3:
                raise ValueError("leitura antiga")
            cps = dados["cps"]
            if isinstance(cps, bool) or not isinstance(cps, int) or cps < 0:
                raise ValueError("CPS precisa ser contagem inteira de RawData")
            if dados["exposure_s"] != 1.0 or dados["timing_quality"] != "live_receipt":
                raise ValueError("exposição/tempo ambíguo")
            session, sequence = dados["session_id"], int(dados["sequence"])
            if session == self._last_session and sequence <= self._last_sequence:
                raise ValueError("leitura repetida")
            self._last_session, self._last_sequence = session, sequence
            dados = dict(dados, dose_usv=None, cpm=60*cps)
            super()._processar_leitura(dict(evento, dados=dados))
        except (KeyError, ValueError, TypeError):
            self.descartadas += 1
