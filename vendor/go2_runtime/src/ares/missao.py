"""Missões gravadas em SQLite (`<pasta_dados>/ares.db`) com exportação CSV/JSON.

Uma conexão única (WAL) protegida por lock: as gravações vêm do event loop e
as consultas podem vir de threads (rotas síncronas do servidor). Poses são
gravadas no máximo a 5 Hz por missão (pelo `ts` da pose).
"""
import csv
import io
import json
import pathlib
import sqlite3
import threading
import time
from typing import Optional, Tuple

from .modelos import Amostra, Leitura, Pose

INTERVALO_MIN_POSE_S = 0.2  # 5 Hz

COLUNAS_AMOSTRA = ("ts", "x", "y", "dr_usvh", "cpm", "cps", "lacuna_pose_s")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS missoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT,
    modo TEXT NOT NULL,
    iniciada REAL NOT NULL,
    encerrada REAL,
    centro_x REAL NOT NULL,
    centro_y REAL NOT NULL,
    fonte_sim_json TEXT,
    resultado_json TEXT
);
CREATE TABLE IF NOT EXISTS poses (
    missao_id INTEGER NOT NULL, ts REAL, x REAL, y REAL, yaw REAL
);
CREATE TABLE IF NOT EXISTS leituras (
    missao_id INTEGER NOT NULL, ts REAL, dr_usvh REAL, cpm INTEGER, cps INTEGER,
    dose_usv REAL, detector_id TEXT
);
CREATE TABLE IF NOT EXISTS amostras (
    missao_id INTEGER NOT NULL, ts REAL, x REAL, y REAL, dr_usvh REAL, cpm INTEGER,
    cps INTEGER, lacuna_pose_s REAL
);
CREATE INDEX IF NOT EXISTS idx_poses ON poses(missao_id, ts);
CREATE INDEX IF NOT EXISTS idx_leituras ON leituras(missao_id, ts);
CREATE INDEX IF NOT EXISTS idx_amostras ON amostras(missao_id, ts);
"""


class RepositorioMissoes:
    """Grava e consulta missões, poses, leituras e amostras."""

    def __init__(self, pasta_dados) -> None:
        pasta = pathlib.Path(pasta_dados)
        pasta.mkdir(parents=True, exist_ok=True)
        self.caminho = pasta / "ares.db"
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_ESQUEMA)
            columns = {r[1] for r in self._con.execute("PRAGMA table_info(missoes)")}
            if "metadata_json" not in columns:
                self._con.execute("ALTER TABLE missoes ADD COLUMN metadata_json TEXT")
            self._con.commit()
        self._ultima_pose: dict = {}

    def fechar(self) -> None:
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------ gravação
    def criar(
        self,
        nome: Optional[str],
        modo: str,
        centro: Tuple[float, float],
        fonte_sim: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO missoes (nome, modo, iniciada, centro_x, centro_y, fonte_sim_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    nome,
                    modo,
                    time.time(),
                    float(centro[0]),
                    float(centro[1]),
                    None if fonte_sim is None else json.dumps(fonte_sim),
                ),
            )
            if metadata is not None:
                self._con.execute("UPDATE missoes SET metadata_json = ? WHERE id = ?",
                                  (json.dumps(metadata), cur.lastrowid))
            self._con.commit()
            return int(cur.lastrowid)

    def registrar_pose(self, missao_id: int, pose: Pose) -> None:
        ultima = self._ultima_pose.get(missao_id)
        if ultima is not None and pose.ts - ultima < INTERVALO_MIN_POSE_S:
            return
        self._ultima_pose[missao_id] = pose.ts
        self._executar(
            "INSERT INTO poses VALUES (?, ?, ?, ?, ?)",
            (missao_id, pose.ts, pose.x, pose.y, pose.yaw),
        )

    def registrar_leitura(self, missao_id: int, leitura: Leitura) -> None:
        self._executar(
            "INSERT INTO leituras VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                missao_id,
                leitura.ts,
                leitura.dr_usvh,
                leitura.cpm,
                leitura.cps,
                leitura.dose_usv,
                leitura.detector_id,
            ),
        )

    def registrar_amostra(self, missao_id: int, a: Amostra) -> None:
        self._executar(
            "INSERT INTO amostras VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (missao_id, a.ts, a.x, a.y, a.dr_usvh, a.cpm, a.cps, a.lacuna_pose_s),
        )

    def encerrar(self, missao_id: int, resultado: Optional[dict]) -> None:
        self._ultima_pose.pop(missao_id, None)
        self._executar(
            "UPDATE missoes SET encerrada = ?, resultado_json = ? WHERE id = ?",
            (time.time(), None if resultado is None else json.dumps(resultado), missao_id),
        )

    def _executar(self, sql: str, parametros: tuple) -> None:
        with self._lock:
            self._con.execute(sql, parametros)
            self._con.commit()

    # ------------------------------------------------------------------ consulta
    def listar(self) -> list:
        with self._lock:
            linhas = self._con.execute(
                "SELECT m.id, m.nome, m.modo, m.iniciada, m.encerrada, m.centro_x, m.centro_y,"
                " (SELECT COUNT(*) FROM amostras a WHERE a.missao_id = m.id) AS n_amostras"
                " FROM missoes m ORDER BY m.id DESC"
            ).fetchall()
        return [dict(l) for l in linhas]

    def obter(self, missao_id: int) -> Optional[dict]:
        with self._lock:
            linha = self._con.execute(
                "SELECT m.*, (SELECT COUNT(*) FROM amostras a WHERE a.missao_id = m.id)"
                " AS n_amostras FROM missoes m WHERE m.id = ?",
                (missao_id,),
            ).fetchone()
        if linha is None:
            return None
        m = dict(linha)
        fonte, resultado = m.pop("fonte_sim_json"), m.pop("resultado_json")
        metadata = m.pop("metadata_json")
        if metadata is not None:
            m["metadata"] = json.loads(metadata)
        m["fonte_sim"] = None if fonte is None else json.loads(fonte)
        m["resultado"] = None if resultado is None else json.loads(resultado)
        return m

    def _amostras(self, missao_id: int) -> list:
        with self._lock:
            linhas = self._con.execute(
                f"SELECT {', '.join(COLUNAS_AMOSTRA)} FROM amostras"
                " WHERE missao_id = ? ORDER BY ts",
                (missao_id,),
            ).fetchall()
        return [dict(l) for l in linhas]

    def exportar_csv(self, missao_id: int) -> str:
        if self.obter(missao_id) is None:
            raise KeyError(missao_id)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(COLUNAS_AMOSTRA)
        for a in self._amostras(missao_id):
            w.writerow([a[c] for c in COLUNAS_AMOSTRA])
        return buf.getvalue()

    def exportar_json(self, missao_id: int) -> dict:
        m = self.obter(missao_id)
        if m is None:
            raise KeyError(missao_id)
        resultado = m.pop("resultado")
        export = {"missao": m, "amostras": self._amostras(missao_id), "resultado": resultado}
        if m.get("metadata", {}).get("detector") == "Radiacode 110":
            with self._lock:
                for table in ("poses", "leituras"):
                    export[table] = [dict(row) for row in self._con.execute(
                        f"SELECT * FROM {table} WHERE missao_id = ? ORDER BY ts", (missao_id,))]
        return export
