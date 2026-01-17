from typing import Any, List, Optional
from ipaddress import ip_address
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.api import deps
from app.api.api_v1.endpoints.utils import retrieve_ue_state
from app.api.api_v1.endpoints.paths import get_random_point
from app.tools.distance import check_distance

try:
    from app.handover.runtime import runtime as handover_runtime
except ModuleNotFoundError:  # pragma: no cover - fallback for tests
    class _FallbackRuntime:
        ensure_topology = staticmethod(lambda *args, **kwargs: None)
        upsert_ue_state = staticmethod(lambda *args, **kwargs: None)

    handover_runtime = _FallbackRuntime()  # type: ignore[assignment]

router = APIRouter()


def enrich_ues_with_cell_info(ues: list, json_ues: list) -> list:
    """Enrich UE JSON representations with cell and gNB information.
    
    Adds cell_id_hex and gNB_id to each UE JSON object based on the
    corresponding UE ORM object's Cell relationship.
    
    Args:
        ues: List of UE ORM objects (with Cell relationship)
        json_ues: List of UE JSON-encoded dictionaries
        
    Returns:
        Enriched json_ues list (modified in-place, also returned)
    """
    # Build lookup: Cell_id -> (cell_id_hex, gNB_id)
    cell_lookup = {}
    for ue_obj in ues:
        if ue_obj.Cell_id is not None and ue_obj.Cell_id not in cell_lookup:
            cell_lookup[ue_obj.Cell_id] = (
                ue_obj.Cell.cell_id if ue_obj.Cell else None,
                ue_obj.Cell.gNB_id if ue_obj.Cell else None
            )
    
    # Enrich JSON objects using O(n) lookup
    for json_ue in json_ues:
        cell_id = json_ue.get('Cell_id')
        if cell_id is not None and cell_id in cell_lookup:
            cell_id_hex, gnb_id = cell_lookup[cell_id]
            json_ue['cell_id_hex'] = cell_id_hex
            json_ue['gNB_id'] = gnb_id
        else:
            json_ue['cell_id_hex'] = None
            json_ue['gNB_id'] = None
    
    return json_ues


def add_gnb_id_to_ue_json(ue_obj, json_ue: dict) -> dict:
    """Add gNB_id to a single UE JSON object based on Cell relationship.
    
    Args:
        ue_obj: UE ORM object with Cell relationship
        json_ue: UE JSON-encoded dictionary
        
    Returns:
        Modified json_ue dict (modified in-place, also returned)
    """
    if ue_obj.Cell_id is not None and ue_obj.Cell:
        json_ue['gNB_id'] = ue_obj.Cell.gNB_id
    else:
        json_ue['gNB_id'] = None
    return json_ue


def _sync_handover_runtime(
    db: Session,
    owner_id: int,
    supi: str,
    payload: dict,
) -> None:
    """Push the latest UE snapshot into the shared handover runtime."""

    latitude = payload.get("latitude")
    longitude = payload.get("longitude")

    if latitude is None or longitude is None:
        return

    try:
        cells = crud.cell.get_multi_by_owner(db=db, owner_id=owner_id, skip=0, limit=200)
    except Exception:  # noqa: BLE001 - defensive fallback
        cells = []

    json_cells = jsonable_encoder(cells) if cells else []
    if json_cells:
        handover_runtime.ensure_topology(json_cells)
        nearest = check_distance(latitude, longitude, json_cells)
        candidate_id: Optional[int] = nearest.get("id") if nearest else None
    else:
        candidate_id = None

    handover_runtime.upsert_ue_state(
        supi,
        float(latitude),
        float(longitude),
        payload.get("speed"),
        payload.get("Cell_id"),
        candidate_id,
    )


@router.get("", response_model=List[schemas.UEhex])
def read_UEs(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve UEs.
    """
    if crud.user.is_superuser(current_user):
        UEs = crud.ue.get_multi(db, skip=skip, limit=limit)
    else:
        UEs = crud.ue.get_multi_by_owner(
            db=db, owner_id=current_user.id, skip=skip, limit=limit
        )
    json_UEs = jsonable_encoder(UEs)
    enrich_ues_with_cell_info(UEs, json_UEs)

    return json_UEs


@router.post("", response_model=schemas.UE)
def create_UE(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.UECreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new UE.
    """
    #Validate Unique ids
    ipv4_obj = item_in.ip_address_v4 if not isinstance(item_in.ip_address_v4, str) else ip_address(item_in.ip_address_v4)
    ipv6_obj = item_in.ip_address_v6 if not isinstance(item_in.ip_address_v6, str) else ip_address(item_in.ip_address_v6)

    if crud.ue.get_supi(db=db, supi=item_in.supi):
        raise HTTPException(
            status_code=409, detail=f"UE with supi {item_in.supi} already exists")
    elif crud.ue.get_ipv4(db=db, ipv4=str(ipv4_obj), owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"UE with ipv4 {str(ipv4_obj)} already exists")
    elif crud.ue.get_ipv6(db=db, ipv6=str(getattr(ipv6_obj, "exploded", ipv6_obj)), owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"UE with ipv6 {str(ipv6_obj)} already exists")
    elif crud.ue.get_mac(db=db, mac=str(item_in.mac_address), owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"UE with mac {str(item_in.mac_address)} already exists")
    elif crud.ue.get_externalId(db=db, externalId=item_in.external_identifier, owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"UE with external id {str(item_in.mac_address)} already exists")

    json_data = jsonable_encoder(item_in)
    db_payload = dict(json_data)
    db_payload['ip_address_v4'] = str(ipv4_obj)
    db_payload['ip_address_v6'] = str(getattr(ipv6_obj, "exploded", ipv6_obj))
    db_payload['Cell_id'] = None

    UE = crud.ue.create_with_owner(db=db, obj_in=db_payload, owner_id=current_user.id)

    response_data = dict(db_payload)
    response_data.update({"supi": item_in.supi, "path_id": 0, "gNB_id": None})

    _sync_handover_runtime(db, current_user.id, item_in.supi, response_data)

    return response_data


@router.put("/{supi}", response_model=schemas.UE)
def update_UE(
    *,
    db: Session = Depends(deps.get_db),
    supi: str = Path(..., description="The SUPI of the UE you want to update"),
    item_in: schemas.UEUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update a UE.
    """
    UE = crud.ue.get_supi(db=db, supi=supi)
    if not UE:
        raise HTTPException(status_code=404, detail="UE not found")
    if not crud.user.is_superuser(current_user) and (UE.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    ipv4_obj = item_in.ip_address_v4 if not isinstance(item_in.ip_address_v4, str) else ip_address(item_in.ip_address_v4)
    ipv6_obj = item_in.ip_address_v6 if not isinstance(item_in.ip_address_v6, str) else ip_address(item_in.ip_address_v6)
    ipv4_str = str(ipv4_obj)
    ipv6_str = str(getattr(ipv6_obj, "exploded", ipv6_obj))

    if (UE.ip_address_v4 != ipv4_str) and crud.ue.get_ipv4(db=db, ipv4=ipv4_str, owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"This ipv4 {ipv4_str} already exists")
    elif (UE.ip_address_v6 != ipv6_str) and crud.ue.get_ipv6(db=db, ipv6=ipv6_str, owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"This ipv6 {ipv6_str} already exists")
    elif (UE.mac_address != item_in.mac_address) and crud.ue.get_mac(db=db, mac=str(item_in.mac_address), owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"This mac {item_in.mac_address} already exists")
    elif (UE.external_identifier != item_in.external_identifier) and crud.ue.get_externalId(db=db, externalId=item_in.external_identifier, owner_id=current_user.id):
        raise HTTPException(
            status_code=409, detail=f"This external id {item_in.mac_address} already exists")

    json_data = jsonable_encoder(item_in)
    db_payload = dict(json_data)
    db_payload['ip_address_v4'] = ipv4_str
    db_payload['ip_address_v6'] = ipv6_str

    UE = crud.ue.update(db=db, db_obj=UE, obj_in=db_payload)

    response_data = dict(db_payload)
    response_data.update({
        "supi": supi,
        "path_id": UE.path_id,
        "gNB_id": getattr(UE.Cell, "gNB_id", None),
        "Cell_id": UE.Cell_id,
    })

    _sync_handover_runtime(db, current_user.id, supi, response_data)

    return response_data


@router.get("/{supi}", response_model=schemas.UE)
def read_UE(
    *,
    db: Session = Depends(deps.get_db),
    supi: str = Path(...,
                     description="The SUPI of the UE you want to retrieve"),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get UE by supi.
    """
    UE = crud.ue.get_supi(db=db, supi=supi)
    if not UE:
        raise HTTPException(status_code=404, detail="UE not found")
    if not crud.user.is_superuser(current_user) and (UE.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    json_UE = jsonable_encoder(UE)
    add_gnb_id_to_ue_json(UE, json_UE)

    return json_UE


@router.delete("/{supi}", response_model=schemas.UE)
def delete_UE(
    *,
    db: Session = Depends(deps.get_db),
    supi: str = Path(..., description="The SUPI of the UE you want to delete"),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a UE.
    """
    UE = crud.ue.get_supi(db=db, supi=supi)
    if not UE:
        raise HTTPException(status_code=404, detail="UE not found")
    if not crud.user.is_superuser(current_user) and (UE.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    if retrieve_ue_state(supi, current_user.id):
        raise HTTPException(
            status_code=400, detail=f"UE with SUPI {supi} is currently moving. You are not allowed to remove a UE while it's moving")
    else:
        json_UE = jsonable_encoder(UE)
        add_gnb_id_to_ue_json(UE, json_UE)

        crud.ue.remove_supi(db=db, supi=supi)
        return json_UE

### Get list of UEs of specific gNB

@router.get("/by_gNB/{gNB_id}", response_model=List[schemas.UE])
def read_gNB_id(
    *,
    db: Session = Depends(deps.get_db),
    gNB_id: str = Path(
        ...,
        description="The gNB id of the gNB in hexadecimal format",
        examples={"default": {"value": "AAAAA1"}},
    ),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get gNB of specific UE.
    """
    gNB = crud.gnb.get_gNB_id(db=db, id=gNB_id)
    if not gNB:
        raise HTTPException(
            status_code=404, detail=f"gNB with id {gNB_id} not found")
    if not crud.user.is_superuser(current_user) and (gNB.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    cells = crud.cell.get_by_gNB_id(db=db, gNB_id=gNB.id)
    ue_list = []

    for cell in cells:
        UEs = crud.ue.get_by_Cell(db=db, cell_id=cell.id)
        json_UEs = jsonable_encoder(UEs)
        for json_UE, UE in zip(json_UEs, UEs):
            add_gnb_id_to_ue_json(UE, json_UE)
        ue_list.extend(json_UEs)

    if not ue_list:
        raise HTTPException(
            status_code=404, detail="There are no UEs associated with this gNB")
    return ue_list


### Get list of UEs of Specific Cells

@router.get("/by_Cell/{cell_id}", response_model=List[schemas.UE])
def read_UE_Cell(
    *,
    db: Session = Depends(deps.get_db),
    cell_id: str = Path(
        ...,
        description="The cell id of the cell in hexadecimal format",
        examples={"default": {"value": "AAAAA1001"}},
    ),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get Cell of specifc UE.
    """
    cell = crud.cell.get_Cell_id(db=db, id=cell_id)
    if not cell:
        raise HTTPException(
            status_code=404, detail=f"Cell with id {cell_id} not found")
    if not crud.user.is_superuser(current_user) and (cell.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    UEs = crud.ue.get_by_Cell(db=db, cell_id=cell.id)
    if not UEs:
        raise HTTPException(
            status_code=404, detail="There are no UEs associated with this cell")
    json_UEs = jsonable_encoder(UEs)
    for json_UE, UE in zip(json_UEs, UEs):
        add_gnb_id_to_ue_json(UE, json_UE)

    return json_UEs

#Assign paths to UEs
@router.post("/associate/path", response_model=schemas.ue_path)
def assign_predefined_path(
    *,
    db: Session = Depends(deps.get_db),
    item_in: schemas.ue_path,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Assign paths to UEs
    """
    if retrieve_ue_state(item_in.supi, current_user.id):
        raise HTTPException(status_code=400, detail=f"UE with SUPI {item_in.supi} is currently moving. You are not allowed to edit UE's path while it's moving")

    UE = crud.ue.get_supi(db=db, supi=item_in.supi)
    if not UE:
        raise HTTPException(status_code=404, detail="UE not found")
    if not crud.user.is_superuser(current_user) and (UE.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    if item_in.path >= 1:
        path = crud.path.get(db=db, id=item_in.path)
        if not path:
            raise HTTPException(
                status_code=409, detail="ERROR: This path_id you specified doesn't exist. Please create a new path with this path_id or use an existing path")
    elif item_in.path == 0:
        crud.ue.update(db=db, db_obj=UE, obj_in={'path_id' : 0})
        return item_in
    
    #Assign the coordinates on path change
    if UE.path_id != item_in.path:
        json_data = jsonable_encoder(UE)
        json_data['path_id'] = item_in.path
        random_point = get_random_point(db, item_in.path)
        json_data['latitude'] = random_point.get('latitude')
        json_data['longitude'] = random_point.get('longitude')
        crud.ue.update(db=db, db_obj=UE, obj_in=json_data)

    return item_in
