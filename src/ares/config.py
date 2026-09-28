"""Configuração da aplicação: defaults e leitura do ambiente."""
import os
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
    go2_aes_key: Optional[str] = None
    offset_detector: tuple = field(default=(0.0, 0.0))
    latencia_leitura_s: float = 0.5
    lacuna_pose_max_s: float = 0.5
    lado_area_m: float = 20.0
    resolucao_estimador_m: float = 0.25
    resolucao_mapa_m: float = 0.5
    altura_fonte_m: float = 0.25
    vx_max: float = 0.5
    vy_max: float = 0.3
    vyaw_max: float = 1.0
    watchdog_s: float = 0.5

    def __post_init__(self) -> None:
        if self.modo not in MODOS_VALIDOS:
            raise ValueError(
                f"modo inválido: {self.modo!r} (esperado um de {MODOS_VALIDOS})"
            )

        self._validar_positivo("porta", self.porta)
        self._validar_positivo("latencia_leitura_s", self.latencia_leitura_s)
        self._validar_positivo("lacuna_pose_max_s", self.lacuna_pose_max_s)
        self._validar_positivo("lado_area_m", self.lado_area_m)
        self._validar_positivo("resolucao_estimador_m", self.resolucao_estimador_m)
        self._validar_positivo("resolucao_mapa_m", self.resolucao_mapa_m)
        self._validar_positivo("altura_fonte_m", self.altura_fonte_m)
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
        if "GO2_AES_KEY" in env:
            kwargs["go2_aes_key"] = env["GO2_AES_KEY"]
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
