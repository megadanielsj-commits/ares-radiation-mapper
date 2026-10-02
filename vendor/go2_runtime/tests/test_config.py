"""Testes da configuração (defaults, leitura de ambiente, validação)."""
import pytest

from ares.config import Config


def test_config_defaults():
    cfg = Config()

    assert cfg.modo == "simulacao"
    assert cfg.host == "127.0.0.1"
    assert cfg.porta == 8000
    assert cfg.dados == "dados"
    assert cfg.fs5000_url == "ws://127.0.0.1:1096/ws"
    assert cfg.fs5000_aparelho is None
    assert cfg.go2_aes_key is None
    assert cfg.offset_detector == (0.0, 0.0)
    assert cfg.latencia_leitura_s == 0.5
    assert cfg.lacuna_pose_max_s == 0.5
    assert cfg.lado_area_m == 20.0
    assert cfg.resolucao_estimador_m == 0.5
    assert cfg.resolucao_mapa_m == 0.5
    assert cfg.altura_fonte_m == 0.25
    assert cfg.vx_max == 0.5
    assert cfg.vy_max == 0.3
    assert cfg.vyaw_max == 1.0
    assert cfg.watchdog_s == 0.5
    assert cfg.cps_por_usvh == 2.6
    assert cfg.exposicao_s == 1.0


def test_config_de_ambiente_le_variaveis():
    env = {
        "ARES_MODO": "real",
        "ARES_HOST": "0.0.0.0",
        "ARES_PORTA": "9000",
        "ARES_DADOS": "outro_dir",
        "FS5000_URL": "ws://127.0.0.1:1234/ws",
        "FS5000_APARELHO": "fs5000-2",
        "GO2_AES_KEY": "chave-secreta",
        "ARES_OFFSET_DETECTOR": "0.1,-0.2",
    }

    cfg = Config.de_ambiente(env=env)

    assert cfg.modo == "real"
    assert cfg.host == "0.0.0.0"
    assert cfg.porta == 9000
    assert cfg.dados == "outro_dir"
    assert cfg.fs5000_url == "ws://127.0.0.1:1234/ws"
    assert cfg.fs5000_aparelho == "fs5000-2"
    assert cfg.go2_aes_key == "chave-secreta"
    assert cfg.offset_detector == (0.1, -0.2)


def test_config_de_ambiente_vazio_usa_defaults():
    cfg = Config.de_ambiente(env={})

    assert cfg.modo == "simulacao"
    assert cfg.offset_detector == (0.0, 0.0)


def test_config_modo_invalido_levanta_valueerror():
    with pytest.raises(ValueError):
        Config(modo="invalido")

    with pytest.raises(ValueError):
        Config.de_ambiente(env={"ARES_MODO": "invalido"})


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("porta", 0),
        ("porta", -1),
        ("lado_area_m", 0.0),
        ("resolucao_estimador_m", -0.1),
        ("resolucao_mapa_m", 0.0),
        ("cps_por_usvh", 0.0),
        ("cps_por_usvh", -2.6),
        ("exposicao_s", 0.0),
        ("exposicao_s", -1.0),
        ("vx_max", 0.0),
        ("vy_max", -0.5),
        ("vyaw_max", 0.0),
        ("watchdog_s", 0.0),
        ("latencia_leitura_s", -0.1),
        ("lacuna_pose_max_s", 0.0),
    ],
)
def test_config_valores_nao_positivos_levantam_valueerror(campo, valor):
    with pytest.raises(ValueError):
        Config(**{campo: valor})


def test_config_offset_detector_parseado_do_ambiente():
    cfg = Config.de_ambiente(env={"ARES_OFFSET_DETECTOR": "1.5,2.5"})

    assert cfg.offset_detector == (1.5, 2.5)
