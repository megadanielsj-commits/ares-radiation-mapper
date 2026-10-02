# ARES Console 1.0.0 — publicação e ensaio de 08/10/2026

Esta é a versão de referência do console aprovado. O mapa usa taxa de dose em
mSv/h nos quatro modos. O canal USB permanece independente do robô e conserva
contagens, taxa reportada, espectros disponíveis e timestamps em seus arquivos.
O teste conjunto com Go2 físico ainda precisa ser realizado: os testes de
software não validam o rádio, a montagem ou a resposta temporal do detector.

## Preparar no computador do teste, com internet

Use Linux e o Docker Engine/Compose já utilizados nos ensaios anteriores.
Extraia `ARES_Console_Oficial_1.0.0.zip`. Na pasta extraída:

```bash
bash ares-console iniciar
```

Abra http://127.0.0.1:8001. O iniciador constrói a imagem `ares-operator-console:1.0.0`
se ela ainda não existir, espera o servidor ficar saudável e preserva dados do
console anterior ao encerrá-lo. Faça isso **antes** de conectar ao Wi-Fi do Go2,
que pode não oferecer internet. O modo inicial é Simulação completa.

1. Em **Fonte simulada**, aplique X/Y e taxa de dose a 1 m; inicie o mapeamento.
2. Percorra uma trajetória por teclado, pare, encerre e baixe os dados.
3. Conecte o Radiacode por cabo USB de dados; feche os leitores anteriores.
4. Selecione **Robô simulado**. Espere USB online e taxa de dose disponível.
5. Confira o visor do aparelho configurado em Sv contra a taxa do painel.
   A legenda do mapa usa mSv/h; 0,12 µSv/h equivale a `1,20E-4 mSv/h`.
   A conversão do valor bruto do SDK permanece provisória até essa comparação.
6. Inicie, percorra a trajetória, encerre, baixe o ZIP e verifique CPS e `dr_usvh`
   separados em `amostras.csv`. Não interprete as coordenadas virtuais como
   posição física do detector.
7. Pare o sistema para liberar o USB e as portas:

```bash
bash ares-console parar
```

Os resultados ficam em `resultados/console` dentro da pasta deste pacote.
Fechar a página não encerra a aquisição; use o botão de encerramento e o comando
acima. O leitor USB segue registrando entre missões enquanto seu modo está ativo.
Permissões USB continuam sendo as já configuradas; o contêiner não é privilegiado.

Leve este pacote e use o mesmo computador com a imagem já construída. Se for
necessário transferir para outro computador Linux compatível com a arquitetura
da imagem, exporte-a antes, ainda no computador preparado:

```bash
docker save ares-operator-console:1.0.0 | gzip > ARES_Console_1.0.0_imagem.tar.gz
```

No outro computador, com Docker instalado e o pacote extraído:

```bash
gunzip -c ARES_Console_1.0.0_imagem.tar.gz | docker load
bash ares-console iniciar
```

## Publicar no GitHub

Na pasta do pacote, execute:

```bash
bash PUBLICAR_CONSOLE_GITHUB.sh
```

O script cria um checkout separado, importa o bundle e publica
`release/ares-console-1.0.0`. Usa sua autenticação Git já existente e não faz
force push, não modifica `ares-wifi` e não envia registros de campo.

Link para a equipe:
https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/release/ares-console-1.0.0

Verifique os checks de **Actions** dessa branch. O CI executa testes em Python
3.10/3.12, regressões do mapa, lint, tipos e construção/inicialização da imagem.
Depois abra:
https://github.com/megadanielsj-commits/ares-radiation-mapper/compare/main...release/ares-console-1.0.0?expand=1

Título sugerido: `ARES Console 1.0.0: Radiacode independente e mapa em taxa de dose`.
Descrição sugerida:

> Consolida o console aprovado com quatro combinações de entradas, mantendo o
> runtime Go2/Wi-Fi, o sincronizador e a aquisição independente. O mapa usa a taxa
> de dose reportada do Radiacode e apresenta mSv/h, conservando CPS/CPM e dados
> brutos. Inclui Docker, verificações e roteiro do ensaio de 08/10/2026. A integração
> física conjunta com o Go2 será validada no ensaio; latência e offset continuam
> parâmetros de campo.

Após revisão e checks verdes, o merge torna essa versão visível na branch
principal. Até lá, a equipe deve usar o link da branch de release, pois a página
inicial do repositório ainda mostra `main`. Publicar não comprova teste de hardware.

## No dia: manter a sequência do trabalho de integração

Primeiro valide o FS-5000 na estrutura existente. Antes de trocar para este
console, encerre o processo que controla o Go2 e qualquer outra sessão WebRTC
do mesmo robô. O serviço FS-5000 e sua implementação permanecem preservados.

1. Coloque o Go2 pronto para caminhar pelo controle oficial, com área de teste
   definida pela equipe. Este console não acrescenta controles de postura.
2. Conecte o computador ao Wi-Fi LocalAP do robô; feche aplicativos que mantenham
   outra sessão WebRTC. Confirme a rede:

```bash
ping -c 2 192.168.12.1
```

3. Inicie o console com `bash ares-console iniciar`. Em **Detector simulado**,
   confirme posição real online, configure uma fonte no referencial local `odom`
   mostrado no painel e faça uma missão curta. Habilite o teclado com a confirmação
   do robô real, teste movimento breve, liberação da tecla e **Parar movimento**.
4. Encerre e salve. Conecte o Radiacode no computador e selecione **Equipamentos
   reais**. Espere pose real e USB online, com taxa disponível e coerente com o visor.
5. Faça primeiro uma missão de 10 minutos, com deslocamento, parada, retorno a uma
   posição conhecida e exportação. Compare `ts`, X/Y, CPS e `dr_usvh` nos registros;
   a associação usa `timestamp_da_leitura - latencia_leitura_s`, como no runtime
   de referência. Registre se o atraso cresce ou permanece estável.
6. Confira a posição física de montagem e a resposta temporal da **taxa de dose**.
   Ela pode ter média interna diferente das contagens brutas. Os padrões 0,5 s e
   offset 0,0 são valores iniciais, não calibração verificada do Radiacode no Go2.
   A equipe pode ajustar os parâmetros existentes após medir essas diferenças:

```bash
bash ares-console parar
ARES_LATENCIA_LEITURA_S=0.5 ARES_OFFSET_DETECTOR=0,0 bash ares-console iniciar
```

O offset é X/Y em metros no referencial do robô, aplicado pelo sincronizador
existente. A latência não elimina a média interna do detector. Só avance para o
ensaio prolongado depois de verificar resposta, parada, sincronização e exportação.

O estudo de referência documenta firmware Go2 até 1.1.14 sem chave AES; a partir
de 1.1.15 pode exigir `GO2_AES_KEY`, caminho ainda não validado nele. Confirme com
a equipe a versão do robô antes do ensaio. Se houver chave válida, forneça-a pelo
ambiente local já previsto; não a grave no repositório.

## Diagnóstico e critérios de aceitação

Se o painel não abrir ou um componente não conectar:

```bash
bash ares-console verificar
sudo ss -ltnp '( sport = :8001 or sport = :1098 )'
lsusb
```

Pare o leitor antigo pelo iniciador dele se 1098 estiver ocupada. Não execute
dois leitores USB simultâneos. Taxa indisponível com CPS presente pode indicar
configuração de unidade desconhecida/R ou taxa antiga; consulte os logs e
`session.json` da aquisição, confira Sv no aparelho e reinicie a sessão.

Aceite o ensaio quando os equipamentos reais fornecem pose e taxa recente,
os dados são posicionados sem atraso progressivo, movimento/parada funcionam,
a unidade confere com o visor e os arquivos exportados preservam contagens,
dose, timestamps e posições. O mapa estima um campo a partir das amostras e do
modelo aprovado; a comparação com medições de referência é parte do ensaio.
Guarde o ZIP exportado e toda a pasta `resultados/console`, incluindo banco,
registros USB, `session.json` e diagnósticos. Quedas não devem gerar dose fictícia
nem reprocessar histórico antigo como medição atual.
