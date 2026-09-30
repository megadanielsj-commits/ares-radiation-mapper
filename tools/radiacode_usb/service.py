#!/usr/bin/env python3
"""Read-only local WS bridge. USB stays in a separate recorder process."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import math
from pathlib import Path
import sys
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


class Bridge:
    def __init__(self, output, *, serial=None, freshness_s=3.0, poll=.25,
                 spectrum_interval=15.0, backoff_min=1.0, backoff_max=10.0):
        self.output = Path(output).resolve()
        self.serial = serial
        self.freshness_s = freshness_s
        self.poll = poll
        self.spectrum_interval = spectrum_interval
        self.backoff_min, self.backoff_max = backoff_min, backoff_max
        self.device = {"id": "radiacode-usb", "modelo": "Radiacode 110",
                       "estado": "desconectado", "erro": "Aguardando contagens USB",
                       "dose_conversion_verified": False}
        self.latest = None
        self.queues = set()
        self.published = self.discarded = self.dropped_for_slow_clients = 0
        self.last_received_ns = None
        self.session = None
        self.last_sequence = 0
        self.child = None
        self.tasks = []
        self.offset = 0
        self.identity = None

    def subscribe(self):
        queue = asyncio.Queue(maxsize=4)
        self.queues.add(queue)
        return queue

    def publish(self, event):
        for queue in tuple(self.queues):
            if queue.full():
                queue.get_nowait()
                self.dropped_for_slow_clients += 1
            queue.put_nowait(event)

    def state(self, connected, error=None):
        value = "conectado" if connected else "desconectado"
        if (self.device["estado"], self.device["erro"]) != (value, error):
            self.device.update(estado=value, erro=error)
            self.publish({"tipo": "estado", "dados": dict(self.device)})
        if not connected:
            self.latest = None

    def accept(self, row):
        """Publish only fresh, consecutive-bin counts; never replay an old backlog."""
        try:
            if row["schema_version"] != "ares-radiacode-counts-1" or row.get("timing_quality") != "live_receipt":
                raise ValueError("tempo de recebimento ambíguo")
            age = (time.monotonic_ns() - int(row["received_monotonic_ns"])) / 1e9
            wall_age = time.time() - int(row["received_utc_ns"]) / 1e9
            if not 0 <= age <= self.freshness_s or not -.1 <= wall_age <= self.freshness_s:
                raise ValueError("contagem antiga ou relógio do computador alterado")
            cps = row["cps"]
            if isinstance(cps, bool) or not isinstance(cps, int) or cps < 0 or row["exposure_s"] != 1.0:
                raise ValueError("contagem/exposição inválida")
            session = row["session_id"]
            seq = int(row["sequence"])
            if session == self.session and seq <= self.last_sequence:
                raise ValueError("sequência repetida")
            dose = row.get("dose_rate_uSv_h")
            if dose is not None and (not math.isfinite(dose) or dose < 0):
                raise ValueError("dose inválida")
            self.session, self.last_sequence = session, seq
            new_id = f"radiacode:{row['serial_number']}:{session}"
            if self.device["id"] != new_id:
                # Tell the existing CEIA client that the old connection is gone.
                self.state(False, "Nova sessão USB")
                self.device["id"] = new_id
                self.device.update(session_id=session, serial_number=row["serial_number"])
            self.last_received_ns = row["received_monotonic_ns"]
            self.state(True)
            self.latest = {
                "tipo": "leitura", "aparelho_id": new_id, "ts": time.time(),
                "dados": {"ts": row["received_utc_ns"] / 1e9, "dr_usvh": dose,
                          "dose_usv": None, "cps": cps, "cpm": 60*cps,
                          "sequence": seq, "session_id": session, "exposure_s": 1.0,
                          "dose_conversion_verified": False,
                          "time_basis": row["time_basis"],
                          "timing_quality": row["timing_quality"]},
            }
            self.publish(self.latest)
            self.published += 1
            return True
        except (KeyError, TypeError, ValueError, OverflowError):
            self.discarded += 1
            return False

    def check_freshness(self):
        if self.last_received_ns is not None and (time.monotonic_ns()-self.last_received_ns)/1e9 > self.freshness_s:
            self.state(False, "Sem contagem USB recente")

    async def start(self):
        self.output.mkdir(parents=True, exist_ok=True)
        self.tasks = [asyncio.create_task(self.supervise()), asyncio.create_task(self.follow())]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.child is not None and self.child.returncode is None:
            with suppress(ProcessLookupError):
                self.child.terminate()
            try:
                await asyncio.wait_for(self.child.wait(), 8)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    self.child.kill()
                await self.child.wait()
        self.state(False, "Serviço encerrado")

    async def supervise(self):
        backoff = self.backoff_min
        while True:
            session = self.output / (time.strftime("usb-%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8])
            self.identity, self.offset = session, 0
            self.last_received_ns = None
            self.state(False, "Conectando ao USB")
            before = self.published
            cmd = [sys.executable, "-u", str(Path(__file__).with_name("reader.py")),
                   "--output", str(session), "--seconds", "0", "--require-counts",
                   "--poll", str(self.poll), "--spectrum-interval", str(self.spectrum_interval)]
            if self.serial:
                cmd.extend(["--serial", self.serial])
            with (self.output / (session.name + ".log")).open("ab", buffering=0) as log:
                self.child = await asyncio.create_subprocess_exec(*cmd, stdout=log, stderr=asyncio.subprocess.STDOUT)
                code = await self.child.wait()
            self.identity = None
            self.state(False, f"Leitor USB encerrou (código {code}); reconectando")
            print(self.device["erro"], flush=True)
            if self.published > before:
                backoff = self.backoff_min
            await asyncio.sleep(backoff)
            backoff = min(2*backoff, self.backoff_max)

    @staticmethod
    def read_lines(path, offset):
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                lines = []
                for _ in range(128):
                    start = stream.tell()
                    line = stream.readline(65536)
                    if not line.endswith(b"\n"):
                        stream.seek(start)
                        break
                    lines.append(line)
                return stream.tell(), lines
        except FileNotFoundError:
            return offset, []

    async def follow(self):
        while True:
            identity = self.identity
            if identity is not None:
                offset, lines = await asyncio.to_thread(self.read_lines, identity / "counts_1s.jsonl", self.offset)
                if identity == self.identity:
                    self.offset = offset
                    for line in lines:
                        try:
                            self.accept(json.loads(line))
                        except (ValueError, UnicodeDecodeError):
                            self.discarded += 1
            self.check_freshness()
            await asyncio.sleep(.05)


def create_app(bridge, *, manage_reader=True):
    stopping = asyncio.Event()

    @asynccontextmanager
    async def life(_):
        if manage_reader:
            await bridge.start()
        try:
            yield
        finally:
            stopping.set()
            if manage_reader:
                await bridge.stop()

    app = FastAPI(title="ARES Radiacode USB", lifespan=life)

    @app.get("/health")
    async def health():
        bridge.check_freshness()
        return {"service": "radiacode-usb", "detector": bridge.device,
                "published": bridge.published, "discarded": bridge.discarded,
                "dropped_for_slow_clients": bridge.dropped_for_slow_clients,
                "output": str(bridge.output)}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        origin = sock.headers.get("origin")
        if origin is not None and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            await sock.close(code=1008)
            return
        await sock.accept()
        queue = bridge.subscribe()
        disconnected = asyncio.Event()
        async def watch_disconnect():
            try:
                while True:
                    message = await sock.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    # This service is read-only; received application commands are ignored.
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                disconnected.set()
        receiver = asyncio.create_task(watch_disconnect())
        try:
            bridge.check_freshness()
            await sock.send_json({"tipo": "snapshot", "dados": [dict(bridge.device)]})
            # No cached reading: joining a mission never injects historical counts.
            while not stopping.is_set() and not disconnected.is_set():
                try:
                    event = await asyncio.wait_for(queue.get(), 1)
                except asyncio.TimeoutError:
                    continue
                if event.get("tipo") == "leitura":
                    if time.time() - event["dados"]["ts"] > bridge.freshness_s:
                        continue
                    # A dropped status event must not hide a new USB session.
                    await asyncio.wait_for(sock.send_json({"tipo": "snapshot", "dados": [dict(bridge.device)]}), 1)
                await asyncio.wait_for(sock.send_json(event), 1)
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            bridge.queues.discard(queue)
            with suppress(Exception):
                await sock.close()
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="resultados/ceia/usb")
    parser.add_argument("--serial")
    parser.add_argument("--port", type=int, default=1098)
    args = parser.parse_args()
    bridge = Bridge(args.output, serial=args.serial)
    uvicorn.run(create_app(bridge), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
