"""Posterior physical field plus bounded local residual on an adaptive quadtree."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from ares_mapper.config import (
    AdaptiveGridConfig,
    DetectorConfig,
    InferenceConfig,
    ResidualConfig,
    WorldConfig,
)
from ares_mapper.domain.models import FieldCell, SourcePosterior
from ares_mapper.inference.particle_filter import (
    RegularizedParticleFilter,
    weighted_quantile,
)
from ares_mapper.mapping.grid import GridSpec
from ares_mapper.mapping.observation_grid import ObservationGrid
from ares_mapper.mapping.quadtree import AdaptiveQuadtree, QuadNode
from ares_mapper.mapping.residual import ResidualIDW


@dataclass(slots=True)
class AdaptiveReconstruction:
    cells: list[FieldCell]
    arrays: dict[str, np.ndarray]
    leaf_count: int
    physical_minimum_cell_m: float


class AdaptiveFieldReconstructor:
    def __init__(
        self,
        world: WorldConfig,
        inference: InferenceConfig,
        grid_config: AdaptiveGridConfig,
        residual_config: ResidualConfig,
        detectors: dict[str, DetectorConfig],
        particle_filter: RegularizedParticleFilter,
        observation_grid: ObservationGrid,
        *,
        minimum_distance_m: float,
        display_smoothing_alpha: float = 0.25,
    ) -> None:
        self.world = world
        self.inference = inference
        self.grid_config = grid_config
        self.residual_config = residual_config
        self.detectors = detectors
        self.particle_filter = particle_filter
        self.observation_grid = observation_grid
        self.minimum_distance_m = minimum_distance_m
        self.display_smoothing_alpha = display_smoothing_alpha
        self.tree = AdaptiveQuadtree(world.bounds_m, grid_config)
        self.residual = ResidualIDW(residual_config, grid_config.observation_cell_m)
        self._cell_by_node_bounds: dict[tuple[float, float, float, float], FieldCell] = {}
        self._display_parameters: np.ndarray | None = None
        self._display_parameter_sequence = -1

    def reconstruct(
        self,
        at_time_ns: int,
        raster_grid: GridSpec,
        posterior: SourcePosterior,
        *,
        detector_height_m: float,
        update_display_state: bool = True,
    ) -> AdaptiveReconstruction:
        self._smoothed_display_parameters(update=update_display_state)
        physical_minimum = self._physical_minimum_resolution()
        evaluator = self._refinement_evaluator(posterior, detector_height_m)
        self.tree.update(evaluator, physical_minimum)
        leaves = self.tree.leaves()
        node_centers: list[tuple[float, float]] = []
        node_sizes: list[float] = []
        operational_bounds: list[tuple[float, float, float, float]] = []
        valid_leaves: list[QuadNode] = []
        bounds = self.world.bounds_m
        for leaf in leaves:
            clipped = (
                max(leaf.x_min, bounds.x_min),
                min(leaf.x_max, bounds.x_max),
                max(leaf.y_min, bounds.y_min),
                min(leaf.y_max, bounds.y_max),
            )
            if clipped[1] <= clipped[0] or clipped[3] <= clipped[2]:
                continue
            operational_bounds.append(clipped)
            node_centers.append(((clipped[0] + clipped[1]) / 2.0, (clipped[2] + clipped[3]) / 2.0))
            node_sizes.append(max(clipped[1] - clipped[0], clipped[3] - clipped[2]))
            valid_leaves.append(leaf)

        centers = np.asarray(node_centers, dtype=float)
        sizes = np.asarray(node_sizes, dtype=float)
        render_seed = self.particle_filter.update_sequence * 1009 + 73
        render_samples, source_exists, calibration_factors = self._render_parameters(render_seed)
        physical_draws = self._physical_draws(
            centers,
            detector_height_m,
            render_samples,
            source_exists,
            calibration_factors,
        )
        # The arithmetic mean of inverse-square fields is not a safe display
        # statistic: a tiny exploratory posterior tail can dominate a cell
        # whenever one high-strength particle lands nearby.  A weighted
        # posterior median is deterministic and ignores those low-mass tails
        # while still preserving the joint position/strength distribution.
        physical_center = self._robust_physical_center(
            centers,
            detector_height_m,
        )
        physical_p05, physical_p50, physical_p95 = np.quantile(
            physical_draws,
            [0.05, 0.50, 0.95],
            axis=0,
        )
        support_points, support_rates, support_variances, _ = self.observation_grid.support_arrays()
        if len(support_points):
            support_physical = self._robust_physical_center(
                support_points,
                detector_height_m,
            )
            support_residuals = support_rates - support_physical
        else:
            support_residuals = np.empty((0,), dtype=float)
        residual_mean, residual_variance, distance_to_support = self.residual.predict(
            centers,
            support_points,
            support_residuals,
            support_variances,
            sizes,
        )
        support_radius_m = max(
            self.grid_config.observation_cell_m,
            self.residual_config.maximum_support_cells * self.grid_config.observation_cell_m,
        )
        residual_supported = distance_to_support < support_radius_m
        correction_fraction = self.residual_config.maximum_relative_correction
        noise_floor = max(
            (detector.robust_base_std_uSv_h for detector in self.detectors.values()),
            default=0.03,
        )
        if correction_fraction > 0:
            residual_limit = np.where(
                residual_supported,
                correction_fraction * np.maximum(physical_center, 0.0),
                0.0,
            )
        else:
            residual_limit = np.zeros_like(physical_center)
        posterior_variance = np.var(physical_draws, axis=0)
        residual_gain = np.divide(
            posterior_variance,
            posterior_variance + residual_variance + noise_floor**2,
            out=np.zeros_like(posterior_variance),
            where=np.isfinite(posterior_variance + residual_variance),
        )
        confidence_weighted_residual = residual_mean * np.clip(
            residual_gain,
            0.0,
            1.0,
        )
        bounded_residual = np.clip(
            confidence_weighted_residual,
            -residual_limit,
            residual_limit,
        )
        bounded_residual_variance = np.minimum(
            residual_variance,
            (residual_limit / 1.645) ** 2,
        )
        rng = np.random.Generator(np.random.PCG64(render_seed + 313))
        residual_noise = rng.normal(
            bounded_residual[None, :],
            np.sqrt(np.maximum(bounded_residual_variance, 0.0))[None, :],
            physical_draws.shape,
        )
        residual_noise = np.clip(
            residual_noise,
            -residual_limit[None, :],
            residual_limit[None, :],
        )
        final_draws = np.maximum(0.0, physical_draws + residual_noise)
        p05, _, p95 = np.quantile(final_draws, [0.05, 0.50, 0.95], axis=0)
        means = np.maximum(0.0, physical_center + bounded_residual)
        p05 = np.minimum(p05, means)
        p95 = np.maximum(p95, means)
        p50 = means
        probability_above = np.mean(
            final_draws >= self.grid_config.probability_threshold_uSv_h,
            axis=0,
        )
        coverage, effective_observations, exposure, last_updates = (
            self.observation_grid.query_stats(centers)
        )
        source_probability = self._sampled_source_probability(
            centers,
            render_samples,
            source_exists,
            bandwidth_m=max(physical_minimum, self.grid_config.minimum_cell_m),
            cell_area_m2=np.maximum(sizes * sizes, 1e-6),
        )
        cells: list[FieldCell] = []
        self._cell_by_node_bounds = {}
        for index, (leaf, cell_bounds) in enumerate(
            zip(valid_leaves, operational_bounds, strict=True)
        ):
            total_contribution = abs(float(physical_center[index])) + abs(
                float(bounded_residual[index])
            )
            model_fraction = (
                abs(float(physical_center[index])) / total_contribution
                if total_contribution > 1e-12
                else 1.0
            )
            cell = FieldCell(
                bounds=cell_bounds,
                level=leaf.level,
                center=node_centers[index],
                posterior_mean=float(physical_center[index]),
                posterior_quantiles=(
                    float(physical_p05[index]),
                    float(physical_p50[index]),
                    float(physical_p95[index]),
                ),
                posterior_std=float(np.std(physical_draws[:, index])),
                residual_mean=float(bounded_residual[index]),
                residual_variance=float(bounded_residual_variance[index]),
                mean_uSv_h=float(means[index]),
                p05_uSv_h=float(p05[index]),
                p50_uSv_h=float(p50[index]),
                p95_uSv_h=float(p95[index]),
                relative_uncertainty=float(
                    (p95[index] - p05[index]) / max(2.0 * means[index], 1e-6)
                ),
                probability_above_threshold=float(probability_above[index]),
                coverage_time_s=float(coverage[index]),
                effective_observations=float(effective_observations[index]),
                distance_to_support_m=(
                    float(distance_to_support[index])
                    if math.isfinite(float(distance_to_support[index]))
                    else None
                ),
                last_update_ns=(int(last_updates[index]) if last_updates[index] > 0 else None),
                refinement_reason=list(leaf.refinement_reason),
                model_fraction=model_fraction,
                residual_fraction=1.0 - model_fraction,
            )
            cells.append(cell)
            self._cell_by_node_bounds[leaf.bounds] = cell
        arrays = self._rasterize(
            raster_grid,
            source_probability_by_cell=source_probability,
            exposure_by_cell=exposure,
        )
        return AdaptiveReconstruction(
            cells=cells,
            arrays=arrays,
            leaf_count=len(cells),
            physical_minimum_cell_m=physical_minimum,
        )

    def _render_parameters(
        self,
        seed: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        samples, exists = self.particle_filter.render_samples(
            self.inference.render_particles,
            seed=max(0, int(seed % (2**63 - 1))),
        )
        calibration_fraction = max(
            (detector.calibration_uncertainty_fraction for detector in self.detectors.values()),
            default=0.0,
        )
        if calibration_fraction > 0:
            rng = np.random.Generator(np.random.PCG64(max(0, seed + 191)))
            factors = np.maximum(
                0.05,
                rng.normal(1.0, calibration_fraction, (len(samples), 1)),
            )
        else:
            factors = np.ones((len(samples), 1), dtype=float)
        return samples, exists, factors

    def _physical_draws(
        self,
        points_xy: np.ndarray,
        detector_height_m: float,
        samples: np.ndarray,
        exists: np.ndarray,
        calibration_factors: np.ndarray,
    ) -> np.ndarray:
        dx = samples[:, 0, None] - points_xy[None, :, 0]
        dy = samples[:, 1, None] - points_xy[None, :, 1]
        dz_sq = (self.inference.source_z_m - detector_height_m) ** 2
        distance_sq = np.maximum(
            dx * dx + dy * dy + dz_sq,
            self.minimum_distance_m**2,
        )
        background = np.exp(samples[:, 3])[:, None]
        strength = np.exp(samples[:, 2])[:, None] * exists[:, None]
        rates = background + strength / distance_sq
        return rates * calibration_factors

    def _robust_physical_center(
        self,
        points_xy: np.ndarray,
        detector_height_m: float,
    ) -> np.ndarray:
        """Return one coherent field from robust posterior parameters.

        Global rendering is enabled only for a stable, unimodal posterior.
        Component-wise weighted medians are therefore a cheap robust center of
        that mode.  Unlike a cell-wise arithmetic mean of inverse-square
        fields, this representation can contain exactly one source and cannot
        turn a low-probability exploratory particle into a remote hotspot.
        """
        if len(points_xy) == 0:
            return np.empty((0,), dtype=float)
        source_x, source_y, log_strength, log_background = self._smoothed_display_parameters(
            update=False
        )
        strength = math.exp(log_strength)
        background = math.exp(log_background)
        dz_sq = (self.inference.source_z_m - detector_height_m) ** 2
        distance_sq = np.maximum(
            (points_xy[:, 0] - source_x) ** 2 + (points_xy[:, 1] - source_y) ** 2 + dz_sq,
            self.minimum_distance_m**2,
        )
        return background + strength / distance_sq

    def _smoothed_display_parameters(self, *, update: bool = True) -> np.ndarray:
        particles = self.particle_filter.particles
        weights = self.particle_filter.weights
        weights = weights / max(float(np.sum(weights)), 1e-300)
        current = np.asarray(
            [
                float(weighted_quantile(particles[:, 0], [0.5], weights)[0]),
                float(weighted_quantile(particles[:, 1], [0.5], weights)[0]),
                float(weighted_quantile(particles[:, 2], [0.5], weights)[0]),
                float(weighted_quantile(particles[:, 3], [0.5], weights)[0]),
            ],
            dtype=float,
        )
        sequence = self.particle_filter.update_sequence
        if self._display_parameters is None:
            self._display_parameters = current
            self._display_parameter_sequence = sequence
        elif update and sequence != self._display_parameter_sequence:
            alpha = self.display_smoothing_alpha
            self._display_parameters = (1.0 - alpha) * self._display_parameters + alpha * current
            self._display_parameter_sequence = sequence
        return self._display_parameters

    def reset_display_state(self) -> None:
        self._display_parameters = None
        self._display_parameter_sequence = -1

    def _physical_minimum_resolution(self) -> float:
        pose_term = 2.0 * self.observation_grid.maximum_pose_std_m()
        speed_term = self.observation_grid.speed_percentile(95.0) * 1.0 / 2.0
        return max(self.grid_config.minimum_cell_m, pose_term, speed_term)

    @staticmethod
    def _sampled_source_probability(
        points_xy: np.ndarray,
        posterior_samples: np.ndarray,
        source_exists: np.ndarray,
        *,
        bandwidth_m: float,
        cell_area_m2: np.ndarray,
    ) -> np.ndarray:
        """Approximate the display KDE with deterministic posterior draws."""

        dx = points_xy[:, 0, None] - posterior_samples[None, :, 0]
        dy = points_xy[:, 1, None] - posterior_samples[None, :, 1]
        bandwidth_sq = max(bandwidth_m, 1e-6) ** 2
        kernels = np.exp(-0.5 * (dx * dx + dy * dy) / bandwidth_sq)
        density = np.mean(
            kernels * source_exists.astype(float)[None, :],
            axis=1,
        ) / (2.0 * math.pi * bandwidth_sq)
        return np.clip(density * cell_area_m2, 0.0, 1.0)

    def _refinement_evaluator(
        self, posterior: SourcePosterior, detector_height_m: float
    ) -> Callable[[QuadNode], tuple[bool, list[str], float]]:
        support_points, _, _, _ = self.observation_grid.support_arrays()
        support_tree = cKDTree(support_points) if len(support_points) else None
        estimate_x, estimate_y = posterior.posterior_map_x_y
        strength = posterior.posterior_median_strength_at_1m
        background = posterior.posterior_background
        credible_cells = posterior.credible_regions["95"].cells
        vertical_distance_sq = (self.inference.source_z_m - detector_height_m) ** 2
        minimum_distance_sq = self.minimum_distance_m**2

        def evaluator(node: QuadNode) -> tuple[bool, list[str], float]:
            reasons: list[str] = []
            target = self.grid_config.far_cell_m
            if node.size_m > self.grid_config.far_cell_m:
                reasons.append("BASE_FAR_RESOLUTION")
            if support_tree is not None:
                distance = float(support_tree.query(node.center, k=1)[0])
                if distance <= 2.0 * self.grid_config.default_cell_m:
                    target = min(target, self.grid_config.default_cell_m)
                    reasons.append("MEASURED_SUPPORT")
            if any(self._bounds_intersect(node.bounds, cell) for cell in credible_cells):
                target = min(target, self.grid_config.near_cell_m)
                reasons.append("SOURCE_CREDIBLE_REGION")
            values = [
                background
                + strength
                / max(
                    (x_m - estimate_x) ** 2 + (y_m - estimate_y) ** 2 + vertical_distance_sq,
                    minimum_distance_sq,
                )
                for x_m, y_m in (
                    node.center,
                    (node.x_min, node.y_min),
                    (node.x_min, node.y_max),
                    (node.x_max, node.y_min),
                    (node.x_max, node.y_max),
                )
            ]
            relative_variation = (max(values) - min(values)) / max(
                sum(values) / len(values),
                1e-9,
            )
            if relative_variation >= self.grid_config.refine_relative_variation:
                target = min(target, self.grid_config.near_cell_m)
                reasons.append("FIELD_GRADIENT")
            return node.size_m > target + 1e-9, reasons, target

        return evaluator

    def _rasterize(
        self,
        grid: GridSpec,
        *,
        source_probability_by_cell: np.ndarray,
        exposure_by_cell: np.ndarray,
    ) -> dict[str, np.ndarray]:
        shape = grid.shape
        arrays = {
            "mean": np.full(shape, np.nan),
            "p05": np.full(shape, np.nan),
            "p50": np.full(shape, np.nan),
            "p95": np.full(shape, np.nan),
            "uncertainty": np.full(shape, np.nan),
            "relative_uncertainty": np.full(shape, np.nan),
            "coverage_time": np.zeros(shape),
            "exposure": np.zeros(shape),
            "source_probability": np.zeros(shape),
            "probability_above": np.full(shape, np.nan),
            "distance_to_support": np.full(shape, np.nan),
            "model_fraction": np.full(shape, np.nan),
            "residual_fraction": np.full(shape, np.nan),
            "coverage_mask": np.zeros(shape, dtype=bool),
        }
        cells = list(self._cell_by_node_bounds.values())
        cell_index_by_identity = {id(cell): index for index, cell in enumerate(cells)}
        for row, y_m in enumerate(grid.y_coordinates_m):
            for column, x_m in enumerate(grid.x_coordinates_m):
                lookup_x = min(
                    float(x_m),
                    float(np.nextafter(self.world.bounds_m.x_max, self.world.bounds_m.x_min)),
                )
                lookup_y = min(
                    float(y_m),
                    float(np.nextafter(self.world.bounds_m.y_max, self.world.bounds_m.y_min)),
                )
                node = self.tree.find_leaf(lookup_x, lookup_y)
                cell = self._cell_by_node_bounds.get(node.bounds)
                if cell is None:
                    continue
                cell_index = cell_index_by_identity[id(cell)]
                arrays["mean"][row, column] = cell.mean_uSv_h
                arrays["p05"][row, column] = cell.p05_uSv_h
                arrays["p50"][row, column] = cell.p50_uSv_h
                arrays["p95"][row, column] = cell.p95_uSv_h
                arrays["uncertainty"][row, column] = math.sqrt(
                    cell.posterior_std**2 + cell.residual_variance
                )
                arrays["relative_uncertainty"][row, column] = cell.relative_uncertainty
                arrays["coverage_time"][row, column] = cell.coverage_time_s
                arrays["exposure"][row, column] = exposure_by_cell[cell_index]
                arrays["source_probability"][row, column] = source_probability_by_cell[cell_index]
                arrays["probability_above"][row, column] = cell.probability_above_threshold
                arrays["distance_to_support"][row, column] = (
                    cell.distance_to_support_m if cell.distance_to_support_m is not None else np.nan
                )
                arrays["model_fraction"][row, column] = cell.model_fraction
                arrays["residual_fraction"][row, column] = cell.residual_fraction
                arrays["coverage_mask"][row, column] = cell.coverage_time_s > 0
        return arrays

    @staticmethod
    def _bounds_intersect(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> bool:
        return not (
            first[1] <= second[0]
            or first[0] >= second[1]
            or first[3] <= second[2]
            or first[2] >= second[3]
        )
