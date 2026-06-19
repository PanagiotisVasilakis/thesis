from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# Shared properties
class CellBase(BaseModel):
    """Base schema for Cell entities."""
    cell_id: str = Field(..., pattern=r'^[A-Fa-f0-9]{9}$', description="Unique 9-character hex identifier for the cell")
    name: Optional[str] = Field(default=None, description="Human-readable name for the cell")
    description: Optional[str] = Field(default=None, description="Optional description of the cell")
    gNB_id: Optional[int] = Field(default=None, description="ID of the parent gNB")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate in degrees")
    radius: float = Field(..., description="Cell coverage radius in meters")
    carrier_frequency_hz: float = Field(default=3.5e9, gt=0)
    bandwidth_hz: float = Field(default=100e6, gt=0)
    resource_blocks: int = Field(default=273, gt=0)
    tx_power_dbm: float = Field(default=46.0)
    antenna_height_m: float = Field(default=35.0, gt=0)
    azimuth_deg: float = Field(default=0.0, ge=0.0, lt=360.0)
    tilt_deg: float = Field(default=4.0, ge=-90.0, le=90.0)
    horizontal_beamwidth_deg: float = Field(default=65.0, gt=0.0, le=360.0)
    max_gain_dbi: float = Field(default=17.0)
    front_to_back_db: float = Field(default=30.0, ge=0.0)
    noise_figure_db: float = Field(default=7.0, ge=0.0)
    frequency_reuse_group: int = Field(default=1, ge=0)
    los_probability: float = Field(default=1.0, ge=0.0, le=1.0)
    
    
# Properties to receive on item creation
class CellCreate(CellBase):
    name: str


# Properties to receive on item update
class CellUpdate(CellBase):
    pass


# Properties shared by models stored in DB
class CellInDBBase(CellBase):
    name: Optional[str]
    owner_id: Optional[int]
    gNB_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


# Properties to return to client
class Cell(CellInDBBase):
    id: Optional[int]


# Properties properties stored in DB
class CellInDB(CellInDBBase):
    pass
