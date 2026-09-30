# Radiacode 110 + Go2 — preparação e teste USB

Este pacote contém um leitor USB independente e a adaptação do projeto
`ares-wifi` para receber suas contagens por WebSocket. Para o teste atual,
somente o Radiacode precisa estar conectado. A posição e o movimento do robô
são simulados. O Go2 físico será usado no segundo modo, no laboratório.

## Executar agora

Baixe `ARES_Radiacode_GO2_USB_v2.zip` na pasta Downloads. Com o Radiacode
conectado por USB e internet disponível, copie este bloco completo:

```bash
python3 -m zipfile -e "$HOME/Downloads/ARES_Radiacode_GO2_USB_v2.zip" "$HOME" &&
cd "$HOME/ARES_Radiacode_GO2_USB_v2" &&
bash ensaio preparar &&
bash ensaio usb-simulado
```

O computador deve ter Docker Engine e o plugin Docker Compose, como nos
testes anteriores. A construção instala as dependências e verifica a
aplicação instalada na imagem: HTML, JavaScript, API e robô simulado. Nenhum
equipamento físico é necessário durante `preparar`. As imagens são
construídas no computador; o ZIP contém o código e não as imagens binárias.

Ao iniciar, o script encerra os contêineres das versões anteriores desta
integração sem apagar os dados. Se houver outro leitor USB fora desses
contêineres, encerre-o antes com Ctrl+C. O Radiacode tem um único leitor USB;
os consumidores recebem seus dados pelo serviço independente.

O endereço só é anunciado como pronto após a página, o JavaScript e a API
responderem. Abra **http://127.0.0.1:8001** no mesmo computador.

1. Confira **Robô simulado ok**, **Radiacode ok** e CPS atualizado.
2. Clique em **Iniciar missão**. A aquisição USB já está gravando; esse clique
   começa a gravação da missão com posição.
3. Use as setas ou WASD para mover o robô virtual por alguns minutos. O número
   de amostras deve aumentar. **Aquisição sem calibração** é esperado neste teste.
4. Clique em **Encerrar missão** e confira a exportação CSV/JSON pelo painel.
5. Para finalizar os serviços e exportar automaticamente as missões, execute:

```bash
cd "$HOME/ARES_Radiacode_GO2_USB_v2" && bash ensaio parar
```

Os serviços permanecem em segundo plano e não param sozinhos após uma hora.
Fechar o navegador não encerra a aquisição. O painel anterior continua
separadamente em `bash ares radiacode-dashboard`, na porta 8000;
use um leitor USB por vez.

## No dia do teste com o Go2

Execute `preparar` e o teste acima antes de ir ao laboratório. Depois, não
será necessário baixar dependências para mudar para o Go2 real.

Primeiro validem FS-5000 + Go2 na estrutura original. Antes de trocar para
Radiacode, encerrem a missão e o controlador anterior do Go2. Conectem o
computador ao Wi-Fi do robô e o Radiacode por USB. Na mesma pasta, executem:

```bash
cd "$HOME/ARES_Radiacode_GO2_USB_v2" && bash ensaio usb-robo
```

O script troca o modo simulado pelo real. Abra **http://127.0.0.1:8001**,
aguarde Go2 e Radiacode conectados e inicie uma missão curta. Câmera,
teleoperação, watchdog e sincronização usam a implementação original
`ares-wifi`, revisão `84f9148`. Nenhuma missão ou movimento começa pelo
comando de inicialização. O serviço FS-5000 da porta 1096 não é modificado.

Se a montagem exigir offset do detector ou chave AES, use os valores
conferidos pela equipe. As opções disponíveis são:

- `ARES_OFFSET_DETECTOR="dx,dy"`, em metros no referencial do robô;
- `ARES_LATENCIA_LEITURA_S`, inicialmente 0,5 s, conforme o sincronizador original;
- `GO2_AES_KEY`, somente se necessária para esse firmware;
- `ARES_RADIACODE_CPS_POR_USVH`, somente após medir uma calibração específica.

Essas opções são variáveis de ambiente e não exigem alteração do código.
Exemplo apenas de sintaxe para um offset que deverá ser medido:

```bash
ARES_OFFSET_DETECTOR="0.10,0.00" bash ensaio usb-robo
```

Para declarar o ensaio físico validado, confirmem controle e pose do Go2,
contagens atuais, aumento das amostras e exportação. Façam também uma
desconexão e reconexão USB para conferir a retomada. Latência e offset
ainda precisam ser verificados nessa montagem.

## Arquivos e diagnóstico

Todos os dados novos ficam dentro da pasta extraída:

| Caminho | Conteúdo |
|---|---|
| `resultados/integracao/usb/` | Sessões USB independentes, JSONL/CSV, espectros e logs |
| `resultados/integracao/simulacao/ares.db` | Missões com posição simulada |
| `resultados/integracao/real/ares.db` | Missões com posição real do Go2 |
| `resultados/integracao/{simulacao,real}/exportados/` | CSV/JSON das missões |
| `resultados/integracao/diagnostico-*/` | Estado e logs dos contêineres, quando a inicialização falha |

```bash
bash ensaio verificar
bash ensaio logs
```

`verificar` mostra os estados USB e ARES e os últimos logs. Ctrl+C em `logs`
encerra apenas a visualização. Um painel disponível com USB não confirmado
é informado explicitamente; isso não conta como sucesso da leitura real.
Se o detector não for encontrado ou houver erro de permissão:

```bash
bash 01_diagnostico_usb.sh
bash 03_permissao_usb.sh
```

Reconecte o cabo depois de configurar a permissão. Os dados antigos não são
copiados nem apagados por esta atualização; permanecem na pasta anterior.

## Semântica das medições

`readings.jsonl` conserva o CPS fracionário/suavizado do detector.
`counts_1s.jsonl` contém contagens inteiras obtidas de dois bins RawData
consecutivos de aproximadamente 0,5 s; essa é a entrada da aplicação Go2.
CPM nessa entrada é `60 × CPS`, não uma integração independente de um minuto.
A dose acumulada convertida permanece `null`.

A taxa de dose usa a conversão provisória já identificada nos arquivos.
Compare com o visor antes de declarar validada a unidade µSv/h. Sem fator
CPS por µSv/h específico do Radiacode, a missão grava posição, contagem e
timestamp e mantém a estimativa da fonte desabilitada. O fator 2,6 do
FS-5000 não é reutilizado.

O CSV posicionado contém `ts,x,y,dr_usvh,cpm,cps,lacuna_pose_s`. `ts` é o
recebimento UTC em segundos Unix; a posição é interpolada em
`ts - latencia_leitura_s`. O JSON inclui metadados, poses, leituras e amostras.
Dados antigos, repetidos ou recebidos em lotes de tempo incerto ficam nos
arquivos USB, mas não são apresentados como posições atuais.

Veja [docs/VALIDACAO_INTEGRACAO.md](docs/VALIDACAO_INTEGRACAO.md) para os testes
executados e [docs/CONTRATO_USB_WEBSOCKET.md](docs/CONTRATO_USB_WEBSOCKET.md)
para o contrato entre módulos. A combinação física Go2 + Radiacode ainda
depende do ensaio no laboratório.

## Publicação no GitHub

Depois de conferir este pacote, execute:

```bash
bash publicar_no_github.sh
```

O script usa o bundle completo incluído no ZIP e publica sem `force`:

- `feat/radiacode-independent`: leitor USB, serviço e painel anterior;
- `feat/radiacode-go2-wifi`: adaptação da estrutura Go2/WebRTC.

As branches `main` e `ares-wifi` não são alteradas. O envio ocorre somente
quando você executa o comando com seu acesso ao GitHub.
