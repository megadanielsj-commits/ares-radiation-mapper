# Fonte simulada no painel aprovado

Nesta demonstração, fonte, detector e robô são simulados. Não conecte dispositivos
físicos. O desenho, as cores e os controles do painel aprovado são preservados.
Usa o backend de simulação original da branch de integração e a imagem Docker
`ares-radiacode-go2:20260930-r5`, já usada na versão anterior; a apresentação do campo é atualizada pelo volume da demonstração. A primeira execução só a constrói se ela ainda não existir no computador.

Antes de trocar de modo, encerre a missão e execute `bash ensaio parar` na pasta
`ARES_Radiacode_GO2_USB_v4`. Isso preserva e exporta os dados do teste USB.

Na pasta deste pacote:

```bash
bash simulacao iniciar
```

Abra http://127.0.0.1:8001. A fonte começa em x=4 m, y=3 m; intensidade S=8
µSv·m²/h. O robô começa na origem. Clique em **Iniciar missão**, mova-o pelas
setas e observe a variação das contagens e as cores das posições percorridas.
Setas para cima/baixo avançam/recuam; esquerda/direita giram.

Abra **Configurar fonte simulada** para mudar X, Y e intensidade com **Aplicar fonte**, antes da missão. Para mudar
durante um ensaio, encerre a missão e comece outra, preservando os dados anteriores.
A fonte é marcada no mapa como referência
conhecida da simulação; essa marca não representa uma localização estimada.

O modelo é fundo + S/(r²+h²), com fundo 0,15 µSv/h, h=0,25 m e contagens Poisson
de 1 segundo. A sensibilidade sintética de 80 CPS/(µSv/h) serve à demonstração e
não é uma calibração do Radiacode. A taxa exibida tem média móvel de 30 segundos;
CPS reage mais rapidamente. A dose acumulada também é inteiramente simulada.

Encerre pelo botão **Encerrar missão e salvar** para baixar CSV/JSON pelo painel.
Para parar os serviços e exportar as missões no computador:

```bash
bash simulacao parar
```

Resultados em `resultados/fonte-simulada/`. Fechar o navegador não para a simulação;
ela continua até o comando de parada. Este modo usa apenas a porta 8001, não abre
USB, não inicia o serviço da porta 1098 e não conecta ao Go2 físico.

Para voltar ao ensaio USB, pare esta simulação e execute o comando habitual na
pasta `ARES_Radiacode_GO2_USB_v4`: `bash ensaio usb-simulado` ou, com o robô real,
`bash ensaio usb-robo`.

## Campo completo e escala coerente — v3

A borda recortada da versão anterior vinha do mapa IDW local limitado a 1,5 m.
Nesta demonstração o fundo do mapa passa a ser um campo contínuo estimado em
cada ponto da área visível. Os parâmetros vêm do estimador bayesiano original
alimentado pelas leituras sincronizadas; a posição e a intensidade configuradas
no formulário não são usadas para desenhar antecipadamente um campo verdadeiro.
A marca FONTE continua sendo apenas a referência conhecida da simulação.

A apresentação usa uma aproximação do campo com os parâmetros estimados de
posição, intensidade e fundo do modelo pontual. A contribuição da fonte é
ponderada por sua probabilidade estimada. É um campo previsto, não uma alegação
de que todos os pontos do espaço foram medidos. A interface identifica o campo
como estimado e sinaliza levantamento parcial quando o modelo tem limites ativos
ou ainda não consegue distinguir fonte de fundo.

A legenda, os pontos e a superfície usam uma escala comum de CPS em cada quadro.
Se surge um máximo novo, todas as cores são recalculadas e o raster anterior é
invalidado; os valores e timestamps das medições antigas não são modificados.
O máximo medido da missão é mantido mesmo quando o limite de pontos visíveis
remove os pontos mais antigos da memória gráfica. Uma nova missão reinicia a
escala. A previsão do modelo também entra nos limites exibidos na legenda.

A dose acumulada segue vindo da leitura simulada. Os controles, a API e a
exportação de leituras permanecem os da versão validada.

Validação: três testes Python da demonstração, nove testes JavaScript incluindo
os seis compartilhados do painel, e renderização real do canvas com 96 amostras
sintéticas processadas pelo estimador original. O teste de recoloração confirmou
que 100 CPS muda de vermelho quando o máximo passa a 10.000 CPS e que o valor
armazenado continua sendo 100 CPS.
