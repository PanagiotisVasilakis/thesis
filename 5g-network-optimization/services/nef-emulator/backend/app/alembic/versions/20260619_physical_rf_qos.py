"""Persist physical RF and UE QoS inputs.

Revision ID: 20260619_rf_qos
Revises: d4867f3a4c0a
"""

from alembic import op
import sqlalchemy as sa


revision = "20260619_rf_qos"
down_revision = "d4867f3a4c0a"
branch_labels = None
depends_on = None


CELL_COLUMNS = {
    "carrier_frequency_hz": sa.Float(),
    "bandwidth_hz": sa.Float(),
    "resource_blocks": sa.Integer(),
    "tx_power_dbm": sa.Float(),
    "antenna_height_m": sa.Float(),
    "azimuth_deg": sa.Float(),
    "tilt_deg": sa.Float(),
    "horizontal_beamwidth_deg": sa.Float(),
    "max_gain_dbi": sa.Float(),
    "front_to_back_db": sa.Float(),
    "noise_figure_db": sa.Float(),
    "frequency_reuse_group": sa.Integer(),
    "los_probability": sa.Float(),
}

UE_COLUMNS = {
    "speed_mps": sa.Float(),
    "service_type": sa.String(),
    "service_priority": sa.Integer(),
    "latency_requirement_ms": sa.Float(),
    "throughput_requirement_mbps": sa.Float(),
    "reliability_pct": sa.Float(),
    "jitter_requirement_ms": sa.Float(),
}


def upgrade():
    for name, column_type in CELL_COLUMNS.items():
        op.add_column("cell", sa.Column(name, column_type, nullable=True))
    for name, column_type in UE_COLUMNS.items():
        op.add_column("ue", sa.Column(name, column_type, nullable=True))


def downgrade():
    for name in reversed(tuple(UE_COLUMNS)):
        op.drop_column("ue", name)
    for name in reversed(tuple(CELL_COLUMNS)):
        op.drop_column("cell", name)
