"""2FA only for administrators, device change counting

Решение владельца (DECISIONS п. 11): двухфакторная проверка — только у администраторов.
Миграция только добавляет учет новых устройств. Данные 2FA участников удаляет уже новый код
при запуске (services/retention.py, clear_member_two_factor): миграция идет раньше
перезапуска API, и прежний код, которому нужна 2FA участника, еще несколько секунд отвечает.
Очистка здесь выкинула бы участников из сайта и приложения в это окно.

Revision ID: 2408fb4c00ae
Revises: 2135158254eb
"""

import sqlalchemy as sa

from alembic import op

revision = "2408fb4c00ae"
down_revision = "2135158254eb"
branch_labels = None
depends_on = None


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


def downgrade():
    op.drop_column("app_devices", "removed_by_admin")
    op.drop_column("app_devices", "new_device")
