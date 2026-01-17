from typing import List

from pydantic import BaseModel

from app import schemas

class Scenario(BaseModel):
    gNBs: List[schemas.gNBCreate]
    cells: List[schemas.CellCreate]
    UEs: List[schemas.UECreate]
    paths: List[schemas.Path]
    ue_path_association: List[schemas.ue_path]
