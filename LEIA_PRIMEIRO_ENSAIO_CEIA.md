# Radiacode 110 — ensaio na estrutura do CEIA

Este pacote acrescenta o Radiacode à estrutura `ares-wifi` do Werik, revisada
no commit `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`. O código de sincronização,
teleop, WebRTC do Go2 e cliente do FS-5000 permanece igual a essa revisão.
O painel anterior continua disponível por `bash ares radiacode-dashboard`.

## Preparar antes de ir ao laboratório

Use o Linux e o Docker que já funcionaram com o Radiacode. Pare qualquer
leitor antigo com Ctrl+C; para o novo ensaio use `bash ensaio parar`.
Com internet, dentro da pasta extraída deste ZIP, execute:

```bash
bash ensaio preparar
```

Esse comando constrói as duas imagens: leitor USB independente e aplicação
CEIA. Faça isso antes de conectar ao Wi-Fi do Go2, que pode ficar sem internet.
A construção deve terminar sem erro. As imagens ainda precisam ser construídas
no seu computador; não há imagens binárias dentro do ZIP.

## Primeiro teste: USB real e robô simulado

Conecte o Radiacode e feche qualquer outro programa que use seu USB. A permissão
USB configurada nos testes anteriores continua válida para o mesmo usuário.
Execute:

```bash
bash ensaio usb-simulado
```

Abra **http://127.0.0.1:8001**. Este é o painel do CEIA, usado para conferir a
integração com a estrutura dele. Seu painel anterior continua em outro comando
e não precisa ser substituído.

1. Aguarde detector e robô conectados e novas contagens aparecendo.
2. Clique em **Iniciar missão**. Antes desse clique, só o leitor independente
   está gravando; as posições da missão começam a ser salvas após o início.
3. Mova o robô pelas teclas/botões do painel durante alguns minutos.
4. Veja o número de amostras aumentar. A indicação **Aquisição sem calibração**
   é esperada: a missão grava contagens e posição sem estimar a fonte.
5. Clique em **Encerrar missão**. Confira o CSV/JSON pelo painel.
6. No terminal execute `bash ensaio parar`. Isso encerra os contêineres deste
   ensaio e exporta as missões salvas automaticamente.

Os serviços ficam em segundo plano e não param sozinhos após uma hora. Use
**Encerrar missão** no painel e `bash ensaio parar` para finalizar.

## No laboratório: USB real e Go2 real

Primeiro validem a montagem FS-5000 + Go2 do Werik. Para trocar de detector,
encerrem a missão e o painel que está comandando o Go2; um controlador por vez.
O novo ensaio usa a rede do host, como o `ares-wifi`, e não mexe no serviço
FS-5000 da porta 1096.

Com as imagens já preparadas, conecte o computador ao Wi-Fi do Go2 e o Radiacode
por USB. Execute:

```bash
bash ensaio parar
bash ensaio usb-robo
```

Abra **http://127.0.0.1:8001**. Aguarde os dois componentes conectados, inicie a
missão e repita o procedimento curto de movimento e exportação. O comando
não começa movimento nem missão automaticamente. A câmera e o controle são
os do Werik.

O offset físico do detector em relação ao referencial do robô pode ser informado
pelo CEIA, em metros, antes de iniciar:

```bash
ARES_OFFSET_DETECTOR="0.10,0.00" bash ensaio usb-robo
```

Esse valor é um exemplo, não uma medida da montagem. Se o firmware exigir uma
chave AES, use a mesma `GO2_AES_KEY` do teste do Werik. Sem chave fornecida,
mantém-se o comportamento original. Não grave a chave no repositório.

## Onde os arquivos ficam

Tudo fica na pasta extraída do pacote:

- `resultados/ceia/usb/`: sessões USB, logs e JSONL/CSV independentes do robô;
- `resultados/ceia/simulacao/ares.db`: missões com posição simulada;
- `resultados/ceia/real/ares.db`: missões com posição do Go2;
- `resultados/ceia/simulacao/exportados/` e `resultados/ceia/real/exportados/`:
  CSV/JSON gerados por `bash ensaio parar` ou `bash ensaio exportar`.

O JSON exportado inclui missão, metadados, poses, leituras e amostras posicionadas.
O CSV contém `ts,x,y,dr_usvh,cpm,cps,lacuna_pose_s`; `ts` é o timestamp UTC de
recebimento, em segundos Unix. A posição foi interpolada no instante
`ts - latencia_leitura_s`, conforme a regra original do Werik.

## Diagnóstico simples

```bash
bash ensaio verificar
bash ensaio logs
```

`verificar` mostra o estado do serviço USB e da aplicação CEIA. `logs` mostra
os serviços; Ctrl+C fecha apenas a visualização dos logs. O detalhe do leitor
USB fica nos arquivos `.log` em `resultados/ceia/usb/`.

Se houver erro de permissão ou nenhum dispositivo, execute:

```bash
bash 01_diagnostico_usb.sh
bash 03_permissao_usb.sh
```

Depois reconecte o cabo. Em uma desconexão durante o ensaio, a aplicação deve
indicar detector desconectado. O serviço tenta reconectar e abre uma nova
sessão ao recuperar o USB; as contagens antigas não viram posição atual.

## Medições e limites do primeiro ensaio

- `readings.jsonl` mantém CPS fracionário/suavizado e taxa de dose do detector,
  como no teste anterior aprovado.
- `counts_1s.jsonl` contém contagens inteiras formadas por dois registros RawData
  consecutivos de aproximadamente 0,5 s. É essa entrada que alimenta o CEIA.
- `cpm` nesta entrada é **60 × contagens de um segundo**; não é uma janela
  independente de um minuto. A dose acumulada convertida é `null`.
- A taxa de dose usa conversão provisória e está identificada como tal. Compare
  com o visor em µSv/h antes de afirmar que a conversão está validada.
- Sem `ARES_RADIACODE_CPS_POR_USVH`, a missão salva posição e contagens e não
  calcula mapa calibrado nem localização probabilística da fonte. O fator
  2,6 do FS-5000 não é aplicado ao Radiacode.
- A latência inicial é 0,5 s, a regra já usada pelo sincronizador do Werik.
  Ela ainda precisa ser medida na montagem real; o polling USB e o tempo da
  exposição introduzem incerteza na posição. É ajustável por
  `ARES_LATENCIA_LEITURA_S`, sem mudar o algoritmo dele.
- Dados recebidos em grandes lotes, repetidos ou antigos são preservados nos
  arquivos USB, mas rejeitados pelo fluxo de posicionamento em tempo real.

Pronto para iniciar a validação em bancada. O ensaio Go2 físico + Radiacode
não foi realizado nesta preparação. A leitura real de uma hora já fornecida
por você e os testes de software estão descritos em
[docs/VALIDACAO_ENSAIO_CEIA.md](docs/VALIDACAO_ENSAIO_CEIA.md).

## Disponibilizar ao CEIA no GitHub

Depois de conferir este pacote:

```bash
bash publicar_no_github.sh
```

O script importa o bundle completo que acompanha o ZIP e publica duas branches,
sem `force`, sem alterar `main` nem `ares-wifi`:

- `feat/radiacode-independent`: leitor, serviço USB e painel anterior;
- `feat/radiacode-ceia-test`: adaptação mínima da estrutura do Werik.

Envie as duas URLs impressas pelo script. A segunda contém o código que deve
ser revisado para o ensaio na estrutura CEIA. O envio só ocorre quando você
executa esse comando no computador com seu acesso ao GitHub.
