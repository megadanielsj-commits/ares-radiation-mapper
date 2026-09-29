"""Estimador bayesiano em grade da posição da fonte de radiação.

Observação estatística: a contagem de 1 s (`cps`) do detector, que no FS-5000
real é Poisson e independente entre segundos (o DR é uma média móvel de ~30 s,
fortemente autocorrelacionada, e só serve para exibição).

Modelo: taxa esperada no detector `μ = b + S·g`, com `g = 1/(r² + h²)`,
S em µSv/h a 1 m e b o fundo em µSv/h; contagem `c ~ Poisson(k·T·μ)`, com
k = `cps_por_usvh` e T = `exposicao_s`.

Hipóteses:

- H1 (existe fonte): célula (x, y) × S × b, S e b em grades log-espaçadas,
  prior uniforme na grade;
- H0 (só fundo): b na mesma grade.

Log-verossimilhança (constantes iguais em H0 e H1 descartadas):

    log L1(célula, S, b) = Σ_i c_i·log(b + S·g_i) − k·T·(b·n + S·Σ_i g_i)
    log L0(b)            = (Σ_i c_i)·log b        − k·T·b·n

A acumulação é incremental: o termo linear usa estatísticas suficientes
(n, Σc e Σg por célula) e o termo `c·log(μ)` só é somado — num array
(células, S, b) em float64 — quando c > 0, pois com c = 0 ele é nulo.
`P(fonte)` vem da razão das evidências (média da verossimilhança na grade de
cada hipótese) com prior 0,5.

Limite inferior de S (`s_min`, padrão 0,1 µSv/h a 1 m): hipóteses de H1 com S
pequeno demais para produzir contagens distinguíveis do fundo são, na
prática, cópias de H0 e fixam um piso para `P(fonte)` quando não há fonte
(≈ fração da grade de S indistinguível do fundo). Com `s_min` = 0,01 esse
piso chega a ~0,2 numa missão de 10 min só de fundo; com 0,1 fica abaixo de
~0,12. Uma fonte de 0,1 µSv/h a 1 m já é mais fraca que o fundo típico
(~0,17 µSv/h) a 1 m dela.
"""
import math
from typing import Optional, Tuple

import numpy as np

from .modelos import Amostra


def _arredondar(valor: float, digitos: int = 6) -> float:
    """Arredonda `valor` para `digitos` algarismos significativos."""
    if valor == 0.0 or not math.isfinite(valor):
        return float(valor)
    casas = digitos - 1 - math.floor(math.log10(abs(valor)))
    return float(round(valor, casas))


def _probabilidade(log_z1: float, log_z0: float) -> float:
    """`1 / (1 + exp(log_z0 − log_z1))` sem overflow."""
    delta = log_z0 - log_z1
    if delta >= 0.0:
        e = math.exp(-delta)
        return e / (1.0 + e)
    return 1.0 / (1.0 + math.exp(delta))


def _contagem_valida(valor) -> Optional[float]:
    """Contagem como float, ou `None` se não for finita ou for negativa."""
    try:
        c = float(valor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c) or c < 0.0:
        return None
    return c


class EstimadorGrade:
    """Estimador bayesiano em grade da posição (e intensidade) da fonte."""

    def __init__(
        self,
        centro: Tuple[float, float] = (0.0, 0.0),
        lado_m: float = 20.0,
        resolucao_m: float = 0.5,
        altura_m: float = 0.25,
        cps_por_usvh: float = 2.6,
        exposicao_s: float = 1.0,
        s_min: float = 0.1,
        s_max: float = 1000.0,
        n_s: int = 40,
        b_min: float = 0.01,
        b_max: float = 2.0,
        n_b: int = 64,
    ) -> None:
        self.centro = (float(centro[0]), float(centro[1]))
        self.lado_m = float(lado_m)
        self.resolucao_m = float(resolucao_m)
        self.altura_m = float(altura_m)
        self.cps_por_usvh = float(cps_por_usvh)
        self.exposicao_s = float(exposicao_s)
        self._kt = self.cps_por_usvh * self.exposicao_s

        self.nx = max(1, round(lado_m / resolucao_m))
        self.ny = self.nx
        self.n_s = int(n_s)
        self.n_b = int(n_b)

        cx, cy = self.centro
        self.x0 = cx - self.lado_m / 2.0
        self.y0 = cy - self.lado_m / 2.0
        self._xs = self.x0 + (np.arange(self.nx) + 0.5) * self.resolucao_m
        self._ys = self.y0 + (np.arange(self.ny) + 0.5) * self.resolucao_m
        # centros das células achatados na ordem (ix, iy)
        self._cx = np.repeat(self._xs, self.ny)
        self._cy = np.tile(self._ys, self.nx)

        self._s_grid = np.logspace(math.log10(s_min), math.log10(s_max), self.n_s)
        self._b_grid = np.logspace(math.log10(b_min), math.log10(b_max), self.n_b)
        self._log_b = np.log(self._b_grid)

        n_celulas = self.nx * self.ny
        # Σ c_i·log(b + S·g_i) sobre as amostras com c_i > 0
        self._termo_log = np.zeros((n_celulas, self.n_s, self.n_b), dtype=np.float64)
        # buffer reaproveitado em `atualizar` e `resultado`
        self._buf = np.empty_like(self._termo_log)
        self._soma_g = np.zeros(n_celulas, dtype=np.float64)
        self._soma_c = 0.0
        self._n = 0
        self.rejeitadas = 0

    # -- acumulação ---------------------------------------------------------

    def atualizar(self, a: Amostra) -> None:
        """Acumula uma amostra (posição do detector + cps) na grade."""
        c = _contagem_valida(getattr(a, "cps", None))
        try:
            x = float(a.x)
            y = float(a.y)
        except (TypeError, ValueError):
            x = y = math.nan
        if c is None or not (math.isfinite(x) and math.isfinite(y)):
            self.rejeitadas += 1
            return

        dx = self._cx - x
        dy = self._cy - y
        g = 1.0 / (dx * dx + dy * dy + self.altura_m * self.altura_m)

        self._soma_g += g
        self._soma_c += c
        self._n += 1

        if c > 0.0:
            sg = g[:, None] * self._s_grid[None, :]
            buf = self._buf
            np.add(sg[:, :, None], self._b_grid[None, None, :], out=buf)
            np.log(buf, out=buf)
            if c != 1.0:
                buf *= c
            self._termo_log += buf

    # -- resultado ----------------------------------------------------------

    def resultado(self) -> dict:
        """Resumo serializável em JSON (sem NaN) do estado atual."""
        if self._n == 0:
            uniforme = _arredondar(1.0 / (self.nx * self.ny))
            return {
                "n": 0,
                "rejeitadas": self.rejeitadas,
                "p_fonte": None,
                "x_map": None,
                "y_map": None,
                "s_map": None,
                "b_map": None,
                "x_media": None,
                "y_media": None,
                "desvio_m": None,
                "regiao95": None,
                "marginal": [[uniforme] * self.ny for _ in range(self.nx)],
                "s_no_limite": False,
                "fonte_na_borda": False,
            }

        kt = self._kt
        n = self._n
        n_celulas = self.nx * self.ny

        # log L1 = termo_log − k·T·(b·n + S·Σg), montado no buffer
        linear_b = kt * n * self._b_grid  # (n_b,)
        linear_s = kt * self._soma_g[:, None] * self._s_grid[None, :]  # (células, n_s)
        log_l1 = self._buf
        np.subtract(self._termo_log, linear_s[:, :, None], out=log_l1)
        log_l1 -= linear_b[None, None, :]

        # MAP conjunto (célula, S, b)
        i_map = int(np.argmax(log_l1))
        _, is_map, ib_map = np.unravel_index(i_map, log_l1.shape)
        maximo = float(log_l1.flat[i_map])

        # exp(log L1 − máx) no próprio buffer; massa por célula
        log_l1 -= maximo
        np.exp(log_l1, out=log_l1)
        massa = log_l1.reshape(n_celulas, -1).sum(axis=1)
        total = float(massa.sum())
        n_hip1 = n_celulas * self.n_s * self.n_b
        log_z1 = maximo + math.log(total) - math.log(n_hip1)

        log_l0 = self._soma_c * self._log_b - kt * n * self._b_grid
        m0 = float(np.max(log_l0))
        log_z0 = m0 + math.log(float(np.sum(np.exp(log_l0 - m0)))) - math.log(self.n_b)

        p_fonte = _probabilidade(log_z1, log_z0)

        marginal = (massa / total).reshape(self.nx, self.ny)
        ix_moda, iy_moda = np.unravel_index(int(np.argmax(marginal)), marginal.shape)

        px = marginal.sum(axis=1)
        py = marginal.sum(axis=0)
        x_media = float(np.dot(px, self._xs))
        y_media = float(np.dot(py, self._ys))
        var = float(np.dot(px, (self._xs - x_media) ** 2)) + float(
            np.dot(py, (self._ys - y_media) ** 2)
        )
        desvio_m = math.sqrt(max(0.0, var))

        borda = ix_moda in (0, self.nx - 1) or iy_moda in (0, self.ny - 1)

        return {
            "n": n,
            "rejeitadas": self.rejeitadas,
            "p_fonte": float(p_fonte),
            "x_map": float(self._xs[ix_moda]),
            "y_map": float(self._ys[iy_moda]),
            "s_map": float(self._s_grid[is_map]),
            "b_map": float(self._b_grid[ib_map]),
            "x_media": x_media,
            "y_media": y_media,
            "desvio_m": desvio_m,
            "regiao95": self._regiao95(marginal),
            "marginal": [[_arredondar(float(v)) for v in linha] for linha in marginal],
            "s_no_limite": bool(is_map == self.n_s - 1),
            "fonte_na_borda": bool(borda),
        }

    def _regiao95(self, marginal: np.ndarray) -> dict:
        """Menor conjunto de células cuja massa marginal soma ≥ 95%."""
        plano = marginal.reshape(-1)
        ordem = np.argsort(plano)[::-1]
        acumulado = np.cumsum(plano[ordem])
        k = min(int(np.searchsorted(acumulado, 0.95)) + 1, plano.size)

        mascara = np.zeros(plano.size, dtype=bool)
        mascara[ordem[:k]] = True
        mascara = mascara.reshape(self.nx, self.ny)

        return {
            "x0": float(self.x0),
            "y0": float(self.y0),
            "res": self.resolucao_m,
            "nx": self.nx,
            "ny": self.ny,
            "mascara": [[bool(v) for v in linha] for linha in mascara],
        }
