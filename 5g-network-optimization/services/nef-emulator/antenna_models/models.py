import math
import numpy as np
from datetime import datetime
from .patterns import AntennaPattern, IsotropicPattern, ThreeGPPSectorPattern, MassiveMIMOPattern

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
        pl = self.path_loss_db(ue_position)
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

    def path_loss_db(self, ue_position, include_shadowing: bool = False) -> float:
        """Computes large-scale path loss in dB per 3GPP TR 38.901 NLOS UMa scenario."""
        # Distance in meters
        d = math.dist(self.position, ue_position)
        # Free-space PL at d0: PL0 = 20log10(4π d0 fc / c)
        c = 3e8
        pl0 = 20 * math.log10(4 * math.pi * self.d0 * self.fc * 1e9 / c)
        # 10 n log10(d/d0)
        pl = pl0 + 10 * self.n * math.log10(max(d, self.d0) / self.d0)
        # Add log-normal shadowing
        pl += np.random.normal(0, self.sigma)
        return pl

    def rsrp_dbm(self, ue_position, include_shadowing: bool = False):
        """Received RSRP in dBm."""
        return self.tx_power_dbm - self.path_loss_db(ue_position)

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

    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        dx = ue_position[0] - self.position[0]
        dy = ue_position[1] - self.position[1]
        d_2d = math.hypot(dx, dy)
        d_3d = math.hypot(d_2d, ue_position[2] - self.position[2])
        f_mhz = self.frequency_hz / 1e6
        # TR36.814 Urban Micro NLOS: PL = 36.7·log10(d_3d) + 22.7 + 26·log10(f_MHz)
        pl = 36.7 * math.log10(max(d_3d,1e-3)) + 22.7 + 26 * math.log10(f_mhz)
        return pl


class PicoCellModel(BaseAntennaModel):
    """
    Indoor Pico cell using Free‑Space Path Loss (FSPL).
    """

    def path_loss_db(self, ue_position, include_shadowing: bool = False):
        dx = ue_position[0] - self.position[0]
        dy = ue_position[1] - self.position[1]
        d_3d = math.hypot(math.hypot(dx, dy), ue_position[2] - self.position[2])
        f_mhz = self.frequency_hz / 1e6
        # FSPL (dB) = 20·log10(d) + 20·log10(f) + 32.45, where d in km
        d_km = max(d_3d/1000, 1e-6)
        pl = 20*math.log10(d_km) + 20*math.log10(f_mhz) + 32.45
        return pl
