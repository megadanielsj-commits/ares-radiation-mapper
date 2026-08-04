"""Parallel H0/H1 source-existence evidence accounting."""

from __future__ import annotations

import math


class SourceExistenceModel:
    """Updates source odds from marginal likelihoods without mixing particle sets."""

    def __init__(self, prior_probability: float) -> None:
        probability = min(1.0 - 1e-12, max(1e-12, prior_probability))
        self._log_odds = math.log(probability) - math.log1p(-probability)
        self.log_bayes_factor = 0.0

    @property
    def probability(self) -> float:
        if self._log_odds >= 0:
            return 1.0 / (1.0 + math.exp(-self._log_odds))
        exponential = math.exp(self._log_odds)
        return exponential / (1.0 + exponential)

    def update(self, log_evidence_h1: float, log_evidence_h0: float) -> float:
        increment = max(-25.0, min(25.0, log_evidence_h1 - log_evidence_h0))
        self.log_bayes_factor += increment
        self._log_odds = max(-60.0, min(60.0, self._log_odds + increment))
        return self.probability
