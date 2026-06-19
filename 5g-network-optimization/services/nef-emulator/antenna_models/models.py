import hashlib
import math
import random
from abc import ABC, abstractmethod
from rf_models.path_loss import ABGPathLossModel, CloseInPathLossModel

class BaseAntennaModel(ABC):
    """Abstract antenna with position, frequency, and TX power."""

    def __init__(self, antenna_id, position, frequency_hz, tx_power_dbm):
        """
        Args:
            antenna_id: unique string
            position: (x, y, z) meters
            frequency_hz: carrier frequency
            tx_power_dbm: transmit power in dBm
        """
        self.antenna_id = antenna_id
        self.position = position
        self.frequency_hz = frequency_hz
        self.tx_power_dbm = tx_power_dbm

    @abstractmethod
    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        """Override in subclasses with a specific path-loss model."""
        raise NotImplementedError

    def rsrp_dbm(self, ue_position, include_shadowing: bool = False):
        """Received signal power with no shadowing/fast‑fading."""
        pl = self.path_loss_db(ue_position, include_shadowing=include_shadowing)
        return self.tx_power_dbm - pl

class MacroCellModel:
    """Deterministic directional 3GPP TR 38.901 Rural Macro RF model.

    ``tx_power_dbm`` is total carrier power. ``rsrp_dbm`` returns reference
    signal power per resource element, while ``received_power_dbm`` returns
    total received carrier power for SINR calculations.
    """

    MODEL_NAME = "3gpp_tr_38_901_rma_directional"
    MODEL_VERSION = "v2"

    def __init__(
        self,
        ant_id,
        position,
        frequency_hz,
        tx_power_dbm,
        *,
        bandwidth_hz=100e6,
        resource_blocks=273,
        noise_figure_db=7.0,
        azimuth_deg=0.0,
        tilt_deg=4.0,
        horizontal_beamwidth_deg=65.0,
        vertical_beamwidth_deg=10.0,
        max_gain_dbi=17.0,
        front_to_back_db=30.0,
        frequency_reuse_group=1,
        los_probability=1.0,
        shadow_fading_std_db=4.0,
        shadowing_enabled=True,
        random_seed=0,
        average_building_height_m=5.0,
        street_width_m=20.0,
    ):
        """
        Args:
          ant_id: Unique antenna identifier
          position: (x,y,z) tuple in meters
          frequency_hz: Carrier frequency in Hz
          tx_power_dbm: Transmit power in dBm
          d0: Reference distance (m)
          path_loss_exponent: Environment-specific exponent (e.g., 3.76 for Urban Macro NLOS) :contentReference[oaicite:0]{index=0}
          sigma_sf: Shadow-fading std dev (dB)
          bandwidth_hz: System bandwidth in Hz
        """
        self.ant_id = ant_id
        self.position = position
        self.frequency_hz = float(frequency_hz)
        self.fc = self.frequency_hz / 1e9  # GHz
        self.tx_power_dbm = tx_power_dbm
        self.bw = float(bandwidth_hz)
        self.resource_blocks = int(resource_blocks)
        self.noise_figure_db = float(noise_figure_db)
        self.azimuth_deg = float(azimuth_deg) % 360.0
        self.tilt_deg = float(tilt_deg)
        self.horizontal_beamwidth_deg = float(horizontal_beamwidth_deg)
        self.vertical_beamwidth_deg = float(vertical_beamwidth_deg)
        self.max_gain_dbi = float(max_gain_dbi)
        self.front_to_back_db = float(front_to_back_db)
        self.frequency_reuse_group = int(frequency_reuse_group)
        self.los_probability = min(1.0, max(0.0, float(los_probability)))
        self.shadow_fading_std_db = float(shadow_fading_std_db)
        self.shadowing_enabled = bool(shadowing_enabled)
        self.random_seed = int(random_seed)
        self.average_building_height_m = float(average_building_height_m)
        self.street_width_m = float(street_width_m)

        if self.bw <= 0 or self.resource_blocks <= 0:
            raise ValueError("bandwidth_hz and resource_blocks must be positive")

    @staticmethod
    def _wrap_angle(angle_deg: float) -> float:
        return (angle_deg + 180.0) % 360.0 - 180.0

    def antenna_gain_dbi(self, ue_position) -> float:
        dx = float(ue_position[0]) - float(self.position[0])
        dy = float(ue_position[1]) - float(self.position[1])
        dz = float(ue_position[2]) - float(self.position[2])
        horizontal_distance = max(math.hypot(dx, dy), 1e-9)
        bearing_deg = math.degrees(math.atan2(dx, dy)) % 360.0
        horizontal_offset = self._wrap_angle(bearing_deg - self.azimuth_deg)
        horizontal_attenuation = min(
            12.0 * (horizontal_offset / self.horizontal_beamwidth_deg) ** 2,
            self.front_to_back_db,
        )

        elevation_deg = math.degrees(math.atan2(-dz, horizontal_distance))
        vertical_offset = elevation_deg - self.tilt_deg
        vertical_attenuation = min(
            12.0 * (vertical_offset / self.vertical_beamwidth_deg) ** 2,
            self.front_to_back_db,
        )
        total_attenuation = min(
            horizontal_attenuation + vertical_attenuation,
            self.front_to_back_db,
        )
        return self.max_gain_dbi - total_attenuation

    def _deterministic_uniform(self, ue_position, namespace: str) -> float:
        quantized = tuple(round(float(value) / 10.0) for value in ue_position)
        payload = f"{self.random_seed}:{self.ant_id}:{namespace}:{quantized}".encode()
        digest = hashlib.sha256(payload).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64)

    def _is_los(self, ue_position) -> bool:
        return self._deterministic_uniform(ue_position, "los") < self.los_probability

    def _shadow_fading_db(self, ue_position, *, los: bool) -> float:
        if not self.shadowing_enabled or self.shadow_fading_std_db <= 0:
            return 0.0
        quantized = tuple(round(float(value) / 10.0) for value in ue_position)
        payload = f"{self.random_seed}:{self.ant_id}:shadow:{los}:{quantized}".encode()
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        sigma = self.shadow_fading_std_db if los else max(6.0, self.shadow_fading_std_db)
        return random.Random(seed).gauss(0.0, sigma)

    def _rma_los_path_loss_db(self, d_2d: float, d_3d: float) -> float:
        # 3GPP TR 38.901 RMa LOS, valid for 10 m <= d_2D <= 10 km.
        h = min(20.0, max(5.0, self.average_building_height_m))
        h_bs = max(10.0, float(self.position[2]))
        h_ut = 1.5
        d_bp = 2.0 * math.pi * h_bs * h_ut * self.frequency_hz / 3.0e8

        def pl1(distance_3d: float) -> float:
            return (
                20.0 * math.log10(40.0 * math.pi * distance_3d * self.fc / 3.0)
                + min(0.03 * h**1.72, 10.0) * math.log10(distance_3d)
                - min(0.044 * h**1.72, 14.77)
                + 0.002 * math.log10(h) * distance_3d
            )

        if d_2d <= d_bp:
            return pl1(d_3d)
        d_bp_3d = math.sqrt(d_bp**2 + (h_bs - h_ut) ** 2)
        return pl1(d_bp_3d) + 40.0 * math.log10(d_3d / d_bp_3d)

    def _rma_nlos_path_loss_db(self, d_3d: float, los_path_loss: float) -> float:
        h = min(20.0, max(5.0, self.average_building_height_m))
        w = min(50.0, max(5.0, self.street_width_m))
        h_bs = max(10.0, float(self.position[2]))
        h_ut = 1.5
        nlos = (
            161.04
            - 7.1 * math.log10(w)
            + 7.5 * math.log10(h)
            - (24.37 - 3.7 * (h / h_bs) ** 2) * math.log10(h_bs)
            + (43.42 - 3.1 * math.log10(h_bs)) * (math.log10(d_3d) - 3.0)
            + 20.0 * math.log10(self.fc)
            - (3.2 * (math.log10(11.75 * h_ut)) ** 2 - 4.97)
        )
        return max(los_path_loss, nlos)

    def path_loss_db(self, ue_position, include_shadowing: bool = False) -> float:
        d_2d = max(math.dist(self.position[:2], ue_position[:2]), 10.0)
        d_3d = max(math.dist(self.position, ue_position), 10.0)
        los = self._is_los(ue_position)
        los_path_loss = self._rma_los_path_loss_db(d_2d, d_3d)
        path_loss = los_path_loss if los else self._rma_nlos_path_loss_db(d_3d, los_path_loss)
        if include_shadowing:
            path_loss += self._shadow_fading_db(ue_position, los=los)
        return path_loss

    def received_power_dbm(self, ue_position, include_shadowing: bool | None = None):
        if include_shadowing is None:
            include_shadowing = self.shadowing_enabled
        return (
            self.tx_power_dbm
            + self.antenna_gain_dbi(ue_position)
            - self.path_loss_db(ue_position, include_shadowing=include_shadowing)
        )

    def rsrp_dbm(self, ue_position, include_shadowing: bool | None = None):
        reference_elements = 12 * self.resource_blocks
        return self.received_power_dbm(
            ue_position,
            include_shadowing=include_shadowing,
        ) - 10.0 * math.log10(reference_elements)

    def thermal_noise_dbm(self) -> float:
        return -174.0 + 10.0 * math.log10(self.bw) + self.noise_figure_db

    def provenance(self) -> dict:
        return {
            "model_name": self.MODEL_NAME,
            "model_version": self.MODEL_VERSION,
            "fallback": False,
            "carrier_frequency_hz": self.frequency_hz,
            "bandwidth_hz": self.bw,
            "resource_blocks": self.resource_blocks,
            "noise_figure_db": self.noise_figure_db,
            "antenna_pattern": "3gpp_sector_65deg",
            "path_loss_model": "3gpp_tr_38_901_rma",
            "frequency_reuse_group": self.frequency_reuse_group,
        }

    def sinr_db(self, ue_position, interfering_antennas):
        """
        Signal-to-Interference-plus-Noise Ratio in dB.
        
        interfering_antennas: list of other MacroCellModel instances
        """
        # Desired signal (linear mW)
        signal_dbm = self.received_power_dbm(ue_position)
        S = 10 ** (signal_dbm / 10)
        # Interference sum (linear mW)
        I = sum(
            10 ** (ant.received_power_dbm(ue_position) / 10)
            for ant in interfering_antennas
            if getattr(ant, "frequency_reuse_group", 1) == self.frequency_reuse_group
        )
        noise_dbm = self.thermal_noise_dbm()
        N = 10 ** (noise_dbm / 10)
        # SINR
        sinr = 10 * math.log10(S / (I + N))
        return sinr

class MicroCellModel(BaseAntennaModel):
    """
    Urban Microcell (3GPP TR36.814 Urban Micro NLOS approximation).
    """

    def __init__(self, antenna_id, position, frequency_hz, tx_power_dbm, sigma_sf=4.0):
        super().__init__(antenna_id, position, frequency_hz, tx_power_dbm)
        self.path_loss_model = ABGPathLossModel(alpha=3.67, beta=22.7, gamma=2.6, sigma=sigma_sf)

    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        d = math.dist(self.position, ue_position)
        f_ghz = self.frequency_hz / 1e9
        return self.path_loss_model.calculate_path_loss(
            d,
            f_ghz,
            include_shadowing=include_shadowing,
        )


class PicoCellModel(BaseAntennaModel):
    """
    Indoor Pico cell using Free‑Space Path Loss (FSPL).
    """

    def __init__(self, antenna_id, position, frequency_hz, tx_power_dbm, sigma_sf=0.0):
        super().__init__(antenna_id, position, frequency_hz, tx_power_dbm)
        self.path_loss_model = CloseInPathLossModel(n=2.0, sigma=sigma_sf)

    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        d = math.dist(self.position, ue_position)
        f_ghz = self.frequency_hz / 1e9
        return self.path_loss_model.calculate_path_loss(
            d,
            f_ghz,
            include_shadowing=include_shadowing,
        )
