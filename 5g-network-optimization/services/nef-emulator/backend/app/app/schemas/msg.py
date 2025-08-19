from typing import Annotated

from pydantic import BaseModel, StringConstraints


class Msg(BaseModel):
    supi: Annotated[str, StringConstraints(pattern=r'^[0-9]{15,16}$')]
