"""Controlador de teleoperação: velocidade com heartbeat, watchdog e limites.

O navegador manda a velocidade desejada continuamente (heartbeat ≥ 5 Hz);
`definir` só guarda o valor (já saturado) e marca a hora do último heartbeat
(`time.monotonic()`, imune a ajustes do relógio de parede).

Um laço interno confere o watchdog a `verificacao_hz` (20 Hz por padrão),
independente da taxa de `mover` (`hz`, 5 Hz por padrão). Enquanto a
velocidade for diferente de zero ele publica `mover` a `hz` — como tarefa
de fundo, sem esperar a resposta (um novo `mover` é pulado enquanto o
anterior segue em voo); na transição para zero (por `definir(0, 0, 0)`,
por `parar()` ou pelo watchdog ao vencer `watchdog_s` sem heartbeat) o
`mover` pendente é cancelado (só se abandona a espera da resposta — o
comando já foi mandado ao robô pelo canal de dados) e `parar_movimento` é
chamado na hora. O robô só é dado como parado depois de um StopMove
bem-sucedido: enquanto a parada estiver pendente ela é repetida a cada
ciclo.

Um contador de sequência marca cada `mover` enviado; `parar_movimento`
guarda o valor antes de mandar o StopMove e só marca o robô como parado se
o contador não mudou nesse meio-tempo. Assim, um `mover` que a corrida deixe
entrar entre o início e o fim de um StopMove lento nunca é o último comando
que o robô recebe: a próxima volta do laço, vendo velocidade zero e o robô
ainda "em movimento", manda outro StopMove.

Cada chamada ao robô tem tempo limite (`tempo_limite_s`), então o laço nunca
fica preso num enlace caído. Erros do robô ficam em `ultimo_erro` (limpo no
próximo sucesso), vão para o log com vazão limitada e não derrubam o laço —
segurança física: sem heartbeat fresco o robô para, sempre. Se o laço em si
terminar por uma exceção não tratada (fora de `encerrar()`), isso também vai
para `ultimo_erro` e para o log — a saída silenciosa do laço nunca passa
despercebida.

Latência de parada no pior caso, a partir do último heartbeat:
`watchdog_s + 1/verificacao_hz` — um `mover` em voo não atrasa mais essa
latência, pois o laço não espera a resposta dele: ao vencer o watchdog ele
cancela essa espera e manda o StopMove na hora (a confirmação do StopMove
em si pode levar até `tempo_limite_s` a mais, mas o comando já foi enviado).
"""
import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

INTERVALO_LOG_ERRO_S = 5.0


def _limitar(valor: float, maximo: float) -> float:
    return max(-maximo, min(maximo, valor))


class Teleop:
    """Controla um `Robo` (real ou simulado) com watchdog de velocidade."""

    def __init__(
        self,
        robo,
        vx_max: float,
        vy_max: float,
        vyaw_max: float,
        watchdog_s: float = 0.5,
        hz: float = 5.0,
        tempo_limite_s: float = 1.0,
        verificacao_hz: float = 20.0,
    ) -> None:
        self.robo = robo
        self._vx_max = vx_max
        self._vy_max = vy_max
        self._vyaw_max = vyaw_max
        self._watchdog_s = watchdog_s
        self._periodo_mover = 1.0 / hz
        self._tempo_limite_s = tempo_limite_s
        self._periodo_verificacao = 1.0 / max(verificacao_hz, hz)

        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0
        self._ultimo_heartbeat: Optional[float] = None  # time.monotonic()
        self._proximo_mover = 0.0
        # True desde o primeiro Move até um StopMove bem-sucedido
        self._movendo = False
        # incrementado a cada `mover` enviado; usado por `_tentar_parar` para
        # saber se um Move concorrente invalidou uma parada em andamento
        self._seq_mover = 0
        self._tarefa_mover: Optional[asyncio.Task] = None

        self.ultimo_erro: Optional[str] = None
        self._ultimo_log_erro: Optional[float] = None
        self._tarefa: Optional[asyncio.Task] = None

    def definir(self, vx: float, vy: float, vyaw: float) -> None:
        """Define a velocidade desejada (já saturada) e marca o heartbeat."""
        self._vx = _limitar(vx, self._vx_max)
        self._vy = _limitar(vy, self._vy_max)
        self._vyaw = _limitar(vyaw, self._vyaw_max)
        self._ultimo_heartbeat = time.monotonic()

    async def parar(self) -> None:
        """PARAR imediato: zera a velocidade e manda `parar_movimento` na hora.

        Cancela um `mover` pendente (só a espera da resposta; o comando já
        foi mandado ao robô) e não espera por ele. Se o StopMove falhar, a
        parada fica pendente e o laço a repete.
        """
        self._zerar()
        self._cancelar_tarefa_mover()
        await self._tentar_parar()

    async def iniciar(self) -> None:
        """Sobe o laço de teleop (chamar de novo enquanto roda não faz nada)."""
        if self._tarefa is not None and not self._tarefa.done():
            return
        self._tarefa = asyncio.create_task(self._laco())
        self._tarefa.add_done_callback(self._ao_laco_terminar)

    async def encerrar(self) -> None:
        """Cancela o laço e manda StopMove (com tempo limite)."""
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except asyncio.CancelledError:
                pass
            self._tarefa = None
        await self.parar()

    # ------------------------------------------------------------------ laço
    def _zerar(self) -> None:
        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0

    def _heartbeat_expirado(self, agora: float) -> bool:
        return (
            self._ultimo_heartbeat is None
            or (agora - self._ultimo_heartbeat) >= self._watchdog_s
        )

    async def _laco(self) -> None:
        while True:
            await asyncio.sleep(self._periodo_verificacao)
            agora = time.monotonic()
            if self._heartbeat_expirado(agora):
                self._zerar()

            if self._vx or self._vy or self._vyaw:
                if agora >= self._proximo_mover:
                    self._proximo_mover = agora + self._periodo_mover
                    # pula um novo Move enquanto o anterior ainda está em voo
                    if self._tarefa_mover is None or self._tarefa_mover.done():
                        self._tarefa_mover = asyncio.create_task(self._mover())
            elif self._movendo:
                # não espera a resposta do Move em voo: só abandona a espera,
                # o comando já foi mandado ao robô pelo canal de dados
                self._cancelar_tarefa_mover()
                await self._tentar_parar()

    def _cancelar_tarefa_mover(self) -> None:
        if self._tarefa_mover is not None and not self._tarefa_mover.done():
            self._tarefa_mover.cancel()
        self._tarefa_mover = None

    async def _mover(self) -> None:
        # marcado antes do envio: um Move sem resposta pode ter chegado ao robô
        self._seq_mover += 1
        self._movendo = True
        try:
            await asyncio.wait_for(
                self.robo.mover(self._vx, self._vy, self._vyaw), timeout=self._tempo_limite_s
            )
        except Exception as e:
            self._registrar_erro("erro ao mover o robô", e)
        else:
            self.ultimo_erro = None

    async def _tentar_parar(self) -> bool:
        # guarda a sequência antes do StopMove: se um Move concorrente entrar
        # enquanto o StopMove estiver em voo, o robô não pode ser dado como
        # parado só porque este StopMove teve sucesso
        seq_no_pedido = self._seq_mover
        try:
            await asyncio.wait_for(self.robo.parar_movimento(), timeout=self._tempo_limite_s)
        except Exception as e:
            self._movendo = True  # parada pendente: o laço tenta de novo
            self._registrar_erro("erro ao parar o robô", e)
            return False
        if seq_no_pedido == self._seq_mover:
            self._movendo = False
        self.ultimo_erro = None
        self._ultimo_log_erro = None
        return True

    def _ao_laco_terminar(self, tarefa: asyncio.Task) -> None:
        """Se o laço terminar sozinho (fora de `encerrar()`), registra o erro."""
        if tarefa.cancelled():
            return
        excecao = tarefa.exception()
        if excecao is None:
            return
        detalhe = str(excecao) or type(excecao).__name__
        self.ultimo_erro = detalhe
        log.error("laço de teleop encerrou sozinho, fora de encerrar(): %s", detalhe)

    def _registrar_erro(self, contexto: str, e: Exception) -> None:
        detalhe = str(e)
        if not detalhe:
            if isinstance(e, asyncio.TimeoutError):
                detalhe = f"sem resposta do robô em {self._tempo_limite_s:.1f} s"
            else:
                detalhe = type(e).__name__
        self.ultimo_erro = detalhe
        agora = time.monotonic()
        if self._ultimo_log_erro is None or agora - self._ultimo_log_erro >= INTERVALO_LOG_ERRO_S:
            self._ultimo_log_erro = agora
            log.warning("%s: %s", contexto, detalhe)
