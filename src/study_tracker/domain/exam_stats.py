"""Aggregation helpers for exam grouping and statistics."""

from __future__ import annotations


def aggregate_by_group(exams: list[dict]) -> dict[int, float]:
    """Average exam score by group id."""
    scores_by_group: dict[int, list[float]] = {}
    for exam in exams:
        for group_id in exam.get("group_ids", []):
            scores_by_group.setdefault(int(group_id), []).append(float(exam.get("score", 0)))
    return {gid: sum(vals) / len(vals) for gid, vals in scores_by_group.items()}
