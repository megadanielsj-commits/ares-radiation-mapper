# ARES Console 1.0.2 — Go2 e Radiacode 110

Console de levantamento radiométrico com aquisição USB independente e integração
Go2/WebRTC baseada no trabalho do Werik. Esta branch é a versão operacional.
Os iniciadores e guias das versões anteriores foram retirados da árvore atual;
o histórico permanece no Git. O mapa, o gradiente, a paleta e a interface aprovada
permanecem iguais à versão 1.0.2 publicada em `8c9a428`.

## Executar

Linux, Docker Engine com Compose e navegador. Na raiz desta pasta:

```bash
bash ares-console iniciar
```

Abra **http://127.0.0.1:8001**. O console inicia em simulação completa.
Escolha as entradas no menu do cabeçalho, espere os componentes ficarem online
e clique em **Iniciar mapeamento**.

| Modo | Robô | Radiação |
|---|---|---|
| Simulação completa | Virtual | Sintética |
| Robô simulado | Virtual | Radiacode real por USB |
| Detector simulado | Go2 real pelo Wi-Fi | Sintética |
| Equipamentos reais | Go2 real pelo Wi-Fi | Radiacode real por USB |

Encerre e salve a missão antes de mudar o modo. A duração encerra a missão;
fechar o navegador não encerra a aquisição independente. Para diagnóstico e parada:

```bash
bash ares-console verificar
bash ares-console parar
```

Construa a imagem com internet **antes** de conectar ao Wi-Fi LocalAP do Go2.
A imagem oficial usa Python 3.12. Seu nome permanece `ares-operator-console:1.0.2`:
a consolidação modifica documentação, testes, CI e iniciadores antigos, sem mudar
o programa executado por essa imagem. A primeira execução constrói a imagem
se ela não estiver no computador.

## Dados e mapa

A taxa reportada pelo Radiacode alimenta o mapa. CPS/CPM permanecem separados;
não há calibração CPS→dose no caminho real. Ausência de taxa permanece ausente,
sem criar um zero ou uma taxa a partir das contagens. O leitor grava os registros
antes da publicação WebSocket. JSONL, CSV, SQLite e cálculos mantêm a precisão.
Apenas a interface escolhe os prefixos SI para dose e taxa, com `/h` nas taxas.
A dose da missão é a integral das taxas aceitas, não o total histórico do aparelho.

Os dados ficam em `resultados/console/`, com missões por modo e sessões USB
independentes. **Baixar dados da missão** entrega o ZIP após o encerramento.
Guarde também a pasta completa, incluindo `session.json` e logs USB.

## Documentação de operação

- [LEIA_PRIMEIRO_CONSOLE.md](LEIA_PRIMEIRO_CONSOLE.md): controles, modos e arquivos.
- [ROTEIRO_ENSAIO_GO2.md](ROTEIRO_ENSAIO_GO2.md): reunião e sequência do ensaio.
- [LEIA_PRIMEIRO_USB.md](LEIA_PRIMEIRO_USB.md): diagnóstico e leitor independente.
- [CONTRATO_USB_WEBSOCKET.md](docs/CONTRATO_USB_WEBSOCKET.md): eventos e timestamps.
- [PUBLICACAO_E_TESTE.md](PUBLICACAO_E_TESTE.md): publicação e preparação offline.
- [CHECKUP_20261004.md](CHECKUP_20261004.md): auditoria do GitHub e consolidação.

## Framework de integração

`vendor/go2_runtime` mantém o driver Go2, o sincronizador, a teleoperação/watchdog
e o contrato de radiação da referência `ares-wifi`, revisão `84f9148`.
A adaptação Radiacode acrescenta dose opcional e metadados/exportações, e a
camada do console publica o mapa aprovado. Não é uma reimplementação do controle
ou do sincronizador do Werik. Veja [PROVENANCE.md](vendor/go2_runtime/PROVENANCE.md).

O FS-5000 não é uma entrada selecionável neste console. Seu teste com o Go2 deve
usar a [branch original ares-wifi](https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/ares-wifi),
que permanece preservada. Encerre aquele controlador antes de usar o mesmo Go2
neste console. Latência, offset da montagem, firmware e resposta temporal da taxa
precisam ser conferidos no ensaio físico.

| Pasta | Papel |
|---|---|
| `tools/operator_console/` | Console oficial, seleção de entradas e Docker |
| `tools/radiacode_usb/` | Leitor USB e serviço WebSocket independente |
| `vendor/go2_runtime/` | Runtime de integração e seus testes |
| `src/ares_mapper/` | Motor do mapa, simulação, registros e componentes de base |
| `tests/` | Testes e auxiliares de compatibilidade; não são iniciadores de operação |
| `config/` | Cenários/configuração do motor |
| `validation/` | Relatórios das verificações |

Os módulos de base e cenários de desenvolvimento permanecem porque fazem parte
do motor e da cobertura de testes. Eles não definem outro console operacional.

## Desenvolvimento e CI

Use Python 3.12 para o console e a integração Go2. A suíte do pacote de base
continua testada em Python 3.10 e 3.12; console/runtime/Docker usam 3.12.

```bash
python -m pip install -e '.[dev,fs5000,radiacode-usb]'
python -m pip install -r vendor/go2_runtime/requirements-go2-wifi.txt
python -m pip install --no-deps unitree_webrtc_connect==2.2.0
PYTHONPATH=src python -m pytest -q tests tools/operator_console/test_console.py tools/operator_console/test_stationary_map.py
PYTHONPATH=vendor/go2_runtime/src python -m pytest -q vendor/go2_runtime/tests
node --test tools/operator_console/console.test.cjs tests/radiacode/dashboard_usb.test.cjs vendor/go2_runtime/tests/approved_dashboard.test.cjs
python -m tools.operator_console.check_map_lock
ruff check src tests
mypy src
```

Execute as duas suítes Python separadamente para não misturar módulos homônimos.
O CI verifica a imagem do console e o serviço USB independente. Testes com
substitutos de hardware não confirmam a montagem e o desempenho do Go2 físico.
