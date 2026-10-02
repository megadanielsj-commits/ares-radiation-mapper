"""`python -m ares [--modo simulacao|real] [--porta N] [--host H] [--permitir-rede]`."""
import argparse
import dataclasses
import sys

import uvicorn

from .config import MODOS_VALIDOS, Config
from .orquestrador import criar_orquestrador
from .servidor.app import criar_app

HOSTS_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _eh_loopback(host: str) -> bool:
    return host in HOSTS_LOOPBACK


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m ares", description="ARES: mapeamento de radiação")
    p.add_argument("--modo", choices=MODOS_VALIDOS)
    p.add_argument("--porta", type=int)
    p.add_argument("--host")
    p.add_argument(
        "--permitir-rede",
        action="store_true",
        help=(
            "permite ligar num endereço que não seja loopback "
            "(127.0.0.1/localhost/::1); ver aviso de segurança"
        ),
    )
    args = p.parse_args(argv)

    config = Config.de_ambiente()
    mudancas = {
        k: v for k, v in vars(args).items() if v is not None and k != "permitir_rede"
    }
    if mudancas:
        config = dataclasses.replace(config, **mudancas)

    if not _eh_loopback(config.host) and not args.permitir_rede:
        print(
            f"ERRO: --host {config.host!r} não é loopback (127.0.0.1/localhost/::1).\n"
            "O painel do ARES não tem autenticação e inclui teleop do robô: ligado\n"
            "num endereço alcançável pela rede, qualquer um nela poderia comandar o\n"
            "robô. Se isso for intencional (ex.: acessar de outro dispositivo numa\n"
            "rede confiável), rode de novo com --permitir-rede.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    orq = criar_orquestrador(config)
    app = criar_app(orq, orq.teleop)
    host = "localhost" if config.host in ("127.0.0.1", "0.0.0.0") else config.host
    print(f"ARES em http://{host}:{config.porta}  (modo={config.modo})", flush=True)
    uvicorn.run(app, host=config.host, port=config.porta, log_level="warning")


if __name__ == "__main__":
    main()
