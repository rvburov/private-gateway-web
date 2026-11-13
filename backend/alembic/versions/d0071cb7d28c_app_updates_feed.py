"""App update feed: signed manifests of client releases

Лента обновлений программы (0.3.0): манифест update.json байт в байт и подпись update.json.sig
на каждую версию. Новая таблица, прежние не меняются: прежний код API работает на новой схеме.

Revision ID: d0071cb7d28c
Revises: 2408fb4c00ae
"""

import sqlalchemy as sa

from alembic import op

revision = "d0071cb7d28c"
down_revision = "2408fb4c00ae"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_updates",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("rollout", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('stable','beta')", name="app_update_channel"),
        sa.CheckConstraint("rollout BETWEEN 0 AND 100", name="app_update_rollout"),
        sa.PrimaryKeyConstraint("version"),
    )


def downgrade():
    op.drop_table("app_updates")
