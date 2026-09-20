from __future__ import annotations

import math


def _distance(left: float, right: float) -> float:
    return abs(left - right)


def dtw_align(
    reference: list[float],
    learner: list[float],
) -> tuple[list[float], list[float], float]:
    if not reference or not learner:
        return [], [], math.inf

    rows = len(reference) + 1
    columns = len(learner) + 1
    infinity = float("inf")
    cost = [[infinity] * columns for _ in range(rows)]
    cost[0][0] = 0.0

    for row in range(1, rows):
        for column in range(1, columns):
            local = _distance(reference[row - 1], learner[column - 1])
            cost[row][column] = local + min(
                cost[row - 1][column],
                cost[row][column - 1],
                cost[row - 1][column - 1],
            )

    aligned_reference: list[float] = []
    aligned_learner: list[float] = []
    row = len(reference)
    column = len(learner)
    while row > 0 and column > 0:
        aligned_reference.append(reference[row - 1])
        aligned_learner.append(learner[column - 1])
        candidates = (
            (cost[row - 1][column - 1], row - 1, column - 1),
            (cost[row - 1][column], row - 1, column),
            (cost[row][column - 1], row, column - 1),
        )
        _, next_row, next_column = min(candidates)
        row, column = next_row, next_column

    aligned_reference.reverse()
    aligned_learner.reverse()
    normalized_cost = cost[-1][-1] / max(len(aligned_reference), 1)
    return aligned_reference, aligned_learner, normalized_cost


def mean_and_stddev(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance)
