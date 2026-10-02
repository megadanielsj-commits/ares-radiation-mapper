# Verificação do ARES Console 1.0.0 — 02/10/2026

Versão de referência preparada para o ensaio de 08/10/2026. A interface aprovada
foi preservada; esta revisão muda o título para **Mapa de calor** e alimenta o
mapa real com a taxa de dose reportada, apresentando **mSv/h**. Não há conversão
CPS→dose do FS-5000 aplicada ao Radiacode.

## Referências comparadas

| Componente | Referência | Resultado |
|---|---|---|
| Trabalho original de integração Go2/Wi-Fi | `ares-wifi`, `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f` | A branch remota continua nessa revisão na consulta de 02/10/2026 |
| Driver Go2, sincronizador e teleop | Arquivos originais do runtime acima | Sem diferenças entre a referência original e a adaptação Radiacode |
| Runtime com adaptador Radiacode | `4048f7c8b4ffe2cc0f604a8bae1b89d4763aa4f2` | Os 30 arquivos copiados em `vendor/go2_runtime/src/ares` são idênticos byte a byte |
| Mapa, paleta e integração protegidos | Console aprovado `a84b972f9d27bb3f2bc7dc32a3bb4e9581f25d08` | Os 56 hashes e o próprio `map.lock.json` continuam iguais |
| SDK USB | `cdump/radiacode`, tag `0.4.0`, commit `3e9a2aaec60aa1da06834310c5fb660133e734d3` | Unidades/escala conferidas no código e na documentação primária dessa versão |
| Base para publicação | `main`, `fcf4377be8ccfd86f7d56343c58b0fc342fd3cdc` | Ancestral desta implementação; a publicação usa uma branch de release separada |

O runtime adaptado já continha seleção do detector, metadados Radiacode e
exportação de leituras/poses. Esses acréscimos anteriores não são atribuídos ao
código original do Werik. O console usa sua aquisição, interpolação temporal,
worker ordenado fora do event loop, reconexão e watchdog. A subclasse troca o
worker/publicação do mapa; não cria outro driver de robô ou sincronizador.

## Alterações nesta revisão

- O mapa real recebe `dr_usvh`; CPS/CPM permanecem como canais separados nos
  registros USB e no CSV/SQLite de amostras posicionadas. O modo de observação
  existente do motor passa de contagens para taxa de dose, com prior na mesma
  unidade da evidência. Nenhum arquivo do núcleo de inferência foi alterado.
- Internamente a taxa continua em µSv/h; somente a apresentação usa mSv/h.
  Taxas baixas usam notação científica com duas casas na mantissa. O layout,
  desenho, interpolação, cálculo de cores e correção de permanência da v3
  permanecem protegidos. A seção HTML do mapa só muda o título solicitado.
- O recebimento da taxa tem timestamps próprios no registro de contagens.
  Contagens novas não tornam uma taxa antiga recente. O bridge não publica
  dose rotulada em Sv se a configuração consultada é R ou desconhecida.
  Não altera configurações do detector. Uma dose ausente não vira zero:
  bloqueia o início ou é omitida do mapa, mantendo o registro bruto.
- A dose integrada mantém o anchor do servidor, evitando somar novamente os
  mesmos intervalos ao receber amostras e atualizações do mapa. Não representa
  a dose acumulada total do aparelho e não recupera intervalos perdidos.
- O CI mantém os testes Python 3.10/3.12 e passa a validar também o Compose do
  console antes de construir a imagem. A tipagem global exclui explicitamente
  o módulo terceiro FS-5000 já preservado; os módulos próprios seguem verificados.
  Isso trata os erros de tipagem do fornecedor sem editar seu protocolo.

## Verificações executadas

- **127 testes Python do pacote passaram**, incluindo modos, contratos USB,
  exportação, falta/retorno de dose, taxa antiga, unidade desconhecida, parada,
  controle exclusivo e as regressões de permanência sobre a fonte.
- **209 testes do runtime Go2/Radiacode de referência passaram**, executados
  contra o código vendorizado. Exercitam contratos de sincronização, persistência,
  recepção e controle com substitutos de hardware.
- **10 testes JavaScript do console/mapa e 1 do painel USB passaram**. Conferem
  paleta preservada, redesenho numérico coerente, posicionamento do raster,
  mSv/h, precisão armazenada, contagem total e ausência de dupla integração.
- `ruff check src tests`, `mypy src` (76 módulos), verificação SHA-256 do mapa,
  `git diff --check` e sintaxe Bash dos iniciadores passaram.
- Imports usados no build, configuração YAML do Compose e workflow CI foram
  verificados. SDK Radiacode e driver Unitree permanecem nas versões previstas.
- Chrome 145: simulação completa em cinco resoluções (1920, 1536, 1366, 1024
  e 390 px), menu de modos, fonte recolhível, configuração de duração, teclado,
  ampliação/restauração, parada e exportação. Os outros três modos passaram
  com substitutos dos contratos de hardware. Título e unidade do mapa foram
  conferidos; taxa reportada 0,22 µSv/h apareceu como `2,20E-4 mSv/h`, enquanto
  CPS 100 permaneceu separado. Não houve erros JavaScript na execução concluída.

Comandos para reproduzir as verificações principais em ambiente de desenvolvimento:

```bash
python -m pip install -e '.[dev,fs5000,radiacode-usb]'
PYTHONPATH=src:vendor/go2_runtime/src python -m pytest tests tools/operator_console/test_console.py tools/operator_console/test_stationary_map.py tools/source_simulation/test_demo.py
node --test tools/operator_console/console.test.cjs tests/radiacode/dashboard_usb.test.cjs
python -m tools.operator_console.check_map_lock
ruff check src tests
mypy src
bash -n ares-console PUBLICAR_CONSOLE_GITHUB.sh
```

## Limites e validação em campo

Não há Docker Engine nem Go2/Radiacode físicos neste ambiente. **A imagem Docker
não foi construída aqui**, e o workflow novo ainda precisa executar após a
publicação. O computador de operação constrói `ares-operator-console:1.0.0` pelo
iniciador; isso deve acontecer com internet antes de conectar ao LocalAP.

As confirmações anteriores do operador cobrem simulação completa e USB real com
robô virtual na versão anterior. Como o canal que alimenta o mapa foi alterado,
repita esse teste nesta versão. Os testes automatizados não substituem essa
verificação física, nem validam Go2+Radiacode juntos, firmware/AES, média interna
da taxa, latência, offset ou precisão radiométrica da reconstrução.

A conversão de dose do SDK continua marcada provisória. Confira Sv e a taxa do
visor antes do ensaio. Preserve o padrão temporal do Werik e ajuste os parâmetros
existentes só após medir a resposta da taxa e a montagem. O roteiro completo é
[PUBLICACAO_E_TESTE.md](PUBLICACAO_E_TESTE.md).

Referências primárias do SDK consultadas:
https://github.com/cdump/radiacode/blob/0.4.0/docs/guides/measurements.md
https://github.com/cdump/radiacode/blob/0.4.0/src/radiacode/examples/radiacode-exporter.py
