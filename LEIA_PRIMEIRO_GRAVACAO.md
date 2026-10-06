# ARES — gravação com fonte simulada oculta

Esta edição parte do Console 1.0.2 consolidado. A fonte continua ativa no
simulador, mas sua marcação e a legenda "Fonte configurada" começam ocultas.
O mapa inicia sem medições e é construído pelo movimento e pelas leituras, com
o mesmo gradiente, paleta, interpolação e correção de permanência aprovados.
Os rótulos de simulação continuam visíveis para identificar a demonstração.

## Iniciar

Salve `ARES_Console_1.0.2_Gravacao.zip` em Downloads e copie:

```bash
python3 -m zipfile -e "$HOME/Downloads/ARES_Console_1.0.2_Gravacao.zip" "$HOME" &&
cd "$HOME/ARES_Console_1.0.2_Gravacao" &&
bash ares-console iniciar
```

Abra **http://127.0.0.1:8001**. A imagem Docker desta edição tem a identificação
`ares-operator-console:1.0.2-recording` e será construída na primeira execução,
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

## Encerrar o programa

```bash
cd "$HOME/ARES_Console_1.0.2_Gravacao" && bash ares-console parar
```

Os registros desta edição ficam em `resultados/console` dentro da pasta de gravação.
A edição é separada do pacote preparado para o ensaio com o Go2. Para retornar ao
console oficial, pare esta edição e execute o iniciador na pasta oficial.
Não use o script de publicação da release para publicar esta edição de gravação.

## Alteração e verificação

Somente a camada da interface controla a visibilidade do marcador original.
Os 56 arquivos protegidos, todos os módulos de aquisição/runtime e o mapa
original foram preservados. As verificações desta edição estão em
`validation/recording_20261006.json` e no XML da regressão do console.
