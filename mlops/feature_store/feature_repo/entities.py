"""Feast entities shared by the feature repository and downstream pipelines."""

from ._feast_compat import Entity, ValueType

# UE entity keyed by ``ue_id``. Keeping the entity name stable (`ue_id`) avoids
# breaking existing materialisation jobs and training pipelines.
ue = Entity(
    name="ue_id",
    join_keys=["ue_id"],
    description="User equipment identifier used for feature joins",
    value_type=ValueType.STRING,
)

__all__ = ["ue"]
