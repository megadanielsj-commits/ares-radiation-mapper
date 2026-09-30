# Fonte simulada no painel aprovado

Nesta demonstração, fonte, detector e robô são simulados. Não conecte dispositivos
físicos. O desenho, as cores e os controles do painel aprovado são preservados.
Usa o backend de simulação original da branch de integração e a imagem Docker
`ares-radiacode-go2:20260930-r5`, corrigida para renderizar a grade interpolada. A primeira execução a constrói
se ela ainda não existir no computador.

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

## Correção nesta versão

O painel agora recebe os eventos de grade e desenha o gradiente IDW local
produzido pelo mapa original do ARES, com posição e orientação corretas.
Cores cobrem a vizinhança amostrada; regiões não investigadas permanecem sem
valores. A dose acumulada vem da leitura simulada e um único caminho de
atualização evita alternância com valores ausentes.
