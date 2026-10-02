"""Testes do mapa medido (grade de contagens do detector, sem IDW no DR)."""
import math

import pytest

from ares.mapa import MapaMedido
from ares.modelos import Amostra


def _amostra(x, y, cps, ts=0.0):
    return Amostra(
        ts=ts, x=x, y=y, dr_usvh=0.0, cpm=cps * 60, cps=cps, lacuna_pose_s=0.0
    )


def test_celula_vazia_nao_aparece_em_celulas():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0)
    assert mapa.celulas() == []


def test_media_por_celula_a_partir_do_cps():
    # k=2.0, T=1.0 -> media = soma_cps/(k*T*n)
    mapa = MapaMedido(
        centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0, cps_por_usvh=2.0, exposicao_s=1.0
    )
    mapa.adicionar(_amostra(0.2, 0.2, 4))
    mapa.adicionar(_amostra(0.6, 0.9, 6))  # mesma célula que a anterior
    celulas = mapa.celulas()
    assert len(celulas) == 1
    c = celulas[0]
    assert c["n"] == 2
    assert c["media"] == pytest.approx((4 + 6) / (2.0 * 1.0 * 2))


def test_celulas_agrupam_por_indice_de_grade():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0)
    mapa.adicionar(_amostra(0.4, 0.4, 10))  # célula (2,2)
    mapa.adicionar(_amostra(-1.4, -1.4, 20))  # célula (0,0)
    celulas = sorted(mapa.celulas(), key=lambda c: (c["x"], c["y"]))
    assert len(celulas) == 2
    assert celulas[0]["n"] == 1
    assert celulas[1]["n"] == 1


def test_amostra_nao_finita_e_rejeitada_e_contada():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0)
    mapa.adicionar(_amostra(math.nan, 0.0, 5))
    mapa.adicionar(_amostra(0.0, math.inf, 5))
    assert mapa.celulas() == []
    assert mapa.rejeitadas == 2


def test_amostra_fora_da_area_e_rejeitada_e_contada():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0)
    mapa.adicionar(_amostra(1000.0, 1000.0, 5))
    assert mapa.celulas() == []
    assert mapa.rejeitadas == 1


def test_amostra_cps_invalido_e_rejeitada():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0)
    mapa.adicionar(_amostra(0.0, 0.0, -5))
    assert mapa.celulas() == []
    assert mapa.rejeitadas == 1


def test_grade_interpolada_formato_e_json_serializavel():
    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0, raio_idw_m=1.5)
    mapa.adicionar(_amostra(0.2, 0.2, 4))
    grade = mapa.grade_interpolada()
    assert grade["nx"] == 4
    assert grade["ny"] == 4
    assert grade["res"] == 1.0
    assert len(grade["valores"]) == 4
    assert len(grade["valores"][0]) == 4
    import json

    texto = json.dumps(grade)
    assert "NaN" not in texto


def test_celula_longe_fica_none_na_grade_interpolada():
    mapa = MapaMedido(
        centro=(0.0, 0.0), lado_m=20.0, resolucao_m=1.0, raio_idw_m=1.5
    )
    mapa.adicionar(_amostra(0.5, 0.5, 4))
    grade = mapa.grade_interpolada()
    # canto oposto da grade, bem longe do único ponto medido
    assert grade["valores"][0][0] is None


def test_valor_interpolado_fica_entre_os_dois_pontos_medidos():
    mapa = MapaMedido(
        centro=(0.0, 0.0),
        lado_m=6.0,
        resolucao_m=1.0,
        raio_idw_m=1.5,
        cps_por_usvh=2.0,
        exposicao_s=1.0,
    )
    # duas células medidas com médias bem diferentes, com uma célula vazia
    # entre elas a até 1 m de cada uma (dentro do raio de 1,5 m de ambas)
    mapa.adicionar(_amostra(-1.5, 0.5, 2))  # célula da esquerda: media baixa
    mapa.adicionar(_amostra(0.5, 0.5, 40))  # célula da direita: media alta

    grade = mapa.grade_interpolada()
    x0, y0, res = grade["x0"], grade["y0"], grade["res"]

    def indice(x, y):
        return int((x - x0) / res), int((y - y0) / res)

    ix_baixa, iy = indice(-1.5, 0.5)
    ix_alta, _ = indice(0.5, 0.5)
    # célula entre as duas medidas (dentro do raio de ambas)
    ix_meio = (ix_baixa + ix_alta) // 2

    v_baixa = grade["valores"][ix_baixa][iy]
    v_alta = grade["valores"][ix_alta][iy]
    v_meio = grade["valores"][ix_meio][iy]

    assert v_baixa is not None and v_alta is not None and v_meio is not None
    assert v_baixa < v_meio < v_alta


def test_celula_medida_retorna_seu_proprio_valor_na_grade_interpolada():
    mapa = MapaMedido(
        centro=(0.0, 0.0), lado_m=4.0, resolucao_m=1.0, raio_idw_m=1.5,
        cps_por_usvh=2.0, exposicao_s=1.0,
    )
    mapa.adicionar(_amostra(0.2, 0.2, 4))
    celula = mapa.celulas()[0]
    grade = mapa.grade_interpolada()
    x0, y0, res = grade["x0"], grade["y0"], grade["res"]
    ix = int((celula["x"] - x0) / res)
    iy = int((celula["y"] - y0) / res)
    assert grade["valores"][ix][iy] == pytest.approx(celula["media"])


def test_desempenho_grade_interpolada_grid_40x40(benchmark=None):
    import time

    mapa = MapaMedido(centro=(0.0, 0.0), lado_m=20.0, resolucao_m=0.5, raio_idw_m=1.5)
    # popula quase todas as células
    n = 0
    x0 = mapa.x0
    y0 = mapa.y0
    for ix in range(mapa.nx):
        for iy in range(mapa.ny):
            if (ix + iy) % 3 != 0:
                continue
            x = x0 + (ix + 0.5) * mapa.resolucao_m
            y = y0 + (iy + 0.5) * mapa.resolucao_m
            mapa.adicionar(_amostra(x, y, 5 + n % 7))
            n += 1

    inicio = time.perf_counter()
    mapa.grade_interpolada()
    duracao = time.perf_counter() - inicio
    assert duracao < 0.05
