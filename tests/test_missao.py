import csv
import io
import threading

import pytest

from ares.missao import RepositorioMissoes
from ares.modelos import Amostra, Leitura, Pose


@pytest.fixture
def repo(tmp_path):
    r = RepositorioMissoes(tmp_path / "dados")
    yield r
    r.fechar()


def _amostra(ts, x=1.0, y=2.0, cps=3):
    return Amostra(ts=ts, x=x, y=y, dr_usvh=0.2, cpm=30, cps=cps, lacuna_pose_s=0.05)


def test_cria_banco_em_wal(tmp_path):
    r = RepositorioMissoes(tmp_path / "d")
    try:
        assert (tmp_path / "d" / "ares.db").exists()
        assert r._con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        r.fechar()


def test_criar_obter_listar_encerrar(repo):
    id1 = repo.criar("m1", "simulacao", (1.5, -2.0), fonte_sim={"x": 4, "y": 3, "s": 2})
    id2 = repo.criar(None, "real", (0.0, 0.0))
    assert id1 != id2

    m = repo.obter(id1)
    assert m["nome"] == "m1" and m["modo"] == "simulacao"
    assert (m["centro_x"], m["centro_y"]) == (1.5, -2.0)
    assert m["fonte_sim"] == {"x": 4, "y": 3, "s": 2}
    assert m["encerrada"] is None and m["resultado"] is None
    assert m["iniciada"] > 0

    repo.encerrar(id1, {"p_fonte": 0.9, "x_map": 4.0})
    m = repo.obter(id1)
    assert m["encerrada"] >= m["iniciada"]
    assert m["resultado"] == {"p_fonte": 0.9, "x_map": 4.0}

    lista = repo.listar()
    assert [x["id"] for x in lista] == [id2, id1]  # mais recente primeiro
    assert lista[1]["n_amostras"] == 0
    assert "resultado" not in lista[0]
    assert repo.obter(9999) is None


def test_poses_limitadas_a_5hz(repo):
    mid = repo.criar("m", "simulacao", (0, 0))
    for i in range(50):  # 50 poses em 1 s (50 Hz)
        repo.registrar_pose(mid, Pose(ts=100.0 + i * 0.02, x=i, y=0, yaw=0))
    n = repo._con.execute("SELECT COUNT(*) FROM poses WHERE missao_id=?", (mid,)).fetchone()[0]
    assert n == 5
    # o limite é por missão
    outra = repo.criar("n", "simulacao", (0, 0))
    repo.registrar_pose(outra, Pose(ts=100.0, x=0, y=0, yaw=0))
    n2 = repo._con.execute("SELECT COUNT(*) FROM poses WHERE missao_id=?", (outra,)).fetchone()[0]
    assert n2 == 1


def test_leituras_e_amostras_e_exportacao(repo):
    mid = repo.criar("m", "simulacao", (0, 0))
    repo.registrar_leitura(mid, Leitura(ts=10.0, dr_usvh=0.2, cpm=30, cps=1, dose_usv=0.5, detector_id="d1"))
    repo.registrar_amostra(mid, _amostra(10.0, x=1.0, cps=4))
    repo.registrar_amostra(mid, _amostra(11.0, x=2.0, cps=0))
    n = repo._con.execute("SELECT COUNT(*) FROM leituras WHERE missao_id=?", (mid,)).fetchone()[0]
    assert n == 1
    assert repo.obter(mid)["n_amostras"] == 2

    texto = repo.exportar_csv(mid)
    linhas = list(csv.DictReader(io.StringIO(texto)))
    assert [float(l["x"]) for l in linhas] == [1.0, 2.0]
    assert [int(l["cps"]) for l in linhas] == [4, 0]
    assert set(linhas[0]) == {"ts", "x", "y", "dr_usvh", "cpm", "cps", "lacuna_pose_s"}

    repo.encerrar(mid, {"p_fonte": None})
    j = repo.exportar_json(mid)
    assert j["missao"]["id"] == mid
    assert len(j["amostras"]) == 2 and j["amostras"][0]["cps"] == 4
    assert j["resultado"] == {"p_fonte": None}


def test_exportar_missao_inexistente(repo):
    with pytest.raises(KeyError):
        repo.exportar_csv(42)
    with pytest.raises(KeyError):
        repo.exportar_json(42)


def test_gravacao_de_varias_threads(repo):
    mid = repo.criar("m", "simulacao", (0, 0))

    def gravar(k):
        for i in range(50):
            repo.registrar_amostra(mid, _amostra(k * 1000 + i))

    ts = [threading.Thread(target=gravar, args=(k,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert repo.obter(mid)["n_amostras"] == 200


def test_persiste_entre_aberturas(tmp_path):
    r = RepositorioMissoes(tmp_path)
    mid = r.criar("m", "real", (0, 0))
    r.registrar_amostra(mid, _amostra(1.0))
    r.fechar()
    r2 = RepositorioMissoes(tmp_path)
    try:
        assert r2.obter(mid)["n_amostras"] == 1
    finally:
        r2.fechar()
