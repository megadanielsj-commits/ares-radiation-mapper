"""Diagnostico: o Go2 esta publicando DDS que este host recebe?

Read-only. Nao comanda o robo. Assina rt/lowstate (sempre publicado pelo Go2
EDU) e rt/sportmodestate (pose usada pelo ARES) e conta mensagens.

Uso (dentro da imagem hardware; ver ./diagnose-go2-dds):
    python go2_dds_probe.py <iface> <domain> <segundos>
"""
import sys
import time

iface = sys.argv[1] if len(sys.argv) > 1 else "enp7s0"
domain = int(sys.argv[2]) if len(sys.argv) > 2 else 0
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_

print(f"init iface={iface} domain={domain}", flush=True)
ChannelFactoryInitialize(domain, iface)

counts = {"low": 0, "sport": 0}
first_pos = {"sport": None}

s_low = ChannelSubscriber("rt/lowstate", LowState_)
s_low.Init(lambda m: counts.__setitem__("low", counts["low"] + 1), 10)

def _sport_cb(m: object) -> None:
    counts["sport"] += 1
    if first_pos["sport"] is None:
        first_pos["sport"] = tuple(float(v) for v in m.position)

s_sport = ChannelSubscriber("rt/sportmodestate", SportModeState_)
s_sport.Init(_sport_cb, 10)

print(f"ouvindo {secs:.0f}s ...", flush=True)
t0 = time.time()
while time.time() - t0 < secs:
    time.sleep(1.0)
    print(f"  rt/lowstate={counts['low']}  rt/sportmodestate={counts['sport']}", flush=True)

print(f"\nRESULT lowstate={counts['low']} sportmodestate={counts['sport']}", flush=True)
if counts["low"] == 0 and counts["sport"] == 0:
    print("VERDICT: SEM DDS. Robo nao expoe DDS (modo dev/app/servico). ARES nao recebe pose.", flush=True)
elif counts["sport"] == 0:
    print("VERDICT: DDS vivo, mas SEM sportmodestate. Servico de sport/estado do robo.", flush=True)
else:
    print(f"VERDICT: OK. Pose fluindo. first_pos={first_pos['sport']}. ARES vai funcionar.", flush=True)
