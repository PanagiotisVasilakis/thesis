from typing import TYPE_CHECKING
from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from .user import User  # noqa: F401
    from .UE import UE as UEModel  # noqa: F401
    from .gNB import gNB as GNBModel  # noqa: F401


class Cell(Base):
    # id for db/primary key
    id = Column(Integer, primary_key=True, index=True)

    #id of each cell in hexadecimal number
    cell_id = Column(String, index=True)
    name = Column(String, index=True)
    description = Column(String, index=True)
    latitude = Column(Float, index=True)
    longitude = Column(Float, index=True)
    radius = Column(Float, index=True)
    carrier_frequency_hz = Column(Float, default=3.5e9)
    bandwidth_hz = Column(Float, default=100e6)
    resource_blocks = Column(Integer, default=273)
    tx_power_dbm = Column(Float, default=46.0)
    antenna_height_m = Column(Float, default=35.0)
    azimuth_deg = Column(Float, default=0.0)
    tilt_deg = Column(Float, default=4.0)
    horizontal_beamwidth_deg = Column(Float, default=65.0)
    max_gain_dbi = Column(Float, default=17.0)
    front_to_back_db = Column(Float, default=30.0)
    noise_figure_db = Column(Float, default=7.0)
    frequency_reuse_group = Column(Integer, default=1)
    los_probability = Column(Float, default=1.0)

    #Foreign Keys
    owner_id = Column(Integer, ForeignKey("user.id"))
    gNB_id = Column(Integer, ForeignKey("gnb.id"))

    # Relationships
    owner = relationship("User", back_populates="Cells")
    UE = relationship("UE", back_populates="Cell")
    gNB = relationship("gNB", back_populates="Cells")
