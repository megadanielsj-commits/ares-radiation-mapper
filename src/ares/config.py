"""Configuração da aplicação: defaults e leitura do ambiente."""
import os
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

MODOS_VALIDOS = ("simulacao", "real")


@dataclass
class Config:
    """Configuração central da aplicação, com defaults e validação."""

    modo: str = "simulacao"
    host: str = "127.0.0.1"
    porta: int = 8000
    dados: str = "dados"
    fs5000_url: str = "ws://127.0.0.1:1096/ws"
    fs5000_aparelho: Optional[str] = None
    fonte_radiacao: str = "padrao"
    radiacode_url: str = "ws://127.0.0.1:1098/ws"
    radiacode_cps_por_usvh: Optional[float] = None
    go2_aes_key: Optional[str] = None
    offset_detector: tuple = field(default=(0.0, 0.0))
    latencia_leitura_s: float = 0.5
    lacuna_pose_max_s: float = 0.5
    lado_area_m: float = 20.0
    resolucao_estimador_m: float = 0.5
    resolucao_mapa_m: float = 0.5
    altura_fonte_m: float = 0.25
    cps_por_usvh: float = 2.6
    exposicao_s: float = 1.0
    vx_max: float = 0.5
    vy_max: float = 0.3
    vyaw_max: float = 1.0
    watchdog_s: float = 0.5

    def __post_init__(self) -> None:
        if self.modo not in MODOS_VALIDOS:
            raise ValueError(
                f"modo inválido: {self.modo!r} (esperado um de {MODOS_VALIDOS})"
            )

        if self.fonte_radiacao not in ("padrao", "radiacode"):
            raise ValueError("fonte_radiacao deve ser padrao ou radiacode")
        if self.radiacode_cps_por_usvh is not None:
            if not math.isfinite(self.radiacode_cps_por_usvh):
                raise ValueError("radiacode_cps_por_usvh deve ser finito")
            self._validar_positivo("radiacode_cps_por_usvh", self.radiacode_cps_por_usvh)
        self._validar_positivo("porta", self.porta)
        self._validar_positivo("latencia_leitura_s", self.latencia_leitura_s)
        self._validar_positivo("lacuna_pose_max_s", self.lacuna_pose_max_s)
        self._validar_positivo("lado_area_m", self.lado_area_m)
        self._validar_positivo("resolucao_estimador_m", self.resolucao_estimador_m)
        self._validar_positivo("resolucao_mapa_m", self.resolucao_mapa_m)
        self._validar_positivo("altura_fonte_m", self.altura_fonte_m)
        self._validar_positivo("cps_por_usvh", self.cps_por_usvh)
        self._validar_positivo("exposicao_s", self.exposicao_s)
        self._validar_positivo("vx_max", self.vx_max)
        self._validar_positivo("vy_max", self.vy_max)
        self._validar_positivo("vyaw_max", self.vyaw_max)
        self._validar_positivo("watchdog_s", self.watchdog_s)

    @staticmethod
    def _validar_positivo(nome: str, valor) -> None:
        if valor <= 0:
            raise ValueError(f"{nome} deve ser positivo, recebido: {valor!r}")

    @classmethod
    def de_ambiente(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        """Constrói a configuração a partir de variáveis de ambiente."""
        if env is None:
            env = os.environ

        kwargs = {}

        if "ARES_MODO" in env:
            kwargs["modo"] = env["ARES_MODO"]
        if "ARES_HOST" in env:
            kwargs["host"] = env["ARES_HOST"]
        if "ARES_PORTA" in env:
            kwargs["porta"] = int(env["ARES_PORTA"])
        if "ARES_DADOS" in env:
            kwargs["dados"] = env["ARES_DADOS"]
        if "FS5000_URL" in env:
            kwargs["fs5000_url"] = env["FS5000_URL"]
        if "FS5000_APARELHO" in env:
            kwargs["fs5000_aparelho"] = env["FS5000_APARELHO"]
        if "ARES_FONTE_RADIACAO" in env:
            kwargs["fonte_radiacao"] = env["ARES_FONTE_RADIACAO"]
        if "ARES_RADIACODE_URL" in env:
            kwargs["radiacode_url"] = env["ARES_RADIACODE_URL"]
        if env.get("ARES_RADIACODE_CPS_POR_USVH"):
            kwargs["radiacode_cps_por_usvh"] = float(env["ARES_RADIACODE_CPS_POR_USVH"])
        if "ARES_LATENCIA_LEITURA_S" in env:
            kwargs["latencia_leitura_s"] = float(env["ARES_LATENCIA_LEITURA_S"])
        if "GO2_AES_KEY" in env:
            kwargs["go2_aes_key"] = env["GO2_AES_KEY"] or None
        if "ARES_OFFSET_DETECTOR" in env:
            kwargs["offset_detector"] = cls._parsear_offset(
                env["ARES_OFFSET_DETECTOR"]
            )

        return cls(**kwargs)

    @staticmethod
    def _parsear_offset(valor: str) -> tuple:
        partes = valor.split(",")
        if len(partes) != 2:
            raise ValueError(
                f"ARES_OFFSET_DETECTOR deve ter o formato 'dx,dy', recebido: {valor!r}"
            )
        dx, dy = partes
        return (float(dx), float(dy))
