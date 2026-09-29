# Operação real (Go2 + FS-5000)

Passo a passo para mapear radiação com o robô e o medidor de verdade. Leia
inteiro antes de começar — em especial a seção 5 (segurança).

## 1. Pré-requisitos

- Go2 EDU ligado, firmware **V1.1.11** (ou ≤ 1.1.14 — sem chave AES; fw
  ≥ 1.1.15 exige `GO2_AES_KEY`, não validado neste projeto).
- FS-5000 conectado por USB no PC que vai rodar o ARES.
- PC com Wi-Fi (para a wifi do robô) e USB livre (para o FS-5000).

## 2. Conectar o PC na wifi do robô

O Go2 no modo LocalAP cria uma rede própria (robô em `192.168.12.1`).
Conecte o PC a essa rede — **sem outra conexão WebRTC ativa** (só uma por
vez; feche qualquer app oficial da Unitree que esteja conversando com o
robô).

```bash
# confirma que o robô responde
ping -c 2 192.168.12.1
```

## 3. Subir o serviço do FS-5000

O ARES **não abre a serial**: ele é cliente do WebSocket do
`FS_5000_quickstart`. Suba esse serviço primeiro (repositório irmão, fora
deste):

```bash
cd ../FS_5000_quickstart
docker compose up -d fs5000          # ou: python3 webapp/server.py
curl -s localhost:1096/api/aparelhos  # confirma que o aparelho aparece
```

O ARES só faz `GET`/WS nesse serviço — nunca chama as rotas `POST` dele
(configurar, zerar dose), então ele não interfere no aparelho.

## 4. Subir o ARES em modo real

Com o PC já na wifi do robô e o serviço do FS-5000 no ar:

```bash
docker compose --profile real up -d ares-real
# ou, sem Docker:
PYTHONPATH=src ARES_MODO=real python3 -m ares
```

Abra `http://127.0.0.1:8000`. As pílulas **Go2** e **FS-5000** no topo
mostram o estado de cada componente:

- **verde**: conectado;
- **cinza/vermelho**: tentando reconectar (backoff até 10 s) — o app sobe
  mesmo assim, e volta sozinho quando o componente aparecer;
- a **missão só pode ser iniciada com os dois conectados**.

Se o Go2 não conectar: confirme a rede wifi (seção 2), que não há outra
sessão WebRTC aberta (só uma por vez) e o firmware (`GO2_AES_KEY` só é
necessário em fw ≥ 1.1.15).

## 5. Segurança antes de andar

- O robô **só anda enquanto o navegador manda heartbeat de velocidade**
  (≥ 5 Hz) pela aba aberta no painel. Trocar de aba, fechar o navegador ou
  perder a conexão do WebSocket **para o robô** (watchdog de 0,5 s).
- Limites de velocidade padrão: `|vx| ≤ 0,5 m/s`, `|vy| ≤ 0,3 m/s`,
  `|vyaw| ≤ 1,0 rad/s` — configuráveis, nunca ultrapassáveis pelo teleop.
- **PARAR** (botão ou tecla espaço) manda `StopMove` na hora, repetido até
  confirmar.
- Encerrar a missão, cair o WebSocket ou encerrar o servidor **também**
  manda `StopMove`.
- Não há rota automática: o robô só anda com alguém no controle,
  continuamente.
- Latência de parada no pior caso (do último heartbeat até o comando ser
  enviado ao robô): `watchdog_s + 1/verificacao_hz` ≈ 0,55 s. Detalhes em
  [`arquitetura.md`](arquitetura.md#laço-de-segurança-do-teleop).

Antes de andar de verdade, teste **Levantar** e **PARAR** com o robô
deitado/parado no chão, com espaço livre ao redor.

## 6. Fazendo a missão

1. Clique **Iniciar missão** (nome opcional).
2. Levante o robô (**Levantar**) e ande com setas/WASD (Q/E para strafe
   lateral), cobrindo a área de interesse — quanto mais o percurso cruzar
   diferentes distâncias e ângulos em torno de uma possível fonte, mais
   cedo o estimador consegue distingui-la do fundo (ver
   [`modelo.md`](modelo.md#3-estimador-bayesiano-em-grade), critérios de
   detectabilidade).
3. Acompanhe **P(fonte)**, a posição estimada e o mapa de calor no painel.
4. **PARAR** a qualquer momento; **Encerrar missão** ao terminar (ou deixe
   o watchdog agir se algo der errado).
5. Exporte CSV/JSON da missão na lista à direita, se quiser levar os dados
   para outra análise.

## 7. Ao final

```bash
docker compose --profile real down
cd ../FS_5000_quickstart && docker compose down   # se não for mais precisar
```

## 8. O que ainda não foi validado

Os helpers de WebRTC do Go2 (`src/ares/robo/go2.py`) são portados do
`go2_wifi_quickstart`, já validado em hardware real naquele projeto — mas
o **modo real do ARES em si** (a integração completa: teleop + estimador +
missão gravada, tudo com o robô andando de verdade) ainda não foi testado
em hardware neste projeto. Valide com cautela, em espaço controlado, antes
de qualquer uso operacional.
