"""Testes do estimador bayesiano em grade (verossimilhança de Poisson sobre o CPS).

Os dados são gerados como o FS-5000 real se comporta: uma contagem Poisson
independente por segundo, `c ~ Poisson(k·(b + S·g))`, ao longo de um percurso
em zigue-zague (cortador de grama) a ~0,4 m/s, uma amostra por segundo.
"""
import functools
import json
import math
import statistics
import time

import numpy as np
import pytest

from ares.estimativa import EstimadorGrade
from ares.modelos import Amostra, Leitura, Pose
from ares.simulacao.campo import CampoRadiacao
from ares.simulacao.detector import DetectorSimulado
from ares.sincronizacao import Sincronizador

K = 2.6
ALTURA = 0.25


# --- geração de dados -------------------------------------------------------


def _zigzag(n=600, velocidade=0.4, meio=9.0, linhas=12, deslocamento_y=0.0):
    """`n` pontos (1 por segundo) num zigue-zague que cobre a área.

    Linhas horizontais de x = −meio a +meio em `linhas` alturas igualmente
    espaçadas (a 12 linhas e 0,4 m/s, 600 amostras cobrem a área uma vez).
    Percursos mais longos recomeçam o zigue-zague.
    """
    ys = np.linspace(-meio, meio, linhas) + deslocamento_y
    vertices = []
    for i, y in enumerate(ys):
        xa, xb = (-meio, meio) if i % 2 == 0 else (meio, -meio)
        vertices += [(xa, y), (xb, y)]
    vertices = np.array(vertices)
    segmentos = np.diff(vertices, axis=0)
    comprimentos = np.hypot(segmentos[:, 0], segmentos[:, 1])
    acumulado = np.concatenate([[0.0], np.cumsum(comprimentos)])

    distancias = (np.arange(n) * velocidade) % acumulado[-1]
    j = np.searchsorted(acumulado, distancias, side="right") - 1
    j = np.minimum(j, len(segmentos) - 1)
    fracao = (distancias - acumulado[j]) / comprimentos[j]
    return vertices[j] + fracao[:, None] * segmentos[j]


def _contagens(pontos, b, s=0.0, fonte=(0.0, 0.0), semente=0):
    rng = np.random.default_rng(semente)
    r2 = (pontos[:, 0] - fonte[0]) ** 2 + (pontos[:, 1] - fonte[1]) ** 2
    mu = b + s / (r2 + ALTURA**2)
    return rng.poisson(K * mu)


def _amostras(pontos, contagens):
    return [
        Amostra(
            ts=float(i),
            x=float(p[0]),
            y=float(p[1]),
            dr_usvh=float(c) / K,
            cpm=int(c) * 60,
            cps=int(c),
            lacuna_pose_s=0.0,
        )
        for i, (p, c) in enumerate(zip(pontos, contagens))
    ]


def _estimar(amostras, **kwargs):
    estimador = EstimadorGrade(centro=(0.0, 0.0), **kwargs)
    for a in amostras:
        estimador.atualizar(a)
    return estimador


@functools.lru_cache(maxsize=None)
def _missao(b, s, fonte, semente, n=600, deslocamento_y=0.0):
    """Resultado de uma missão padrão (memoizado para os testes reaproveitarem)."""
    pontos = _zigzag(n=n, deslocamento_y=deslocamento_y)
    contagens = _contagens(pontos, b, s, fonte, semente)
    return _estimar(_amostras(pontos, contagens)).resultado()


def _tamanho_regiao(r):
    return int(np.sum(np.array(r["regiao95"]["mascara"])))


def _celula(regiao, x, y):
    ix = int(math.floor((x - regiao["x0"]) / regiao["res"]))
    iy = int(math.floor((y - regiao["y0"]) / regiao["res"]))
    return ix, iy


FUNDOS_LOCALIZACAO = (0.1, 0.1666, 0.25)
SEMENTES = (1, 2, 3)
# centro de célula (grade de 0,5 m começando em −10) perto de (3, −2)
FONTE_CENTRO = (3.25, -2.25)
# ponto arbitrário fora dos centros e dos cantos das células
FONTE_FORA = (3.13, -1.94)


# --- localização ------------------------------------------------------------


@pytest.mark.parametrize("semente", SEMENTES)
@pytest.mark.parametrize("b", FUNDOS_LOCALIZACAO)
def test_fonte_em_centro_de_celula_e_localizada(b, semente):
    r = _missao(b, 5.0, FONTE_CENTRO, semente)

    assert r["p_fonte"] > 0.95
    erro = math.hypot(r["x_map"] - FONTE_CENTRO[0], r["y_map"] - FONTE_CENTRO[1])
    assert erro < 1.0

    regiao = r["regiao95"]
    ix, iy = _celula(regiao, *FONTE_CENTRO)
    assert regiao["mascara"][ix][iy] is True


@pytest.mark.parametrize("semente", SEMENTES)
@pytest.mark.parametrize("b", FUNDOS_LOCALIZACAO)
def test_fonte_fora_da_grade_e_localizada(b, semente):
    r = _missao(b, 5.0, FONTE_FORA, semente)

    assert r["p_fonte"] > 0.95
    erro = math.hypot(r["x_map"] - FONTE_FORA[0], r["y_map"] - FONTE_FORA[1])
    assert erro < 1.0


# --- só fundo ---------------------------------------------------------------


@pytest.mark.parametrize("semente", SEMENTES)
@pytest.mark.parametrize("b", (0.08, 0.12, 0.1666, 0.25, 0.5))
def test_so_fundo_nao_indica_fonte(b, semente):
    r = _missao(b, 0.0, (0.0, 0.0), semente)
    assert r["p_fonte"] < 0.2


def test_so_fundo_em_missao_longa_nao_indica_fonte():
    # b = 0,1666 cai entre dois pontos da grade de b
    r = _missao(0.1666, 0.0, (0.0, 0.0), 1, n=3600)
    assert r["p_fonte"] < 0.2


# --- fonte fraca ------------------------------------------------------------


def test_fonte_fraca_perto_do_percurso_e_detectada():
    """S = 0,5 com b = 0,15 e o percurso a ~0,8 m da fonte (a fonte fica no
    meio de duas linhas do zigue-zague) está no limite de detecção numa única
    passada de 10 min: o excesso esperado perto da fonte é de ~18 contagens
    sobre ~4 de fundo, e a flutuação Poisson às vezes o reduz bastante.
    Exigimos P(fonte) > 0,9 na maioria das missões (sementes 1..5) e que
    nenhuma aponte fortemente para "sem fonte"."""
    valores = [
        _missao(0.15, 0.5, (3.0, -2.0), semente, deslocamento_y=-0.3636)["p_fonte"]
        for semente in (1, 2, 3, 4, 5)
    ]
    assert sum(p > 0.9 for p in valores) >= 3, valores
    assert min(valores) > 0.4, valores


# --- alertas ----------------------------------------------------------------


def test_s_no_limite_quando_fonte_mais_forte_que_a_grade():
    pontos = _zigzag()
    contagens = _contagens(pontos, 0.15, 5.0, (3.0, -2.0), 1)
    r = _estimar(_amostras(pontos, contagens), s_max=1.0).resultado()

    assert r["s_no_limite"] is True
    assert r["s_map"] == pytest.approx(1.0)


def test_sem_alertas_em_caso_nominal():
    r = _missao(0.1666, 5.0, FONTE_CENTRO, 1)
    assert r["s_no_limite"] is False
    assert r["fonte_na_borda"] is False


def test_fonte_na_borda_quando_fonte_fora_da_area():
    """Fonte em (15, 0), fora da área (|x| ≤ 10). Com S = 5 ela contribui no
    máximo 5/36 ≈ 0,14 µSv/h no ponto mais próximo do percurso (x = 9), abaixo
    do fundo, e nem é detectada (P(fonte) ≈ 0,09); com S = 50 é detectada e a
    estimativa encosta na borda da grade."""
    pontos = _zigzag()
    contagens = _contagens(pontos, 0.15, 50.0, (15.0, 0.0), 1)
    r = _estimar(_amostras(pontos, contagens)).resultado()

    assert r["p_fonte"] > 0.95
    assert r["fonte_na_borda"] is True


# --- robustez ---------------------------------------------------------------


def test_amostras_invalidas_sao_rejeitadas_sem_alterar_o_resultado():
    pontos = _zigzag(n=200)
    contagens = _contagens(pontos, 0.15, 5.0, FONTE_CENTRO, 2)
    boas = _amostras(pontos, contagens)

    def ruim(i, **campos):
        base = dict(ts=float(i), x=0.0, y=0.0, dr_usvh=0.1, cpm=6, cps=1, lacuna_pose_s=0.0)
        base.update(campos)
        return Amostra(**base)

    ruins = [
        ruim(0, x=math.nan),
        ruim(1, y=math.inf),
        ruim(2, x=-math.inf),
        ruim(3, cps=-1),
        ruim(4, cps=math.nan),
        ruim(5, cps=math.inf),
        ruim(6, cps=None),
    ]

    limpo = _estimar(boas)
    sujo = EstimadorGrade(centro=(0.0, 0.0))
    for i, a in enumerate(boas):
        sujo.atualizar(a)
        if i % 25 == 0 and ruins:
            sujo.atualizar(ruins.pop())
    while ruins:
        sujo.atualizar(ruins.pop())

    r_limpo = limpo.resultado()
    r_sujo = sujo.resultado()

    assert r_sujo["rejeitadas"] == 7
    assert r_limpo["rejeitadas"] == 0
    assert r_sujo["n"] == r_limpo["n"] == 200
    r_sujo.pop("rejeitadas")
    r_limpo.pop("rejeitadas")
    assert r_sujo == r_limpo
    json.dumps(r_sujo, allow_nan=False)


def test_amostra_com_cps_zero_informa():
    """cps = 0 ainda informa (termo linear): muitos zeros perto de um ponto
    afastam a fonte de lá."""
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    for i in range(50):
        estimador.atualizar(
            Amostra(ts=float(i), x=3.25, y=-2.25, dr_usvh=0.0, cpm=0, cps=0, lacuna_pose_s=0.0)
        )
    r = estimador.resultado()

    assert r["n"] == 50
    assert r["rejeitadas"] == 0
    regiao = r["regiao95"]
    ix, iy = _celula(regiao, 3.25, -2.25)
    assert regiao["mascara"][ix][iy] is False
    assert r["p_fonte"] < 0.5


# --- formato do resultado ---------------------------------------------------

CHAVES = {
    "n",
    "rejeitadas",
    "p_fonte",
    "x_map",
    "y_map",
    "s_map",
    "b_map",
    "x_media",
    "y_media",
    "desvio_m",
    "regiao95",
    "marginal",
    "s_no_limite",
    "fonte_na_borda",
}


def test_sem_amostras_p_fonte_e_none():
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    r = estimador.resultado()

    assert set(r) == CHAVES
    assert r["n"] == 0
    assert r["rejeitadas"] == 0
    assert r["p_fonte"] is None
    assert r["x_map"] is None
    assert r["regiao95"] is None
    assert len(r["marginal"]) == estimador.nx == 40
    assert len(r["marginal"][0]) == estimador.ny == 40
    json.dumps(r, allow_nan=False)


def test_resultado_tem_formato_da_spec_e_e_json_sem_nan():
    r = _missao(0.1666, 5.0, FONTE_CENTRO, 1)

    assert set(r) == CHAVES
    assert set(r["regiao95"]) == {"x0", "y0", "res", "nx", "ny", "mascara"}
    assert r["regiao95"]["nx"] == r["regiao95"]["ny"] == 40
    assert r["regiao95"]["res"] == 0.5
    assert r["regiao95"]["x0"] == -10.0 and r["regiao95"]["y0"] == -10.0
    assert isinstance(r["n"], int) and isinstance(r["rejeitadas"], int)
    for chave in ("p_fonte", "x_map", "y_map", "s_map", "b_map", "x_media", "y_media", "desvio_m"):
        assert isinstance(r[chave], float) and math.isfinite(r[chave])
    assert isinstance(r["s_no_limite"], bool) and isinstance(r["fonte_na_borda"], bool)

    marginal = np.array(r["marginal"])
    assert marginal.shape == (40, 40)
    assert marginal.min() >= 0.0
    assert marginal.sum() == pytest.approx(1.0, abs=1e-4)

    texto = json.dumps(r, allow_nan=False)
    assert json.loads(texto) == r


def test_resultado_sem_nan_com_dados_extremos():
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    for i in range(20):
        estimador.atualizar(
            Amostra(ts=float(i), x=0.0, y=0.0, dr_usvh=1e4, cpm=0, cps=100000, lacuna_pose_s=0.0)
        )
    estimador.atualizar(Amostra(ts=21.0, x=9.9, y=9.9, dr_usvh=0.0, cpm=0, cps=0, lacuna_pose_s=0.0))
    r = estimador.resultado()
    json.dumps(r, allow_nan=False)
    assert 0.0 <= r["p_fonte"] <= 1.0


# --- incerteza --------------------------------------------------------------


def test_regiao95_encolhe_com_mais_amostras():
    pontos = _zigzag(n=600)
    contagens = _contagens(pontos, 0.1666, 5.0, FONTE_CENTRO, 1)
    amostras = _amostras(pontos, contagens)

    poucas = _tamanho_regiao(_estimar(amostras[:60]).resultado())
    muitas = _tamanho_regiao(_estimar(amostras).resultado())

    assert muitas < poucas
    assert poucas >= 10 * muitas


def test_amostras_num_ponto_so_dao_regiao_grande():
    pontos = np.zeros((600, 2))
    contagens = _contagens(pontos, 0.1666, 5.0, (3.0, -2.0), 1)
    r = _estimar(_amostras(pontos, contagens)).resultado()

    assert _tamanho_regiao(r) > 0.2 * 40 * 40
    assert r["desvio_m"] > 3.0


# --- desempenho -------------------------------------------------------------


def test_desempenho():
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    positiva = Amostra(ts=0.0, x=1.0, y=1.0, dr_usvh=1.0, cpm=180, cps=3, lacuna_pose_s=0.0)
    zero = Amostra(ts=0.0, x=1.0, y=1.0, dr_usvh=0.0, cpm=0, cps=0, lacuna_pose_s=0.0)
    estimador.atualizar(positiva)  # aquece

    def mediana(f, vezes):
        tempos = []
        for _ in range(vezes):
            inicio = time.perf_counter()
            f()
            tempos.append(time.perf_counter() - inicio)
        return statistics.median(tempos)

    t_positiva = mediana(lambda: estimador.atualizar(positiva), 21)
    t_zero = mediana(lambda: estimador.atualizar(zero), 201)
    t_resultado = mediana(estimador.resultado, 11)

    assert t_positiva < 0.060
    assert t_zero < 0.002
    assert t_resultado < 0.150


# --- ponta a ponta com o detector simulado ----------------------------------


def _ponta_a_ponta(campo, semente, n=600):
    """DetectorSimulado → Sincronizador → EstimadorGrade num percurso roteirizado.

    A leitura do segundo i cobre o intervalo [t_i − 0,5; t_i + 0,5] e chega em
    t_i + 0,5; o sincronizador (latência 0,5 s) a posiciona em t_i.
    """
    pontos = _zigzag(n=n)
    posicao = {"atual": None}
    leituras = []
    detector = DetectorSimulado(
        campo, posicao_detector=lambda: posicao["atual"], cps_por_usvh=K, semente=semente
    )
    detector.assinar(leituras.append)

    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=0.5)
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    t0 = 1000.0

    def pose_em(t):
        s = t - t0
        i = min(int(math.floor(s)), n - 2)
        f = s - i
        x = pontos[i][0] + f * (pontos[i + 1][0] - pontos[i][0])
        y = pontos[i][1] + f * (pontos[i + 1][1] - pontos[i][1])
        return Pose(ts=t, x=float(x), y=float(y), yaw=0.0)

    sinc.adicionar_pose(pose_em(t0))
    for i in range(n - 1):
        t = t0 + i
        posicao["atual"] = (float(pontos[i][0]), float(pontos[i][1]))
        detector._amostrar()
        leitura = leituras[-1]
        sinc.adicionar_pose(pose_em(t + 0.5))
        sinc.adicionar_pose(pose_em(t + 1.0))
        sinc.adicionar_leitura(
            Leitura(
                ts=t + 0.5,
                dr_usvh=leitura.dr_usvh,
                cpm=leitura.cpm,
                cps=leitura.cps,
                dose_usv=leitura.dose_usv,
                detector_id=leitura.detector_id,
            )
        )
        for a in sinc.drenar():
            estimador.atualizar(a)

    return estimador.resultado(), leituras


def test_ponta_a_ponta_so_fundo_nao_indica_fonte():
    r, leituras = _ponta_a_ponta(CampoRadiacao(fundo_usvh=0.15, altura_m=ALTURA), semente=5)

    assert r["n"] == 599
    assert r["rejeitadas"] == 0
    assert r["p_fonte"] < 0.2


def test_ponta_a_ponta_com_fonte_localiza():
    campo = CampoRadiacao(fundo_usvh=0.15, altura_m=ALTURA)
    campo.definir_fonte(3.0, -2.0, 5.0)
    r, _ = _ponta_a_ponta(campo, semente=6)

    assert r["p_fonte"] > 0.95
    assert math.hypot(r["x_map"] - 3.0, r["y_map"] + 2.0) < 1.0
