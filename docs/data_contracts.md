# Contratos de dados

Os modelos Pydantic autoritativos estão em `src/ares_mapper/domain/models.py`.

## PoseSample

Contém tempo de origem, tempo de recebimento, linha do tempo, posição, quaternion,
velocidade, covariâncias, qualidade e, apenas no evento bruto de simulação, pose
verdadeira. A V0.3 também
preserva os campos do `SportModeState`: modo, marcha, altura, obstáculos, forças e
cinemática dos pés, além de giroscópio, acelerômetro e temperatura da IMU.

## RadiationSample

Contém DR, D, CPS, CPM, AVG, DT, S, W, início, fim e centro efetivo da janela,
latência, qualidade e payload bruto. A taxa de dose é a observação espacial
principal.

A dose acumulada continua fora do mapa de taxa de dose. Sua variação é usada
como auditoria e, somente quando há pacotes ausentes, como observação integral
fraca do intervalo não coberto.

## ObservationWindow

É a unidade estatística da inferência. Contém o `RadiationSample` sanitizado, a
trajetória observada do detector, pesos de quadratura, covariâncias, extrínseca,
limites de integração, erro de sincronização, modo de observação e origem da
evidência. Campos `true_*` são removidos antes deste contrato.

## MappedSample

Liga uma leitura à pose interpolada, informa posição da base e do detector, método
de sincronização, lacuna temporal, qualidade e flags. Também contém comprimento do
trecho atravessado, velocidade média, permanência e incerteza de pose durante a
janela.

## SourcePosterior

Contém probabilidade de fonte, posição média e MAP, intensidade, fundo, regiões
de credibilidade, ESS, entropia, estado de identificabilidade e diagnósticos do
modelo.

## FieldCell e MapPrediction

`FieldCell` descreve cada folha da quadtree, incluindo quantis, incerteza,
resíduo, cobertura, exposição, distância ao suporte e motivo do refinamento.
`MapPrediction` transporta a projeção raster para o navegador e mantém previsão,
cobertura e verdade simulada em camadas distintas.
