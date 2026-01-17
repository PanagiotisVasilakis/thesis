from fastapi import APIRouter

from app.api.api_v1 import endpoints
from .endpoints import (
     monitoringevent,
     qosInformation,
     mobility_patterns,
 )
from .endpoints.ml_api import router as ml_router

api_router = APIRouter()
api_router.include_router(endpoints.login.router, tags=["login"])
api_router.include_router(endpoints.users.router, prefix="/users", tags=["users"])
api_router.include_router(endpoints.utils.router, prefix="/utils", tags=["UI"])
api_router.include_router(endpoints.ue_movement.router, prefix="/ue_movement", tags=["Movement"])
api_router.include_router(endpoints.paths.router, prefix="/paths", tags=["Paths"])
api_router.include_router(endpoints.gNB.router, prefix="/gNBs", tags=["gNBs"])
api_router.include_router(endpoints.Cell.router, prefix="/Cells", tags=["Cells"])
api_router.include_router(endpoints.UE.router, prefix="/UEs", tags=["UEs"])
api_router.include_router(endpoints.qosInformation.router, prefix="/qosInfo", tags=["QoS Information"])

# Register ML endpoints
api_router.include_router(
    ml_router,
    prefix="/ml",
    tags=["ml-service"]
)

# Create a subapp for 3GPP APIs
nef_router = APIRouter()
nef_router.include_router(endpoints.monitoringevent.router, prefix="/3gpp-monitoring-event/v1", tags=["Monitoring Event API"])
nef_router.include_router(endpoints.qosMonitoring.router, prefix="/3gpp-as-session-with-qos/v1", tags=["Session With QoS API"])

# Include the mobility patterns router
api_router.include_router(
    mobility_patterns.router,
    prefix="/mobility-patterns",
    tags=["mobility-patterns"],
)
