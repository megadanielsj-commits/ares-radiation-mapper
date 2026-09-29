"""`python -m ares [--modo simulacao|real] [--porta N] [--host H]`."""
import argparse
import dataclasses

import uvicorn

from .config import MODOS_VALIDOS, Config
from .orquestrador import criar_orquestrador
from .servidor.app import criar_app


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m ares", description="ARES: mapeamento de radiação")
    p.add_argument("--modo", choices=MODOS_VALIDOS)
    p.add_argument("--porta", type=int)
    p.add_argument("--host")
    args = p.parse_args(argv)

    config = Config.de_ambiente()
    mudancas = {k: v for k, v in vars(args).items() if v is not None}
    if mudancas:
        config = dataclasses.replace(config, **mudancas)

    orq = criar_orquestrador(config)
    app = criar_app(orq, orq.teleop)
    host = "localhost" if config.host in ("127.0.0.1", "0.0.0.0") else config.host
    print(f"ARES em http://{host}:{config.porta}  (modo={config.modo})", flush=True)
    uvicorn.run(app, host=config.host, port=config.porta, log_level="warning")


if __name__ == "__main__":
    main()
