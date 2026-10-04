# Regressões do runtime Go2/WebRTC

São 209 casos Python e 6 JavaScript da adaptação Go2/Radiacode sobre a referência
original `ares-wifi` do Werik (`84f9148`). Suas fontes foram publicadas na versão
`8c9a4280ebcf085ddf7cde3b2809750968bb10d2`, em `vendor/go2_runtime/tests`, e ficam
preservadas nesta consolidação.

Execute em separado da suíte principal, com `PYTHONPATH=vendor/go2_runtime/src`.
Use Python 3.12 com as dependências de `requirements-go2-wifi.txt` e Unitree 2.2.0.
Veja [ROTEIRO_ENSAIO_GO2.md](../../../ROTEIRO_ENSAIO_GO2.md).

`approved_dashboard.test.cjs` verifica o adaptador da referência, preservado como
parte da dependência. A interface atual e o mapa por taxa têm seus testes em
`tools/operator_console`. A presença dos arquivos de referência não oferece outro
iniciador ao operador.
