"""Add credentials to clinic users.

Revision ID: 0002_user_credentials
Revises: 0001_clinic_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_user_credentials"
down_revision = "0001_clinic_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.create_check_constraint(
        "ck_users_credentials_pair", "users", "(email IS NULL) = (password_hash IS NULL)"
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_constraint("ck_users_credentials_pair", "users", type_="check")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
