"""
Compatibilidade: stubs de áudio/vídeo (apenas quando faltam).

O driver `unitree_webrtc_connect` importa `sounddevice`, `pyaudio`, `cv2` e
`pydub` no topo dos seus módulos (features de áudio/vídeo). Para APENAS ler
estado e mandar comandos de movimento nós NÃO precisamos delas.

Este módulo injeta módulos falsos em `sys.modules` ANTES de o driver ser
importado — **mas só para as libs que não estiverem instaladas**. Se elas
estiverem instaladas de verdade, os módulos reais são usados.

Importe este módulo ANTES de importar `unitree_webrtc_connect`.
"""
import sys
import types
import importlib.util


class _Stub(types.ModuleType):
    def __getattr__(self, nome):
        return types.SimpleNamespace()


def _instalado(nome: str) -> bool:
    try:
        return importlib.util.find_spec(nome) is not None
    except Exception:
        return False


for _m in ("sounddevice", "pyaudio", "cv2", "pydub"):
    if _m in sys.modules:
        continue            # já importado
    if _instalado(_m):
        continue            # lib real presente -> usa o real
    sys.modules[_m] = _Stub(_m)   # ausente -> stub (só estado/movimento)
