# ARES — gravação com fonte simulada oculta e escala de cores

Esta edição parte do Console 1.0.2 consolidado. A fonte continua ativa no
simulador, mas sua marcação e a legenda "Fonte configurada" começam ocultas.
O mapa inicia sem medições e é construído pelo movimento e pelas leituras, com
o mesmo gradiente, paleta, interpolação e correção de permanência aprovados.
Os rótulos de simulação continuam visíveis para identificar a demonstração.

## Iniciar

Salve `ARES_Console_1.0.2_Gravacao_v2.zip` em Downloads e copie:

```bash
python3 -m zipfile -e "$HOME/Downloads/ARES_Console_1.0.2_Gravacao_v2.zip" "$HOME" &&
cd "$HOME/ARES_Console_1.0.2_Gravacao_v2" &&
bash ares-console iniciar
```

Abra **http://127.0.0.1:8001**. A imagem Docker desta edição tem a identificação
`ares-operator-console:1.0.2-recording-v2` e será construída na primeira execução,
com internet. Ela não sobrescreve a imagem oficial `1.0.2`.
O iniciador encerra o console anterior para liberar a mesma porta; os resultados
anteriores permanecem na pasta em que foram gravados.

## Preparar e filmar

1. Mantenha **Simulação completa**. Não é necessário conectar detector ou robô.
2. Abra **Fonte simulada**, escolha X/Y e taxa a 1 metro e clique em **Aplicar fonte**.
3. Deixe **Mostrar fonte no mapa** desmarcado e feche o bloco **Fonte simulada**
   para não exibir suas coordenadas durante a gravação.
4. Inicie a gravação da tela e clique em **Iniciar mapeamento**. Use as setas do
   teclado para percorrer a área; o mapa surge conforme as medições entram.
5. Se desejar revelar a posição verdadeira ao final, abra **Fonte simulada** e
   marque **Mostrar fonte no mapa**. Essa opção pode mudar durante a missão;
   não muda fonte, leituras, dados exportados, cores ou cálculos.
6. Termine pelo botão **Encerrar e salvar**. **Baixar dados** exporta a missão.

Para uma nova tomada, após encerrar, clique em **Aplicar fonte** novamente;
isso limpa o mapa da interface para a próxima missão. Ao recarregar a página,
a marcação volta ao padrão oculto, mas a missão em andamento não é reiniciada.

A opção também funciona em **Detector simulado** (Go2 real e radiação sintética).
Com radiação USB real não há fonte configurada a revelar; os modos e a aquisição
permanecem com a estrutura da versão oficial.

## Escolher a escala de cores

Abra **Escala de cores** no painel lateral:

- **Automático** conserva o comportamento original: os limites são definidos
  pelo ARES com as regras da missão. Não introduz uma nova escala pelo mínimo
  e máximo de todas as amostras.
- **Manual** permite definir a **taxa mínima azul** e a **taxa máxima vermelha**.
  Cada valor tem sua unidade: nSv/h, µSv/h, mSv/h ou Sv/h. Por exemplo,
  azul `100 nSv/h` e vermelho `10 µSv/h`.

Clique em **Aplicar escala**, tanto ao mudar os limites quanto ao voltar ao
automático. Valores fora dos limites usam as cores das extremidades. Os limites
devem ser positivos, com vermelho maior que azul, pois a escala original é
logarítmica; o vermelho deve ser pelo menos 1,000001 vez o azul. Uma entrada
inválida exibe uma mensagem e conserva a última escala aplicada.

A escala pode mudar durante a missão: o mapa inteiro, os pontos anteriores e a
barra de cores são redesenhados juntos. As leituras, a grade numérica, os arquivos
exportados e a interpolação não são alterados. Escolher uma unidade converte
somente o limite de apresentação; CPS/CPM continuam separados da taxa de dose.
A escala funciona nos quatro modos. Ela é uma preferência da página, não um
parâmetro de aquisição: ao recarregar, volta a **Automático**. Para repetir uma
gravação com os mesmos limites, reaplique-os.

## Cadência e velocidade do robô virtual

As leituras simuladas seguem a mesma cadência nominal da ponte Radiacode usada
pelo ARES: **uma janela de 1 segundo**, formada no USB por dois registros
RawData de aproximadamente 0,5 s. A consulta USB a cada 0,25 s não significa
uma nova medição nesse intervalo. A simulação completa roda em tempo real
(1×), sem o jitter artificial de chegada. A taxa de dose real pode ter seu
próprio instante de atualização; atrasos e agrupamentos do USB dependem do
equipamento. Não se trata de reproduzir sua resposta física ou suavização.

Em **Simulação completa**, antes de iniciar uma missão, abra **Configurar**,
ajuste **Velocidade do robô virtual · m/s** e clique em **Aplicar entradas**.
O padrão é `0,45 m/s`; o intervalo permitido é de `0,05` a `2,00 m/s`.
As setas para frente e para trás usam essa velocidade. Soltar as setas,
perder o foco e o watchdog continuam parando o movimento. A velocidade de
rotação continua igual. Para mudar a velocidade durante uma gravação,
encerre e salve a missão, ajuste-a e inicie outra.

Essa opção não acelera o relógio nem a cadência das leituras e não modifica
o controle dos demais modos ou os limites de teleop do Go2 real.

## Encerrar o programa

```bash
cd "$HOME/ARES_Console_1.0.2_Gravacao_v2" && bash ares-console parar
```

Os registros desta edição ficam em `resultados/console` dentro da pasta de gravação.
A edição é separada do pacote preparado para o ensaio com o Go2. Para retornar ao
console oficial, pare esta edição e execute o iniciador na pasta oficial.
Não use o script de publicação da release para publicar esta edição de gravação.

## Alteração e verificação

Somente a camada da interface controla a visibilidade do marcador original
e os limites opcionais da escala de cores.
Os 56 arquivos protegidos, os núcleos originais de aquisição/sincronização e
o renderizador original foram preservados. O adaptador do console configura
somente a cadência sintética e a velocidade virtual solicitadas. As verificações estão em
`validation/recording_scale_20261006.json` e no XML da regressão do console.
