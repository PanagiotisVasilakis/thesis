from pydantic import BaseModel, Field


class SUPIMessage(BaseModel):
    """Message schema for SUPI (Subscription Permanent Identifier) lookups."""
    supi: str = Field(..., pattern=r'^[0-9]{15,16}$', description="15 or 16 digit SUPI identifier")


# Backward compatibility alias
Msg = SUPIMessage
