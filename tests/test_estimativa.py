"""Testes do estimador bayesiano em grade (verossimilhança de Poisson sobre o CPS).

Os dados são gerados como o FS-5000 real se comporta: uma contagem Poisson
independente por segundo, `c ~ Poisson(k·(b + S·g))`, ao longo de um percurso
em zigue-zague (cortador de grama) a ~0,4 m/s, uma amostra por segundo.
"""
import functools
import json
import math
import statistics
import threading
import time
import warnings

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


# Área pequena (10 m, 20×20 células, n_b = 32): percorrer a grade cheia a
# cada amostra (40×40×40×64) custa ~30 ms; a área pequena, ~3 ms.
PEQUENA = dict(lado_m=10.0, n_b=32)
# zigue-zague da área pequena: 8 linhas em ±4,5 m (~81 m ≈ 200 amostras)
ZIGZAG_PEQUENO = dict(meio=4.5, linhas=8)
LINHAS_PEQUENO = np.linspace(-4.5, 4.5, 8)


@functools.lru_cache(maxsize=None)
def _missao(b, s, fonte, semente, n=200, zigzag=None, grade=None):
    """Resultado de uma missão (memoizado para os testes reaproveitarem).

    `zigzag` e `grade` são tuplas de pares (chave, valor) — por padrão, a
    área pequena percorrida uma vez.
    """
    zigzag = dict(zigzag) if zigzag is not None else ZIGZAG_PEQUENO
    grade = dict(grade) if grade is not None else PEQUENA
    pontos = _zigzag(n=n, **zigzag)
    contagens = _contagens(pontos, b, s, fonte, semente)
    return _estimar(_amostras(pontos, contagens), **grade).resultado()


def _tamanho_regiao(r):
    return int(np.sum(np.array(r["regiao95"]["mascara"])))


def _celula(regiao, x, y):
    ix = int(math.floor((x - regiao["x0"]) / regiao["res"]))
    iy = int(math.floor((y - regiao["y0"]) / regiao["res"]))
    return ix, iy


FUNDOS_LOCALIZACAO = (0.1, 0.1666, 0.25)
# centro de célula (grade de 0,5 m começando em −5), entre duas linhas do percurso
FONTE_CENTRO = (2.25, -1.25)
# ponto arbitrário fora dos centros e dos cantos das células; cai na célula
# (14, 7), de centro (2,25; −1,25), a 0,21 m dele
FONTE_FORA = (2.08, -1.12)
S_LOCALIZACAO = 5.0


def _confere_intensidades(r, s, b):
    assert s / 2.0 <= r["s_map"] <= s * 2.0, r["s_map"]
    assert r["b_map"] == pytest.approx(b, rel=0.3), r["b_map"]


# --- localização ------------------------------------------------------------


@pytest.mark.parametrize("b", FUNDOS_LOCALIZACAO)
def test_fonte_em_centro_de_celula_e_localizada(b):
    r = _missao(b, S_LOCALIZACAO, FONTE_CENTRO, 1)

    assert r["p_fonte"] > 0.95
    erro = math.hypot(r["x_map"] - FONTE_CENTRO[0], r["y_map"] - FONTE_CENTRO[1])
    assert erro < 1.0
    _confere_intensidades(r, S_LOCALIZACAO, b)

    regiao = r["regiao95"]
    ix, iy = _celula(regiao, *FONTE_CENTRO)
    assert regiao["mascara"][ix][iy] is True


def test_fonte_fora_da_grade_e_localizada():
    b = 0.1666
    r = _missao(b, S_LOCALIZACAO, FONTE_FORA, 1)

    assert r["p_fonte"] > 0.95
    erro = math.hypot(r["x_map"] - FONTE_FORA[0], r["y_map"] - FONTE_FORA[1])
    assert erro < 1.0
    _confere_intensidades(r, S_LOCALIZACAO, b)

    # a região de 95% contém a célula da fonte ou uma das 8 vizinhas
    regiao = r["regiao95"]
    ix, iy = _celula(regiao, *FONTE_FORA)
    assert (ix, iy) == (14, 7)
    vizinhas = [
        regiao["mascara"][ix + dx][iy + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)
    ]
    assert any(vizinhas)


def test_marginal_indexada_por_ix_iy_com_x0_y0_no_canto_da_grade():
    r = _missao(0.1666, S_LOCALIZACAO, FONTE_CENTRO, 1)
    regiao = r["regiao95"]
    marginal = np.array(r["marginal"])

    ix, iy = np.unravel_index(int(np.argmax(marginal)), marginal.shape)
    assert r["x_map"] == pytest.approx(regiao["x0"] + (ix + 0.5) * regiao["res"])
    assert r["y_map"] == pytest.approx(regiao["y0"] + (iy + 0.5) * regiao["res"])
    # a fonte está em x > 0 e y < 0: a moda fica na metade de ix alto e iy baixo
    assert ix >= regiao["nx"] // 2 > iy
    assert regiao["mascara"][ix][iy] is True


# --- só fundo ---------------------------------------------------------------

# área padrão (20 m) coberta uma vez: 12 linhas em ±9 m, 600 amostras
COBERTURA_TOTAL = (("meio", 9.0), ("linhas", 12))
GRADE_PADRAO_B16 = (("n_b", 16),)
# o pior caso entre as sementes 1..8 dos fundos abaixo
PIOR_SO_FUNDO = (0.25, 6)


@pytest.mark.parametrize(
    "b, semente", [(b, 1) for b in (0.08, 0.12, 0.1666, 0.25, 0.5)] + [PIOR_SO_FUNDO]
)
def test_so_fundo_com_cobertura_total_nao_indica_fonte(b, semente):
    r = _missao(b, 0.0, (0.0, 0.0), semente, n=600, zigzag=COBERTURA_TOTAL, grade=GRADE_PADRAO_B16)
    assert r["p_fonte"] < 0.2


@pytest.mark.parametrize("semente", (1, 2, 3))
@pytest.mark.parametrize("meio, linhas", [(2.0, 5), (4.0, 8)])
def test_so_fundo_com_cobertura_parcial_nao_indica_fonte(meio, linhas, semente):
    """O robô anda só em ±2 m ou ±4 m de uma área de 20 m: a maior parte das
    células não é visitada e não pode sustentar P(fonte)."""
    zigzag = (("meio", meio), ("linhas", linhas))
    r = _missao(0.17, 0.0, (0.0, 0.0), semente, n=300, zigzag=zigzag, grade=GRADE_PADRAO_B16)
    assert r["p_fonte"] < 0.2


def test_so_fundo_em_missao_longa_nao_indica_fonte():
    # b = 0,1666 cai entre dois pontos da grade de b; 3600 amostras = 1 h
    r = _missao(0.1666, 0.0, (0.0, 0.0), 1, n=3600, grade=(("lado_m", 10.0), ("n_b", 16)))
    assert r["p_fonte"] < 0.2


# --- fonte fraca ------------------------------------------------------------

# fonte sobre a 4ª linha do zigue-zague pequeno
FONTE_NA_LINHA = (1.0, float(LINHAS_PEQUENO[3]))


def test_fonte_fraca_sobre_o_percurso_e_detectada():
    """S = 0,5 com b = 0,15 e o percurso passando sobre a fonte: ~40 contagens
    de excesso numa passada."""
    valores = [
        _missao(0.15, 0.5, FONTE_NA_LINHA, semente)["p_fonte"] for semente in (1, 2, 3)
    ]
    assert min(valores) > 0.95, valores


def test_fonte_muito_fraca_sobre_o_percurso_costuma_ser_detectada():
    """S = 0,1 (1,6 µSv/h no detector sobre a fonte, ~10 contagens de excesso
    em 2–3 s de passagem) está no limite: exigimos P(fonte) > 0,8 na maioria
    das missões e, quando detectada, a moda a menos de 1 m da fonte."""
    resultados = [_missao(0.15, 0.1, FONTE_NA_LINHA, semente) for semente in (1, 2, 3, 4, 5)]
    detectadas = [r for r in resultados if r["p_fonte"] > 0.8]
    assert len(detectadas) >= 3, [r["p_fonte"] for r in resultados]
    for r in detectadas:
        assert math.hypot(r["x_map"] - FONTE_NA_LINHA[0], r["y_map"] - FONTE_NA_LINHA[1]) < 1.0


# --- hipóteses detectáveis --------------------------------------------------


def test_sem_hipotese_detectavel_p_fonte_e_none():
    pontos = _zigzag(n=50, **ZIGZAG_PEQUENO)
    contagens = _contagens(pontos, 0.15, 5.0, FONTE_CENTRO, 1)
    estimador = _estimar(_amostras(pontos, contagens), contagens_min_detectaveis=1e12, **PEQUENA)
    r = estimador.resultado()

    assert set(r) == CHAVES
    assert r["n"] == 50
    assert r["p_fonte"] is None
    # posição, intensidades e região continuam no formato normal (grade toda)
    for chave in ("x_map", "y_map", "s_map", "b_map", "x_media", "y_media", "desvio_m"):
        assert isinstance(r[chave], float) and math.isfinite(r[chave])
    assert np.array(r["marginal"]).sum() == pytest.approx(1.0, abs=1e-4)
    json.dumps(r, allow_nan=False)


def test_uma_amostra_so_nao_distingue_fonte_de_fundo():
    estimador = EstimadorGrade(centro=(0.0, 0.0), **PEQUENA)
    estimador.atualizar(
        Amostra(ts=0.0, x=1.0, y=1.0, dr_usvh=5.0, cpm=0, cps=13, lacuna_pose_s=0.0)
    )
    r = estimador.resultado()
    assert r["n"] == 1
    assert r["p_fonte"] is None
    json.dumps(r, allow_nan=False)


# --- alertas ----------------------------------------------------------------


def test_s_no_limite_quando_fonte_mais_forte_que_a_grade():
    pontos = _zigzag(**ZIGZAG_PEQUENO, n=200)
    contagens = _contagens(pontos, 0.15, 5.0, FONTE_CENTRO, 1)
    r = _estimar(_amostras(pontos, contagens), s_max=1.0, **PEQUENA).resultado()

    assert r["s_no_limite"] is True
    assert r["s_map"] == pytest.approx(1.0)


def test_b_no_limite_quando_fundo_acima_da_grade():
    r = _missao(5.0, 0.0, (0.0, 0.0), 1)
    assert r["b_no_limite"] is True
    assert r["b_map"] == pytest.approx(2.0)


def test_b_no_limite_quando_fundo_abaixo_da_grade():
    r = _missao(0.001, 0.0, (0.0, 0.0), 1)
    assert r["b_no_limite"] is True
    assert r["b_map"] == pytest.approx(0.01)


def test_sem_alertas_em_caso_nominal():
    r = _missao(0.1666, S_LOCALIZACAO, FONTE_CENTRO, 1)
    assert r["s_no_limite"] is False
    assert r["b_no_limite"] is False
    assert r["fonte_na_borda"] is False


def test_fonte_na_borda_quando_fonte_fora_da_area():
    """Fonte em (8, 0), fora da área (|x| ≤ 5), com S = 50: a ≥ 3,5 m do
    percurso ainda soma ~4 µSv/h no ponto mais próximo; é detectada e a
    estimativa encosta na borda da grade."""
    r = _missao(0.15, 50.0, (8.0, 0.0), 1)

    assert r["p_fonte"] > 0.95
    assert r["fonte_na_borda"] is True


# --- robustez ---------------------------------------------------------------


class _SemCps:
    ts = 0.0
    x = 0.0
    y = 0.0


def test_amostras_invalidas_sao_rejeitadas_sem_alterar_o_resultado():
    pontos = _zigzag(n=120, **ZIGZAG_PEQUENO)
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
        ruim(7, x=1.0001e4),
        ruim(8, y=-2e4),
        ruim(9, cps=1_000_001),
        ruim(10, x=10**400),
        ruim(11, x="abc"),
        _SemCps(),
        object(),
    ]
    n_ruins = len(ruins)

    limpo = _estimar(boas, **PEQUENA)
    sujo = EstimadorGrade(centro=(0.0, 0.0), **PEQUENA)
    for i, a in enumerate(boas):
        sujo.atualizar(a)
        if i % 8 == 0 and ruins:
            sujo.atualizar(ruins.pop())
    while ruins:
        sujo.atualizar(ruins.pop())

    r_limpo = limpo.resultado()
    r_sujo = sujo.resultado()

    assert r_sujo["rejeitadas"] == n_ruins
    assert r_limpo["rejeitadas"] == 0
    assert r_sujo["n"] == r_limpo["n"] == 120
    r_sujo.pop("rejeitadas")
    r_limpo.pop("rejeitadas")
    assert r_sujo == r_limpo
    json.dumps(r_sujo, allow_nan=False)


def test_amostra_com_cps_zero_informa():
    """cps = 0 ainda informa (termo linear): muitos zeros perto de um ponto
    afastam a fonte de lá."""
    estimador = EstimadorGrade(centro=(0.0, 0.0), **PEQUENA)
    for i in range(50):
        estimador.atualizar(
            Amostra(ts=float(i), x=2.25, y=-1.25, dr_usvh=0.0, cpm=0, cps=0, lacuna_pose_s=0.0)
        )
    r = estimador.resultado()

    assert r["n"] == 50
    assert r["rejeitadas"] == 0
    regiao = r["regiao95"]
    ix, iy = _celula(regiao, 2.25, -1.25)
    assert regiao["mascara"][ix][iy] is False


def test_entradas_extremas_validas_nao_geram_warning_nem_nan():
    estimador = EstimadorGrade(centro=(0.0, 0.0), **PEQUENA)
    extremos = [(0.0, 0.0, 1_000_000), (1e4, -1e4, 1_000_000), (-1e4, 1e4, 0), (4.9, 4.9, 0)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for i in range(20):
            x, y, c = extremos[i % len(extremos)]
            estimador.atualizar(
                Amostra(ts=float(i), x=x, y=y, dr_usvh=0.0, cpm=0, cps=c, lacuna_pose_s=0.0)
            )
        r = estimador.resultado()

    assert r["rejeitadas"] == 0
    json.dumps(r, allow_nan=False)
    assert 0.0 <= r["p_fonte"] <= 1.0


# --- concorrência -----------------------------------------------------------


def test_atualizar_e_resultado_concorrentes_dao_o_mesmo_que_em_sequencia():
    # grade grande o bastante para o numpy soltar o GIL nas operações
    grade = dict(lado_m=10.0, n_b=32)
    pontos = _zigzag(n=60, meio=2.0, linhas=5)
    contagens = _contagens(pontos, 0.3, 2.0, (1.0, 0.5), 3)
    amostras = _amostras(pontos, contagens)

    concorrente = EstimadorGrade(centro=(0.0, 0.0), **grade)
    parciais = []
    fim = threading.Event()
    erros = []

    def ler():
        try:
            while not fim.is_set():
                parciais.append(concorrente.resultado())
                time.sleep(0.002)  # não monopoliza o lock
        except Exception as e:  # pragma: no cover - só em falha
            erros.append(e)

    leitores = [threading.Thread(target=ler) for _ in range(2)]
    for t in leitores:
        t.start()
    try:
        for a in amostras:
            concorrente.atualizar(a)
    finally:
        fim.set()
        for t in leitores:
            t.join()

    assert not erros
    sequencial = EstimadorGrade(centro=(0.0, 0.0), **grade)
    por_n = {0: sequencial.resultado()}
    for i, a in enumerate(amostras, start=1):
        sequencial.atualizar(a)
        por_n[i] = sequencial.resultado()

    assert concorrente.resultado() == por_n[len(amostras)]
    # houve leituras no meio da acumulação
    assert any(0 < r["n"] < len(amostras) for r in parciais)
    for r in parciais:
        assert r == por_n[r["n"]]


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
    "b_no_limite",
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
    # grade padrão (20 m, 40×40, n_b = 64), reaproveitando a missão ponta a ponta
    r, _ = _ponta_a_ponta_com_fonte()

    assert set(r) == CHAVES
    assert set(r["regiao95"]) == {"x0", "y0", "res", "nx", "ny", "mascara"}
    assert r["regiao95"]["nx"] == r["regiao95"]["ny"] == 40
    assert r["regiao95"]["res"] == 0.5
    assert r["regiao95"]["x0"] == -10.0 and r["regiao95"]["y0"] == -10.0
    assert isinstance(r["n"], int) and isinstance(r["rejeitadas"], int)
    for chave in ("p_fonte", "x_map", "y_map", "s_map", "b_map", "x_media", "y_media", "desvio_m"):
        assert isinstance(r[chave], float) and math.isfinite(r[chave])
    for chave in ("s_no_limite", "b_no_limite", "fonte_na_borda"):
        assert isinstance(r[chave], bool)

    marginal = np.array(r["marginal"])
    assert marginal.shape == (40, 40)
    assert marginal.min() >= 0.0
    assert marginal.sum() == pytest.approx(1.0, abs=1e-4)
    mascara = np.array(r["regiao95"]["mascara"])
    assert mascara.shape == (40, 40) and mascara.dtype == bool

    texto = json.dumps(r, allow_nan=False)
    assert json.loads(texto) == r


# --- incerteza --------------------------------------------------------------


def test_regiao95_encolhe_com_mais_amostras():
    pontos = _zigzag(n=200, **ZIGZAG_PEQUENO)
    contagens = _contagens(pontos, 0.1666, S_LOCALIZACAO, FONTE_CENTRO, 1)
    amostras = _amostras(pontos, contagens)

    poucas = _tamanho_regiao(_estimar(amostras[:30], **PEQUENA).resultado())
    muitas = _tamanho_regiao(_estimar(amostras, **PEQUENA).resultado())

    assert poucas >= 10 * muitas


def test_amostras_num_ponto_so_dao_regiao_grande():
    pontos = np.zeros((150, 2))
    contagens = _contagens(pontos, 0.1666, S_LOCALIZACAO, (3.0, -2.0), 1)
    r = _estimar(_amostras(pontos, contagens), **PEQUENA).resultado()

    assert _tamanho_regiao(r) > 0.2 * 20 * 20
    assert r["desvio_m"] > 1.5


# --- desempenho -------------------------------------------------------------


def test_desempenho():
    """Metas: `atualizar` < 60 ms (c > 0) e < 2 ms (c = 0); `resultado` < 150 ms.
    O teste admite 3× a meta (mediana de N execuções) para não falhar numa
    máquina carregada."""
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    positiva = Amostra(ts=0.0, x=1.0, y=1.0, dr_usvh=1.0, cpm=180, cps=3, lacuna_pose_s=0.0)
    zero = Amostra(ts=0.0, x=2.0, y=1.0, dr_usvh=0.0, cpm=0, cps=0, lacuna_pose_s=0.0)
    estimador.atualizar(positiva)  # aquece
    estimador.atualizar(zero)

    def mediana(f, vezes):
        tempos = []
        for _ in range(vezes):
            inicio = time.perf_counter()
            f()
            tempos.append(time.perf_counter() - inicio)
        return statistics.median(tempos)

    t_positiva = mediana(lambda: estimador.atualizar(positiva), 15)
    t_zero = mediana(lambda: estimador.atualizar(zero), 201)
    t_resultado = mediana(estimador.resultado, 7)

    assert t_positiva < 3 * 0.060
    assert t_zero < 3 * 0.002
    assert t_resultado < 3 * 0.150


# --- ponta a ponta com o detector simulado ----------------------------------


def _ponta_a_ponta(campo, semente, n=600, zigzag=(), grade=()):
    """DetectorSimulado → Sincronizador → EstimadorGrade num percurso roteirizado.

    A leitura do segundo i cobre o intervalo [t_i − 0,5; t_i + 0,5] e chega em
    t_i + 0,5; o sincronizador (latência 0,5 s) a posiciona em t_i.
    """
    pontos = _zigzag(n=n, **dict(zigzag))
    posicao = {"atual": None}
    leituras = []
    detector = DetectorSimulado(
        campo, posicao_detector=lambda: posicao["atual"], cps_por_usvh=K, semente=semente
    )
    detector.assinar(leituras.append)

    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=0.5)
    estimador = EstimadorGrade(centro=(0.0, 0.0), **dict(grade))
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


@functools.lru_cache(maxsize=None)
def _ponta_a_ponta_com_fonte():
    campo = CampoRadiacao(fundo_usvh=0.15, altura_m=ALTURA)
    campo.definir_fonte(3.0, -2.0, 5.0)
    return _ponta_a_ponta(campo, semente=6)


def test_ponta_a_ponta_so_fundo_nao_indica_fonte():
    # área pequena: a grade padrão já é exercitada no caso com fonte
    r, _ = _ponta_a_ponta(
        CampoRadiacao(fundo_usvh=0.15, altura_m=ALTURA),
        semente=5,
        n=200,
        zigzag=tuple(ZIGZAG_PEQUENO.items()),
        grade=tuple(PEQUENA.items()),
    )

    assert r["n"] == 199
    assert r["rejeitadas"] == 0
    assert r["p_fonte"] < 0.2


def test_ponta_a_ponta_com_fonte_localiza():
    r, _ = _ponta_a_ponta_com_fonte()

    assert r["p_fonte"] > 0.95
    assert math.hypot(r["x_map"] - 3.0, r["y_map"] + 2.0) < 1.0
