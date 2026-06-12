"""Validated A3 parameter sets and deterministic tuning grids."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Dict, Iterator, Optional, Sequence, Tuple


def _validate_range(name: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True)
class A3Parameters:
    """Operator-style A3 parameters used by the non-ML baselines.

    The condition implemented by this module is:

    neighbour_rsrp_dbm + a3_offset_db > serving_rsrp_dbm + hysteresis_db

    ``minimum_neighbour_rsrp_dbm`` is an optional guard for experiments that
    want to avoid handing over to very weak cells. It is disabled by default.
    """

    a3_offset_db: float = 0.0
    hysteresis_db: float = 3.0
    time_to_trigger_s: float = 1.0
    cooldown_s: float = 2.0
    minimum_neighbour_rsrp_dbm: Optional[float] = None

    def __post_init__(self) -> None:
        _validate_range("a3_offset_db", self.a3_offset_db, -24.0, 24.0)
        _validate_range("hysteresis_db", self.hysteresis_db, 0.0, 24.0)
        _validate_range("time_to_trigger_s", self.time_to_trigger_s, 0.0, 10.0)
        _validate_range("cooldown_s", self.cooldown_s, 0.0, 600.0)
        if self.minimum_neighbour_rsrp_dbm is not None:
            _validate_range(
                "minimum_neighbour_rsrp_dbm",
                self.minimum_neighbour_rsrp_dbm,
                -160.0,
                -40.0,
            )

    def to_dict(self) -> Dict[str, Optional[float]]:
        """Return a stable JSON-serializable parameter dictionary."""
        return asdict(self)


FIXED_A3_PARAMETERS = A3Parameters(
    a3_offset_db=0.0,
    hysteresis_db=3.0,
    time_to_trigger_s=1.0,
    cooldown_s=2.0,
)


@dataclass(frozen=True)
class A3ParameterGrid:
    """Deterministic search grid for tuned A3 baselines."""

    a3_offset_db_values: Sequence[float] = (-2.0, 0.0, 2.0)
    hysteresis_db_values: Sequence[float] = (1.0, 2.0, 3.0, 4.0)
    time_to_trigger_s_values: Sequence[float] = (0.0, 1.0, 2.0)
    cooldown_s_values: Sequence[float] = (0.0, 2.0, 5.0)
    minimum_neighbour_rsrp_dbm_values: Sequence[Optional[float]] = (None,)

    def __post_init__(self) -> None:
        if not self.a3_offset_db_values:
            raise ValueError("a3_offset_db_values must not be empty")
        if not self.hysteresis_db_values:
            raise ValueError("hysteresis_db_values must not be empty")
        if not self.time_to_trigger_s_values:
            raise ValueError("time_to_trigger_s_values must not be empty")
        if not self.cooldown_s_values:
            raise ValueError("cooldown_s_values must not be empty")
        if not self.minimum_neighbour_rsrp_dbm_values:
            raise ValueError("minimum_neighbour_rsrp_dbm_values must not be empty")
        for params in self.iter_parameters():
            params.__post_init__()

    def iter_parameters(self) -> Iterator[A3Parameters]:
        """Yield parameter combinations in deterministic nested-loop order."""
        for offset, hysteresis, ttt, cooldown, min_rsrp in product(
            self.a3_offset_db_values,
            self.hysteresis_db_values,
            self.time_to_trigger_s_values,
            self.cooldown_s_values,
            self.minimum_neighbour_rsrp_dbm_values,
        ):
            yield A3Parameters(
                a3_offset_db=float(offset),
                hysteresis_db=float(hysteresis),
                time_to_trigger_s=float(ttt),
                cooldown_s=float(cooldown),
                minimum_neighbour_rsrp_dbm=None
                if min_rsrp is None
                else float(min_rsrp),
            )

    def as_tuple(self) -> Tuple[A3Parameters, ...]:
        """Materialize the grid while preserving deterministic order."""
        return tuple(self.iter_parameters())


DEFAULT_TUNING_GRID = A3ParameterGrid()

