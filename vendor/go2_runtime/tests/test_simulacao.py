"""Testes da camada de simulação: campo, robô e detector."""
import asyncio
import math
import time

import pytest

from ares.simulacao.campo import CampoRadiacao
from ares.simulacao.detector import DetectorSimulado
from ares.simulacao.robo import RoboSimulado


# --- CampoRadiacao ---------------------------------------------------------


def test_campo_sem_fonte_e_so_fundo():
    campo = CampoRadiacao(fundo_usvh=0.2)
    assert campo.fonte is None
    assert campo.taxa(0.0, 0.0) == pytest.approx(0.2)
    assert campo.taxa(100.0, -50.0) == pytest.approx(0.2)


def test_campo_com_fonte_segue_inverso_do_quadrado():
    campo = CampoRadiacao(fundo_usvh=0.0, altura_m=0.0)
    campo.definir_fonte(0.0, 0.0, 10.0)

    assert campo.fonte == (0.0, 0.0, 10.0)
    assert campo.taxa(1.0, 0.0) == pytest.approx(10.0)
    assert campo.taxa(2.0, 0.0) == pytest.approx(2.5)


def test_campo_soma_fundo_e_fonte_com_altura():
    campo = CampoRadiacao(fundo_usvh=0.15, altura_m=0.25)
    campo.definir_fonte(0.0, 0.0, 1.0)

    esperado = 0.15 + 1.0 / (0.0**2 + 0.25**2)
    assert campo.taxa(0.0, 0.0) == pytest.approx(esperado)


def test_campo_remover_fonte_volta_pro_fundo():
    campo = CampoRadiacao(fundo_usvh=0.3)
    campo.definir_fonte(1.0, 1.0, 5.0)
    campo.remover_fonte()

    assert campo.fonte is None
    assert campo.taxa(1.0, 1.0) == pytest.approx(0.3)


# --- RoboSimulado ------------------------------------------------------------


def test_robo_comeca_em_pe_na_origem():
    robo = RoboSimulado()
    assert robo.em_pe is True
    assert (robo.x, robo.y, robo.yaw) == (0.0, 0.0, 0.0)
    assert robo.estado() == {"conectado": True, "erro": None, "em_pe": True}


def test_robo_anda_reto_integrando_cinematica():
    async def cenario():
        robo = RoboSimulado(vx_max=1.0, vy_max=1.0, vyaw_max=2.0, frequencia_hz=20.0)
        await robo.iniciar()
        try:
            await robo.mover(vx=0.5, vy=0.0, vyaw=0.0)
            await asyncio.sleep(1.0)
        finally:
            await robo.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.x == pytest.approx(0.5, abs=0.06)
    assert robo.y == pytest.approx(0.0, abs=0.01)


def test_robo_gira_integrando_yaw():
    async def cenario():
        robo = RoboSimulado(vx_max=1.0, vy_max=1.0, vyaw_max=2.0, frequencia_hz=20.0)
        await robo.iniciar()
        try:
            await robo.mover(vx=0.0, vy=0.0, vyaw=1.0)
            await asyncio.sleep(1.0)
        finally:
            await robo.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.yaw == pytest.approx(1.0, abs=0.06)


def test_robo_limita_velocidades_ao_construtor():
    async def cenario():
        robo = RoboSimulado(vx_max=0.5, vy_max=0.3, vyaw_max=1.0, frequencia_hz=20.0)
        await robo.iniciar()
        try:
            await robo.mover(vx=100.0, vy=100.0, vyaw=100.0)
            await asyncio.sleep(0.5)
        finally:
            await robo.encerrar()
        return robo

    robo = asyncio.run(cenario())
    # em 0,5 s, no máximo vx_max * 0,5 s de deslocamento (com folga p/ 1 passo)
    assert robo.x <= 0.5 * 0.5 + 0.05
    assert robo.y <= 0.3 * 0.5 + 0.05
    assert robo.yaw <= 1.0 * 0.5 + 0.1


def test_robo_deitado_nao_anda():
    async def cenario():
        robo = RoboSimulado(frequencia_hz=20.0)
        await robo.iniciar()
        try:
            await robo.deitar()
            await robo.mover(vx=0.5, vy=0.5, vyaw=1.0)
            await asyncio.sleep(0.3)
        finally:
            await robo.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.em_pe is False
    assert (robo.x, robo.y, robo.yaw) == (0.0, 0.0, 0.0)


def test_robo_levantar_depois_de_deitar_volta_a_andar():
    async def cenario():
        robo = RoboSimulado(frequencia_hz=20.0)
        await robo.iniciar()
        try:
            await robo.deitar()
            await robo.mover(vx=0.5, vy=0.0, vyaw=0.0)
            await asyncio.sleep(0.2)
            await robo.levantar()
            await asyncio.sleep(0.5)
        finally:
            await robo.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.em_pe is True
    assert robo.x > 0.0


def test_robo_publica_poses_para_assinantes():
    poses = []

    async def cenario():
        robo = RoboSimulado(frequencia_hz=20.0)
        robo.assinar_pose(poses.append)
        await robo.iniciar()
        try:
            await asyncio.sleep(0.3)
        finally:
            await robo.encerrar()

    asyncio.run(cenario())
    assert len(poses) >= 4
    for pose in poses:
        assert pose.ts > 0


def test_robo_assinante_com_excecao_nao_derruba_o_laco():
    boas_poses = []

    def assinante_ruim(pose):
        raise RuntimeError("falha proposital")

    async def cenario():
        robo = RoboSimulado(frequencia_hz=20.0)
        robo.assinar_pose(assinante_ruim)
        robo.assinar_pose(boas_poses.append)
        await robo.iniciar()
        try:
            await asyncio.sleep(0.3)
        finally:
            await robo.encerrar()

    asyncio.run(cenario())
    assert len(boas_poses) >= 4


def test_robo_encerrar_sem_tarefa_iniciada_nao_falha():
    async def cenario():
        robo = RoboSimulado()
        await robo.encerrar()

    asyncio.run(cenario())


# --- DetectorSimulado --------------------------------------------------------


def _detector_fixo(campo, x=0.0, y=0.0, **kwargs):
    return DetectorSimulado(campo, posicao_detector=lambda: (x, y), **kwargs)


def test_detector_media_dr_em_fundo_puro_aproxima_fundo():
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(
        campo,
        periodo_s=0.01,
        janela_s=0.2,
        cps_por_usvh=3000.0,
        semente=1,
    )

    # preenche a janela antes de começar a coletar leituras
    for _ in range(20):
        detector._amostrar()

    valores = []
    detector.assinar(lambda leitura: valores.append(leitura.dr_usvh))
    for _ in range(200):
        detector._amostrar()

    media = sum(valores) / len(valores)
    assert media == pytest.approx(0.2, rel=0.25)


def test_detector_perto_da_fonte_da_leitura_bem_maior():
    campo = CampoRadiacao(fundo_usvh=0.2, altura_m=0.25)
    campo.definir_fonte(0.0, 0.0, 50.0)
    detector = _detector_fixo(
        campo,
        x=0.0,
        y=0.0,
        periodo_s=0.01,
        janela_s=0.2,
        cps_por_usvh=3000.0,
        semente=2,
    )

    valores = []
    detector.assinar(lambda leitura: valores.append(leitura.dr_usvh))
    for _ in range(220):
        detector._amostrar()

    media = sum(valores) / len(valores)
    assert media > campo.fundo_usvh * 5


def test_detector_e_deterministico_com_mesma_semente():
    campo1 = CampoRadiacao(fundo_usvh=0.2)
    campo2 = CampoRadiacao(fundo_usvh=0.2)

    det1 = _detector_fixo(campo1, periodo_s=0.05, janela_s=0.5, semente=7)
    det2 = _detector_fixo(campo2, periodo_s=0.05, janela_s=0.5, semente=7)

    leituras1 = []
    leituras2 = []
    det1.assinar(leituras1.append)
    det2.assinar(leituras2.append)

    for _ in range(30):
        det1._amostrar()
        det2._amostrar()

    assert len(leituras1) == len(leituras2) == 30
    for l1, l2 in zip(leituras1, leituras2):
        assert l1.dr_usvh == pytest.approx(l2.dr_usvh)
        assert l1.cpm == l2.cpm
        assert l1.cps == l2.cps
        assert l1.dose_usv == pytest.approx(l2.dose_usv)


def test_detector_pula_periodo_sem_posicao():
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = DetectorSimulado(campo, posicao_detector=lambda: None, periodo_s=0.01, semente=3)

    valores = []
    detector.assinar(valores.append)
    for _ in range(10):
        detector._amostrar()

    assert valores == []


def test_detector_acumula_dose():
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(campo, periodo_s=0.01, janela_s=0.2, cps_por_usvh=3000.0, semente=4)

    doses = []
    detector.assinar(lambda leitura: doses.append(leitura.dose_usv))
    for _ in range(50):
        detector._amostrar()

    assert doses[-1] >= doses[0]
    assert all(b >= a for a, b in zip(doses, doses[1:]))


def test_detector_estado_traz_detector_id():
    campo = CampoRadiacao()
    detector = _detector_fixo(campo, detector_id="fs5000-9")
    estado = detector.estado()
    assert estado["conectado"] is True
    assert estado["erro"] is None
    assert estado["detector_id"] == "fs5000-9"


def test_detector_iniciar_e_encerrar_ciclo_de_vida_limpo():
    async def cenario():
        campo = CampoRadiacao(fundo_usvh=0.2)
        detector = _detector_fixo(campo, periodo_s=0.02, janela_s=0.1, semente=5)
        leituras = []
        detector.assinar(leituras.append)
        await detector.iniciar()
        try:
            await asyncio.sleep(0.15)
        finally:
            await detector.encerrar()
        return leituras

    leituras = asyncio.run(cenario())
    assert len(leituras) >= 3


def test_detector_assinante_com_excecao_nao_derruba_o_laco():
    boas_leituras = []

    def assinante_ruim(leitura):
        raise RuntimeError("falha proposital")

    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(campo, periodo_s=0.01, semente=6)
    detector.assinar(assinante_ruim)
    detector.assinar(boas_leituras.append)

    for _ in range(10):
        detector._amostrar()

    assert len(boas_leituras) == 10


def test_detector_encerrar_sem_tarefa_iniciada_nao_falha():
    async def cenario():
        campo = CampoRadiacao()
        detector = _detector_fixo(campo)
        await detector.encerrar()

    asyncio.run(cenario())


@pytest.mark.parametrize("periodo_s", [0.1, 0.5, 1.0, 2.0])
def test_detector_dose_independe_do_periodo_amostragem(periodo_s):
    """Dose acumulada deve ser independente do período de amostragem.

    Com campo de fundo puro a 0.36 µSv/h, após N períodos de duração periodo_s,
    a dose total deve ser ≈ 0.36 * (N * periodo_s) / 3600, com tolerância ±10%.
    """
    fundo_usvh = 0.36
    campo = CampoRadiacao(fundo_usvh=fundo_usvh)

    # Suficiente para que o erro relativo Poisson seja pequeno
    n_periodos = 20000
    tempo_total_s = n_periodos * periodo_s
    dose_esperada_usv = fundo_usvh * tempo_total_s / 3600.0

    detector = _detector_fixo(
        campo,
        periodo_s=periodo_s,
        janela_s=5.0,
        cps_por_usvh=2.6,
        semente=42,
    )

    leituras = []
    detector.assinar(leituras.append)
    for _ in range(n_periodos):
        detector._amostrar()

    dose_acumulada = leituras[-1].dose_usv if leituras else 0.0

    # Tolerância ±10%
    tolerancia = 0.1
    assert dose_acumulada == pytest.approx(
        dose_esperada_usv, rel=tolerancia
    ), (
        f"periodo_s={periodo_s}: "
        f"dose acumulada={dose_acumulada:.6f} µSv, "
        f"esperada={dose_esperada_usv:.6f} µSv"
    )


# --- DetectorSimulado imitando o FS-5000 (CPS Poisson + DR média móvel) ------


def _autocorr_passo1(valores):
    import numpy as np

    v = np.asarray(valores, dtype=float)
    v = v - v.mean()
    return float(np.sum(v[1:] * v[:-1]) / np.sum(v * v))


@pytest.mark.parametrize("periodo_s", [0.01, 1.0])
def test_detector_cps_e_contagem_poisson_de_1s(periodo_s):
    """CPS é uma contagem Poisson de 1 s (média k·taxa), qualquer que seja o período."""
    import numpy as np

    fundo_usvh = 2.0
    k = 2.6
    campo = CampoRadiacao(fundo_usvh=fundo_usvh)
    detector = _detector_fixo(campo, periodo_s=periodo_s, cps_por_usvh=k, semente=11)

    brutos = []
    detector.assinar(lambda leitura: brutos.append(leitura.cps))
    for _ in range(20000):
        detector._amostrar()

    assert all(type(c) is int and c >= 0 for c in brutos)
    cps = np.asarray(brutos, dtype=float)
    media = cps.mean()
    assert media == pytest.approx(k * fundo_usvh, rel=0.03)
    assert cps.var() / media == pytest.approx(1.0, abs=0.05)
    assert abs(_autocorr_passo1(cps)) < 0.05


def test_detector_dr_e_media_movel_autocorrelacionada():
    """DR é média móvel de 30 s (padrão) das contagens: suave e atrasado."""
    import numpy as np

    fundo_usvh = 0.17
    k = 2.6
    campo = CampoRadiacao(fundo_usvh=fundo_usvh)
    detector = _detector_fixo(campo, cps_por_usvh=k, semente=12)

    leituras = []
    detector.assinar(leituras.append)
    for _ in range(3000):
        detector._amostrar()

    dr = np.asarray([leitura.dr_usvh for leitura in leituras[30:]])
    assert dr.mean() == pytest.approx(fundo_usvh, rel=0.1)
    assert _autocorr_passo1(dr) > 0.9


def test_detector_dr_e_cpm_consistentes_com_janela_de_cps():
    campo = CampoRadiacao(fundo_usvh=0.5)
    k = 2.6
    detector = _detector_fixo(campo, cps_por_usvh=k, janela_s=4.0, semente=13)

    leituras = []
    detector.assinar(leituras.append)
    for _ in range(50):
        detector._amostrar()

    for i in range(3, len(leituras)):
        janela = [leitura.cps for leitura in leituras[i - 3 : i + 1]]
        dr_esperado = sum(janela) / 4.0 / k
        assert leituras[i].dr_usvh == pytest.approx(dr_esperado)
        assert leituras[i].cpm == round(leituras[i].dr_usvh * k * 60.0)


def test_detector_janela_padrao_e_30s():
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(campo, semente=14)
    assert detector._janela.maxlen == 30


def test_detector_ts_inclui_latencia_de_leitura_padrao():
    """`Leitura.ts` deve ser a hora da contagem + a latência (padrão 0,5 s).

    O sincronizador trata `ts` como instante de chegada e subtrai a latência
    para achar o instante efetivo (de contagem); sem essa compensação o
    sincronizador buscaria a pose de meio segundo no passado, associando a
    contagem feita AGORA à posição de onde o robô estava antes.
    """
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(campo, periodo_s=0.01, semente=20)

    antes = time.time()
    detector.assinar(lambda leitura: None)
    leituras = []
    detector.assinar(leituras.append)
    detector._amostrar()
    depois = time.time()

    assert leituras[0].ts == pytest.approx((antes + depois) / 2 + 0.5, abs=0.05)


def test_detector_ts_usa_latencia_configurada():
    campo = CampoRadiacao(fundo_usvh=0.2)
    detector = _detector_fixo(campo, periodo_s=0.01, semente=21, latencia_leitura_s=1.2)

    leituras = []
    detector.assinar(leituras.append)
    antes = time.time()
    detector._amostrar()
    depois = time.time()

    assert leituras[0].ts == pytest.approx((antes + depois) / 2 + 1.2, abs=0.05)
