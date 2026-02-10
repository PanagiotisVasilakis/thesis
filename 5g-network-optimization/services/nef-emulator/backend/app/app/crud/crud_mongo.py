"""MongoDB CRUD operations with type hints."""
from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo.database import Database
from pymongo.results import DeleteResult, InsertOneResult, UpdateResult


def read_all(db: Database, collection_name: str, owner: int) -> List[Dict[str, Any]]:
    """Get all documents for an owner."""
    collection = db[collection_name]
    return list(collection.find({'owner_id': owner}, {'_id': False, 'owner_id': False}))


def read_uuid(db: Database, collection_name: str, uuid: str) -> Optional[Dict[str, Any]]:
    """Get a document by its ObjectId (without returning _id field)."""
    collection = db[collection_name]
    return collection.find_one({'_id': ObjectId(uuid)}, {'_id': False})


def read(db: Database, collection_name: str, key: str, value: Any) -> Optional[Dict[str, Any]]:
    """Find a single document by key-value pair."""
    collection = db[collection_name]
    return collection.find_one({key: value})


def read_by_multiple_pairs(
    db: Database, collection_name: str, **kwargs: Any
) -> Optional[Dict[str, Any]]:
    """Find a single document matching multiple key-value pairs."""
    collection = db[collection_name]
    return collection.find_one(kwargs)


def update(
    db: Database, collection_name: str, uuid: str, json_data: Dict[str, Any]
) -> UpdateResult:
    """Replace a document by its ObjectId."""
    return db[collection_name].replace_one({"_id": ObjectId(uuid)}, json_data)


def update_new_field(
    db: Database, collection_name: str, uuid: str, json_data: Dict[str, Any]
) -> UpdateResult:
    """Add/update fields in an existing document."""
    return db[collection_name].update_one({'_id': ObjectId(uuid)}, {'$set': json_data})


def create(db: Database, collection_name: str, json_data: Dict[str, Any]) -> InsertOneResult:
    """Insert a new document."""
    return db[collection_name].insert_one(json_data)


def delete_by_uuid(db: Database, collection_name: str, uuid: str) -> DeleteResult:
    """Delete a document by its ObjectId."""
    return db[collection_name].delete_one({"_id": ObjectId(uuid)})


def delete_by_item(db: Database, collection_name: str, key: str, value: Any) -> DeleteResult:
    """Delete a document by key-value match."""
    return db[collection_name].delete_one({key: value})


def read_all_gNB_profiles(db: Database, collection_name: str, gnb_id: int) -> List[Dict[str, Any]]:
    """Get all QoS profiles for a gNB."""
    collection = db[collection_name]
    return list(collection.find({'gNB_id': gnb_id}, {'_id': False}))


def read_gNB_qosprofile(
    db: Database, collection_name: str, gnb_id: int, qos_id: Any
) -> Optional[Dict[str, Any]]:
    """Get a specific QoS profile by gNB and profile ID."""
    collection = db[collection_name]
    return collection.find_one({'gNB_id': gnb_id, 'value': qos_id}, {'_id': False})
