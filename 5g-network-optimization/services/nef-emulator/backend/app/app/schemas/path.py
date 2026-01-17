from typing import Annotated, List, Optional

from pydantic import BaseModel, Field, ConfigDict


# Shared properties | used for request body in endpoint/items.py
#We can declare a UserBase model that serves as a base for our other models. And then we can make subclasses of that model that inherit its attributes
class Point(BaseModel):
    """Geographic point with latitude and longitude."""
    latitude: Annotated[float, Field(ge=-90, le=90, description="Latitude in degrees")]
    longitude: Annotated[float, Field(ge=-180, le=180, description="Longitude in degrees")]

class PathBase(BaseModel):
    description: Optional[str] = None
    start_point: Optional[Point] = None
    end_point: Optional[Point] = None
    color: Optional[str] = None

# Properties to receive on item creation
class PathCreate(PathBase):
    points: Optional[List[Point]] = None 


# Properties to receive on item update
class PathUpdate(PathBase):
    points: Optional[List[Point]] = None 


# Properties shared by models stored in DB
class PathInDBBase(PathBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# Properties to return to client (get all | skip points list)
class Paths(PathInDBBase):
    pass 

# Properties to return to client (get by id)
class Path(PathInDBBase):
    points: Optional[List[Point]] = None 

# Properties properties stored in DB
class PathInDB(PathInDBBase):
    pass
