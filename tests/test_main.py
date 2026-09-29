"""Testes do `python -m ares` (CLI): a recusa de ligar num host não loopback
sem `--permitir-rede` (segurança: o painel expõe teleop do robô sem
autenticação nenhuma)."""
import pytest

import ares.__main__ as main_mod


@pytest.fixture(autouse=True)
def _sem_env_sensivel(monkeypatch):
    # isola de qualquer ARES_HOST/ARES_MODO já no ambiente de quem roda os testes
    for chave in ("ARES_HOST", "ARES_MODO", "ARES_PORTA"):
        monkeypatch.delenv(chave, raising=False)


def _uvicorn_run_falso(chamadas):
    def _run(app, host, port, log_level):
        chamadas["host"] = host
        chamadas["port"] = port

    return _run


def test_host_nao_loopback_recusado_sem_permitir_rede(capsys):
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["--host", "0.0.0.0"])
    assert exc.value.code != 0
    saida = capsys.readouterr().err
    assert "loopback" in saida.lower()
    assert "permitir-rede" in saida


def test_host_nao_loopback_recusado_endereco_de_rede(capsys):
    with pytest.raises(SystemExit):
        main_mod.main(["--host", "192.168.12.5"])
    assert "loopback" in capsys.readouterr().err.lower()


def test_host_nao_loopback_aceito_com_permitir_rede(monkeypatch, tmp_path):
    monkeypatch.setenv("ARES_DADOS", str(tmp_path / "dados"))
    chamadas = {}
    monkeypatch.setattr(main_mod.uvicorn, "run", _uvicorn_run_falso(chamadas))
    main_mod.main(["--host", "0.0.0.0", "--permitir-rede"])
    assert chamadas["host"] == "0.0.0.0"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_host_loopback_nao_precisa_de_permitir_rede(monkeypatch, tmp_path, host):
    monkeypatch.setenv("ARES_DADOS", str(tmp_path / "dados"))
    chamadas = {}
    monkeypatch.setattr(main_mod.uvicorn, "run", _uvicorn_run_falso(chamadas))
    main_mod.main(["--host", host])
    assert chamadas["host"] == host


def test_sem_flag_de_host_usa_padrao_loopback(monkeypatch, tmp_path):
    monkeypatch.setenv("ARES_DADOS", str(tmp_path / "dados"))
    chamadas = {}
    monkeypatch.setattr(main_mod.uvicorn, "run", _uvicorn_run_falso(chamadas))
    main_mod.main([])
    assert chamadas["host"] == "127.0.0.1"
