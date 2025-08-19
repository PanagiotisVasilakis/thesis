from typing import Optional, Annotated

from pydantic import BaseModel, StringConstraints


# Shared properties
class gNBBase(BaseModel):
    gNB_id: Annotated[str, StringConstraints(pattern=r'^[A-Fa-f0-9]{6}$')]
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None

# Properties to receive on item creation
class gNBCreate(gNBBase):
    name: str

# Properties to receive on item update
class gNBUpdate(gNBBase):
    pass


# Properties shared by models stored in DB
class gNBInDBBase(gNBBase):
    name: Optional[str]
    owner_id: Optional[int]
    class Config:
        orm_mode = True


# Properties to return to client
class gNB(gNBInDBBase):
    id: Optional[int]


# Properties properties stored in DB
class gNBInDB(gNBInDBBase):
    pass
