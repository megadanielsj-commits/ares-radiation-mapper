"""One operator surface over the classic simulator and Werik's independent inputs.

No map or teleoperation algorithm is implemented here. Live inputs use Werik's
Orquestrador/Sincronizador/Teleop unchanged; its ordered worker calls the exact
v4 MapService after synchronization. The complete simulation uses v4 directly.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import socket
import sys
import threading
import time

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor/go2_runtime/src"))

from ares.config import Config
from ares.missao import RepositorioMissoes
from ares.orquestrador import Orquestrador
from ares.radiacao.radiacode import ClienteRadiacode
from ares.robo.go2 import Go2WebRTC
from ares.simulacao.campo import CampoRadiacao
from ares.simulacao.detector import DetectorSimulado
from ares.simulacao.robo import RoboSimulado
from ares.teleop import Teleop
from ares_mapper.config import load_scenario
from ares_mapper.core.event_bus import EventBus
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.domain.enums import MappingQuality, MissionState, Quality, SyncMethod
from ares_mapper.domain.models import ExposureSummary, MappedSample
from ares_mapper.mapping.service import MapService

MODES = {
    "simulation": {"name": "Simulação completa", "robot": "simulated", "radiation": "simulated"},
    "usb_simulated_robot": {"name": "Radiacode real · robô simulado", "robot": "simulated", "radiation": "real"},
    "robot_simulated_source": {"name": "Go2 real · fonte simulada", "robot": "real", "radiation": "simulated"},
    "hardware": {"name": "Go2 e Radiacode reais", "robot": "real", "radiation": "real"},
}

# The USB bridge publishes one pair of 0.5 s RawData bins per 1 s count window.
# Its 0.25 s USB polling interval is not the measurement cadence.
RADIACODE_READING_PERIOD_S = 1.0


def json_finite(value):
    """Unknown statistical bounds become JSON null, without changing the model."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: json_finite(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_finite(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class ConsoleBus(EventBus):
    async def publish(self, event_type, payload):
        await super().publish(event_type, json_finite(payload))


class Setup(BaseModel):
    mode: str = "simulation"
    x_m: float = Field(default=7.5, ge=-100, le=100, allow_inf_nan=False)
    y_m: float = Field(default=5.5, ge=-100, le=100, allow_inf_nan=False)
    dose_rate_at_1m_uSv_h: float = Field(default=10_000, gt=0, le=10_000_000, allow_inf_nan=False)
    duration_s: int = Field(default=3600, ge=10, le=86400)
    simulated_robot_speed_m_s: float = Field(default=.45, ge=.05, le=2, allow_inf_nan=False)


def scenario(data, setup):
    config = load_scenario(ROOT / "config/scenarios/static_source.yaml")
    config.application.data_directory = Path(data) / setup.mode
    config.application.open_browser = False
    config.mission.duration_s = setup.duration_s
    if setup.mode == "simulation":
        # Change motion speed, not the clock or the detector's sampling time.
        config.mission.simulation_speed = 1.0
        config.trajectory.speed_m_s = setup.simulated_robot_speed_m_s
        for detector in config.detectors:
            detector.publish_rate_hz = 1.0 / RADIACODE_READING_PERIOD_S
            detector.jitter_ms_std = 0
            detector.dropout_probability = 0
            detector.duplicate_probability = 0
        controller = MissionController(config)
        controller.configure_static_simulation_source(x_m=setup.x_m, y_m=setup.y_m,
            dose_rate_at_1m_uSv_h=setup.dose_rate_at_1m_uSv_h)
        return controller.scenario
    # Live odometry is relative to the Go2, including negative coordinates.
    config.world.bounds_m.x_min, config.world.bounds_m.x_max = -10, 10
    config.world.bounds_m.y_min, config.world.bounds_m.y_max = -10, 10
    config.trajectory.start_m = [0, 0, .32]
    config.detectors[0].sensor_id = "simulated_radiation" if MODES[setup.mode]["radiation"] == "simulated" else "radiacode_usb"
    config.radiation_sources[0].position_keyframes[0].x_m = setup.x_m
    config.radiation_sources[0].position_keyframes[0].y_m = setup.y_m
    config.radiation_sources[0].strength_keyframes[0].dose_rate_at_reference_uSv_h = setup.dose_rate_at_1m_uSv_h
    if MODES[setup.mode]["radiation"] == "real":
        config.radiation_sources[0].enabled = False
        # Map the separately reported dose rate. Preserve raw CPS in the
        # original acquisition/synchronization path; no count calibration.
        config.detectors[0].observation_mode = "dose_rate_robust"
        config.detectors[0].response_mode = "dose_direct"
        config.detectors[0].response_compensation_enabled = False
        config.radiation_sources[0].strength_keyframes[0].dose_rate_at_reference_uSv_h = 250
    return config


class MapWorker:
    """Translate synchronized samples, then call the unchanged v4 map worker."""
    def __init__(self, owner, mission_id):
        self.owner = owner
        self.samples = []
        self.skipped_dose_samples = 0
        self.lock = threading.Lock()
        c = owner.scenario
        self.service = MapService(mission_id, c.world, c.mapping, field=None,
            inference=c.inference, grid_config=c.grid, residual_config=c.residual,
            detectors=c.detectors, seed=c.mission.seed)

    def atualizar(self, sample):
        with self.lock:
            self._update(sample)

    def _update(self, sample):
        rate = sample.cps / self.owner.sensitivity if self.owner.simulated_radiation else sample.dr_usvh
        if rate is None or not math.isfinite(rate) or rate < 0:
            # The original repository still keeps the positioned count sample.
            # A missing reported dose is not zero and must not be fabricated.
            self.skipped_dose_samples += 1
            return
        elapsed = sample.ts - self.owner.latency - self.owner.started_wall
        if elapsed < 0:
            return  # raw data remain recorded; no pre-mission point is mapped
        n = len(self.samples) + 1
        pose = self.owner.orq.ultima_pose
        mapped = MappedSample(mission_id=self.owner.mission_id,
            mapped_sequence=n, radiation_sequence=n, sensor_id=self.owner.scenario.detectors[0].sensor_id,
            time_domain_id=f"host:{self.owner.mission_id}", effective_measurement_time_ns=int(elapsed*1e9),
            frame_id="odom", base_x_m=sample.x, base_y_m=sample.y, base_z_m=.32,
            sensor_x_m=sample.x, sensor_y_m=sample.y, sensor_z_m=.57,
            sensor_yaw_rad=pose.yaw if pose else 0,
            dose_rate_uSv_h_raw=rate, dose_rate_uSv_h_filtered=rate,
            cumulative_dose_uSv=None, cps=sample.cps, cpm=sample.cpm,
            integration_time_s=1, sync_method=SyncMethod.LINEAR_SLERP,
            max_pose_gap_ms=1000*sample.lacuna_pose_s, sync_error_estimate_ms=1000*self.owner.latency,
            pose_quality=Quality.VALID, radiation_quality=Quality.VALID,
            mapping_quality=MappingQuality.VALID,
            flags=["WERIK_TIMESTAMP_SYNC", "SIMULATED_RADIATION" if self.owner.simulated_radiation else "DOSE_CONVERSION_UNVERIFIED"])
        filtered = self.service.add_sample(mapped)
        if sample.dr_usvh is not None and math.isfinite(sample.dr_usvh) and sample.dr_usvh >= 0:
            self.owner.reported_dose_integral += sample.dr_usvh/3600
        self.samples.append(filtered)

    def prediction(self):
        with self.lock:
            prediction = self.service.predict(self.owner.current_time_ns)
            return self.owner.map_presentation(prediction)


class LiveOrchestrator(Orquestrador):
    """Replace only the presentation worker; original input and sync loops persist."""
    def _metadata_radiacode(self):
        metadata = super()._metadata_radiacode()
        metadata.update(operation_mode=self.console.setup.mode,
            radiation_mode="simulated" if self.console.simulated_radiation else "real")
        if self.console.simulated_radiation:
            metadata.update(detector="Synthetic detector", source="simulation",
                dose_conversion_verified=True, cumulative_dose_available=True)
        return metadata

    async def _publicar_resultado(self, mission):
        worker = mission.estimador
        prediction = await asyncio.to_thread(worker.prediction)
        self.console.latest_map = prediction
        # The dose anchor covers precisely these samples. Publish them first,
        # so a mapped_sample cannot be counted again after its map_update.
        await self.console.publish_mapped(prediction.sample_count)
        await self.console.event_bus.publish("map_update", self.console.latest_map)
        result = {"missao_id": mission.id, "n": len(worker.samples),
            "map_engine": "ares_classic_v4", "dose_conversion_verified": False}
        self.ultimo_resultado = result
        return result


class LiveController:
    def __init__(self, config, setup, data, event_bus, factories=None):
        self.scenario, self.setup, self.event_bus = config, setup, event_bus
        self.simulated_radiation = MODES[setup.mode]["radiation"] == "simulated"
        self.sensitivity = config.detectors[0].sensitivity_cps_per_uSv_h
        self.latency = float(os.getenv("ARES_LATENCIA_LEITURA_S", ".5"))
        self.started_wall = 0
        self.state = MissionState.READY
        self.mission_id = None
        self.mission_directory = None
        self.latest_map = self.map_service = None
        self.worker = None
        self.pump_task = self.timer_task = None
        self._published = 0
        self.reported_dose_integral = 0
        self._lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        factories = factories or {}
        robot_real = MODES[setup.mode]["robot"] == "real"
        self.robot = (factories.get("real_robot", lambda: Go2WebRTC(aes_128_key=os.getenv("GO2_AES_KEY") or None))() if robot_real
                      else factories.get("simulated_robot", RoboSimulado)())
        self.field = None
        if self.simulated_radiation:
            self.field = CampoRadiacao(fundo_usvh=config.world.background.dose_rate_uSv_h,
                altura_m=abs(config.inference.source_z_m - .57))
            self.field.definir_fonte(setup.x_m, setup.y_m, setup.dose_rate_at_1m_uSv_h)
            def position():
                pose = self.orq.ultima_pose
                return (pose.x, pose.y) if pose is not None else None
            radiation = DetectorSimulado(self.field, position,
                periodo_s=RADIACODE_READING_PERIOD_S, cps_por_usvh=self.sensitivity,
                latencia_leitura_s=self.latency, semente=config.mission.seed)
        else:
            radiation = factories.get("real_radiation", ClienteRadiacode)()
        conf = Config(modo="real" if robot_real else "simulacao", dados=str(Path(data)/setup.mode),
            fonte_radiacao="radiacode", latencia_leitura_s=self.latency,
            offset_detector=Config._parsear_offset(os.getenv("ARES_OFFSET_DETECTOR", "0,0")))
        self.repo = RepositorioMissoes(conf.dados)
        self.teleop = Teleop(self.robot, vx_max=.45, vy_max=.3, vyaw_max=.9, watchdog_s=.5)
        self.orq = LiveOrchestrator(conf, self.robot, radiation, self.repo, campo=self.field, teleop=self.teleop)
        self.orq.console = self

    async def connect(self):
        await self.orq.iniciar()
        self.queue = self.orq.assinar()
        self.pump_task = asyncio.create_task(self._pump())

    async def start(self):
        async with self._lock:
            if self.state == MissionState.RUNNING:
                raise RuntimeError("Encerre a missão atual antes de iniciar outra.")
            reading = self.orq.ultima_leitura
            if not self.simulated_radiation and (reading is None or time.time()-reading.ts > 3):
                raise RuntimeError("Aguardando uma contagem USB recente para iniciar a missão.")
            if not self.simulated_radiation and (
                reading.dr_usvh is None or not math.isfinite(reading.dr_usvh) or reading.dr_usvh < 0
            ):
                raise RuntimeError("Aguardando taxa de dose USB válida para construir o mapa.")
            pose = self.orq.ultima_pose
            if pose is not None:
                bounds = self.scenario.world.bounds_m
                bounds = type(bounds)(x_min=pose.x-10, x_max=pose.x+10,
                    y_min=pose.y-10, y_max=pose.y+10)
                self.scenario.world.bounds_m = bounds
                self.scenario.trajectory.start_m = [pose.x, pose.y, .32]
                if self.simulated_radiation and not (bounds.x_min <= self.setup.x_m <= bounds.x_max and bounds.y_min <= self.setup.y_m <= bounds.y_max):
                    raise RuntimeError("Fonte simulada fora da área de 20 m ao redor do robô. Informe X/Y no referencial odom mostrado no console.")
            if not self.simulated_radiation and self.orq.ultima_leitura is not None:
                # Priors and evidence share the reported dose-rate unit µSv/h.
                reference = max(.001, self.orq.ultima_leitura.dr_usvh)
                self.scenario.inference.background_prior_uSv_h = reference
                self.scenario.inference.background_prior_std_uSv_h = max(.01, reference)
                self.scenario.inference.background_max_uSv_h = max(2, reference*10)
                self.scenario.inference.source_strength_max_uSv_h = max(1000, reference*100)
            info = await self.orq.iniciar_missao("ARES console")
            self.started_wall = time.time()
            self.mission_id = f"live-{self.setup.mode}-{info['id']}"
            self.mission_directory = Path(self.repo.caminho).parent / self.mission_id
            self.mission_directory.mkdir(parents=True, exist_ok=True)
            self.worker = MapWorker(self, self.mission_id)
            self.orq._missao.estimador = self.worker
            self.orq._missao.mapa = None
            self.map_service = self.worker.service
            self.latest_map = None
            self._published = 0
            self.reported_dose_integral = 0
            self.state = MissionState.RUNNING
            self.timer_task = asyncio.create_task(self._duration())
            await self.event_bus.publish("mission_state", self.status())
            return self.mission_id

    async def _duration(self):
        await asyncio.sleep(self.setup.duration_s)
        await self.stop("duration_completed")

    async def _pump(self):
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), .2)
            except asyncio.TimeoutError:
                event = None
            if event and event["tipo"] in ("pose", "leitura"):
                snapshot = self.status()
                key = "pose" if event["tipo"] == "pose" else "radiation"
                if snapshot[key] is not None:
                    await self.event_bus.publish(key, snapshot[key])

    async def publish_mapped(self, count):
        rows = self.worker.samples[self._published:count]
        self._published = count
        for row in rows:
            await self.event_bus.publish("mapped_sample", row)

    def map_presentation(self, prediction):
        if self.simulated_radiation:
            return prediction
        # Dose and map now share the reported-rate channel. Keep the existing
        # mission-dose anchor, without asserting device-total availability.
        exposure = ExposureSummary(cumulative_robot_path_dose_uSv=self.reported_dose_integral,
            cumulative_detector_dose_uSv=self.reported_dose_integral,
            reported_cumulative_dose_uSv=None, audit_state="PROVISIONAL_REPORTED_RATE_INTEGRAL")
        return prediction.model_copy(update={"exposure": exposure})

    @property
    def current_time_ns(self):
        return max(0, int((time.time()-self.started_wall)*1e9)) if self.started_wall else 0

    def status(self):
        p, r = self.orq.ultima_pose, self.orq.ultima_leitura
        radiation = None if r is None else {"dose_rate_uSv_h": r.dr_usvh,
            "cps": r.cps, "cpm": r.cpm, "cumulative_dose_uSv": r.dose_usv,
            "received_utc_ns": int(r.ts*1e9), "integration_time_s": 1}
        if radiation is not None and self.simulated_radiation:
            radiation["dose_rate_uSv_h"] = r.cps / self.sensitivity
        return {"mission_id": self.mission_id, "state": self.state.value,
            "pose": None if p is None else {"x_m": p.x, "y_m": p.y, "yaw_rad": p.yaw, "z_m": .32},
            "radiation": radiation, "counts": {"mapped": len(self.worker.samples) if self.worker else 0},
            "simulation_time_ns": self.current_time_ns, "duration_s": self.setup.duration_s,
            "exposure": self.latest_map.exposure.model_dump(mode="json") if self.latest_map else None}

    def health(self):
        return {"robot": self.robot.estado(), "radiation": self.orq.radiacao.estado()}

    async def samples(self, kind="mapped", offset=0, limit=500):
        if kind != "mapped":
            return []
        return [r.model_dump(mode="json") for r in (self.worker.samples if self.worker else [])[offset:offset+limit]]

    async def stop(self, reason="operator_stop"):
        async with self._stop_lock:
            await self.teleop.parar()
            if self.state != MissionState.RUNNING:
                return
            self.state = MissionState.STOPPING
            if self.timer_task is not asyncio.current_task():
                self.timer_task.cancel()
            await self.orq.encerrar_missao()
            self.state = MissionState.COMPLETED
            await self.export()
            metadata = {"mode": self.setup.mode, "inputs": MODES[self.setup.mode],
                "reason": reason, "timestamp_basis": "host_receipt",
                "position_time_formula": "reading_ts - latencia_leitura_s",
                "latencia_leitura_s": self.latency, "latency_verified_on_robot": False,
                "map_engine": "ares_classic_v4", "map_evidence": "synthetic_counts_calibrated" if self.simulated_radiation else "reported_dose_rate",
                "map_unit": "uSv/h", "map_display_unit": "mSv/h",
                "internal_map_rate_coordinate": "dose_rate_uSv_h",
                "raw_counts_preserved": True,
                "skipped_dose_samples": self.worker.skipped_dose_samples,
                "reported_rate_timing_verified": self.simulated_radiation,
                "dose_conversion_verified": self.simulated_radiation,
                "cumulative_dose_kind": "integral_of_reported_rate_not_detector_total",
                "samples": len(self.worker.samples)}
            (self.mission_directory/"mission.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
            await self.event_bus.publish("mission_state", self.status())

    async def export(self):
        if self.mission_id is None:
            return []
        info = self.repo.exportar_json(int(self.mission_id.rsplit("-", 1)[1]))
        if "poses" not in info:
            with self.repo._lock:
                for table in ("poses", "leituras"):
                    info[table] = [dict(row) for row in self.repo._con.execute(
                        f"SELECT * FROM {table} WHERE missao_id = ? ORDER BY ts", (info["missao"]["id"],))]
        files = []
        map_payload = self.latest_map.model_dump(mode="json") if self.latest_map else {}
        map_payload.update(display_unit="mSv/h", display_factor_from_internal=0.001,
                           dose_conversion_verified=self.simulated_radiation)
        for filename, content in (("amostras.csv", self.repo.exportar_csv(info["missao"]["id"])),
                ("mission_raw.json", json.dumps(info, ensure_ascii=False, indent=2)),
                ("map_latest.json", json.dumps(json_finite(map_payload), ensure_ascii=False, indent=2))):
            path = self.mission_directory/filename
            path.write_text(content, encoding="utf-8")
            files.append(path)
        return files

    async def close(self):
        await self.stop("runtime_closed")
        if self.pump_task:
            self.pump_task.cancel()
            await asyncio.gather(self.pump_task, return_exceptions=True)
            self.orq.cancelar(self.queue)
        await self.orq.encerrar()


class ConsoleRuntime:
    def __init__(self, data, factories=None, manage_usb=True):
        self.data = Path(data)
        self.setup = Setup()
        self.mode = self.setup.mode
        self.event_bus = ConsoleBus()
        self.active = MissionController(scenario(self.data, self.setup))
        self.active.event_bus = self.event_bus
        self.factories = factories
        self.manage_usb = manage_usb
        self.usb = None
        self.usb_log = None
        self.control_enabled = False
        self.operator = None
        self.command_wall = 0
        self.last_message = "Simulação completa selecionada."
        self._lock = asyncio.Lock()
        self._closed = False
        self.watchdog = None

    def __getattr__(self, name):
        return getattr(self.active, name)

    def status(self):
        return json_finite(self.active.status())

    async def open(self):
        self.watchdog = asyncio.create_task(self._watch())

    async def _watch(self):
        while True:
            await asyncio.sleep(.1)
            # Native simulator has no network command watchdog; wrap it here.
            if self.mode == "simulation" and self.command_wall and time.monotonic()-self.command_wall > .5:
                await self.brake()

    async def _usb_start(self):
        if not self.manage_usb or self.usb is not None:
            return
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", 1098))
            except OSError:
                raise RuntimeError("Porta 1098 ocupada. Encerre o leitor USB anterior com o iniciador dele.")
        folder = self.data/"usb"
        folder.mkdir(parents=True, exist_ok=True)
        self.usb_log = (folder/"service.log").open("ab", buffering=0)
        self.usb = await asyncio.create_subprocess_exec(sys.executable, "-u",
            str(ROOT/"tools/radiacode_usb/service.py"), "--output", str(folder),
            stdout=self.usb_log, stderr=asyncio.subprocess.STDOUT)
        await asyncio.sleep(.1)
        if self.usb.returncode is not None:
            await self._usb_stop()
            raise RuntimeError("Serviço USB não iniciou. Veja resultados/console/usb/service.log.")

    async def _usb_stop(self):
        if self.usb is not None:
            if self.usb.returncode is None:
                self.usb.terminate()
                try:
                    await asyncio.wait_for(self.usb.wait(), 15)
                except asyncio.TimeoutError:
                    self.usb.kill()
                    await self.usb.wait()
            self.usb = None
        if self.usb_log is not None:
            self.usb_log.close()
            self.usb_log = None

    async def configure(self, setup):
        if setup.mode not in MODES:
            raise ValueError("Modo de operação desconhecido.")
        async with self._lock:
            if self.state in (MissionState.RUNNING, MissionState.PAUSED, MissionState.STOPPING):
                raise RuntimeError("Encerre e salve a missão antes de trocar as entradas.")
            config = scenario(self.data, setup)  # validate before disconnecting
            await self.brake()
            if isinstance(self.active, LiveController):
                await self.active.close()
            await self._usb_stop()
            if MODES[setup.mode]["radiation"] == "real":
                try:
                    await self._usb_start()
                except RuntimeError:
                    self.mode, self.setup = "simulation", Setup()
                    self.active = MissionController(scenario(self.data, self.setup))
                    self.active.event_bus = self.event_bus
                    raise
            self.mode, self.setup = setup.mode, setup
            self.control_enabled = False
            self.operator = None
            self.command_wall = 0
            if setup.mode == "simulation":
                self.active = MissionController(config)
                self.active.event_bus = self.event_bus
            else:
                self.active = LiveController(config, setup, self.data, self.event_bus, self.factories)
                await self.active.connect()
            self.last_message = f"Entradas selecionadas: {MODES[setup.mode]['name']}."
            await self.event_bus.publish("mission_state", self.status())
            return self.snapshot()

    async def start(self):
        async with self._lock:
            if self.state == MissionState.RUNNING:
                raise RuntimeError("Já existe uma missão em andamento.")
            self.control_enabled = False
            return await self.active.start()

    async def brake(self):
        self.control_enabled = False
        self.command_wall = 0
        if isinstance(self.active, LiveController):
            await self.active.teleop.parar()
        elif self.state in (MissionState.RUNNING, MissionState.PAUSED):
            await self.active.manual_control(0, 0)

    async def stop(self, reason="operator_stop"):
        async with self._lock:
            await self.brake()
            await self.active.stop(reason)

    async def command(self, linear, yaw, client):
        if self.state != MissionState.RUNNING:
            raise RuntimeError("Inicie a missão antes de habilitar o controle.")
        if not self.control_enabled:
            raise RuntimeError("Habilite o controle do robô no console.")
        if self.operator != client:
            raise RuntimeError("O controle pertence a outra sessão do navegador.")
        linear, yaw = float(linear), float(yaw)
        if not all(math.isfinite(x) for x in (linear, yaw)):
            raise ValueError("Velocidade inválida.")
        self.command_wall = time.monotonic() if linear or yaw else 0
        if isinstance(self.active, LiveController):
            self.active.teleop.definir(linear, 0, yaw)
        else:
            limit = self.setup.simulated_robot_speed_m_s
            await self.active.manual_control(max(-limit, min(limit, linear)), max(-.9, min(.9, yaw)))

    def snapshot(self):
        inputs = MODES[self.mode]
        if isinstance(self.active, LiveController):
            health = self.active.health()
            robot, radiation = health["robot"], health["radiation"]
            reading = self.active.orq.ultima_leitura
            reading_age = max(0, time.time()-reading.ts) if reading else None
        else:
            robot = radiation = {"conectado": True, "erro": None}
            reading = self.active.latest_radiation
            reading_age = max(0, (time.time_ns()-reading.received_utc_ns)/1e9) if reading else None
        return {"mode": self.mode, "modes": MODES, "inputs": inputs,
            "robot": robot, "radiation": radiation, "reading_age_s": reading_age,
            "teleop_error": self.active.teleop.ultimo_erro if isinstance(self.active, LiveController) else None,
            "control_enabled": self.control_enabled and self.state == MissionState.RUNNING, "status": self.status(),
            "setup": self.setup.model_dump(), "message": self.last_message,
            "map_version": "classic-v4", "dose_conversion_verified": inputs["radiation"] == "simulated",
            "physical_position": inputs["robot"] == "real", "usb_process_running": self.usb is not None and self.usb.returncode is None}

    async def close(self):
        if self._closed:
            return
        self._closed = True
        await self.stop("server_shutdown")
        if isinstance(self.active, LiveController):
            await self.active.close()
        await self._usb_stop()
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
