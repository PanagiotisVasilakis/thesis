#!/usr/bin/env python3
"""Analytical RF topology preflight; diagnostic only, never thesis evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Sequence

RF_ROOT = Path(__file__).resolve().parents[2] / "5g-network-optimization" / "services" / "nef-emulator"
if str(RF_ROOT) not in sys.path:
    sys.path.insert(0, str(RF_ROOT))

from antenna_models.models import MacroCellModel

from scripts.run_enhanced_experiment import get_scenario


EARTH_RADIUS_M = 6_371_000.0


def preflight(scenario_name: str, *, seed: int, samples: int = 360) -> dict:
    os.environ.setdefault("NEF_URL", "http://diagnostic.invalid")
    os.environ.setdefault("NEF_USERNAME", "diagnostic")
    os.environ.setdefault("NEF_PASSWORD", "diagnostic")
    scenario = get_scenario(scenario_name, seed=seed)
    if scenario is None:
        raise ValueError(f"unknown scenario: {scenario_name}")
    cells = scenario.generate_cells()
    reference = cells[0]

    def local(latitude: float, longitude: float, altitude: float):
        lat = math.radians(latitude)
        lon = math.radians(longitude)
        ref_lat = math.radians(reference.latitude)
        ref_lon = math.radians(reference.longitude)
        return (
            (lon - ref_lon) * math.cos((lat + ref_lat) / 2.0) * EARTH_RADIUS_M,
            (lat - ref_lat) * EARTH_RADIUS_M,
            altitude,
        )

    antennas = []
    for cell in cells:
        antennas.append(
            (
                cell,
                MacroCellModel(
                    cell.cell_id,
                    local(cell.latitude, cell.longitude, cell.antenna_height_m),
                    cell.carrier_frequency_hz,
                    cell.tx_power_dbm,
                    bandwidth_hz=cell.bandwidth_hz,
                    resource_blocks=cell.resource_blocks,
                    noise_figure_db=cell.noise_figure_db,
                    azimuth_deg=cell.azimuth_deg,
                    tilt_deg=cell.tilt_deg,
                    horizontal_beamwidth_deg=cell.horizontal_beamwidth_deg,
                    max_gain_dbi=cell.max_gain_dbi,
                    front_to_back_db=cell.front_to_back_db,
                    frequency_reuse_group=cell.frequency_reuse_group,
                    los_probability=cell.los_probability,
                    random_seed=seed,
                ),
            )
        )

    histogram: Counter[int] = Counter()
    rsrp_values: list[float] = []
    sinr_values: list[float] = []
    for index in range(samples):
        latitude, longitude = scenario._interpolate_highway_point(index / (samples - 1))
        position = local(latitude, longitude, 1.5)
        total_power = {
            antenna.ant_id: antenna.received_power_dbm(position)
            for _cell, antenna in antennas
        }
        measurements = []
        for cell, antenna in antennas:
            if math.dist(antenna.position[:2], position[:2]) > cell.radius:
                continue
            interference = sum(
                10 ** (total_power[other.ant_id] / 10.0)
                for _other_cell, other in antennas
                if other.ant_id != antenna.ant_id
                and other.frequency_reuse_group == antenna.frequency_reuse_group
            )
            signal = 10 ** (total_power[antenna.ant_id] / 10.0)
            noise = 10 ** (antenna.thermal_noise_dbm() / 10.0)
            sinr = 10.0 * math.log10(signal / (interference + noise))
            rsrp = antenna.rsrp_dbm(position)
            measurements.append((antenna.ant_id, rsrp, sinr))
            rsrp_values.append(rsrp)
            sinr_values.append(sinr)
        serving = max(measurements, key=lambda item: item[1])[0]
        count = sum(
            cell_id != serving and rsrp >= -115.0 and sinr >= -5.0
            for cell_id, rsrp, sinr in measurements
        )
        histogram[count] += 1
    high_count = sum(count for candidates, count in histogram.items() if candidates >= 3)
    return {
        "scenario": scenario_name,
        "seed": seed,
        "sample_count": samples,
        "cell_count": len(cells),
        "candidate_count_histogram": dict(sorted(histogram.items())),
        "high_complexity_count": high_count,
        "high_complexity_fraction": high_count / samples,
        "median_rsrp_dbm": median(rsrp_values),
        "maximum_rsrp_dbm": max(rsrp_values),
        "median_sinr_db": median(sinr_values),
        "viability_thresholds": {"rsrp_dbm": -115.0, "sinr_db": -5.0},
        "diagnostic_only": True,
        "evidence_eligible": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--scenario", action="append", required=True)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--samples", type=int, default=360)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {
        "reports": [
            preflight(name, seed=args.seed, samples=args.samples)
            for name in args.scenario
        ]
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
