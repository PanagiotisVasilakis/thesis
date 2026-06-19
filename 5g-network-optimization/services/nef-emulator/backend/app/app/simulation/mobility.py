"""Pure distance-based movement helpers for deterministic scenario mobility."""

from __future__ import annotations

import bisect
import math


EARTH_RADIUS_M = 6_371_000.0


def point_distance_m(first: dict, second: dict) -> float:
    lat1 = math.radians(float(first["latitude"]))
    lon1 = math.radians(float(first["longitude"]))
    lat2 = math.radians(float(second["latitude"]))
    lon2 = math.radians(float(second["longitude"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def path_cumulative_distances(points: list[dict]) -> list[float]:
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + point_distance_m(previous, current))
    return distances


def interpolate_path_position(
    points: list[dict], cumulative: list[float], distance_m: float
) -> tuple[float, float, int]:
    if len(points) == 1 or cumulative[-1] <= 0.0:
        return float(points[0]["latitude"]), float(points[0]["longitude"]), 0
    bounded = min(max(0.0, distance_m), cumulative[-1])
    upper = min(len(points) - 1, bisect.bisect_right(cumulative, bounded))
    lower = max(0, upper - 1)
    span = cumulative[upper] - cumulative[lower]
    fraction = 0.0 if span <= 0 else (bounded - cumulative[lower]) / span
    latitude = float(points[lower]["latitude"]) + fraction * (
        float(points[upper]["latitude"]) - float(points[lower]["latitude"])
    )
    longitude = float(points[lower]["longitude"]) + fraction * (
        float(points[upper]["longitude"]) - float(points[lower]["longitude"])
    )
    return latitude, longitude, lower


def advance_ping_pong(
    distance_m: float, direction: int, delta_m: float, path_length_m: float
) -> tuple[float, int]:
    if path_length_m <= 0.0 or delta_m <= 0.0:
        return distance_m, direction
    position = distance_m + direction * delta_m
    current_direction = 1 if direction >= 0 else -1
    while position < 0.0 or position > path_length_m:
        if position > path_length_m:
            position = 2.0 * path_length_m - position
            current_direction = -1
        elif position < 0.0:
            position = -position
            current_direction = 1
    return position, current_direction


def configured_speed_mps(ue_data: dict) -> float:
    numeric = ue_data.get("speed_mps")
    if isinstance(numeric, (int, float)):
        return max(0.0, float(numeric))
    label = str(ue_data.get("speed") or "").upper()
    if label == "HIGH":
        return 33.3
    if label == "LOW":
        return 1.4
    return 0.0
