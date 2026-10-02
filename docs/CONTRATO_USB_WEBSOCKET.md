# Contrato entre o módulo USB e a estrutura ARES

O detector é acessado por libusb e `radiacode==0.4.0`, em um processo exclusivo.
O serviço lê somente `counts_1s.jsonl` e publica no WebSocket local
`ws://127.0.0.1:1098/ws`. A aplicação ARES não recebe acesso ao USB.

| Evento | Campo | Semântica |
|---|---|---|
| `snapshot` | `dados` | Lista de dispositivos; formato do quickstart FS-5000 |
| `estado` | `dados.id`, `dados.estado` | Sessão USB; `conectado` exige contagem recente |
| `leitura` | `aparelho_id` | `radiacode:<serial>:<sessão>`; muda após reconexão |
| `leitura` | `dados.ts` | Recebimento do segundo bin, UTC Unix em segundos |
| `leitura` | `dados.cps` | Contagem inteira em exposição nominal de 1 s |
| `leitura` | `dados.cpm` | 60 × contagem; não é uma integração independente de 60 s |
| `leitura` | `dados.dr_usvh` | Taxa do canal bruto conhecido, em µSv/h; `null` se indisponível ou antiga; nunca derivada de CPS |
| `leitura` | `dados.dose_rate_received_utc_ns` | Timestamp próprio do recebimento da taxa; distinto do timestamp da contagem |
| `leitura` | `dados.dose_rate_age_s`, `dados.dose_unavailable_reason` | Idade da taxa e motivo de indisponibilidade |
| `leitura` | `dados.dose_rate_native_unit`, `dados.dose_rate_raw`, `dados.dose_rate_scale`, `dados.dose_rate_conversion_basis` | Unidade/valor brutos e identificação da conversão validada pelo contrato |
| `leitura` | `dados.dose_usv` | `null`, dose acumulada sem conversão validada |
| `leitura` | `dados.session_id`, `dados.sequence` | Deduplicação e identificação da sessão |

O serviço não recebe comandos para zerar dose, espectro, leitura ou alarmes.
O leitor pode ajustar o relógio na inicialização, conforme o comportamento
da biblioteca já documentado no kit USB.

Dois RawData consecutivos com separação de 0,4–0,6 s formam uma contagem de
1 s: `count_rate_1 / 2 + count_rate_2 / 2`. Cada parcela deve ser inteira,
finita e não negativa. Intervalos inválidos ou repetidos interrompem o par.
Esse formato foi conferido nos 7.200 registros da hora enviada pelo usuário.
A interpretação permanece específica aos registros desse detector/biblioteca;
os valores e tempos originais são conservados em `raw_records.jsonl`.

O tempo `dt` do registro do detector serve para continuidade dos bins, não
como relógio UTC absoluto de posicionamento. A aplicação mantém a regra do
Werik: posição interpolada em `dados.ts - ARES_LATENCIA_LEITURA_S`. O valor
inicial 0,5 s ainda requer validação física.

`counts_1s.jsonl` conserva `dose_rate_uSv_h` com sua precisão, metadados e
timestamps UTC/monotônico próprios da taxa. O serviço exige esses timestamps
recentes, canal bruto `R/h`, fator 10.000 e a identificação da convenção do SDK.
`get_alarm_limits().dose_unit` descreve o visor/alarmes, não substitui a unidade
bruta; `R` nesse campo sozinho não invalida a taxa. A comparação absoluta com o
visor segue como verificação do ensaio físico. A média interna da taxa pode
diferir da janela de contagens de 1 s.

No console atual, o mapa recebe `dr_usvh`; se faltar taxa, não recebe CPS nem
um zero inventado. Dose integrada da missão é calculada pelo console a partir
das taxas e dos intervalos válidos; não representa dose acumulada histórica do
detector. Os arquivos e mensagens conservam valores numéricos, sem formatação
por prefixo SI. A mudança de unidade ocorre somente nos rótulos da interface.

A publicação não espera consumidores: filas têm quatro eventos e descartam
os mais antigos quando cheias. Leituras mais antigas que 3 s, repetidas ou
marcadas `batched_uncertain` não chegam ao posicionamento. Um snapshot antes
da leitura informa a sessão atual mesmo se um evento de estado foi perdido.
O cliente ARES também confere a idade e a sequência.

Ao perder os dados atuais, o estado vira desconectado. O supervisor USB abre
uma sessão nova ao reconectar, com espera progressiva de 1–10 s. Todos os
registros duráveis da sessão anterior permanecem nos arquivos. Essa política
mantém a aquisição independente do controle e das poses do Go2.
