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
