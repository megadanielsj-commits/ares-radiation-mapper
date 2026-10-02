# ARES — console de operação v2

O mapa, as cores, o gradiente, o desenho do Go2 e a interpolação da versão v4
aprovada foram preservados. A modernização se limita à interface de operação e
à seleção de entradas. O console é uma versão candidata; a v4 continua incluída.

Nesta revisão o mapa ocupa a área principal, com uma única coluna de telemetria.
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
automaticamente o USB ou o Go2. Clique em **Configurar**, escolha o modo e a
duração da missão e clique em **Aplicar entradas**,
espere os componentes ficarem online e clique em **Iniciar mapeamento**.
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
| Radiacode real · robô simulado | Virtual | USB real | Radiacode neste computador |
| Go2 real · fonte simulada | Go2 via Wi-Fi | Sintética | Wi-Fi LocalAP do Go2 |
| Go2 e Radiacode reais | Go2 via Wi-Fi | USB real | Wi-Fi do Go2 e Radiacode no USB |

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

A dose mostrada pelo leitor USB permanece provisória até comparar a unidade com
o visor; nenhuma calibração CPS→dose do FS-5000 é aplicada ao Radiacode. O mapa
real usa **CPS bruto**, como a aquisição do Werik. O mesmo motor e gradiente v4
operam nessa coordenada numérica de contagens, com a unidade CPS indicada na
legenda e no JSON exportado. `k=1` é identidade matemática, não uma calibração
física. Os nomes internos do motor v4 permanecem preservados; o metadado
`internal_map_rate_coordinate` deixa a unidade explícita. A dose exibida ao lado
é um canal separado: a taxa reportada pelo leitor e sua integral nos intervalos
de 1 s posicionados; não é a dose total acumulada no aparelho. Nenhuma dose é
calculada a partir de CPS. CPM do Radiacode é 60×CPS, não uma janela medida de 1 minuto.
O protocolo FS-5000 permanece no runtime de referência, mas sua seleção não é
oferecida neste console Radiacode.

Robô virtual com USB real testa software e aquisição; as coordenadas virtuais
não representam a posição física do detector. Robô real com fonte simulada testa
teleop e sincronização; não mede o ambiente.

## Compatibilidade e retorno

O núcleo do Werik foi incluído da revisão `4048f7c` da adaptação Go2, baseada
na branch original `ares-wifi`. Orquestrador, sincronizador, teleop, drivers e
persistência não foram editados. Uma subclasse troca apenas a publicação do mapa
para o `MapService` v4. A simulação completa chama o `MissionController` v4 sem
adaptação. `map.lock.json` protege os arquivos por SHA-256 na construção da imagem.

Para voltar ao painel anterior, pare o console e execute `bash simulacao iniciar`
na pasta v4. Nenhum resultado antigo é apagado. Esta versão não substitui
automaticamente as branches do ensaio físico no GitHub.

Após validar esta interface, o pacote inclui `ARES_Console_Operacao_GITHUB.bundle`
e `PUBLICAR_CONSOLE_GITHUB.sh`. Executar esse script publica uma branch nova,
`feat/operator-console`, sem substituir a preparação do ensaio físico. A imagem
do console recebe uma construção e um teste de inicialização próprios no CI.

## Verificação de desenvolvimento

```bash
PYTHONPATH=src:vendor/go2_runtime/src python -m pytest tools/operator_console/test_console.py tools/source_simulation/test_demo.py tests/unit tests/integration
node --test tools/source_simulation/dashboard.test.cjs tools/operator_console/console.test.cjs
python -m tools.operator_console.check_map_lock
```
