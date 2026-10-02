# ARES Console 1.0.2 — versão de referência para o ensaio

O mapa, as cores, o gradiente, o desenho do Go2 e a interpolação da versão v4
aprovada foram preservados. Esta revisão mantém a interface aprovada e a correção de permanência da v3.
O título do mapa é **Mapa de calor** e sua legenda usa unidades automáticas de
taxa de dose (nSv/h, µSv/h, mSv/h ou Sv/h) nos quatro modos.
O pacote é a referência de software para o ensaio de 08/10/2026; a validação conjunta
com o Go2 físico continua dependente desse ensaio.

Nesta revisão o mapa ocupa a área principal e a coluna de telemetria fica à esquerda.
O título é **Levantamento Radiométrico**. A revisão 1.0.2 preserva as correções de
aquisição da 1.0.1 e muda somente a apresentação das unidades. Dose e taxa usam
o prefixo adequado à magnitude, normalmente com duas casas e sem notação
científica. Para doses integradas muito pequenas, podem aparecer pSv ou fSv.
Uma dose positiva pequena não vira zero. Além do menor prefixo disponível,
são mantidas casas decimais suficientes para conservar o valor visível.
Somente os rótulos são formatados; dados, registros e cálculos mantêm a precisão
original. A quantidade de amostras permanece inteira.
A logo é exibida em branco, sem fundo branco, por CSS sobre a imagem original.
O bloco de setas foi removido. O teclado mantém o controle já existente.
A contagem de medições posicionadas usa o total da missão, e não o tamanho do
buffer de até 5.000 pontos usado no desenho. A apresentação dos valores não
depende da altura disponível nos antigos cartões de telemetria.

## Iniciar

Requisitos: Linux, Docker Engine com Compose, navegador. Na pasta do pacote:

```bash
bash ares-console iniciar
```

Abra http://127.0.0.1:8001. O sistema abre em simulação completa e não acessa
automaticamente o USB ou o Go2. Escolha o modo no menu **Simulação completa**
do cabeçalho; a seleção aplica a combinação de entradas. Para ajustar a duração,
clique em **Configurar** e em **Aplicar entradas**. Nos modos **Simulação completa**
e **Detector simulado**, abra **Fonte simulada** na coluna esquerda, defina X/Y e
a taxa de dose a 1 metro em mSv/h, e clique em **Aplicar fonte**.
Espere os componentes ficarem online e clique em **Iniciar mapeamento**.
No robô simulado o controle é habilitado ao iniciar. Com robô real, confirme a
área livre e habilite o teclado. Setas mantidas pressionadas movem o
robô; soltar envia zero, perder o foco revoga o controle. **Parar movimento**
interrompe o movimento e mantém o registro; **Encerrar e salvar** termina a missão.
**Ampliar mapa** oculta a coluna lateral e **Restaurar painel** a traz de volta.
A ampliação altera somente o espaço da interface; o mapa mantém sua proporção
espacial, as cores, a escala e o algoritmo de interpolação. Em telas de telefone,
a área de desenho pode ser deslizada lateralmente para manter os eixos legíveis.
Fechar a configuração sem aplicar descarta os ajustes que ainda não foram salvos.
O iniciador encerra o contêiner anterior da fonte simulada, se estiver ativo,
e preserva os resultados dele antes de abrir o console.

| Modo | Posição | Radiação | O que conectar |
|---|---|---|---|
| Simulação completa | Virtual | Sintética | Nada |
| Robô simulado | Virtual | USB real | Radiacode neste computador |
| Detector simulado | Go2 via Wi-Fi | Sintética | Wi-Fi LocalAP do Go2 |
| Equipamentos reais | Go2 via Wi-Fi | USB real | Wi-Fi do Go2 e Radiacode no USB |

As entradas e a fonte ficam bloqueadas durante a missão. Encerre antes de mudar
o modo. A missão termina sozinha após a duração selecionada. Fechar a página
não encerra a aquisição. Para encerrar o sistema e preservar os arquivos:

```bash
bash ares-console parar
```

Com Go2 real, X/Y da fonte simulada usam o referencial local `odom`, mostrado no
console. A área da missão tem 20 m de lado e é centrada na posição inicial do
robô, como no runtime do Werik. Isso também funciona quando a odometria já está
longe de 0,0; não se presume que conectar o Wi-Fi resete a posição do robô.

O leitor USB começa somente nos modos que usam radiação real e termina quando
você seleciona outro modo ou encerra o sistema. Ele continua em processo separado
do servidor e do robô, com registro próprio, filtro de leituras antigas e
reconexão, como no módulo independente. As permissões USB já configuradas no
ensaio anterior continuam necessárias. O registro USB bruto continua entre
missões enquanto esse modo estiver selecionado; a duração escolhida encerra
apenas a missão posicionada e suas exportações.
Se a porta 1098 estiver ocupada, pare o
leitor anterior com o iniciador dele; o console não encerra processos alheios.

## Arquivos e limites do ensaio

**Baixar dados da missão** entrega um ZIP após encerrar a missão. Os arquivos
também ficam em `resultados/console/`, separados por modo. A simulação completa
mantém as exportações nativas v4. Os modos mistos/real mantêm o SQLite do Werik,
CSV de amostras, JSON com leituras e poses, mapa e metadados. O registro USB bruto
fica em `resultados/console/usb/` (CSV/JSONL e espectros, conforme o leitor).

Nos modos reais, a sincronização usa a fórmula e a implementação do Werik:
posição interpolada no instante `timestamp_da_leitura - latencia_leitura_s`.
O padrão 0,5 s e o offset 0,0 precisam ser confrontados com o ensaio real. Para
ajustar parâmetros existentes sem alterar o código:

```bash
ARES_LATENCIA_LEITURA_S=0.5 ARES_OFFSET_DETECTOR=0,0 bash ares-console iniciar
```

O mapa real usa a **taxa de dose reportada pelo Radiacode**, não CPS convertido.
O motor trabalha em µSv/h. Somente os rótulos escolhem a unidade adequada:
0,12 µSv/h aparece como `120,00 nSv/h`; 1.000 µSv/h aparece como `1,00 mSv/h`;
1.000.000 µSv/h aparece como `1,00 Sv/h`. O algoritmo, a paleta e a interpolação permanecem
protegidos; a evidência que entra no mapa é o canal de dose. Os modos simulados
mantêm o modelo sintético aprovado e usam a mesma unidade na legenda.

O SDK 0.4.0 fornece valores brutos escalados. A configuração dos registros USB
disponíveis declara `CHN_DoseRate` em `R/h`. O leitor aplica o fator 10.000 utilizado
pelo exportador dessa versão do SDK para obter µSv/h, sem usar CPS como entrada.
`get_alarm_limits().dose_unit` informa a unidade do visor/alarmes (`R` ou `Sv`),
separada da unidade do canal bruto; não deve impedir essa conversão conhecida.
A convenção do SDK permanece provisória até comparar a taxa com o visor em Sv.
O bridge valida unidade/escala do canal bruto, consistência com o valor bruto e
timestamps próprios recentes da taxa. Unidade bruta desconhecida, taxa ausente
ou antiga mantém contagens e registros, mas não produz dose zero nem ponto
fictício no mapa. Os motivos ficam em `service.log` e no diagnóstico `/health`.
Não altere a unidade do detector durante uma sessão USB: encerre, ajuste no
aparelho e reinicie o console. Não são alterados alarmes ou contadores do detector.

CPS e CPM continuam nos registros independentes e nas amostras posicionadas do
Werik. CPM é 60×CPS, não uma janela medida de um minuto. A dose acumulada no painel
é a integral da taxa dos intervalos posicionados aceitos de 1 s; não é o total do
aparelho nem uma recuperação da dose perdida em interrupções. O JSON do mapa
mantém µSv/h e seus metadados de apresentação de referência em mSv/h e fator 0,001
nos modos mistos/reais. A interface calcula os prefixos apenas nos rótulos a partir
dos valores em µSv/h; não modifica esses metadados ou os números exportados.
Os CSV e o SQLite conservam nomes de campos, unidades e precisão originais.
O protocolo FS-5000 permanece no runtime de referência, mas sua seleção não é
oferecida neste console Radiacode.

Robô virtual com USB real testa software e aquisição; as coordenadas virtuais
não representam a posição física do detector. Robô real com fonte simulada testa
teleop e sincronização; não mede o ambiente.

## Compatibilidade e retorno

Durante a permanência no mesmo ponto, todas as leituras continuam sendo usadas
e registradas. O diagnóstico de geometria mantém posições independentes, para que
a repetição não apague o trajeto do histórico. A reamostragem continua ativa, mas
não injeta novas hipóteses espaciais do prior durante a permanência. A exploração
espacial é retomada ao movimentar o detector. Picos da estimativa só são
considerados locais distintos quando separados por pelo menos uma célula de
observação em metros, evitando falsos alarmes ao concentrar a localização.
Essa correção não congela as cores
ou o mapa e não impede o diagnóstico existente de inconsistência das leituras.

O núcleo do Werik foi incluído da revisão `4048f7c` da adaptação Go2, baseada
na branch original `ares-wifi`. Orquestrador, sincronizador, teleop, drivers e
persistência não foram editados. Uma subclasse troca apenas a publicação do mapa
para o `MapService` v4. A simulação completa chama o `MissionController` v4 sem
adaptação. `map.lock.json` protege os arquivos por SHA-256 na construção da imagem
e documenta os dois arquivos da correção autorizada de permanência. Os demais
54 arquivos protegidos têm os mesmos hashes da v2.

Para voltar ao painel anterior, pare o console e execute `bash simulacao iniciar`
na pasta v4. Nenhum resultado antigo é apagado. Esta versão não substitui
automaticamente as branches do ensaio físico no GitHub.

O pacote inclui `ARES_Console_Oficial_1.0.2_GITHUB.bundle` e `PUBLICAR_CONSOLE_GITHUB.sh`.
O script publica `release/ares-console-1.0.2`, sem force push e sem editar `ares-wifi`.
Consulte [PUBLICACAO_E_TESTE.md](PUBLICACAO_E_TESTE.md) para publicação, preparação
sem internet no campo, sequência dos testes e critérios de aceitação.
A imagem Docker é `ares-operator-console:1.0.2`. O CI constrói a imagem e testa
início, encerramento e exportação em simulação completa.

## Verificação de desenvolvimento

```bash
PYTHONPATH=src:vendor/go2_runtime/src python -m pytest tests tools/operator_console/test_console.py tools/operator_console/test_stationary_map.py tools/source_simulation/test_demo.py
node --test tools/source_simulation/dashboard.test.cjs tools/operator_console/console.test.cjs
python -m tools.operator_console.check_map_lock
```
