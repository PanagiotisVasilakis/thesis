import math

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

    def path_loss_db(self, ue_position):
        """Override in subclasses with a specific path‑loss model."""
        raise NotImplementedError

    def rsrp_dbm(self, ue_position):
        """Received signal power with no shadowing/fast‑fading."""
        pl = self.path_loss_db(ue_position)
        return self.tx_power_dbm - pl

class MacroCellModel(BaseAntennaModel):
    """
    Urban Macrocell (3GPP TR36.814 Urban Macro NLOS approximation).
    Uses simplified Hata‑like model.
    """

    def path_loss_db(self, ue_position):
        # distances
        dx = ue_position[0] - self.position[0]
        dy = ue_position[1] - self.position[1]
        d_2d = math.hypot(dx, dy)
        d_3d = math.hypot(d_2d, ue_position[2] - self.position[2])
        # frequency in MHz
        f_mhz = self.frequency_hz / 1e6
        # 3GPP TR36.814 Urban Macro NLOS: PL = 22·log10(d_3d) + 28 + 20·log10(f_MHz)
        pl = 22 * math.log10(max(d_3d,1e-3)) + 28 + 20 * math.log10(f_mhz)
        return pl


class MicroCellModel(BaseAntennaModel):
    """
    Urban Microcell (3GPP TR36.814 Urban Micro NLOS approximation).
    """

    def path_loss_db(self, ue_position):
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

    def path_loss_db(self, ue_position):
        dx = ue_position[0] - self.position[0]
        dy = ue_position[1] - self.position[1]
        d_3d = math.hypot(math.hypot(dx, dy), ue_position[2] - self.position[2])
        f_mhz = self.frequency_hz / 1e6
        # FSPL (dB) = 20·log10(d) + 20·log10(f) + 32.45, where d in km
        d_km = max(d_3d/1000, 1e-6)
        pl = 20*math.log10(d_km) + 20*math.log10(f_mhz) + 32.45
        return pl
