"""Testes do estimador bayesiano em grade da posição da fonte."""
import math
import time

import numpy as np
import pytest

from ares.estimativa import EstimadorGrade
from ares.modelos import Amostra
from ares.simulacao.campo import CampoRadiacao


def _amostra(rng, campo, x, y, sigma0, fracao, ts):
    """Gera uma amostra ruidosa em (x, y) a partir do modelo do estimador."""
    mu = campo.taxa(x, y)
    sigma = math.sqrt(sigma0**2 + (fracao * mu) ** 2)
    # ruído gaussiano com o mesmo modelo de sigma do estimador (cauda mais
    # leve que a Student-t usada na verossimilhança, o que é conservador)
    dr = mu + rng.normal(0.0, sigma)
    dr = max(0.0, dr)
    return Amostra(ts=ts, x=x, y=y, dr_usvh=dr, cpm=0, lacuna_pose_s=0.0)


def _zigzag(centro, lado, passo=1.0, linhas=None):
    """Gera pontos (x, y) em zigue-zague cobrindo a área do estimador."""
    cx, cy = centro
    meio = lado / 2.0
    ys = np.arange(-meio + passo, meio, passo * 2)
    if linhas is not None:
        ys = ys[:linhas]
    pontos = []
    esquerda_para_direita = True
    for y in ys:
        xs = np.arange(-meio + passo, meio, passo)
        if not esquerda_para_direita:
            xs = xs[::-1]
        for x in xs:
            pontos.append((cx + x, cy + y))
        esquerda_para_direita = not esquerda_para_direita
    return pontos


def test_fonte_forte_e_localizada_com_confianca():
    rng = np.random.default_rng(42)
    campo = CampoRadiacao(fundo_usvh=0.15, altura_m=0.25)
    campo.definir_fonte(3.0, -2.0, 5.0)

    estimador = EstimadorGrade(centro=(0.0, 0.0))

    for i, (x, y) in enumerate(_zigzag((0.0, 0.0), 20.0)):
        a = _amostra(rng, campo, x, y, estimador.sigma0, estimador.fracao, ts=float(i))
        estimador.atualizar(a)

    r = estimador.resultado()

    assert r["n"] > 0
    assert r["p_fonte"] is not None and r["p_fonte"] > 0.95

    erro_map = math.hypot(r["x_map"] - 3.0, r["y_map"] - (-2.0))
    assert erro_map < 1.0

    regiao = r["regiao95"]
    mascara = np.array(regiao["mascara"])
    xs_centros = regiao["x0"] + (np.arange(regiao["nx"]) + 0.5) * regiao["res"]
    ys_centros = regiao["y0"] + (np.arange(regiao["ny"]) + 0.5) * regiao["res"]
    ixs, iys = np.nonzero(mascara)
    distancias = np.hypot(xs_centros[ixs] - 3.0, ys_centros[iys] - (-2.0))
    # a fonte pode cair bem na fronteira entre duas células; exigimos que a
    # região de 95% chegue a menos de uma célula de distância dela.
    assert distancias.min() < regiao["res"]


def test_so_fundo_da_baixa_probabilidade_de_fonte():
    rng = np.random.default_rng(7)
    campo = CampoRadiacao(fundo_usvh=0.15)

    estimador = EstimadorGrade(centro=(0.0, 0.0))

    for i, (x, y) in enumerate(_zigzag((0.0, 0.0), 20.0)):
        a = _amostra(rng, campo, x, y, estimador.sigma0, estimador.fracao, ts=float(i))
        estimador.atualizar(a)

    r = estimador.resultado()

    assert r["n"] > 0
    assert r["p_fonte"] is not None and r["p_fonte"] < 0.2


def test_regiao95_encolhe_com_mais_amostras():
    rng = np.random.default_rng(123)
    campo = CampoRadiacao(fundo_usvh=0.15, altura_m=0.25)
    campo.definir_fonte(3.0, -2.0, 5.0)

    pontos = _zigzag((0.0, 0.0), 20.0)

    estimador_poucas = EstimadorGrade(centro=(0.0, 0.0))
    estimador_muitas = EstimadorGrade(centro=(0.0, 0.0))

    metade = len(pontos) // 3

    for i, (x, y) in enumerate(pontos):
        a = _amostra(rng, campo, x, y, estimador_poucas.sigma0, estimador_poucas.fracao, ts=float(i))
        if i < metade:
            estimador_poucas.atualizar(a)
        estimador_muitas.atualizar(a)

    tam_poucas = sum(sum(linha) for linha in estimador_poucas.resultado()["regiao95"]["mascara"])
    tam_muitas = sum(sum(linha) for linha in estimador_muitas.resultado()["regiao95"]["mascara"])

    assert tam_muitas <= tam_poucas


def test_sem_amostras_p_fonte_e_none():
    estimador = EstimadorGrade(centro=(0.0, 0.0))
    r = estimador.resultado()

    assert r["n"] == 0
    assert r["p_fonte"] is None
    assert r["x_map"] is None
    assert r["regiao95"] is None
    assert len(r["marginal"]) == estimador.nx
    assert len(r["marginal"][0]) == estimador.ny


def test_resultado_e_serializavel_em_json():
    import json

    rng = np.random.default_rng(1)
    campo = CampoRadiacao(fundo_usvh=0.15)
    campo.definir_fonte(1.0, 1.0, 2.0)

    estimador = EstimadorGrade(centro=(0.0, 0.0))
    for i, (x, y) in enumerate(_zigzag((0.0, 0.0), 20.0, linhas=5)):
        a = _amostra(rng, campo, x, y, estimador.sigma0, estimador.fracao, ts=float(i))
        estimador.atualizar(a)

    r = estimador.resultado()
    texto = json.dumps(r)
    assert isinstance(texto, str)


def test_atualizacao_e_rapida():
    rng = np.random.default_rng(0)
    campo = CampoRadiacao(fundo_usvh=0.15)
    campo.definir_fonte(2.0, 2.0, 3.0)

    estimador = EstimadorGrade(centro=(0.0, 0.0))
    a = _amostra(rng, campo, 1.0, 1.0, estimador.sigma0, estimador.fracao, ts=0.0)

    # aquece (compilação/alocação lazy, cache de página etc.)
    estimador.atualizar(a)

    inicio = time.perf_counter()
    for _ in range(5):
        estimador.atualizar(a)
    duracao_media = (time.perf_counter() - inicio) / 5

    # meta é bem abaixo de 50 ms; usamos uma margem generosa para não gerar
    # falsos negativos em máquinas mais lentas.
    assert duracao_media < 0.2
