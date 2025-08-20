from typing import Any

from sqlalchemy.orm import declarative_base, declared_attr


class _Base:
    id: Any
    __name__: str

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


Base = declarative_base(cls=_Base)
