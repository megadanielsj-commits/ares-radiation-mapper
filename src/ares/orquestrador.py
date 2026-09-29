"""Orquestrador: liga robô, detector, sincronizador, missão, estimador e eventos.

Um event loop só. Pose e leituras chegam por callback (no loop) e alimentam o
`Sincronizador`; as amostras resultantes, com missão ativa, vão para o
repositório, o mapa e uma fila consumida em ordem por uma tarefa que roda o
estimador em thread (`asyncio.to_thread`, nunca bloqueia o loop). Uma tarefa
periódica publica `estimativa` e `mapa` (1 Hz) e outra consulta o estado dos
componentes (2 Hz) e publica `estado` quando a conectividade muda.

Eventos (`{"tipo": ..., "dados": ...}`) vão para filas limitadas por
assinante; fila cheia descarta o evento (assinante lento não trava nada).
"""
import asyncio
import logging
import math
import time
from typing import Optional

from .config import Config
from .estimativa import EstimadorGrade
from .mapa import MapaMedido
from .missao import RepositorioMissoes
from .modelos import Amostra, Leitura, Pose
from .sincronizacao import Sincronizador

log = logging.getLogger(__name__)

FONTE_PADRAO = (4.0, 3.0, 2.0)  # x, y [m], S [µSv/h a 1 m]
TAMANHO_FILA_EVENTOS = 1000


def _pose_dict(p: Optional[Pose]) -> Optional[dict]:
    return None if p is None else {"ts": p.ts, "x": p.x, "y": p.y, "yaw": p.yaw}


def _leitura_dict(l: Optional[Leitura]) -> Optional[dict]:
    if l is None:
        return None
    return {
        "ts": l.ts,
        "dr_usvh": l.dr_usvh,
        "cpm": l.cpm,
        "cps": l.cps,
        "dose_usv": l.dose_usv,
        "detector_id": l.detector_id,
    }


def _amostra_dict(a: Amostra) -> dict:
    return {
        "ts": a.ts,
        "x": a.x,
        "y": a.y,
        "dr_usvh": a.dr_usvh,
        "cpm": a.cpm,
        "cps": a.cps,
        "lacuna_pose_s": a.lacuna_pose_s,
    }


class _Missao:
    def __init__(self, id_: int, nome, centro, estimador, mapa) -> None:
        self.id = id_
        self.nome = nome
        self.centro = centro
        self.iniciada = time.time()
        self.estimador = estimador
        self.mapa = mapa
        self.n_amostras = 0

    def info(self) -> dict:
        return {
            "id": self.id,
            "nome": self.nome,
            "iniciada": self.iniciada,
            "centro": list(self.centro),
            "n_amostras": self.n_amostras,
        }


class Orquestrador:
    def __init__(
        self,
        config: Config,
        robo,
        radiacao,
        repositorio: RepositorioMissoes,
        campo=None,
        teleop=None,
        periodo_publicacao_s: float = 1.0,
        periodo_estado_s: float = 0.5,
        intervalo_pose_s: float = 0.1,
    ) -> None:
        self.config = config
        self.robo = robo
        self.radiacao = radiacao
        self.repositorio = repositorio
        self.campo = campo
        self.teleop = teleop
        self._periodo_publicacao_s = periodo_publicacao_s
        self._periodo_estado_s = periodo_estado_s
        self._intervalo_pose_s = intervalo_pose_s

        self._sinc = Sincronizador(
            offset_detector=tuple(config.offset_detector),
            latencia_s=config.latencia_leitura_s,
            lacuna_max_s=config.lacuna_pose_max_s,
        )
        self._assinantes: set = set()
        self._missao: Optional[_Missao] = None
        self._fila_estimador: Optional[asyncio.Queue] = None
        self._tarefas: list = []

        self.ultima_pose: Optional[Pose] = None
        self.ultima_leitura: Optional[Leitura] = None
        self.ultimo_resultado: Optional[dict] = None
        self.ultimo_mapa: Optional[dict] = None
        self._ultimo_evento_pose = 0.0
        self._chave_estado = None

        robo.assinar_pose(self._ao_receber_pose)
        radiacao.assinar(self._ao_receber_leitura)

    # ------------------------------------------------------------------ eventos
    def assinar(self) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue(maxsize=TAMANHO_FILA_EVENTOS)
        self._assinantes.add(fila)
        return fila

    def cancelar(self, fila: asyncio.Queue) -> None:
        self._assinantes.discard(fila)

    def _emitir(self, tipo: str, dados) -> None:
        evento = {"tipo": tipo, "dados": dados}
        for fila in list(self._assinantes):
            try:
                fila.put_nowait(evento)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ ciclo de vida
    async def iniciar(self) -> None:
        if self._tarefas:
            return
        self._fila_estimador = asyncio.Queue()
        await self.robo.iniciar()
        await self.radiacao.iniciar()
        self._tarefas = [
            asyncio.create_task(self._laco_estimador()),
            asyncio.create_task(self._laco_publicacao()),
            asyncio.create_task(self._laco_estado()),
        ]
        if self.teleop is not None:
            await self.teleop.iniciar()

    async def encerrar(self) -> None:
        """Salva a missão ativa, para teleop, robô e radiação e fecha o repositório."""
        if self._missao is not None:
            try:
                await self.encerrar_missao()
            except Exception:
                log.exception("erro ao salvar a missão no encerramento")
        tarefas, self._tarefas = self._tarefas, []
        for t in tarefas:
            t.cancel()
        for t in tarefas:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self.teleop is not None:
            await self.teleop.encerrar()
        await self.robo.encerrar()
        await self.radiacao.encerrar()
        self.repositorio.fechar()

    # ------------------------------------------------------------------ entradas
    def _ao_receber_pose(self, pose: Pose) -> None:
        self.ultima_pose = pose
        self._sinc.adicionar_pose(pose)
        if self._missao is not None:
            self.repositorio.registrar_pose(self._missao.id, pose)
        agora = time.monotonic()
        if agora - self._ultimo_evento_pose >= self._intervalo_pose_s:
            self._ultimo_evento_pose = agora
            self._emitir("pose", _pose_dict(pose))
        self._processar_amostras()

    def _ao_receber_leitura(self, leitura: Leitura) -> None:
        self.ultima_leitura = leitura
        self._sinc.adicionar_leitura(leitura)
        if self._missao is not None:
            self.repositorio.registrar_leitura(self._missao.id, leitura)
        self._emitir("leitura", _leitura_dict(leitura))
        self._processar_amostras()

    def _processar_amostras(self) -> None:
        for a in self._sinc.drenar():
            m = self._missao
            if m is not None:
                m.n_amostras += 1
                self.repositorio.registrar_amostra(m.id, a)
                m.mapa.adicionar(a)
                if self._fila_estimador is not None:
                    self._fila_estimador.put_nowait((m.estimador, a))
            self._emitir("amostra", _amostra_dict(a))

    # ------------------------------------------------------------------ laços
    async def _laco_estimador(self) -> None:
        fila = self._fila_estimador
        while True:
            estimador, amostra = await fila.get()
            try:
                await asyncio.to_thread(estimador.atualizar, amostra)
            except Exception:
                log.exception("erro ao atualizar o estimador")
            finally:
                fila.task_done()

    async def _laco_publicacao(self) -> None:
        while True:
            await asyncio.sleep(self._periodo_publicacao_s)
            m = self._missao
            if m is None:
                continue
            try:
                await self._publicar_resultado(m)
            except Exception:
                log.exception("erro ao calcular a estimativa")

    async def _publicar_resultado(self, m: _Missao) -> dict:
        resultado = await asyncio.to_thread(m.estimador.resultado)
        mapa = await asyncio.to_thread(m.mapa.grade_interpolada)
        resultado = dict(resultado, missao_id=m.id)
        self.ultimo_resultado = resultado
        self.ultimo_mapa = mapa
        self._emitir("estimativa", resultado)
        self._emitir("mapa", mapa)
        return resultado

    async def _laco_estado(self) -> None:
        while True:
            self._verificar_estado()
            await asyncio.sleep(self._periodo_estado_s)

    def _verificar_estado(self, forcar: bool = False) -> None:
        estado = self.estado()
        chave = (
            estado["robo"].get("conectado"),
            estado["robo"].get("erro"),
            estado["radiacao"].get("conectado"),
            estado["radiacao"].get("erro"),
        )
        if forcar or chave != self._chave_estado:
            self._chave_estado = chave
            self._emitir("estado", estado)

    # ------------------------------------------------------------------ estado
    def estado(self) -> dict:
        return {
            "modo": self.config.modo,
            "robo": self.robo.estado(),
            "radiacao": self.radiacao.estado(),
            "missao": None if self._missao is None else self._missao.info(),
            "fonte_sim": self._fonte_sim(),
        }

    def _fonte_sim(self) -> Optional[dict]:
        if self.campo is None or self.campo.fonte is None:
            return None
        x, y, s = self.campo.fonte
        return {"x": x, "y": y, "s": s}

    def snapshot(self) -> dict:
        return dict(
            self.estado(),
            pose=_pose_dict(self.ultima_pose),
            leitura=_leitura_dict(self.ultima_leitura),
            resultado=self.ultimo_resultado,
            mapa=self.ultimo_mapa,
        )

    # ------------------------------------------------------------------ missão
    async def iniciar_missao(self, nome: Optional[str] = None) -> dict:
        if self._missao is not None:
            raise RuntimeError("já existe uma missão ativa")
        if not self.robo.estado().get("conectado"):
            raise RuntimeError("robô não conectado")
        if not self.radiacao.estado().get("conectado"):
            raise RuntimeError("detector de radiação não conectado")
        pose = self.ultima_pose
        if pose is None:
            raise RuntimeError("pose do robô ainda não recebida")

        c = self.config
        centro = (pose.x, pose.y)
        estimador = EstimadorGrade(
            centro=centro,
            lado_m=c.lado_area_m,
            resolucao_m=c.resolucao_estimador_m,
            altura_m=c.altura_fonte_m,
            cps_por_usvh=c.cps_por_usvh,
            exposicao_s=c.exposicao_s,
        )
        mapa = MapaMedido(
            centro=centro,
            lado_m=c.lado_area_m,
            resolucao_m=c.resolucao_mapa_m,
            cps_por_usvh=c.cps_por_usvh,
            exposicao_s=c.exposicao_s,
        )
        id_ = self.repositorio.criar(nome, c.modo, centro, fonte_sim=self._fonte_sim())
        self._missao = _Missao(id_, nome, centro, estimador, mapa)
        self.ultimo_resultado = None
        self.ultimo_mapa = None
        self._verificar_estado(forcar=True)
        return self._missao.info()

    async def encerrar_missao(self) -> dict:
        m = self._missao
        if m is None:
            raise RuntimeError("nenhuma missão ativa")
        self._missao = None  # novas amostras não entram mais nesta missão
        if self._fila_estimador is not None and self._tarefas:
            await self._fila_estimador.join()
        resultado = await self._publicar_resultado(m)
        self.repositorio.encerrar(m.id, resultado)
        self._verificar_estado(forcar=True)
        return dict(m.info(), resultado=resultado)

    # ------------------------------------------------------------------ simulação
    def definir_fonte_simulada(self, x: float, y: float, s: float) -> dict:
        if self.campo is None:
            raise ValueError("fonte simulada só existe no modo simulação")
        x, y, s = float(x), float(y), float(s)
        if not all(math.isfinite(v) for v in (x, y, s)) or s <= 0:
            raise ValueError("x, y devem ser finitos e s > 0")
        self.campo.definir_fonte(x, y, s)
        self._verificar_estado(forcar=True)
        return self._fonte_sim()


def criar_orquestrador(
    config: Config,
    frequencia_robo_hz: float = 20.0,
    periodo_detector_s: float = 1.0,
    semente: Optional[int] = None,
    **kwargs,
) -> Orquestrador:
    """Monta o conjunto do modo configurado (com `Teleop` em `orquestrador.teleop`)."""
    from .teleop import Teleop

    repositorio = RepositorioMissoes(config.dados)
    campo = None
    if config.modo == "simulacao":
        from .simulacao.campo import CampoRadiacao
        from .simulacao.detector import DetectorSimulado
        from .simulacao.robo import RoboSimulado

        robo = RoboSimulado(
            vx_max=config.vx_max,
            vy_max=config.vy_max,
            vyaw_max=config.vyaw_max,
            frequencia_hz=frequencia_robo_hz,
        )
        campo = CampoRadiacao(altura_m=config.altura_fonte_m)
        campo.definir_fonte(*FONTE_PADRAO)
        dx, dy = config.offset_detector

        def posicao_detector():
            cos_yaw, sin_yaw = math.cos(robo.yaw), math.sin(robo.yaw)
            return (
                robo.x + dx * cos_yaw - dy * sin_yaw,
                robo.y + dx * sin_yaw + dy * cos_yaw,
            )

        radiacao = DetectorSimulado(
            campo,
            posicao_detector,
            periodo_s=periodo_detector_s,
            cps_por_usvh=config.cps_por_usvh,
            semente=semente,
        )
    else:
        from .radiacao.fs5000 import ClienteFS5000
        from .robo.go2 import Go2WebRTC

        robo = Go2WebRTC(aes_128_key=config.go2_aes_key)
        radiacao = ClienteFS5000(url=config.fs5000_url, aparelho=config.fs5000_aparelho)

    teleop = Teleop(
        robo,
        vx_max=config.vx_max,
        vy_max=config.vy_max,
        vyaw_max=config.vyaw_max,
        watchdog_s=config.watchdog_s,
    )
    return Orquestrador(config, robo, radiacao, repositorio, campo=campo, teleop=teleop, **kwargs)
