"""Radiacode selection and acquisition, with no physical robot/detector."""
import asyncio
import json
import time

import pytest
from websockets.asyncio.server import serve

from ares.config import Config
from ares.modelos import Leitura, Pose
from ares.orquestrador import criar_orquestrador
from ares.radiacao.radiacode import ClienteRadiacode


def reading(seq=1, session='test', **overrides):
    data = dict(ts=time.time(), dr_usvh=.12, cps=20, cpm=1200, dose_usv=None,
                sequence=seq, session_id=session, exposure_s=1.0, timing_quality='live_receipt')
    data.update(overrides)
    return dict(tipo='leitura', aparelho_id='radiacode:test', dados=data)


def test_env_selects_radiacode_without_fs5000_calibration():
    cfg = Config.de_ambiente({'ARES_FONTE_RADIACAO':'radiacode', 'ARES_RADIACODE_URL':'ws://localhost:1098/ws'})
    assert cfg.fonte_radiacao == 'radiacode' and cfg.radiacode_cps_por_usvh is None
    assert cfg.cps_por_usvh == 2.6  # FS setting remains separate
    for k in ('0', '-1', 'nan', 'inf'):
        with pytest.raises(ValueError):
            Config.de_ambiente({'ARES_RADIACODE_CPS_POR_USVH': k})


def test_client_rejects_stale_fractional_and_repeated_counts_and_resets_session():
    client = ClienteRadiacode()
    client._processar_evento(dict(tipo='snapshot', dados=[dict(id='radiacode:test', estado='conectado')]))
    rows = []
    client.assinar(rows.append)
    client._processar_evento(reading())
    client._processar_evento(reading())
    client._processar_evento(reading(2, ts=time.time()-5))
    client._processar_evento(reading(2, cps=19.6))
    client._processar_evento(reading(2, timing_quality='batched_uncertain'))
    client._processar_evento(reading(1, session='new'))
    assert len(rows) == 2 and rows[0].cps == 20 and rows[0].dose_usv is None
    assert client.descartadas == 4


def test_acquisition_saves_xy_time_counts_without_map_calibration(tmp_path):
    async def run():
        cfg = Config(fonte_radiacao='radiacode', dados=str(tmp_path), latencia_leitura_s=.5)
        orq = criar_orquestrador(cfg)
        # No I/O: inject host-stamped callbacks with analytically known poses.
        now = time.time()
        orq.robo._conectado = True
        client = orq.radiacao
        client._conectado = True
        client._processar_evento(dict(tipo='snapshot', dados=[dict(id='radiacode:test', estado='conectado')]))
        orq._ao_receber_pose(Pose(now-1, 0, 0, 0))
        info = await orq.iniciar_missao('USB test, position simulated')
        # The unchanged synchronizer evaluates position at ts - 0.5.
        orq._ao_receber_pose(Pose(now, 2, 0, 0))
        client._processar_evento(reading(ts=now))
        saved = await orq.encerrar_missao()
        export = orq.repositorio.exportar_json(info['id'])
        orq.repositorio.fechar()
        return saved, export, orq.ultimo_mapa
    saved, export, mapa = asyncio.run(run())
    assert saved['resultado']['tipo'] == 'aquisicao'
    assert saved['n_amostras'] == 1 and saved['resultado']['cps_por_usvh'] is None
    assert export['amostras'][0]['x'] == pytest.approx(1.0)
    assert export['amostras'][0]['cps'] == 20
    assert export['leituras'][0]['dose_usv'] is None and len(export['poses']) == 1
    assert export['missao']['metadata']['dose_conversion_verified'] is False
    assert mapa['unidade'] == 'CPS' and mapa['cps_por_usvh'] is None
    finite = [v for col in mapa['valores'] for v in col if v is not None]
    assert len(finite) > 1 and all(v == pytest.approx(20) for v in finite)
    assert any(v is None for col in mapa['valores'] for v in col)


def test_ws_disconnect_and_reconnect_resume_new_counts(tmp_path):
    async def run():
        calls = 0
        async def handler(ws):
            nonlocal calls
            calls += 1
            id_ = f'radiacode:test:session-{calls}'
            await ws.send(json.dumps(dict(tipo='snapshot', dados=[dict(id=id_, estado='conectado')])))
            event = reading(session=f'session-{calls}')
            event['aparelho_id'] = id_
            await ws.send(json.dumps(event))
            await asyncio.sleep(.02)
        async with serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = ClienteRadiacode(url=f'ws://127.0.0.1:{port}/ws', backoff_min=.02, backoff_max=.04)
            rows = []
            client.assinar(rows.append)
            await client.iniciar()
            try:
                deadline = time.monotonic()+2
                while len(rows)<3 and time.monotonic()<deadline:
                    await asyncio.sleep(.01)
                assert len(rows)>=3
                assert len({row.detector_id for row in rows}) >= 3
            finally:
                await client.encerrar()
            assert not client.estado()['conectado']
    asyncio.run(run())


def test_optional_calibration_never_uses_the_fs5000_coefficient(tmp_path):
    async def run():
        cfg = Config(fonte_radiacao="radiacode", dados=str(tmp_path), radiacode_cps_por_usvh=123.)
        orq = criar_orquestrador(cfg)
        orq.robo._conectado = True
        orq.radiacao._conectado = True
        orq.radiacao._processar_evento(dict(tipo="snapshot", dados=[dict(id="radiacode:test", estado="conectado")]))
        orq._ao_receber_pose(Pose(time.time(), 0, 0, 0))
        await orq.iniciar_missao()
        assert orq._missao.mapa.cps_por_usvh == 123.
        assert orq._missao.estimador.cps_por_usvh == 123.
        await orq.encerrar_missao()
        orq.repositorio.fechar()
    asyncio.run(run())


def test_real_mode_keeps_web_rtc_driver_and_independent_usb_source(tmp_path):
    from ares.robo.go2 import Go2WebRTC
    config = Config(modo="real", fonte_radiacao="radiacode", dados=str(tmp_path))
    orq = criar_orquestrador(config)
    try:
        assert isinstance(orq.robo, Go2WebRTC)
        assert isinstance(orq.radiacao, ClienteRadiacode)
        assert orq.campo is None
        assert not orq.robo.estado()["conectado"]
    finally:
        orq.repositorio.fechar()


def test_new_session_snapshot_replaces_stale_device_selection():
    client = ClienteRadiacode()
    rows = []
    client.assinar(rows.append)
    for session in ('old', 'new'):
        id_ = f'radiacode:test:{session}'
        client._processar_evento(dict(tipo='snapshot', dados=[dict(id=id_, estado='conectado')]))
        event = reading(session=session)
        event['aparelho_id'] = id_
        client._processar_evento(event)
    assert [row.detector_id for row in rows] == ['radiacode:test:old', 'radiacode:test:new']
    assert set(client._estados_aparelhos) == {'radiacode:test:new'}
