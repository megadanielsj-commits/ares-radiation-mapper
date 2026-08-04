# Adaptador FS-5000

A V0.3 inclui parser e fonte serial somente leitura. O módulo:

1. localizar o CH341 por VID `0x1A86` e PID `0x7523`;
2. abrir a serial em `115200 baud`;
3. enviar somente o comando de leitura contínua `0x0E 0x01`;
4. registrar UTC e monotônico no recebimento;
5. converter o payload com `parse_payload`;
6. produz `RadiationSample`;
7. publica health e encerra a porta de forma segura.

Reconexão automática permanece desabilitada até que a política de retomada e a
continuidade da dose acumulada sejam validadas no equipamento.
