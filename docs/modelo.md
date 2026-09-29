# Modelo físico e estimador

## 1. Evidência do aparelho real

Antes de desenhar qualquer estimador é preciso saber que tipo de ruído o
FS-5000 realmente produz. Em ~2 h de dados reais do aparelho (7411 leituras
de 1 s, fundo ambiente ~0,17 µSv/h):

| grandeza | comportamento medido |
|---|---|
| `CPS` (contagem por segundo) | Poisson: variância/média = **1,03**; independente entre segundos (autocorrelação no passo 1 = **0,02**) |
| `DR` (taxa exibida pelo aparelho) | média móvel de ~30 s: autocorrelação no passo 1 = **0,99**, cai a ~0 só no passo 30 |
| calibração | **k = 2,61 cps por µSv/h** (contagens por segundo por unidade de taxa) |

Duas consequências diretas:

1. **A observação estatística correta é o CPS**, não o DR. O DR já é uma
   média móvel — tratá-lo como amostra independente subestimaria a
   incerteza por um fator de dezenas (autocorrelação praticamente 1). O DR
   só é usado para exibição no painel ("Leitura agora").
2. Poisson quase perfeito (var/média ≈ 1) e autocorrelação ≈ 0 no CPS
   justificam a verossimilhança de Poisson por segundo, com segundos
   tratados como amostras independentes — exatamente a hipótese do
   estimador abaixo.

`k = 2,61` medido vira o parâmetro configurável `cps_por_usvh` (padrão
`2,6`, arredondado).

## 2. Modelo físico

Pose do robô no referencial de odometria (`odom`): `(x, y, yaw)`. O
detector está montado no robô com um offset `(dx, dy)` no referencial do
robô (padrão `(0, 0)`), então sua posição no mundo é a pose composta com
esse offset.

Campo de uma fonte pontual estática em `(xf, yf)`, intensidade `S` (µSv/h a
1 m), com o detector a uma altura relativa `h` (padrão 0,25 m) acima do
plano da fonte:

```
r² = (x_det − xf)² + (y_det − yf)²
g  = 1 / (r² + h²)                     # ganho geométrico
μ  = b + S·g                            # taxa esperada no detector, µSv/h
```

`b` é o fundo (µSv/h), assumido uniforme na área da missão. A contagem do
segundo é Poisson:

```
c ~ Poisson(k · T · μ)          k = cps_por_usvh,  T = exposicao_s (1 s)
```

O CPS de uma leitura cobre o **segundo anterior** à sua chegada no serviço
(o firmware soma e só então manda o frame), então o instante efetivo de cada
amostra é `ts − latencia_leitura_s` (padrão 0,5 s) — é essa pose, não a da
chegada, que entra no cálculo de `g`.

## 3. Estimador bayesiano em grade

### Espaço de hipóteses

- **Área**: quadrado de lado `L` (padrão 20 m) centrado na pose do robô ao
  iniciar a missão; resolução 0,5 m → grade 40×40 células.
- **H1 (existe fonte)**: célula `(ix, iy)` × `S` (40 valores log-espaçados
  em `[0,01; 1000]` µSv/h @ 1 m) × `b` (64 valores log-espaçados em
  `[0,01; 2,0]` µSv/h). Prior uniforme em cada grade.
- **H0 (só fundo)**: apenas `b`, mesma grade de 64 valores, prior uniforme.

### Log-verossimilhança

Descartando constantes que aparecem igualmente em H0 e H1 (o `log(c!)` de
cada Poisson):

```
log L1(célula, S, b) = Σᵢ cᵢ·log(b + S·gᵢ) − k·T·(b·n + S·Σᵢ gᵢ)
log L0(b)             = (Σᵢ cᵢ)·log(b)     − k·T·b·n
```

onde a soma é sobre todas as amostras `i` já observadas na missão, `n` é o
número de amostras e `gᵢ` o ganho geométrico daquela amostra até a célula.

**Acumulação incremental**: a cada nova amostra, o termo linear
(`b·n + S·Σgᵢ`) atualiza estatísticas suficientes por célula (`n`, `Σg`);
o termo `c·log(μ)` só é somado ao array `(células, S, b)` quando `c > 0`
(quando `c = 0` ele é nulo) — por isso `atualizar()` é ~30× mais rápido
sem contagem (`< 2 ms`) do que com contagem (`< 60 ms`).

### P(fonte) e hipóteses detectáveis

`P(fonte)` é a razão de evidências (média da verossimilhança em cada grade
de hipóteses, com prior 0,5 entre H0 e H1), mas **H1 só soma as hipóteses
que o percurso já feito seria capaz de distinguir de um fundo constante** —
o critério depende só das posições visitadas e da hipótese, nunca das
contagens observadas:

1. **excesso esperado de contagens**: `k·T·S·Σᵢ gᵢ ≥ contagens_min_detectaveis`
   (padrão 5) — o sinal precisa somar contagens suficientes para não se
   perder no ruído Poisson do fundo;
2. **contraste espacial ao longo do percurso**: `k·T·S²·Σᵢ(gᵢ − ḡ)²/b ≥
   desvio_min_detectavel` (padrão 9, ≈3σ na aproximação de sinal fraco) — sem
   isso, uma fonte distante vista só num trecho curto do percurso soma um
   valor quase constante em todas as amostras e se confunde com um fundo
   `b` um pouco maior; o primeiro critério sozinho não pega esse caso.

Sem essa restrição, células nunca visitadas e fontes fracas ou distantes —
que os dados não conseguem separar de H0 — puxam `P(fonte)` para um piso
artificial (≈ 0,2–0,3 só de fundo com cobertura parcial da área). Isso
condiciona a estimativa **no percurso**, não nos dados: um percurso maior
habilita mais hipóteses de (célula, S) como candidatas, mas quais delas são
favorecidas continua vindo só da verossimilhança dos dados observados.

Sem nenhuma hipótese detectável (ex.: 1–2 amostras, ou percurso todo muito
perto do ponto de partida), `p_fonte = None` — "cobertura insuficiente" no
painel, para não sugerir uma confiança que os dados não sustentam.

A posição estimada (marginal de `(x,y)`, moda, média, região de 95%) e o MAP
conjunto `(S, b)` usam a posterior de H1 restrita às hipóteses detectáveis
quando há alguma; senão, caem para a grade toda (sem essa restrição, só para
não ficar sem saída nenhuma).

### Saídas

`n`, `rejeitadas` (amostras descartadas: não finitas, `|x|` ou `|y| > 10⁴ m`,
ou `cps` fora de `[0, 10⁶]`), `p_fonte`, `x_map`/`y_map` (moda da marginal),
`s_map`/`b_map` (MAP conjunto), `x_media`/`y_media`/`desvio_m`,
`regiao95 {x0, y0, res, nx, ny, mascara}`, `marginal` (grade de densidade),
e os alertas:

- `s_no_limite` — MAP de S no limite inferior ou superior da grade log (o
  valor real pode estar fora do intervalo `[0,01; 1000]`);
- `b_no_limite` — idem para o MAP de b;
- `fonte_na_borda` — a moda da posição está na borda da área 20×20 m (a
  fonte real pode estar fora da área coberta).

Saída sempre em JSON válido, sem `NaN`/`Infinity`. Chamadas ao estimador são
serializadas por um lock interno; o orquestrador as executa numa thread para
não bloquear o event loop com o cálculo em NumPy.

### Limitação: região de 95% é condicional ao modelo

A região de 95% assume fonte pontual estática e pose/tempo exatos. Erros de
odometria do Go2 (deriva acumulada sem SLAM) e de sincronização pose×leitura
tornam essa região **otimista** — o intervalo real de incerteza é maior do
que o reportado. Ver também a seção de limitações do
[`README`](../README.md#9-limitações).

## 4. Mapa medido (para exibição, não para a estimativa)

Grade independente do estimador, resolução 0,5 m: cada célula acumula
`Σcps` e `n`; a taxa exibida é `Σcps / (k·T·n)` — sem o atraso da média
móvel do DR, direto do CPS bruto. Células nunca visitadas ficam vazias; a
interpolação IDW (potência 2) só preenche até 1,5 m de alguma célula
medida, sem extrapolar para áreas nunca visitadas. Ver
[`mapa.py`](../src/ares/mapa.py).
