"""Testes do cliente do serviço FS-5000 (WS local), sem tocar hardware nem rede externa."""
import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from ares.radiacao.fs5000 import ClienteFS5000

BACKOFF_MIN = 0.02
BACKOFF_MAX = 0.05


def _aparelho(id_, estado="conectado", porta="mock://1"):
    return {
        "id": id_, "porta": porta, "estado": estado, "versao": None,
        "ultima": None, "erros_frame": 0, "erro": None,
    }


def _leitura_evento(aparelho_id, ts, dr_usvh=0.2, cpm=120, cps=2, dose_usv=0.001):
    return {
        "tipo": "leitura", "aparelho_id": aparelho_id, "ts": ts,
        "dados": {
            "ts": ts, "dr_usvh": dr_usvh, "dose_usv": dose_usv, "cps": cps,
            "cpm": cpm, "avg_usvh": dr_usvh, "dt": 1.0, "s_usv": dose_usv,
            "alarme": False,
        },
    }


def _estado_evento(aparelho_id, estado):
    ap = _aparelho(aparelho_id, estado=estado)
    return {"tipo": "estado", "aparelho_id": aparelho_id, "ts": 0.0, "dados": ap}


class ServidorFalso:
    """Servidor WS local fake: manda snapshot na conexão, depois o que o teste mandar."""

    def __init__(self, snapshot_aparelhos):
        self.snapshot_aparelhos = snapshot_aparelhos
        self.conexoes = []
        self.filas = []
        self._server = None

    async def _handler(self, ws):
        self.conexoes.append(ws)
        fila: asyncio.Queue = asyncio.Queue()
        self.filas.append(fila)
        await ws.send(json.dumps({"tipo": "snapshot", "dados": self.snapshot_aparelhos}))
        try:
            while True:
                msg = await fila.get()
                if msg is None:
                    await ws.close()
                    return
                await ws.send(json.dumps(msg))
        except Exception:
            pass

    async def iniciar(self):
        self._server = await serve(self._handler, "127.0.0.1", 0)
        porta = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{porta}/ws"

    def enviar(self, evento, indice=-1):
        self.filas[indice].put_nowait(evento)

    async def encerrar(self):
        # destrava os handlers presos em `fila.get()` antes de fechar o servidor,
        # senão `wait_closed()` trava esperando os handlers terminarem.
        for fila in self.filas:
            fila.put_nowait(None)
        self._server.close()
        await self._server.wait_closed()


def test_snapshot_e_leituras_chegam_no_callback():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4")])
        url = await srv.iniciar()
        recebidas = []
        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            srv.enviar(_leitura_evento("1-4", ts=100.0, cps=3))
            for _ in range(50):
                if recebidas:
                    break
                await asyncio.sleep(0.02)
            estado = cliente.estado()
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return recebidas, estado

    recebidas, estado = asyncio.run(cenario())
    assert len(recebidas) == 1
    leitura = recebidas[0]
    assert leitura.ts == 100.0
    assert leitura.cps == 3
    assert leitura.detector_id == "1-4"
    assert estado["conectado"] is True
    assert estado["detector_id"] == "1-4"
    assert estado["erro"] is None


def test_aparelho_configurado_filtra_outros_aparelhos():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4"), _aparelho("2-9")])
        url = await srv.iniciar()
        recebidas = []
        cliente = ClienteFS5000(
            url=url, aparelho="2-9", backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX
        )
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            srv.enviar(_leitura_evento("1-4", ts=1.0))
            srv.enviar(_leitura_evento("2-9", ts=2.0))
            for _ in range(50):
                if recebidas:
                    break
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return cliente, recebidas

    cliente, recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].detector_id == "2-9"
    assert recebidas[0].ts == 2.0
    assert cliente.estado()["detector_id"] == "2-9"


def test_reconecta_apos_queda_do_servidor():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4")])
        url = await srv.iniciar()
        recebidas = []
        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            assert cliente.estado()["conectado"] is True

            # derruba a conexão atual
            await srv.conexoes[0].close()
            for _ in range(50):
                if not cliente.estado()["conectado"]:
                    break
                await asyncio.sleep(0.02)
            assert cliente.estado()["conectado"] is False

            # cliente deve reconectar sozinho (backoff pequeno nos testes)
            for _ in range(100):
                if cliente.estado()["conectado"]:
                    break
                await asyncio.sleep(0.02)
            assert cliente.estado()["conectado"] is True

            srv.enviar(_leitura_evento("1-4", ts=5.0), indice=-1)
            for _ in range(50):
                if recebidas:
                    break
                await asyncio.sleep(0.02)
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return recebidas

    recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].ts == 5.0


def test_estado_reflete_aparelho_desconectado():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4", estado="conectado")])
        url = await srv.iniciar()
        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            assert cliente.estado()["conectado"] is True

            srv.enviar(_estado_evento("1-4", "desconectado"))
            for _ in range(50):
                if not cliente.estado()["conectado"]:
                    break
                await asyncio.sleep(0.02)
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return cliente

    cliente = asyncio.run(cenario())
    estado = cliente.estado()
    assert estado["conectado"] is False
    assert estado["detector_id"] == "1-4"


def test_troca_de_aparelho_automatico_ao_desconectar():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4"), _aparelho("2-9", estado="conectando")])
        url = await srv.iniciar()
        recebidas = []
        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            assert cliente.estado()["detector_id"] == "1-4"

            srv.enviar(_estado_evento("1-4", "desconectado"))
            srv.enviar(_estado_evento("2-9", "conectado"))
            for _ in range(50):
                if cliente.estado()["detector_id"] == "2-9":
                    break
                await asyncio.sleep(0.02)
            estado = cliente.estado()
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return estado

    estado = asyncio.run(cenario())
    assert estado["detector_id"] == "2-9"
    assert estado["conectado"] is True


def test_eventos_malformados_sao_ignorados_e_contados():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4")])
        url = await srv.iniciar()
        recebidas = []
        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            srv.enviar({"tipo": "leitura", "aparelho_id": "1-4", "dados": {"cps": 1}})
            srv.enviar(_leitura_evento("1-4", ts=9.0))
            for _ in range(50):
                if recebidas:
                    break
                await asyncio.sleep(0.02)
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return cliente, recebidas

    cliente, recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].ts == 9.0
    assert cliente.eventos_invalidos >= 1


def test_callback_com_excecao_nao_derruba_o_laco():
    async def cenario():
        srv = ServidorFalso([_aparelho("1-4")])
        url = await srv.iniciar()
        recebidas = []

        def quebra(_leitura):
            raise RuntimeError("callback ruim")

        cliente = ClienteFS5000(url=url, backoff_min=BACKOFF_MIN, backoff_max=BACKOFF_MAX)
        cliente.assinar(quebra)
        cliente.assinar(recebidas.append)
        await cliente.iniciar()
        try:
            for _ in range(50):
                if srv.filas:
                    break
                await asyncio.sleep(0.02)
            srv.enviar(_leitura_evento("1-4", ts=42.0))
            for _ in range(50):
                if recebidas:
                    break
                await asyncio.sleep(0.02)
        finally:
            await cliente.encerrar()
            await srv.encerrar()
        return recebidas

    recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].ts == 42.0
