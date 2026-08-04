"""Mission export package: CSV, grid, image, HTML, NPZ and GeoJSON."""

from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from ares_mapper.config import ScenarioConfig
from ares_mapper.domain.models import MapPrediction
from ares_mapper.radiological_scale import (
    ARES_CLASSIC_COLOR_STOPS,
    PUBLIC_REFERENCE_FRACTION,
    ScaleAnchor,
    regulatory_scale_anchors,
    regulatory_scale_fraction,
)
from ares_mapper.storage.database import MissionStore


class MissionExporter:
    def __init__(
        self,
        mission_directory: Path,
        scenario: ScenarioConfig,
        prediction: MapPrediction,
        manifest: dict[str, Any],
    ) -> None:
        self.mission_directory = mission_directory
        self.scenario = scenario
        self.prediction = prediction
        self.manifest = manifest
        self.exports_directory = mission_directory / "exports"

    async def export_all(self) -> list[Path]:
        self.exports_directory.mkdir(parents=True, exist_ok=True)
        database_path = self.mission_directory / "mission.sqlite"
        datasets = {
            "pose_samples": await MissionStore.read_payloads(database_path, "pose_samples"),
            "radiation_samples": await MissionStore.read_payloads(
                database_path, "radiation_samples"
            ),
            "mapped_samples": await MissionStore.read_payloads(database_path, "mapped_samples"),
            "observation_windows": await MissionStore.read_payloads(
                database_path, "observation_windows"
            ),
            "source_posteriors": await MissionStore.read_payloads(
                database_path, "source_posteriors"
            ),
            "scenario_events": await MissionStore.read_payloads(database_path, "scenario_events"),
        }
        outputs: list[Path] = []
        for name, rows in datasets.items():
            path = self.exports_directory / f"{name}.csv"
            _write_csv(path, rows)
            outputs.append(path)
        outputs.extend(self._export_grid())
        outputs.extend(self._export_visuals(datasets["mapped_samples"]))
        outputs.extend(self._export_geojson(datasets))
        posterior_path = self.exports_directory / "source_posterior_latest.json"
        posterior_path.write_text(
            (
                self.prediction.source_posterior.model_dump_json(indent=2)
                if self.prediction.source_posterior is not None
                else "{}"
            ),
            encoding="utf-8",
        )
        outputs.append(posterior_path)
        scenario_path = self.exports_directory / "scenario.yaml"
        scenario_path.write_text(self.scenario.canonical_yaml(), encoding="utf-8")
        outputs.append(scenario_path)
        manifest_path = self.exports_directory / "mission.json"
        self.manifest["exported_files"] = [path.name for path in outputs] + ["mission.json"]
        manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        outputs.append(manifest_path)
        report_path = self._export_report()
        outputs.append(report_path)
        return outputs

    def _export_grid(self) -> list[Path]:
        x = np.asarray(self.prediction.x_coordinates_m)
        y = np.asarray(self.prediction.y_coordinates_m)
        shape = self.prediction.grid_shape
        values = _as_float_array(self.prediction.values_row_major).reshape(shape)
        coverage = np.asarray(self.prediction.coverage_mask_row_major, dtype=bool).reshape(shape)
        p05 = _as_float_array(self.prediction.p05_values_row_major).reshape(shape)
        p50 = _as_float_array(self.prediction.p50_values_row_major).reshape(shape)
        p95 = _as_float_array(self.prediction.p95_values_row_major).reshape(shape)
        uncertainty = _as_float_array(self.prediction.uncertainty_values_row_major).reshape(shape)
        relative_uncertainty = _as_float_array(
            self.prediction.relative_uncertainty_row_major
        ).reshape(shape)
        coverage_time = _as_float_array(self.prediction.coverage_time_row_major).reshape(shape)
        exposure = _as_float_array(self.prediction.exposure_values_row_major).reshape(shape)
        source_probability = _as_float_array(self.prediction.source_probability_row_major).reshape(
            shape
        )
        model_fraction = _as_float_array(self.prediction.model_fraction_row_major).reshape(shape)
        residual_fraction = _as_float_array(self.prediction.residual_fraction_row_major).reshape(
            shape
        )
        probability_above = _as_float_array(
            self.prediction.probability_above_threshold_row_major
        ).reshape(shape)
        distance_to_support = _as_float_array(
            self.prediction.distance_to_support_row_major
        ).reshape(shape)
        truth = (
            _as_float_array(self.prediction.truth_values_row_major).reshape(shape)
            if self.prediction.truth_values_row_major is not None
            else None
        )
        csv_path = self.exports_directory / "map_latest.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "x_m",
                    "y_m",
                    "mean_uSv_h",
                    "p05_uSv_h",
                    "p50_uSv_h",
                    "p95_uSv_h",
                    "uncertainty_uSv_h",
                    "relative_uncertainty",
                    "coverage_time_s",
                    "exposure_uSv",
                    "source_probability",
                    "probability_above_threshold",
                    "distance_to_support_m",
                    "model_fraction",
                    "residual_fraction",
                    "covered",
                    "truth_uSv_h",
                ]
            )
            for row, y_value in enumerate(y):
                for column, x_value in enumerate(x):
                    writer.writerow(
                        [
                            float(x_value),
                            float(y_value),
                            None if not np.isfinite(values[row, column]) else values[row, column],
                            p05[row, column],
                            p50[row, column],
                            p95[row, column],
                            uncertainty[row, column],
                            relative_uncertainty[row, column],
                            coverage_time[row, column],
                            exposure[row, column],
                            source_probability[row, column],
                            probability_above[row, column],
                            distance_to_support[row, column],
                            model_fraction[row, column],
                            residual_fraction[row, column],
                            bool(coverage[row, column]),
                            (
                                None
                                if truth is None or not np.isfinite(truth[row, column])
                                else truth[row, column]
                            ),
                        ]
                    )
        npz_path = self.exports_directory / "map_latest.npz"
        np.savez_compressed(
            npz_path,
            x_coordinates_m=x,
            y_coordinates_m=y,
            dose_rate_uSv_h=values,
            p05_uSv_h=p05,
            p50_uSv_h=p50,
            p95_uSv_h=p95,
            uncertainty_uSv_h=uncertainty,
            relative_uncertainty=relative_uncertainty,
            coverage_time_s=coverage_time,
            exposure_uSv=exposure,
            source_probability=source_probability,
            probability_above_threshold=probability_above,
            distance_to_support_m=distance_to_support,
            model_fraction=model_fraction,
            residual_fraction=residual_fraction,
            coverage_mask=coverage,
            truth_uSv_h=truth if truth is not None else np.asarray([]),
        )
        cells_path = self.exports_directory / "adaptive_field_cells.json"
        cells_path.write_text(
            json.dumps(
                [cell.model_dump(mode="json") for cell in self.prediction.adaptive_cells],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return [csv_path, npz_path, cells_path]

    def _export_visuals(self, mapped_samples: list[dict[str, Any]]) -> list[Path]:
        x = self.prediction.x_coordinates_m
        y = self.prediction.y_coordinates_m
        z = np.asarray(
            [
                [np.nan if value is None else value for value in row]
                for row in np.asarray(self.prediction.values_row_major, dtype=object).reshape(
                    self.prediction.grid_shape
                )
            ],
            dtype=float,
        )
        scale_minimum = self.scenario.dashboard.scale_min_uSv_h
        scale_maximum = self.scenario.dashboard.scale_max_uSv_h
        scale_mode = self.scenario.dashboard.scale_mode
        logarithmic = scale_mode == "log_fixed"
        regulatory_reference = scale_mode in {
            "public_reference",
            "regulatory_reference",
        }
        background = (
            self.scenario.world.background.dose_rate_uSv_h
            if self.scenario.dashboard.subtract_background_for_scale
            else 0.0
        )
        reference_rate = self.scenario.dashboard.public_reference_rate_uSv_h
        excess_z = np.maximum(z - background, 0.0)
        if regulatory_reference:
            display_z = _regulatory_scale_array(
                excess_z,
                reference_rate_uSv_h=reference_rate,
                maximum_rate_uSv_h=scale_maximum,
            )
            plot_minimum = 0.0
            plot_maximum = 1.0
            anchors = regulatory_scale_anchors(
                reference_rate_uSv_h=reference_rate,
                recording_rate_uSv_h=(self.scenario.dashboard.ioe_recording_rate_uSv_h),
                investigation_rate_uSv_h=(self.scenario.dashboard.ioe_investigation_rate_uSv_h),
                limit_rate_uSv_h=self.scenario.dashboard.ioe_limit_rate_uSv_h,
                occupational_maximum_rate_uSv_h=(self.scenario.dashboard.ioe_maximum_rate_uSv_h),
                maximum_rate_uSv_h=scale_maximum,
            )
            colorscale: str | list[list[float | str]] = [
                [anchor.fraction, anchor.hex_color] for anchor in anchors
            ]
            colorbar: dict[str, Any] = {
                "title": "taxa adicional",
                "tickvals": [anchor.fraction for anchor in anchors[1:]],
                "ticktext": [
                    (
                        f"{_format_rate_with_unit(anchor.rate_uSv_h)}"
                        + (f" — {anchor.label}" if anchor.label else "")
                    )
                    for anchor in anchors[1:]
                ],
            }
            customdata = np.dstack((z, excess_z))
            hovertemplate = (
                "x=%{x:.2f} m<br>y=%{y:.2f} m<br>"
                "acima do fundo=%{customdata[1]:.6g} µSv/h<br>"
                "total=%{customdata[0]:.6g} µSv/h<extra></extra>"
            )
        else:
            display_z = (
                np.where(
                    np.isfinite(z),
                    np.log10(np.maximum(z, max(scale_minimum, 1e-12))),
                    np.nan,
                )
                if logarithmic
                else z
            )
            plot_minimum = math.log10(max(scale_minimum, 1e-12)) if logarithmic else scale_minimum
            plot_maximum = (
                math.log10(max(scale_maximum, scale_minimum * 1.000001))
                if logarithmic
                else scale_maximum
            )
            colorscale = (
                [
                    [
                        fraction,
                        "#" + "".join(f"{channel:02x}" for channel in rgb),
                    ]
                    for fraction, rgb in ARES_CLASSIC_COLOR_STOPS
                ]
                if self.scenario.dashboard.color_scale == "AresClassic"
                else self.scenario.dashboard.color_scale
            )
            colorbar = {"title": "µSv/h"}
            customdata = z
            hovertemplate = (
                "x=%{x:.2f} m<br>y=%{y:.2f} m<br>taxa=%{customdata:.6g} µSv/h<extra></extra>"
            )
        if logarithmic:
            tick_values = np.linspace(plot_minimum, plot_maximum, 5)
            colorbar.update(
                {
                    "tickvals": tick_values.tolist(),
                    "ticktext": [f"{10**value:.3g}" for value in tick_values],
                }
            )
        figure = go.Figure()
        figure.add_trace(
            go.Heatmap(
                x=x,
                y=y,
                z=display_z,
                customdata=customdata,
                colorscale=colorscale,
                colorbar=colorbar,
                zmin=(plot_minimum if scale_mode != "auto" else None),
                zmax=(plot_maximum if scale_mode != "auto" else None),
                hovertemplate=hovertemplate,
                hoverongaps=False,
            )
        )
        if mapped_samples:
            marker_rates = [float(item["dose_rate_uSv_h_filtered"]) for item in mapped_samples]
            marker_colors = (
                [
                    regulatory_scale_fraction(
                        max(rate - background, 0.0),
                        reference_rate_uSv_h=reference_rate,
                        maximum_rate_uSv_h=scale_maximum,
                    )
                    for rate in marker_rates
                ]
                if regulatory_reference
                else [
                    (math.log10(max(rate, max(scale_minimum, 1e-12))) if logarithmic else rate)
                    for rate in marker_rates
                ]
            )
            figure.add_trace(
                go.Scatter(
                    x=[item["sensor_x_m"] for item in mapped_samples],
                    y=[item["sensor_y_m"] for item in mapped_samples],
                    mode="lines+markers",
                    name="Trajetória medida",
                    marker={
                        "size": 5,
                        "color": marker_colors,
                        "colorscale": colorscale,
                        "cmin": (plot_minimum if scale_mode != "auto" else None),
                        "cmax": (plot_maximum if scale_mode != "auto" else None),
                        "line": {"color": "#07151d", "width": 0.7},
                    },
                    line={"color": "rgba(230,240,244,0.55)", "width": 1},
                )
            )
        figure.update_layout(
            title="ARES — mapa estimado de taxa de dose",
            xaxis_title="x [m]",
            yaxis_title="y [m]",
            template="plotly_dark",
            yaxis={"scaleanchor": "x", "scaleratio": 1},
        )
        html_path = self.exports_directory / "map_latest.html"
        figure.write_html(html_path, include_plotlyjs="inline", full_html=True)
        png_path = self.exports_directory / "map_latest.png"
        _render_png(
            png_path,
            z,
            scale_minimum,
            scale_maximum,
            logarithmic=logarithmic,
            regulatory_reference=regulatory_reference,
            public_reference_rate_uSv_h=reference_rate,
            ioe_recording_rate_uSv_h=(self.scenario.dashboard.ioe_recording_rate_uSv_h),
            ioe_investigation_rate_uSv_h=(self.scenario.dashboard.ioe_investigation_rate_uSv_h),
            ioe_limit_rate_uSv_h=self.scenario.dashboard.ioe_limit_rate_uSv_h,
            ioe_maximum_rate_uSv_h=(self.scenario.dashboard.ioe_maximum_rate_uSv_h),
            background_uSv_h=background,
        )
        return [html_path, png_path]

    def _export_geojson(self, datasets: dict[str, list[dict[str, Any]]]) -> list[Path]:
        mapped = datasets["mapped_samples"]
        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["sensor_x_m"], row["sensor_y_m"], row["sensor_z_m"]],
                },
                "properties": {
                    "time_ns": row["effective_measurement_time_ns"],
                    "dose_rate_uSv_h": row["dose_rate_uSv_h_filtered"],
                    "sensor_id": row["sensor_id"],
                },
            }
            for row in mapped
        ]
        if mapped:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [row["sensor_x_m"], row["sensor_y_m"], row["sensor_z_m"]]
                            for row in mapped
                        ],
                    },
                    "properties": {"name": "trajectory_observed"},
                }
            )
        for cell in self.prediction.adaptive_cells:
            x_min, x_max, y_min, y_max = cell.bounds
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [x_min, y_min],
                                [x_max, y_min],
                                [x_max, y_max],
                                [x_min, y_max],
                                [x_min, y_min],
                            ]
                        ],
                    },
                    "properties": {
                        "layer": "adaptive_field_cell",
                        "mean_uSv_h": cell.mean_uSv_h,
                        "p05_uSv_h": cell.p05_uSv_h,
                        "p95_uSv_h": cell.p95_uSv_h,
                        "coverage_time_s": cell.coverage_time_s,
                        "level": cell.level,
                        "refinement_reason": cell.refinement_reason,
                    },
                }
            )
        path = self.exports_directory / "measurements.geojson"
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
            encoding="utf-8",
        )
        return [path]

    def _export_report(self) -> Path:
        metrics = self.prediction.metrics
        rows = "".join(
            f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
            for key, value in metrics.items()
        )
        path = self.exports_directory / "report.html"
        path.write_text(
            f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>ARES — relatório</title>
<style>body{{font:16px system-ui;max-width:900px;margin:40px auto;color:#10232c}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:10px;border-bottom:1px solid #ccd6da;text-align:left}}
h1{{letter-spacing:.08em}}</style></head>
<body><h1>ARES — Relatório da missão</h1>
<p><strong>Missão:</strong> {html.escape(str(self.manifest.get("mission_id")))}</p>
<p>O mapa representa a previsão posterior de taxa de dose em µSv/h. Cobertura
medida, previsão física, resíduo local e incerteza permanecem produtos separados.
As probabilidades são condicionais ao modelo e exigem calibração antes de uso
operacional.</p><h2>Métricas</h2><table>{rows}</table></body></html>""",
            encoding="utf-8",
        )
        return path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, (dict, list))
                        else value
                    )
                    for key, value in row.items()
                }
            )


def _as_float_array(values: list[float | None] | None) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=float)
    return np.asarray([np.nan if value is None else value for value in values], dtype=float)


def _regulatory_scale_array(
    values_uSv_h: np.ndarray,
    *,
    reference_rate_uSv_h: float,
    maximum_rate_uSv_h: float,
) -> np.ndarray:
    values = np.clip(np.asarray(values_uSv_h, dtype=float), 0.0, maximum_rate_uSv_h)
    fractions = np.zeros_like(values)
    below = values <= reference_rate_uSv_h
    fractions[below] = PUBLIC_REFERENCE_FRACTION * values[below] / max(reference_rate_uSv_h, 1e-12)
    above = ~below
    if np.any(above):
        fractions[above] = PUBLIC_REFERENCE_FRACTION + (1.0 - PUBLIC_REFERENCE_FRACTION) * (
            np.log10(values[above] / reference_rate_uSv_h)
            / math.log10(maximum_rate_uSv_h / reference_rate_uSv_h)
        )
    return np.clip(fractions, 0.0, 1.0)


def _format_rate_with_unit(value_uSv_h: float) -> str:
    if value_uSv_h >= 1_000_000:
        return f"{value_uSv_h / 1_000_000:.3g} Sv/h"
    if value_uSv_h >= 1_000:
        return f"{value_uSv_h / 1_000:.3g} mSv/h"
    return f"{value_uSv_h:.3g} µSv/h"


def _render_png(
    path: Path,
    values: np.ndarray,
    minimum: float,
    maximum: float,
    *,
    logarithmic: bool = False,
    regulatory_reference: bool = False,
    public_reference_rate_uSv_h: float = 0.1141552511415525,
    ioe_recording_rate_uSv_h: float = 0.5,
    ioe_investigation_rate_uSv_h: float = 3.0,
    ioe_limit_rate_uSv_h: float = 10.0,
    ioe_maximum_rate_uSv_h: float = 25.0,
    background_uSv_h: float = 0.0,
) -> None:
    valid = np.isfinite(values)
    if maximum <= minimum:
        finite = values[valid]
        minimum = float(np.min(finite)) if finite.size else 0.0
        maximum = float(np.max(finite)) if finite.size else 1.0
    anchors: tuple[ScaleAnchor, ...] = ()
    normalized: NDArray[np.float64]
    stop_positions: NDArray[np.float64]
    stops: NDArray[np.float64]
    if regulatory_reference:
        normalized = _regulatory_scale_array(
            np.maximum(values - background_uSv_h, 0.0),
            reference_rate_uSv_h=public_reference_rate_uSv_h,
            maximum_rate_uSv_h=maximum,
        )
        anchors = regulatory_scale_anchors(
            reference_rate_uSv_h=public_reference_rate_uSv_h,
            recording_rate_uSv_h=ioe_recording_rate_uSv_h,
            investigation_rate_uSv_h=ioe_investigation_rate_uSv_h,
            limit_rate_uSv_h=ioe_limit_rate_uSv_h,
            occupational_maximum_rate_uSv_h=ioe_maximum_rate_uSv_h,
            maximum_rate_uSv_h=maximum,
        )
        stop_positions = np.asarray(
            [anchor.fraction for anchor in anchors],
            dtype=float,
        )
        stops = np.asarray([anchor.rgb for anchor in anchors], dtype=float)
    elif logarithmic:
        minimum = max(minimum, 1e-12)
        maximum = max(maximum, minimum * 1.000001)
        transformed = np.log10(np.maximum(values, minimum))
        transformed_minimum = math.log10(minimum)
        transformed_maximum = math.log10(maximum)
        normalized = np.clip(
            (transformed - transformed_minimum)
            / max(transformed_maximum - transformed_minimum, 1e-12),
            0,
            1,
        )
        stop_positions = np.asarray(
            [fraction for fraction, _ in ARES_CLASSIC_COLOR_STOPS],
            dtype=float,
        )
        stops = np.asarray(
            [rgb for _, rgb in ARES_CLASSIC_COLOR_STOPS],
            dtype=float,
        )
    else:
        normalized = np.clip(
            (values - minimum) / max(maximum - minimum, 1e-12),
            0,
            1,
        )
        stop_positions = np.linspace(0.0, 1.0, 5)
        stops = np.asarray(
            [
                [12, 35, 64],
                [14, 111, 143],
                [34, 190, 153],
                [238, 208, 85],
                [220, 61, 52],
            ],
            dtype=float,
        )
    normalized = np.where(valid, normalized, 0.0)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    for channel in range(3):
        rgba[..., channel] = np.interp(
            normalized,
            stop_positions,
            stops[:, channel],
        ).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0)
    image = Image.fromarray(np.flipud(rgba), mode="RGBA").resize(
        (max(800, values.shape[1] * 8), max(600, values.shape[0] * 8)),
        Image.Resampling.NEAREST,
    )
    canvas = Image.new("RGBA", (image.width + 500, image.height + 80), (7, 21, 29, 255))
    canvas.alpha_composite(image, (70, 30))
    bar_height = image.height
    bar_values = np.linspace(1.0, 0.0, bar_height)[:, None]
    bar_rgb = np.empty((bar_height, 1, 3), dtype=np.uint8)
    for channel in range(3):
        bar_rgb[..., channel] = np.interp(
            bar_values,
            stop_positions,
            stops[:, channel],
        ).astype(np.uint8)
    bar_rgba = np.concatenate(
        (bar_rgb, np.full((bar_height, 1, 1), 255, dtype=np.uint8)),
        axis=2,
    )
    colorbar = Image.fromarray(bar_rgba, mode="RGBA").resize((18, bar_height))
    bar_x = image.width + 92
    canvas.alpha_composite(colorbar, (bar_x, 30))
    draw = ImageDraw.Draw(canvas)
    title = (
        "ARES - contribuicao da fonte acima do fundo"
        if regulatory_reference
        else "ARES - taxa de dose estimada [uSv/h]"
    )
    draw.text((70, 8), title, fill=(231, 240, 244, 255))
    draw.text((8, 30), "y [m]", fill=(168, 191, 200, 255))
    draw.text((70, image.height + 42), "x [m]", fill=(168, 191, 200, 255))
    if regulatory_reference:
        for anchor in anchors[1:]:
            anchor_y = 30 + round(bar_height * (1.0 - anchor.fraction))
            label = _format_rate_with_unit(anchor.rate_uSv_h)
            if anchor.label:
                label += f" - {anchor.label}"
            draw.text(
                (bar_x + 25, anchor_y - 5),
                label,
                fill=(*anchor.rgb, 255),
            )
    else:
        draw.text((bar_x + 25, 25), f"{maximum:.2f}", fill=(231, 240, 244, 255))
        draw.text(
            (bar_x + 25, 25 + bar_height // 2),
            (
                f"{math.sqrt(minimum * maximum):.2f}"
                if logarithmic
                else f"{(minimum + maximum) / 2:.2f}"
            ),
            fill=(168, 191, 200, 255),
        )
        draw.text(
            (bar_x + 25, 20 + bar_height),
            f"{minimum:.2f} uSv/h",
            fill=(231, 240, 244, 255),
        )
    canvas.convert("RGB").save(path)
