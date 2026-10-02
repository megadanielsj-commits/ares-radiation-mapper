"""Campo de radiação simulado: fundo constante + fonte pontual opcional."""
from typing import Optional, Tuple


class CampoRadiacao:
    """Taxa de dose em cada ponto: fundo + fonte pontual em 1/(r²+h²).

    A fonte, quando definida, tem intensidade `s_usvh_1m` em µSv/h a 1 m de
    distância. `altura_m` é a altura relativa entre detector e fonte, usada
    para evitar singularidade quando o detector passa bem por cima da fonte.
    """

    def __init__(self, fundo_usvh: float = 0.15, altura_m: float = 0.25) -> None:
        self.fundo_usvh = fundo_usvh
        self.altura_m = altura_m
        self._fonte: Optional[Tuple[float, float, float]] = None

    def definir_fonte(self, x: float, y: float, s_usvh_1m: float) -> None:
        """Posiciona (ou reposiciona) a fonte pontual."""
        self._fonte = (x, y, s_usvh_1m)

    def remover_fonte(self) -> None:
        """Remove a fonte; o campo volta a ser só o fundo."""
        self._fonte = None

    @property
    def fonte(self) -> Optional[Tuple[float, float, float]]:
        """`(x, y, s_usvh_1m)` da fonte atual, ou `None` se não houver."""
        return self._fonte

    def taxa(self, x: float, y: float) -> float:
        """Taxa de dose esperada em `(x, y)`, em µSv/h."""
        if self._fonte is None:
            return self.fundo_usvh
        fx, fy, s = self._fonte
        r2 = (x - fx) ** 2 + (y - fy) ** 2
        return self.fundo_usvh + s / (r2 + self.altura_m**2)
