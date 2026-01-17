from typing import List

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.crud.base import CRUDBase
from app.models.gNB import gNB
from app.schemas.gNB import gNBCreate, gNBUpdate


class CRUD_gNB(CRUDBase[gNB, gNBCreate, gNBUpdate]):
    def create_with_owner(
        self, db: Session, *, obj_in: gNBCreate, owner_id: int
    ) -> gNB:
        obj_in_data = jsonable_encoder(obj_in)
        db_obj = self.model(**obj_in_data, owner_id=owner_id)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj


### Get gNB of specific User

    def get_multi_by_owner(
        self, db: Session, *, owner_id: int, skip: int = 0, limit: int = 100
    ) -> List[gNB]:
        return (
            db.query(self.model)
            .filter(gNB.owner_id == owner_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_gNB_id(self, db: Session, id: str) -> gNB:
        return db.query(self.model).filter(self.model.gNB_id == id).first()

    def remove_by_gNB_id(self, db: Session, *, id: str) -> gNB:
        obj = db.query(self.model).filter(gNB.gNB_id == id).first()
        if obj is None:
            return None
        db.delete(obj)
        db.commit()
        return obj


gnb = CRUD_gNB(gNB)
