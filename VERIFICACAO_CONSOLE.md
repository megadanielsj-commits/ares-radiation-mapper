# Verificação do ARES Console 1.0.2 — 02/10/2026

Esta revisão altera somente a apresentação da dose e da taxa. A aquisição USB
funcional da 1.0.1 e os números do mapa/arquivos permanecem iguais.

## Unidades automáticas

Dose e taxa selecionam Sv, mSv, µSv, nSv, pSv, fSv ou aSv conforme a magnitude.
As taxas conservam o sufixo /h. Não há notação científica nos rótulos.
Normalmente há duas casas; além do menor prefixo, casas decimais adicionais
evitam transformar um valor pequeno em zero. Valores ausentes continuam como —.

| Valor interno | Rótulo |
|---|---|
| 0,12651909855776466 µSv/h | 126,52 nSv/h |
| 1 µSv/h | 1,00 µSv/h |
| 1.000 µSv/h | 1,00 mSv/h |
| 1.000.000 µSv/h | 1,00 Sv/h |
| 0,000035144194043823516 µSv acumulados | 35,14 pSv |

As alterações ficam nos helpers de formatação do console. Não modificam CPS/CPM,
dose original, CSV, JSONL, WebSocket, SQLite, sincronização ou cálculos. A fonte
simulada continua sendo configurada em mSv/h, com sua unidade explícita no campo.
Os metadados exportados de referência continuam como na 1.0.1; os prefixos são
selecionados apenas na interface a partir dos valores numéricos em µSv/h.

## Verificações desta revisão

- **13 testes JavaScript passaram**, cobrindo prefixos, ausência de dose, precisão
  armazenada, dose pequena positiva, paleta e regressões do mapa.
- **56 hashes protegidos passaram**, incluindo a correção do robô parado.
- **123 arquivos do backend e do mapa** foram comparados byte a byte com
  `67914958f2f7e0f33b625955dad9556881e31dce` (1.0.1), sem diferenças.
  Incluem leitor, serviço, runtime, servidor, núcleo do Werik e CSS.
- Chrome: simulação completa em cinco larguras; os outros três modos passaram
  com substitutos de hardware. Nos modos USB por contrato, o WebSocket real do
  software entregou a taxa completa, CPS 13/CPM 780 e rótulos `126,52 nSv/h`.
  A dose integrada apareceu em pSv e permaneceu positiva. Nenhum erro JavaScript.
- O HTML muda somente a versão do cache de CSS/JS. O iniciador usa a imagem
  `ares-operator-console:1.0.2`, para aplicar os novos rótulos.
- Sintaxe Bash/JavaScript, configuração YAML e `git diff --check` passaram.

O resultado da mudança de rótulos está em `validation/console_1.0.2.json`.
Na preparação posterior para a reunião, as suítes foram repetidas: **144 testes
Python do pacote e 209 do runtime passaram**, além de 13 JavaScript do console/USB
e 6 da referência. As fontes dos 209 testes foram incluídas em
`vendor/go2_runtime/tests` e o CI passa a executá-las em Python 3.12.
Nenhum arquivo executável do produto foi alterado nesta preparação.
Veja `validation/preparacao_ensaio_1.0.2.json`, os XML correspondentes e
[ROTEIRO_ENSAIO_GO2.md](ROTEIRO_ENSAIO_GO2.md) para a comparação com o Werik.

```bash
node --test tools/operator_console/console.test.cjs tests/radiacode/dashboard_usb.test.cjs
python -m tools.operator_console.check_map_lock
bash -n ares-console PUBLICAR_CONSOLE_GITHUB.sh
```

O operador confirmou funcionamento da 1.0.1. Não há detector/Go2 nem Docker Engine
neste ambiente: os modos mistos aqui usam registros compatíveis com o SDK e
contratos virtuais, não hardware físico. A imagem nova deve ser construída pelo
iniciador no computador de operação. Esta execução não publicou no GitHub.
O build/CI e o ensaio conjunto continuam previstos em [PUBLICACAO_E_TESTE.md](PUBLICACAO_E_TESTE.md).
