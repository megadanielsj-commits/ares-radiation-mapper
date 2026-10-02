# Testes da referência Go2/WebRTC adaptada

Os 15 arquivos Python e o arquivo JavaScript foram copiados sem alteração de
`4048f7c8b4ffe2cc0f604a8bae1b89d4763aa4f2`, referência da integração Radiacode
sobre o trabalho original `ares-wifi` do Werik (`84f9148`).

São 209 casos Python e 6 JavaScript. Execute em separado da suíte principal,
com `PYTHONPATH=vendor/go2_runtime/src`; instruções e dependências estão em
[ROTEIRO_ENSAIO_GO2.md](../../../ROTEIRO_ENSAIO_GO2.md).

`approved_dashboard.test.cjs` verifica o painel da referência histórica.
O console atual tem testes próprios em `tools/operator_console`; estes são
os contratos para a interface atual e o mapa por taxa reportada.
