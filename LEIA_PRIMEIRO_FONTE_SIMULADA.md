# Simulação com fonte — interface e cálculo originais

Esta versão restaura o simulador que acompanhava o FS-5000: `ares_mapper`, seu
painel, seu controle por setas e seu serviço de reconstrução do mapa. Não carrega
os adaptadores de apresentação nem a projeção de um pico usada na versão v3.

## Executar

Na pasta do pacote:

```bash
bash simulacao iniciar
```

A primeira execução constrói uma imagem própria do simulador original.
Abra http://127.0.0.1:8001, informe as coordenadas e a taxa da fonte e clique em
**Iniciar mapeamento**. A taxa a 1 metro é informada em **mSv/h**, como no painel
original. Os valores iniciais também são os do cenário original: x=7,5 m,
y=5,5 m e 10 mSv/h a 1 metro. Todos os dados são simulados.

Use as setas para avançar/recuar e girar. A simulação começa em x=2 m, y=2 m.
O botão **Reiniciar mapeamento** salva a missão anterior e inicia uma nova.

## Mapa e escala

O cálculo é o original: primeiro representa o gradiente sustentado pelas
medições; o campo completo só aparece quando os critérios originais de
identificabilidade e estabilidade são atendidos. Não preenche antecipadamente
a área inteira com um pico escolhido a partir de poucas medições.

A paleta, a escala logarítmica da missão, os controles e o desenho do robô são
os do painel original. Durante a missão a escala depende da fonte configurada,
e não do máximo momentâneo das leituras. Superfície, pontos antigos e legenda
usam a mesma escala e são redesenhados juntos.

A única correção no desenho do mapa posiciona a grade nas coordenadas que ela
representa quando o enquadramento automático muda. Não altera os valores do
mapa, a reconstrução ou o layout.

## Parar e salvar

```bash
bash simulacao parar
```

O encerramento normal salva a missão e exporta os arquivos usando o exportador
original. Eles ficam em `resultados/fonte-simulada/<missao>/`, com as exportações
na subpasta `exports/`. Incluem CSV de leituras e amostras sincronizadas, grade,
metadados e demais produtos do simulador original.

O cenário original dura até 3.600 segundos. Fechar o navegador não encerra a
missão. Use o comando de parada para finalizar antes desse prazo.

Os arquivos de v1, v2 e v3 permanecem nas respectivas pastas anteriores.
Esta simulação não utiliza USB nem conexão com um robô físico.
