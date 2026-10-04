# Auxiliares de regressão

Esta pasta preserva contratos e o renderer do motor aprovado para testes.
Não oferece outro iniciador, painel ou modo de operação. O console oficial
continua em `tools/operator_console`, iniciado por `bash ares-console iniciar`.

`classic_app.py` serve o motor exclusivamente dentro dos testes HTTP.
`usb_dashboard_scenario.py` constrói o cenário histórico do adaptador JSONL.
`legacy_service_probe.py` mantém os testes de prontidão anteriores. Seus endpoints
históricos não são instruções para operar o console atual.

`map_renderer.test.cjs` fornece o cenário de desenho usado pelas regressões do
console; preserva paleta, gradiente e posição espacial dos pixels.
