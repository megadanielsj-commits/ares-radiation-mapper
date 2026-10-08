# Atualização da base operacional — 08/10/2026

Esta atualização incorpora a versão com edição da escala do gradiente à branch
`release/ares-console-1.0.2`, para continuidade do desenvolvimento pela equipe
de robótica. O histórico anterior permanece no Git.

## Procedência e escopo

- Base publicada: `cdccfedae83e67c23d2a47cc9b5dae7e7ffa90b0`.
- Fonte oculta: `f480058cdb2051f7aab42a83d75a1e492c42db6e`.
- Escala editável, cadência e velocidade virtual:
  `954b5c4986f9f16435f7e7954b9b5250f9541410`.
- Referência Wi-Fi: `ares-wifi/84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`.

O merge conserva as atualizações recentes do README e os créditos da equipe.
O leitor/serviço USB, o motor `src/ares_mapper`, o runtime `vendor/go2_runtime`
e `config` permanecem iguais à base operacional anterior. A interpolação e a
paleta não mudaram. `tools/operator_console/runtime.py` conserva exatamente a
edição testada em 06/10: cadência sintética e velocidade virtual configuráveis,
sem modificar o transporte USB nem o controle do Go2 real.

## Recursos incorporados

- Escala automática original ou limites manuais para azul/vermelho em unidades de taxa.
- Atualização conjunta da grade, das medições anteriores e da barra de cores.
- Fonte simulada ativa, marcador inicialmente oculto e opção de revelá-lo.
- Leitura simulada nominal de 1 s, sem acelerar o relógio.
- Velocidade linear configurável do robô na simulação completa.
- Testes de controles de simulação incluídos no job do console no GitHub Actions.

O Compose usa `ares-operator-console:1.0.2-recording-v2`, imagem da edição do
gradiente. Os relatórios `recording_*20261006*` são históricos. A conferência
desta promoção está em `validation/gradient_release_20261008.json`.

## Estado físico conhecido

Segundo o relato de 08/10, o controle do Go2 e a operação com detector simulado
funcionaram. O Radiacode real apresentou falha ainda sem diagnóstico documentado
nesta base. A publicação atualiza a base de desenvolvimento; não corrige essa
falha. A implementação posterior do mapa por gaussianas feita pelo responsável
pela integração não foi fornecida nem incorporada neste merge.

## Publicar o pacote

O ZIP de publicação contém os fontes, o bundle e o iniciador. Baixar para Downloads:

```bash
python3 -m zipfile -e "$HOME/Downloads/ARES_Console_1.0.2_Gradiente_GITHUB.zip" "$HOME" &&
cd "$HOME/ARES_Console_1.0.2_Gradiente_GITHUB" &&
bash PUBLICAR_CONSOLE_GITHUB.sh
```

O iniciador clona a branch operacional, importa o bundle e exige avanço normal,
sem `--force`. Alterações novas incompatíveis no GitHub interrompem a atualização
para incorporação antes da publicação. `main`, `ares-wifi`, outras branches e
registros de campo permanecem fora dessa atualização. Autenticação é feita pelo
acesso GitHub já configurado no computador.

Após o push, conferir GitHub Actions e usar:
https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/release/ares-console-1.0.2

## Obter a base para desenvolvimento

```bash
git clone --branch release/ares-console-1.0.2 --single-branch \
  https://github.com/megadanielsj-commits/ares-radiation-mapper.git ares-radiation-mapper
cd ares-radiation-mapper
bash ares-console iniciar
```

Preparar a imagem com internet antes de entrar na rede local do Go2. A página
é `http://127.0.0.1:8001`; os registros ficam em `resultados/console` na pasta
de execução.
