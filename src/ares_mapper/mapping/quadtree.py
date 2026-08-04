"""Persistent adaptive quadtree with refinement hysteresis."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ares_mapper.config import AdaptiveGridConfig, BoundsConfig


@dataclass(slots=True)
class QuadNode:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    level: int = 0
    children: list[QuadNode] = field(default_factory=list)
    merge_counter: int = 0
    refinement_reason: list[str] = field(default_factory=list)

    @property
    def size_m(self) -> float:
        return self.x_max - self.x_min

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.x_min, self.x_max, self.y_min, self.y_max

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def split(self) -> None:
        if self.children:
            return
        x_mid, y_mid = self.center
        next_level = self.level + 1
        self.children = [
            QuadNode(self.x_min, x_mid, self.y_min, y_mid, next_level),
            QuadNode(x_mid, self.x_max, self.y_min, y_mid, next_level),
            QuadNode(self.x_min, x_mid, y_mid, self.y_max, next_level),
            QuadNode(x_mid, self.x_max, y_mid, self.y_max, next_level),
        ]


RefinementEvaluator = Callable[[QuadNode], tuple[bool, list[str], float]]


class AdaptiveQuadtree:
    def __init__(self, bounds: BoundsConfig, config: AdaptiveGridConfig) -> None:
        self.bounds = bounds
        self.config = config
        extent = max(bounds.x_max - bounds.x_min, bounds.y_max - bounds.y_min)
        root_size = 2.0 ** math.ceil(math.log2(max(extent, config.far_cell_m)))
        self.root = QuadNode(
            bounds.x_min,
            bounds.x_min + root_size,
            bounds.y_min,
            bounds.y_min + root_size,
        )
        self.update_count = 0

    def update(self, evaluator: RefinementEvaluator, physical_minimum_m: float) -> None:
        self.update_count += 1
        minimum = max(self.config.minimum_cell_m, physical_minimum_m)
        self._update_node(self.root, evaluator, minimum)
        self._enforce_limit()

    def leaves(self, *, operational_only: bool = True) -> list[QuadNode]:
        result: list[QuadNode] = []

        def visit(node: QuadNode) -> None:
            if node.children:
                for child in node.children:
                    visit(child)
            elif not operational_only or self._intersects_operational(node):
                result.append(node)

        visit(self.root)
        return result

    def find_leaf(self, x_m: float, y_m: float) -> QuadNode:
        node = self.root
        while node.children:
            x_mid, y_mid = node.center
            index = (1 if x_m >= x_mid else 0) + (2 if y_m >= y_mid else 0)
            node = node.children[index]
        return node

    def _update_node(
        self,
        node: QuadNode,
        evaluator: RefinementEvaluator,
        physical_minimum_m: float,
    ) -> None:
        refine, reasons, target_size = evaluator(node)
        node.refinement_reason = reasons
        can_split = node.size_m / 2.0 >= physical_minimum_m - 1e-9
        should_split = refine and node.size_m > target_size + 1e-9 and can_split
        if should_split:
            node.merge_counter = 0
            node.split()
            for child in node.children:
                self._update_node(child, evaluator, physical_minimum_m)
            return
        if not node.children:
            return
        if refine:
            node.merge_counter = 0
            for child in node.children:
                self._update_node(child, evaluator, physical_minimum_m)
            return
        node.merge_counter += 1
        if node.merge_counter >= self.config.merge_hysteresis_updates:
            node.children = []
            node.merge_counter = 0
            return
        for child in node.children:
            self._update_node(child, evaluator, physical_minimum_m)

    def _enforce_limit(self) -> None:
        leaves = self.leaves(operational_only=False)
        if len(leaves) <= self.config.maximum_leaves:
            return
        parents: list[QuadNode] = []

        def collect(node: QuadNode) -> None:
            if node.children and all(child.is_leaf for child in node.children):
                parents.append(node)
            for child in node.children:
                collect(child)

        collect(self.root)
        for parent in sorted(parents, key=lambda item: item.level, reverse=True):
            parent.children = []
            leaves = self.leaves(operational_only=False)
            if len(leaves) <= self.config.maximum_leaves:
                break

    def _intersects_operational(self, node: QuadNode) -> bool:
        return not (
            node.x_max <= self.bounds.x_min
            or node.x_min >= self.bounds.x_max
            or node.y_max <= self.bounds.y_min
            or node.y_min >= self.bounds.y_max
        )
