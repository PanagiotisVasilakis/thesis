from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# Shared properties
class CellBase(BaseModel):
    cell_id: str = Field(..., pattern=r'^[A-Fa-f0-9]{9}$')
    name: Optional[str] = None
    description: Optional[str] = None
    gNB_id: int = None
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius: float
    
    
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
