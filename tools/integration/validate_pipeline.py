#!/usr/bin/env python3
"""Software-only replay through JSONL, WS, ARES API, simulated teleop and export."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
from datetime import datetime

import httpx
from radiacode import RawData
import uvicorn
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools/radiacode_usb'/f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def listener():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    return sock


async def wait_until(cond, seconds=5):
    deadline = time.monotonic()+seconds
    while not cond():
        if time.monotonic()>deadline:
            raise AssertionError('Timeout aguardando condição do pipeline')
        await asyncio.sleep(.02)


async def validate(robot_root, installed=False):
    package_root = Path(robot_root).resolve() if installed else Path(robot_root).resolve()/'src'
    sys.path.insert(0, str(package_root))
    import ares
    if installed:
        assert Path(ares.__file__).resolve().is_relative_to(package_root)
    from ares.config import Config
    from ares.orquestrador import criar_orquestrador
    from ares.servidor.app import criar_app
    service, counts = load('service'), load('counts')
    records = [json.loads(line)['record'] for line in (ROOT/'tests/radiacode/fixtures/real_raw_excerpt.jsonl').read_text().splitlines()]
    with tempfile.TemporaryDirectory(prefix='ares-software-validation-') as temporary:
        base = Path(temporary)
        bridge = service.Bridge(base/'usb')
        bridge.identity = base/'usb'/'REPLAY-NOT-HARDWARE'
        bridge.identity.mkdir(parents=True)
        sock_usb, sock_app = listener(), listener()
        usb_port, app_port = sock_usb.getsockname()[1], sock_app.getsockname()[1]
        usb = uvicorn.Server(uvicorn.Config(service.create_app(bridge, manage_reader=False), log_level='error'))
        config = Config(fonte_radiacao='radiacode', modo='simulacao', dados=str(base/'simulacao'),
                        radiacode_url=f'ws://127.0.0.1:{usb_port}/ws')
        orq = criar_orquestrador(config, periodo_publicacao_s=.1, periodo_estado_s=.05)
        app = uvicorn.Server(uvicorn.Config(criar_app(orq, orq.teleop), log_level='error'))
        running = [asyncio.create_task(usb.serve(sockets=[sock_usb])), asyncio.create_task(app.serve(sockets=[sock_app]))]
        follower = asyncio.create_task(bridge.follow())
        producer = None
        try:
            await wait_until(lambda: usb.started and app.started and orq.radiacao._conectado)
            async def produce(session):
                pairs = counts.PairRawData()
                for data in records:
                    await asyncio.sleep(.25)  # accelerated replay, not a measurement of latency
                    count = pairs.add(RawData(datetime.fromisoformat(data['dt']), data['count_rate'], data['dose_rate']),
                                      time.time_ns(), time.monotonic_ns(), session, 'REPLAY-NOT-HARDWARE')
                    if count is not None:
                        count.update(timing_quality='live_receipt', dose_rate_uSv_h=.12)
                        with (bridge.identity/'counts_1s.jsonl').open('a') as stream:
                            stream.write(json.dumps(count)+'\n')
            producer = asyncio.create_task(produce('first-replay'))
            await wait_until(lambda: orq.radiacao.estado()['conectado'])
            await asyncio.sleep(.5)  # allow pose history for the unchanged 0.5 s correction
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{app_port}', trust_env=False) as client:
                page = await client.get('/')
                assert 'id="radiation-map"' in page.text
                for asset in ('renderer.js', 'integration.js', 'styles.css'):
                    asset_response = await client.get('/static/approved/' + asset)
                    assert asset_response.status_code == 200 and len(asset_response.content) > 1000
                response = await client.post('/api/missao/iniciar', json={'nome':'Replay software; USB e pose física NÃO testados'})
                response.raise_for_status()
                mission_id = response.json()['id']
                async with connect(f'ws://127.0.0.1:{app_port}/ws/comando') as ws:
                    for _ in range(15):
                        await ws.send(json.dumps({'vx':.3, 'vy':0, 'vyaw':0}))
                        await asyncio.sleep(.15)
                    await ws.send(json.dumps({'vx':0, 'vy':0, 'vyaw':0}))
                await producer
                bridge.state(False, 'Interrupção USB simulada')
                await wait_until(lambda: not orq.radiacao.estado()['conectado'])
                bridge.identity = base/'usb'/'NEW-REPLAY-NOT-HARDWARE'
                bridge.identity.mkdir()
                bridge.offset = 0
                producer = asyncio.create_task(produce('second-replay'))
                await wait_until(lambda: orq.radiacao.estado()['conectado'])
                await asyncio.sleep(.6)
                response = await client.post('/api/missao/encerrar')
                response.raise_for_status()
                mission = response.json()
                data = (await client.get(f'/api/missoes/{mission_id}.json')).json()
                csv = (await client.get(f'/api/missoes/{mission_id}/amostras.csv')).text
                assert mission['resultado']['tipo']=='aquisicao' and mission['n_amostras']>=5
                assert all(isinstance(row['cps'],int) for row in data['amostras'])
                assert max(row['x'] for row in data['amostras'])>.3
                assert all(row['dose_usv'] is None for row in data['leituras'])
                assert len({row['detector_id'] for row in data['leituras']})==2
                assert 'ts,x,y,dr_usvh,cpm,cps,lacuna_pose_s' in csv
                spec = importlib.util.spec_from_file_location('exporter', ROOT/'tools/integration/export_sessions.py')
                exporter = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(exporter)
                paths = exporter.export(base)
                assert len(paths) == 2
                saved_json = json.loads(next(Path(p) for p in paths if p.endswith('.json')).read_text())
                assert saved_json['missao']['metadata']['detector'] == 'Radiacode 110'
                assert len(saved_json['amostras']) == len(data['amostras'])
                saved_csv = next(Path(p) for p in paths if p.endswith('.csv')).read_text()
                assert saved_csv.startswith('ts,x,y,dr_usvh,cpm,cps,lacuna_pose_s')
                report = {'hardware_test':False, 'robot_physical_test':False, 'installed_package_test':installed, 'approved_dashboard_assets':True,
                          'input':'accelerated replay of recorded RawData, with new host timestamps',
                          'positioned_samples':len(data['amostras']), 'saved_poses':len(data['poses']),
                          'saved_readings':len(data['leituras']), 'usb_session_recovery':True,
                          'teleop_simulation':True, 'mission_without_calibration':True,
                          'csv_and_json_export':True, 'automatic_file_export':True, 'status':'passed'}
        finally:
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            follower.cancel()
            await asyncio.gather(follower, return_exceptions=True)
            usb.should_exit = app.should_exit = True
            await asyncio.gather(*running)
            sock_usb.close()
            sock_app.close()
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root', required=True)
    parser.add_argument('--installed', action='store_true')
    args=parser.parse_args()
    print(json.dumps(asyncio.run(validate(args.robot_root, args.installed)), indent=2, ensure_ascii=False))
