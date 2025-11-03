from pydantic import BaseModel, Field


class Msg(BaseModel):
    supi: str = Field(..., regex=r'^[0-9]{15,16}$')
