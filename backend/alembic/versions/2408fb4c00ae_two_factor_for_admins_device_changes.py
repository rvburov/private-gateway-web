"""2FA only for administrators, device change counting

Решение владельца (DECISIONS п. 11): двухфакторная проверка — только у администраторов.
У участников удаляются секрет TOTP, резервные коды, доверенные браузеры и незавершенные
шаги входа. auth_version не меняется: участники остаются в аккаунте на сайте и в приложении.
Удаленные секреты не восстанавливаются при downgrade.

Revision ID: 2408fb4c00ae
Revises: 2135158254eb
"""

import sqlalchemy as sa

from alembic import op

revision = "2408fb4c00ae"
down_revision = "2135158254eb"
branch_labels = None
depends_on = None

MEMBERS = "SELECT id FROM users WHERE role = 'member'"


def upgrade():
    op.add_column(
        "app_devices",
        sa.Column("new_device", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "app_devices",
        sa.Column("removed_by_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Первая запись каждой установки у участника — новое устройство, повторные входы — нет
    op.execute(
        """
        UPDATE app_devices SET new_device = true
        WHERE id IN (
            SELECT DISTINCT ON (user_id, device_uid) id FROM app_devices
            ORDER BY user_id, device_uid, created_at, id
        )
        """
    )
    op.execute(f"DELETE FROM recovery_codes WHERE user_id IN ({MEMBERS})")
    op.execute(f"DELETE FROM trusted_devices WHERE user_id IN ({MEMBERS})")
    op.execute(f"DELETE FROM login_challenges WHERE user_id IN ({MEMBERS})")
    op.execute(
        "UPDATE users SET totp_enabled = false, totp_secret_enc = NULL, "
        "totp_key_version = NULL, totp_last_step = NULL WHERE role = 'member'"
    )


def downgrade():
    op.drop_column("app_devices", "removed_by_admin")
    op.drop_column("app_devices", "new_device")
