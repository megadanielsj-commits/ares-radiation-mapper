"""Fail the build if any approved map or original input core has changed."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def check():
    lock = json.loads(Path(__file__).with_name("map.lock.json").read_text())
    for relative, expected in lock["files"].items():
        path = ROOT / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Arquivo protegido alterado: {relative}")
    return lock


if __name__ == "__main__":
    lock = check()
    count = len(lock["files"])
    fixes = len(lock.get("approved_stationary_fix", {}).get("files", {}))
    print(f"Mapa e núcleo de aquisição/sincronização verificados: {count} arquivos; "
          f"correção pontual de permanência: {fixes} arquivos.")
