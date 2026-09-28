"""Estimador bayesiano em grade da posição da fonte de radiação.

Mantém, em uma grade de células (x, y) × intensidade S × fundo b, a
log-verossimilhança acumulada de cada hipótese (H1: existe fonte) e, em
paralelo, de um modelo só-fundo (H0). A verossimilhança usa uma Student-t
robusta (ν configurável) sobre a taxa de dose medida, com σ crescendo com a
taxa esperada (`sigma0` + fração da taxa). `P(fonte)` vem da razão de
evidências de Bayes H1 vs H0 com prior 0,5.
"""
import math
from typing import Optional, Tuple

import numpy as np

from .modelos import Amostra


def _logsumexp(a: np.ndarray) -> float:
    """log-sum-exp numericamente estável sobre todos os elementos de `a`."""
    m = np.max(a)
    if not np.isfinite(m):
        # todos -inf (ou algum +inf, que não deveria ocorrer aqui)
        return float(m)
    return float(m + np.log(np.sum(np.exp(a - m))))


def _arredondar(valor: float, digitos: int = 6) -> float:
    """Arredonda `valor` para `digitos` algarismos significativos."""
    if valor == 0.0 or not math.isfinite(valor):
        return float(valor)
    casas = digitos - 1 - math.floor(math.log10(abs(valor)))
    return float(round(valor, casas))


class EstimadorGrade:
    """Estimador bayesiano em grade da posição (e intensidade) da fonte."""

    def __init__(
        self,
        centro: Tuple[float, float] = (0.0, 0.0),
        lado_m: float = 20.0,
        resolucao_m: float = 0.25,
        altura_m: float = 0.25,
        s_min: float = 0.01,
        s_max: float = 1000.0,
        n_s: int = 40,
        b_min: float = 0.03,
        b_max: float = 1.0,
        n_b: int = 8,
        sigma0: float = 0.03,
        fracao: float = 0.12,
        nu: float = 4.0,
    ) -> None:
        self.centro = centro
        self.lado_m = lado_m
        self.resolucao_m = resolucao_m
        self.altura_m = altura_m
        self.sigma0 = sigma0
        self.fracao = fracao
        self.nu = nu

        self.nx = max(1, round(lado_m / resolucao_m))
        self.ny = self.nx
        self.n_s = n_s
        self.n_b = n_b

        cx, cy = centro
        self.x0 = cx - lado_m / 2.0
        self.y0 = cy - lado_m / 2.0
        self._xs = self.x0 + (np.arange(self.nx) + 0.5) * resolucao_m
        self._ys = self.y0 + (np.arange(self.ny) + 0.5) * resolucao_m

        self._s_grid = np.logspace(math.log10(s_min), math.log10(s_max), n_s)
        self._b_grid = np.logspace(math.log10(b_min), math.log10(b_max), n_b)

        self._log_lik = np.zeros((self.nx, self.ny, n_s, n_b), dtype=np.float64)
        self._log_lik0 = np.zeros((n_b,), dtype=np.float64)
        self._n = 0

        self._log_norm_const = (
            math.lgamma((nu + 1.0) / 2.0)
            - math.lgamma(nu / 2.0)
            - 0.5 * math.log(nu * math.pi)
        )
        self._meio_gl = -(nu + 1.0) / 2.0
        self._inv_nu = 1.0 / nu

        # buffers reaproveitados a cada `atualizar` para evitar realocação da
        # grade completa (nx, ny, n_s, n_b) a cada amostra.
        self._buf_sdenom = np.empty((self.nx, self.ny, n_s), dtype=np.float64)
        self._buf_mu = np.empty((self.nx, self.ny, n_s, n_b), dtype=np.float64)
        self._buf_sigma = np.empty((self.nx, self.ny, n_s, n_b), dtype=np.float64)
        self._buf_z = np.empty((self.nx, self.ny, n_s, n_b), dtype=np.float64)

        self._s_grid_bc = self._s_grid[None, None, :]
        self._b_grid_bc = self._b_grid[None, None, None, :]

    # -- verossimilhança ----------------------------------------------------

    def _logpdf_t_h0(self, x: float, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
        z = (x - mu) / sigma
        return self._log_norm_const - np.log(sigma) + self._meio_gl * np.log1p(
            z * z * self._inv_nu
        )

    def atualizar(self, a: Amostra) -> None:
        """Acumula a log-verossimilhança de uma amostra na grade (H1 e H0)."""
        dx = self._xs[:, None] - a.x
        dy = self._ys[None, :] - a.y
        denom = dx * dx + dy * dy + self.altura_m**2  # (nx, ny)

        # sdenom = S / denom, forma (nx, ny, n_s)
        np.divide(self._s_grid_bc, denom[:, :, None], out=self._buf_sdenom)

        # mu = b + sdenom, forma (nx, ny, n_s, n_b)
        np.add(self._buf_sdenom[:, :, :, None], self._b_grid_bc, out=self._buf_mu)

        # sigma = sqrt(sigma0² + (fracao·mu)²)
        np.multiply(self._buf_mu, self.fracao, out=self._buf_sigma)
        np.multiply(self._buf_sigma, self._buf_sigma, out=self._buf_sigma)
        self._buf_sigma += self.sigma0**2
        np.sqrt(self._buf_sigma, out=self._buf_sigma)

        # z = (x - mu) / sigma
        np.subtract(a.dr_usvh, self._buf_mu, out=self._buf_z)
        self._buf_z /= self._buf_sigma
        np.multiply(self._buf_z, self._buf_z, out=self._buf_z)  # z²
        self._buf_z *= self._inv_nu
        np.log1p(self._buf_z, out=self._buf_z)
        self._buf_z *= self._meio_gl

        # -log(sigma), reaproveitando o buffer de sigma
        np.log(self._buf_sigma, out=self._buf_sigma)
        self._buf_z -= self._buf_sigma
        self._buf_z += self._log_norm_const

        self._log_lik += self._buf_z

        mu0 = self._b_grid
        sigma0 = np.sqrt(self.sigma0**2 + (self.fracao * mu0) ** 2)
        self._log_lik0 += self._logpdf_t_h0(a.dr_usvh, mu0, sigma0)

        self._n += 1

    # -- resultado ------------------------------------------------------

    def resultado(self) -> dict:
        """Resumo serializável em JSON do estado atual do estimador."""
        n_hipoteses_h1 = self.nx * self.ny * self.n_s * self.n_b

        if self._n == 0:
            marginal_uniforme = [
                [_arredondar(1.0 / (self.nx * self.ny)) for _ in range(self.ny)]
                for _ in range(self.nx)
            ]
            return {
                "n": 0,
                "p_fonte": None,
                "x_map": None,
                "y_map": None,
                "s_map": None,
                "b_map": None,
                "x_media": None,
                "y_media": None,
                "desvio_m": None,
                "regiao95": None,
                "marginal": marginal_uniforme,
            }

        log_z1 = _logsumexp(self._log_lik) - math.log(n_hipoteses_h1)
        log_z0 = _logsumexp(self._log_lik0) - math.log(self.n_b)

        delta = log_z0 - log_z1
        if delta > 700:
            p_fonte = 0.0
        elif delta < -700:
            p_fonte = 1.0
        else:
            p_fonte = 1.0 / (1.0 + math.exp(delta))

        # MAP sobre a grade completa (x, y, S, b)
        idx_map = np.unravel_index(np.argmax(self._log_lik), self._log_lik.shape)
        ix_map, iy_map, is_map, ib_map = idx_map
        x_map = float(self._xs[ix_map])
        y_map = float(self._ys[iy_map])
        s_map = float(self._s_grid[is_map])
        b_map = float(self._b_grid[ib_map])

        # marginal em (x, y): log-sum-exp sobre (S, b), normalizada
        log_marg_xy = np.logaddexp.reduce(
            self._log_lik.reshape(self.nx, self.ny, -1), axis=2
        )
        log_marg_xy = log_marg_xy - _logsumexp(log_marg_xy)
        marginal_xy = np.exp(log_marg_xy)
        marginal_xy /= marginal_xy.sum()  # normaliza numericamente também

        x_media = float(np.sum(marginal_xy.sum(axis=1) * self._xs))
        y_media = float(np.sum(marginal_xy.sum(axis=0) * self._ys))
        var_x = float(np.sum(marginal_xy.sum(axis=1) * (self._xs - x_media) ** 2))
        var_y = float(np.sum(marginal_xy.sum(axis=0) * (self._ys - y_media) ** 2))
        desvio_m = float(math.sqrt(max(0.0, var_x + var_y)))

        regiao95 = self._regiao95(marginal_xy)

        marginal_arred = [
            [_arredondar(float(v)) for v in linha] for linha in marginal_xy
        ]

        return {
            "n": self._n,
            "p_fonte": float(p_fonte),
            "x_map": x_map,
            "y_map": y_map,
            "s_map": s_map,
            "b_map": b_map,
            "x_media": x_media,
            "y_media": y_media,
            "desvio_m": desvio_m,
            "regiao95": regiao95,
            "marginal": marginal_arred,
        }

    def _regiao95(self, marginal_xy: np.ndarray) -> dict:
        """Menor conjunto de células cuja massa marginal soma >= 95%."""
        flat = marginal_xy.reshape(-1)
        ordem = np.argsort(flat)[::-1]
        acumulado = np.cumsum(flat[ordem])
        k = int(np.searchsorted(acumulado, 0.95) + 1)
        k = min(k, flat.size)

        mascara_flat = np.zeros(flat.size, dtype=bool)
        mascara_flat[ordem[:k]] = True
        mascara = mascara_flat.reshape(self.nx, self.ny)

        return {
            "x0": self.x0,
            "y0": self.y0,
            "res": self.resolucao_m,
            "nx": self.nx,
            "ny": self.ny,
            "mascara": [[bool(v) for v in linha] for linha in mascara],
        }
