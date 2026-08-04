# Simulação

A simulação separa `ground_truth` de `observed`.

- A trajetória fornece a pose verdadeira.
- O modelo de odometria acrescenta ruído, deriva, latência, perdas e outliers.
- O campo radiológico é integrado ao longo da trajetória verdadeira do detector
  durante cada janela de um segundo.
- O detector acrescenta resposta de primeira ordem, estatística de contagem,
  quantização, ruído e atraso.
- O mapa recebe apenas pose e radiação observadas.

Todas as fontes aleatórias usam `numpy.random.Generator(PCG64(seed))`.

## Campo

Fontes `inverse_square` usam taxa de referência a uma distância configurada e um
raio mínimo. Fontes `gaussian` criam um campo suave para validar o interpolador.
Keyframes permitem mover a fonte e variar sua intensidade.

## Mapa temporal

- `cumulative`: todas as amostras anteriores;
- `sliding_window`: somente os últimos `W` segundos;
- `time_slice`: intervalo escolhido;
- `time_decay`: peso exponencial pela idade da amostra.

Na V0.3, o posterior de fonte estática é cumulativo. Os modos temporais antigos
continuam aceitos na configuração e na camada observada, mas fontes móveis exigem
um modelo de estado futuro; não se apaga evidência do posterior estático
silenciosamente.

## Reconstrução probabilística

Cada observação atualiza partículas `x`, `y`, intensidade a 1 m e fundo. O mapa
global usa um campo central determinístico construído pelos parâmetros robustos
do modo posterior dominante. Amostras leves do posterior continuam propagando
os intervalos de incerteza, mas não definem diretamente a cor central de cada
célula. Um IDW dos resíduos corrige apenas células próximas a suporte medido,
com magnitude limitada; ele não extrapola o campo global nem cria confiança
fora da cobertura.
