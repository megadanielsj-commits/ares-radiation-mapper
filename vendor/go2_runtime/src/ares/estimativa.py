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
(n, Σc, Σg e Σg² por célula) e o termo `c·log(μ)` só é somado — num array
(células, S, b) em float64 — quando c > 0, pois com c = 0 ele é nulo.

Hipóteses detectáveis: `P(fonte)` vem da razão das evidências (média da
verossimilhança na grade de cada hipótese) com prior 0,5, mas H1 considera só
as hipóteses (célula, S, b) que o percurso feito seria capaz de distinguir do
fundo. O critério depende só das posições visitadas e da própria hipótese,
nunca das contagens observadas:

- excesso esperado de contagens `k·T·S·Σg_célula ≥ contagens_min_detectaveis`
  (padrão 5);
- desvio esperado contra o melhor fundo constante, na aproximação de sinal
  fraco, `k·T·S²·Σ(g − ḡ)²/b ≥ desvio_min_detectavel` (padrão 9, ~3σ). A
  parte constante de `S·g` ao longo do percurso se confunde com b: uma fonte
  distante de uma cobertura parcial soma quase o mesmo em todo ponto e não é
  distinguível de um fundo um pouco maior.

Sem essa restrição, células não visitadas, fontes fraquíssimas e fontes
distantes — cópias de H0 diante dos dados — puxam `P(fonte)` para um piso
artificial (≈ 0,2–0,3 só com fundo e cobertura parcial; o critério do excesso
de contagens sozinho ainda deixa ≈ 0,2–0,33). Sem nenhuma hipótese detectável
(ex.: uma única amostra), `p_fonte` é `None` (cobertura insuficiente). A
posterior de posição (marginal, moda, média, região de 95%) e o MAP conjunto
usam a mesma restrição quando há hipóteses detectáveis; senão, a grade toda.

Saídas espaciais: `marginal` e `regiao95["mascara"]` são listas indexadas
`[ix][iy]` (x primeiro), `nx` × `ny`. `regiao95["x0"]`, `["y0"]` são o canto
inferior esquerdo da grade (a borda da célula (0, 0), não o seu centro): a
célula (ix, iy) cobre `[x0 + ix·res, x0 + (ix+1)·res) × [y0 + iy·res,
y0 + (iy+1)·res)` e tem centro `(x0 + (ix+0,5)·res, y0 + (iy+0,5)·res)`.

A região de 95% é condicional ao modelo (fonte pontual estática, pose e
sincronização exatas); erros de odometria ou de tempo a tornam otimista.

Alertas: `s_no_limite` (MAP de S no limite inferior ou superior da grade),
`b_no_limite` (MAP de b no limite) e `fonte_na_borda` (moda na borda da área).

Entradas: amostras sem os atributos, não finitas, com |x| ou |y| > 1e4 m ou
com cps fora de [0; 1e6] são rejeitadas e contadas em `rejeitadas`.

`atualizar` e `resultado` compartilham um buffer e são serializadas por um
lock interno, podendo ser chamadas de threads diferentes.
"""
import math
import threading
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


COORDENADA_MAX_M = 1e4
CPS_MAX = 1e6


def _entrada_valida(a) -> Optional[Tuple[float, float, float]]:
    """`(x, y, cps)` como floats, ou `None` se a amostra for inválida."""
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
    return x, y, c


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
        s_min: float = 0.01,
        s_max: float = 1000.0,
        n_s: int = 40,
        b_min: float = 0.01,
        b_max: float = 2.0,
        n_b: int = 64,
        contagens_min_detectaveis: float = 5.0,
        desvio_min_detectavel: float = 9.0,
    ) -> None:
        self.centro = (float(centro[0]), float(centro[1]))
        self.lado_m = float(lado_m)
        self.resolucao_m = float(resolucao_m)
        self.altura_m = float(altura_m)
        self.cps_por_usvh = float(cps_por_usvh)
        self.exposicao_s = float(exposicao_s)
        self._kt = self.cps_por_usvh * self.exposicao_s
        self.contagens_min_detectaveis = float(contagens_min_detectaveis)
        self.desvio_min_detectavel = float(desvio_min_detectavel)
        self._lock = threading.Lock()

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
        self._soma_g2 = np.zeros(n_celulas, dtype=np.float64)
        self._soma_c = 0.0
        self._n = 0
        self.rejeitadas = 0

    # -- acumulação ---------------------------------------------------------

    def atualizar(self, a: Amostra) -> None:
        """Acumula uma amostra (posição do detector + cps) na grade."""
        entrada = _entrada_valida(a)
        with self._lock:
            if entrada is None:
                self.rejeitadas += 1
                return
            self._acumular(*entrada)

    def _acumular(self, x: float, y: float, c: float) -> None:
        dx = self._cx - x
        dy = self._cy - y
        g = 1.0 / (dx * dx + dy * dy + self.altura_m * self.altura_m)

        self._soma_g += g
        self._soma_g2 += g * g
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
        with self._lock:
            return self._resultado()

    def _resultado(self) -> dict:
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
                "b_no_limite": False,
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

        # hipóteses detectáveis dado o percurso (máscara (célula, S, b))
        detectavel = self._detectaveis()
        n_detectaveis = int(np.count_nonzero(detectavel))
        if 0 < n_detectaveis < detectavel.size:
            np.copyto(log_l1, -np.inf, where=~detectavel)

        # MAP conjunto (célula, S, b)
        i_map = int(np.argmax(log_l1))
        _, is_map, ib_map = np.unravel_index(i_map, log_l1.shape)
        maximo = float(log_l1.flat[i_map])

        # exp(log L1 − máx) no próprio buffer; massa por célula
        log_l1 -= maximo
        np.exp(log_l1, out=log_l1)
        massa = log_l1.reshape(n_celulas, -1).sum(axis=1)
        total = float(massa.sum())

        p_fonte: Optional[float] = None
        if n_detectaveis > 0:
            log_z1 = maximo + math.log(total) - math.log(n_detectaveis)
            log_l0 = self._soma_c * self._log_b - kt * n * self._b_grid
            m0 = float(np.max(log_l0))
            log_z0 = m0 + math.log(float(np.sum(np.exp(log_l0 - m0)))) - math.log(self.n_b)
            p_fonte = float(_probabilidade(log_z1, log_z0))

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
            "p_fonte": p_fonte,
            "x_map": float(self._xs[ix_moda]),
            "y_map": float(self._ys[iy_moda]),
            "s_map": float(self._s_grid[is_map]),
            "b_map": float(self._b_grid[ib_map]),
            "x_media": x_media,
            "y_media": y_media,
            "desvio_m": desvio_m,
            "regiao95": self._regiao95(marginal),
            "marginal": [[_arredondar(float(v)) for v in linha] for linha in marginal],
            "s_no_limite": bool(is_map in (0, self.n_s - 1)),
            "b_no_limite": bool(ib_map in (0, self.n_b - 1)),
            "fonte_na_borda": bool(borda),
        }

    def _detectaveis(self) -> np.ndarray:
        """Máscara (células, n_s, n_b) das hipóteses de H1 detectáveis.

        Depende só do percurso (Σg e Σg² por célula) e da própria hipótese,
        nunca das contagens observadas.
        """
        kt = self._kt
        n = self._n
        # excesso esperado de contagens: k·T·S·Σg
        excesso = (kt * self._soma_g)[:, None] * self._s_grid[None, :]
        # desvio esperado contra o melhor fundo constante (sinal fraco):
        # k·T·S²·Σ(g − ḡ)²/b; a parte constante de S·g se confunde com b
        variacao = np.maximum(self._soma_g2 - self._soma_g * self._soma_g / n, 0.0)
        desvio_b1 = (kt * variacao)[:, None] * (self._s_grid * self._s_grid)[None, :]
        desvio_b1[excesso < self.contagens_min_detectaveis] = 0.0
        return desvio_b1[:, :, None] >= self.desvio_min_detectavel * self._b_grid[None, None, :]

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
