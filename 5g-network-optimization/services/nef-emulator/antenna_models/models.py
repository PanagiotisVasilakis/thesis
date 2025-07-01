import math
import numpy as np
from datetime import datetime
from .patterns import AntennaPattern
from rf_models.path_loss import ABGPathLossModel, CloseInPathLossModel

class BaseAntennaModel:
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

    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        """Override in subclasses with a specific path‑loss model."""
        raise NotImplementedError

    def rsrp_dbm(self, ue_position, include_shadowing: bool = False):
        """Received signal power with no shadowing/fast‑fading."""
        pl = self.path_loss_db(ue_position, include_shadowing=include_shadowing)
        return self.tx_power_dbm - pl

class MacroCellModel:
    """Macrocell RF model using 3GPP TR 38.901 path-loss and SINR calculations."""
    def __init__(self, ant_id, position, frequency_hz, tx_power_dbm,
                 d0=1.0, path_loss_exponent=3.76, sigma_sf=8.0, bandwidth_hz=10e6):
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
        self.fc = frequency_hz / 1e9  # GHz
        self.tx_power_dbm = tx_power_dbm
        self.d0 = d0
        self.n = path_loss_exponent
        self.sigma = sigma_sf
        self.bw = bandwidth_hz
        self.path_loss_model = CloseInPathLossModel(n=self.n, sigma=self.sigma)

    def path_loss_db(self, ue_position, include_shadowing: bool = False) -> float:
        """Compute path loss using the Close-In model."""
        d = math.dist(self.position, ue_position)
        return self.path_loss_model.calculate_path_loss(
            d,
            self.fc,
            include_shadowing=include_shadowing,
        )

    def rsrp_dbm(self, ue_position, include_shadowing: bool = False):
        """Received RSRP in dBm."""
        pl = self.path_loss_db(ue_position, include_shadowing=include_shadowing)
        return self.tx_power_dbm - pl

    def sinr_db(self, ue_position, interfering_antennas):
        """
        Signal-to-Interference-plus-Noise Ratio in dB.
        
        interfering_antennas: list of other MacroCellModel instances
        """
        # Desired signal (linear mW)
        rsrp_dbm = self.rsrp_dbm(ue_position)
        S = 10 ** (rsrp_dbm / 10)
        # Interference sum (linear mW)
        I = sum(10 ** (ant.rsrp_dbm(ue_position) / 10) for ant in interfering_antennas)
        # Thermal noise (mW): kTBF, kT ~ -174 dBm/Hz
        noise_dbm = -174 + 10 * math.log10(self.bw)
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
