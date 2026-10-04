# Integração de hardware no console oficial

O ARES Console usa Radiacode por USB/libusb e Go2 por Wi-Fi/WebRTC. Os componentes
estão descritos em [ROTEIRO_ENSAIO_GO2.md](../ROTEIRO_ENSAIO_GO2.md), com as referências
do Werik, modos e critérios do ensaio. Execute `bash ares-console iniciar`.

A ligação do Go2 real segue o modo LocalAP, no computador conectado ao Wi-Fi do
robô. O Docker compartilha a rede do host. Configuração AES/firmware, offset do
detector e latência da taxa devem ser confirmados na montagem física.

O FS-5000 deve ser testado no projeto original da equipe, disponível na branch
[ares-wifi](https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/ares-wifi).
O cliente FS-5000 está preservado no runtime porque fornece o contrato comum;
não é uma entrada selecionável no console Radiacode. Os adaptadores SDK2/serial
em `src/ares_mapper` pertencem ao motor e à cobertura de compatibilidade.

Para libusb, permissões udev e coleta isolada, consulte
[LEIA_PRIMEIRO_USB.md](../LEIA_PRIMEIRO_USB.md). Para operar o Go2, encerre primeiro
outros controladores do mesmo robô e confira o roteiro de ensaio.
