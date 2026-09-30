#!/usr/bin/env python3
"""Export saved ARES missions without installing the robot or detector SDK."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3


def export(root):
    exported = []
    for database in Path(root).glob("*/ares.db"):
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            for mission in connection.execute("SELECT * FROM missoes"):
                mission = dict(mission)
                folder = database.parent / "exportados"
                folder.mkdir(exist_ok=True)
                for column in ("metadata_json", "fonte_sim_json", "resultado_json"):
                    if column in mission:
                        value = mission.pop(column)
                        mission[column.removesuffix("_json")] = None if value is None else json.loads(value)
                contents = {"missao": mission}
                for table in ("poses", "leituras", "amostras"):
                    contents[table] = [dict(row) for row in connection.execute(
                        f"SELECT * FROM {table} WHERE missao_id=? ORDER BY ts", (mission["id"],))]
                stem = f"missao-{mission['id']}"
                for suffix, rows in (("json", contents), ("csv", contents["amostras"])):
                    path = folder / f"{stem}.{suffix}"
                    temporary = path.with_suffix(path.suffix + ".tmp")
                    with temporary.open("w", encoding="utf-8", newline="") as stream:
                        if suffix == "json":
                            json.dump(rows, stream, ensure_ascii=False, indent=2, allow_nan=False)
                            stream.write("\n")
                        else:
                            fields = ["ts", "x", "y", "dr_usvh", "cpm", "cps", "lacuna_pose_s"]
                            writer = csv.DictWriter(stream, fields, extrasaction="ignore")
                            writer.writeheader()
                            writer.writerows(rows)
                    temporary.replace(path)
                    exported.append(str(path))
        finally:
            connection.close()
    return exported


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default="resultados/integracao")
    for path in export(parser.parse_args().root):
        print(path)
