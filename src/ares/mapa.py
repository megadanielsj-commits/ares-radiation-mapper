"""Mapa medido: grade de contagens do detector, com interpolação IDW local.

Observação estatística: o CPS (contagem do segundo), não o DR do aparelho —
o DR é uma média móvel de ~30 s e chega atrasado em relação à posição atual
do robô (mesma razão do estimador bayesiano em `estimativa.py`).

Convenção de grade igual à do estimador: `x0`, `y0` são o canto inferior
esquerdo (a borda da célula (0, 0), não o seu centro); a célula (ix, iy)
cobre `[x0 + ix·res, x0 + (ix+1)·res) × [y0 + iy·res, y0 + (iy+1)·res)` e tem
centro `(x0 + (ix+0,5)·res, y0 + (iy+0,5)·res)`. Arrays espaciais (`valores`)
são indexados `[ix][iy]` (x primeiro).

`adicionar` acumula `Σcps` e `n` por célula; `celulas()` devolve só as
células com pelo menos uma amostra, com a taxa média em µSv/h
(`Σcps/(k·T·n)`). `grade_interpolada()` estende essas médias por IDW
(potência 2) só até `raio_idw_m` de alguma célula medida — sem extrapolar —
com `None` no resto; o resultado é sempre serializável em JSON (sem NaN).

Amostras não finitas, fora da área ou com cps fora de [0, 1e6] são
rejeitadas silenciosamente e contadas em `rejeitadas`.
"""
import math
from typing import Optional, Tuple

import numpy as np

from .modelos import Amostra

COORDENADA_MAX_M = 1e4
CPS_MAX = 1e6


class MapaMedido:
    """Grade de medições do detector, com interpolação IDW local."""

    def __init__(
        self,
        centro: Tuple[float, float] = (0.0, 0.0),
        lado_m: float = 20.0,
        resolucao_m: float = 0.5,
        raio_idw_m: float = 1.5,
        cps_por_usvh: float = 2.6,
        exposicao_s: float = 1.0,
    ) -> None:
        self.centro = (float(centro[0]), float(centro[1]))
        self.lado_m = float(lado_m)
        self.resolucao_m = float(resolucao_m)
        self.raio_idw_m = float(raio_idw_m)
        self.cps_por_usvh = float(cps_por_usvh)
        self.exposicao_s = float(exposicao_s)
        self._kt = self.cps_por_usvh * self.exposicao_s

        self.nx = max(1, round(self.lado_m / self.resolucao_m))
        self.ny = self.nx

        cx, cy = self.centro
        self.x0 = cx - self.lado_m / 2.0
        self.y0 = cy - self.lado_m / 2.0
        self._xs = self.x0 + (np.arange(self.nx) + 0.5) * self.resolucao_m
        self._ys = self.y0 + (np.arange(self.ny) + 0.5) * self.resolucao_m
        # centros das células achatados na ordem (ix, iy), igual a estimativa.py
        self._cx = np.repeat(self._xs, self.ny)
        self._cy = np.tile(self._ys, self.nx)

        self._soma_cps = np.zeros((self.nx, self.ny), dtype=np.float64)
        self._n = np.zeros((self.nx, self.ny), dtype=np.int64)
        self.rejeitadas = 0

    # -- acumulação ---------------------------------------------------------

    def adicionar(self, a: Amostra) -> None:
        """Acumula uma amostra (posição do detector + cps) na célula da grade."""
        entrada = self._entrada_valida(a)
        if entrada is None:
            self.rejeitadas += 1
            return
        ix, iy, c = entrada
        self._soma_cps[ix, iy] += c
        self._n[ix, iy] += 1

    def _entrada_valida(self, a) -> Optional[Tuple[int, int, float]]:
        try:
            x = float(a.x)
            y = float(a.y)
            c = float(a.cps)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(c)):
            return None
        if abs(x) > COORDENADA_MAX_M or abs(y) > COORDENADA_MAX_M:
            return None
        if c < 0.0 or c > CPS_MAX:
            return None
        ix = int(math.floor((x - self.x0) / self.resolucao_m))
        iy = int(math.floor((y - self.y0) / self.resolucao_m))
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return None
        return ix, iy, c

    # -- resultado ------------------------------------------------------------

    def celulas(self) -> list:
        """Lista de `{x, y, media, n}` só das células com alguma amostra."""
        ix_idx, iy_idx = np.nonzero(self._n)
        n_vals = self._n[ix_idx, iy_idx]
        media_vals = self._soma_cps[ix_idx, iy_idx] / (self._kt * n_vals)
        saida = []
        for ix, iy, n, media in zip(ix_idx, iy_idx, n_vals, media_vals):
            saida.append(
                {
                    "x": float(self._xs[ix]),
                    "y": float(self._ys[iy]),
                    "media": float(media),
                    "n": int(n),
                }
            )
        return saida

    def grade_interpolada(self) -> dict:
        """Grade completa com IDW (potência 2) só até `raio_idw_m`; `None` fora.

        A grade é regular, então a distância entre a célula alvo e uma
        célula medida depende só do deslocamento (`di`, `dj`) entre elas, não
        das posições absolutas. Em vez de uma matriz (células × medidas)
        completa (cara quando quase toda a grade está medida), somamos, para
        cada deslocamento dentro do raio, a contribuição da grade toda
        deslocada — `O(nx·ny·nº de deslocamentos)`, independente de quantas
        células estão medidas.
        """
        medido = self._n > 0
        with np.errstate(invalid="ignore", divide="ignore"):
            valor_medido = np.where(medido, self._soma_cps / (self._kt * self._n), 0.0)

        soma_peso = np.zeros((self.nx, self.ny), dtype=np.float64)
        soma_peso_val = np.zeros((self.nx, self.ny), dtype=np.float64)

        if medido.any():
            k = int(math.ceil(self.raio_idw_m / self.resolucao_m))
            raio2 = self.raio_idw_m * self.raio_idw_m
            for di in range(-k, k + 1):
                for dj in range(-k, k + 1):
                    if di == 0 and dj == 0:
                        continue
                    dist2 = (di * di + dj * dj) * self.resolucao_m * self.resolucao_m
                    if dist2 > raio2:
                        continue
                    peso = 1.0 / dist2

                    # célula alvo (ix, iy) recebe da célula medida (ix+di, iy+dj)
                    src_i0, src_i1, dst_i0, dst_i1 = self._fatia(di, self.nx)
                    src_j0, src_j1, dst_j0, dst_j1 = self._fatia(dj, self.ny)
                    if src_i0 >= src_i1 or src_j0 >= src_j1:
                        continue

                    fonte_medida = medido[src_i0:src_i1, src_j0:src_j1]
                    fonte_valor = valor_medido[src_i0:src_i1, src_j0:src_j1]
                    soma_peso[dst_i0:dst_i1, dst_j0:dst_j1] += peso * fonte_medida
                    soma_peso_val[dst_i0:dst_i1, dst_j0:dst_j1] += (
                        peso * fonte_medida * fonte_valor
                    )

        tem_vizinho = soma_peso > 0.0
        with np.errstate(invalid="ignore", divide="ignore"):
            interpolado = np.where(tem_vizinho, soma_peso_val / soma_peso, np.nan)

        # célula medida usa seu próprio valor, sem interpolação (peso infinito)
        valores_grade = np.where(medido, valor_medido, interpolado)

        valores = [
            [
                None if not math.isfinite(v) else float(v)
                for v in valores_grade[ix]
            ]
            for ix in range(self.nx)
        ]

        return {
            "x0": float(self.x0),
            "y0": float(self.y0),
            "res": self.resolucao_m,
            "nx": self.nx,
            "ny": self.ny,
            "valores": valores,
        }

    @staticmethod
    def _fatia(deslocamento: int, tamanho: int) -> Tuple[int, int, int, int]:
        """Índices `(src0, src1, dst0, dst1)` para copiar a grade deslocada.

        `destino[dst0:dst1] = fonte[src0:src1]` corresponde a
        `destino[i] = fonte[i + deslocamento]` para todo `i` válido.
        """
        if deslocamento >= 0:
            return deslocamento, tamanho, 0, tamanho - deslocamento
        return 0, tamanho + deslocamento, -deslocamento, tamanho
