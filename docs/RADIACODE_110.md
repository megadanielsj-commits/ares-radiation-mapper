# Radiacode 110: aquisição USB independente

O Radiacode 110 já forneceu leituras reais via USB no Linux. O leitor roda em
processo próprio e grava o fluxo radiológico antes de qualquer visualização.
Não usa porta CH341, baud rate nem o processo de odometria do Go2.

## Executar

O procedimento de instalação/diagnóstico detalhado está em
[`LEIA_PRIMEIRO_USB.md`](../LEIA_PRIMEIRO_USB.md). Com o ambiente instalado:

```bash
bash 04_teste_usb.sh                    # aquisição real por 60 segundos
bash 05_robo_simulado_usb.sh            # Radiacode real + pose virtual
```

Para conferir um campo radiológico conhecido, sem detector conectado:

```bash
bash 06_FONTE_SIMULADA.sh              # fonte simulada + pose virtual
```

Na página da simulação configure a fonte e clique em **Iniciar mapeamento**.
Use as setas para deslocar o Go2. Para comparar os modos, encerre um com
`Ctrl+C` antes de iniciar o outro na mesma porta HTTP.

## Fluxo e formatos

| Componente | Entrada | Saída |
|---|---|---|
| `tools/radiacode_usb/reader.py` | USB por `radiacode==0.4.0`/libusb | `readings.csv`, `readings.jsonl`, `raw_records.jsonl`, `spectra.jsonl`, metadados |
| `src/ares_mapper/adapters/radiacode_jsonl.py` | Novas linhas do JSONL | Amostras da missão para o painel e o mapa |
| `tools/radiacode_usb/launch.py` | Leitor e configuração de pose virtual | Dois processos; sessão em `resultados/` |
| `06_FONTE_SIMULADA.sh` | Campo e detector simulados | Missão em `data/missions/` |

O arquivo `readings.jsonl` é a saída autoritativa da aquisição USB: a interface
não bloqueia a leitura nem altera os registros gravados. Recebimento UTC e
monotônico ficam em cada linha; espectros são snapshots acumulados. O cálculo
`CPM = 60 × CPS` é derivado. A conversão da taxa para µSv/h ainda está marcada
como provisória nos arquivos (`dose_conversion_verified=false`); a dose
acumulada do instrumento permanece em unidade bruta até comparação documentada
com o visor. Nada disso depende da posição virtual.

O painel USB só usa coordenadas fictícias. Ele serve para verificar fluxo,
latência aparente e desenho da interface; o gradiente espacial desse teste não
representa a distribuição real. A integração com pose real exige um contrato
de tempo e incerteza validado em outra etapa, mantendo a aquisição isolada.

## Organização no GitHub

- A dependência `radiacode==0.4.0` está declarada no extra `radiacode-usb`.
- `.gitignore` exclui o ambiente Python, `resultados/` e dados pessoais da sessão.
- O CI instala o extra e executa testes Python e um teste JavaScript para o
  painel USB; os testes usam detector artificial e não alegam validação de
  firmware nem hardware em CI.
- A branch do Go2 do CEIA é a base para a integração. O leitor Radiacode não
  é ligado ao processo da odometria nem à teleop do Go2.

Para validação local do código, com as dependências de desenvolvimento:

```bash
python -m pip install -e '.[dev,fs5000,radiacode-usb]'
pytest
node --test tests/radiacode/dashboard_usb.test.cjs
```
