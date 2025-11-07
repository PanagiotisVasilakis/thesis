from pydantic import BaseModel, Field


class Msg(BaseModel):
    supi: str = Field(..., pattern=r'^[0-9]{15,16}$')
