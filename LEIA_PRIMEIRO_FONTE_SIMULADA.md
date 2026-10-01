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

A grade é desenhada nas coordenadas que representa quando o enquadramento
automático muda.

### Melhoria de renderização — v5

O mapa usa interpolação bilinear dos valores numéricos entre nós conhecidos
antes de aplicar a paleta original. O valor intermediário permanece entre o
menor e o maior dos vizinhos. Próximo a uma lacuna, conserva o nó conhecido mais
próximo ou a transparência, sem interpolar através da região desconhecida.

A consulta pelo cursor usa o mesmo cálculo. A imagem da grade é reaproveitada
durante a animação do robô e refeita quando chega um mapa novo ou muda a escala.
Isso reduz a reconstrução de imagens no navegador, mantendo atualização das
cores antigas junto com a legenda.

A subdivisão de quatro pixels por intervalo serve à exibição. Não aumenta a
resolução física, a quantidade de medições ou a precisão do estimador. O cálculo
original de reconstrução, seus critérios de estabilidade e os arquivos
exportados permanecem os mesmos da versão v4.

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

Os arquivos de v1, v2, v3 e v4 permanecem nas respectivas pastas anteriores.
Esta simulação não utiliza USB nem conexão com um robô físico.
