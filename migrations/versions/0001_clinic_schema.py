"""Create the clinic schema.

Revision ID: 0001_clinic_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_clinic_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "patient",
                "doctor",
                "admin",
                native_enum=False,
                create_constraint=True,
                name="ck_users_role",
            ),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) >= 2", name="ck_users_name"),
    )
    op.create_table(
        "specialties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.CheckConstraint("length(trim(name)) >= 2", name="ck_specialties_name"),
    )
    op.create_index(
        "uq_specialties_name_lower",
        "specialties",
        [sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "doctors",
        sa.Column(
            "id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "specialty_id",
            sa.Integer(),
            sa.ForeignKey("specialties.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_doctors_specialty_id", "doctors", ["specialty_id"])
    op.create_table(
        "access_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    op.create_index("ix_access_tokens_user_id", "access_tokens", ["user_id"])
    op.create_table(
        "schedules",
        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("weekday", sa.Integer(), primary_key=True),
        sa.Column("start", sa.Time(timezone=False), nullable=False),
        sa.Column("end", sa.Time(timezone=False), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedules_weekday"),
        sa.CheckConstraint("slot_minutes BETWEEN 5 AND 120", name="ck_schedules_slot_minutes"),
        sa.CheckConstraint('"end" > start', name="ck_schedules_window"),
        sa.CheckConstraint(
            'extract(second from start) = 0 AND extract(second from "end") = 0',
            name="ck_schedules_whole_minutes",
        ),
        sa.CheckConstraint(
            '(extract(epoch from ("end" - start))::numeric % (slot_minutes * 60)) = 0',
            name="ck_schedules_divisible",
        ),
    )
    op.create_table(
        "days_off",
        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date(), primary_key=True),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "booked",
                "cancelled",
                "done",
                native_enum=False,
                create_constraint=True,
                name="ck_appointments_status",
            ),
            nullable=False,
            server_default="booked",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_appointments_window"),
    )
    op.create_index(
        "uq_appointments_active_slot",
        "appointments",
        ["doctor_id", "starts_at"],
        unique=True,
        postgresql_where=sa.text("status != 'cancelled'"),
    )
    op.create_index("ix_appointments_patient_starts", "appointments", ["patient_id", "starts_at"])
    op.create_index("ix_appointments_doctor_starts", "appointments", ["doctor_id", "starts_at"])
    op.create_table(
        "medical_records",
        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id", ondelete="RESTRICT"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("diagnosis", sa.String(500), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(diagnosis)) >= 1", name="ck_medical_records_diagnosis"),
    )


def downgrade() -> None:
    op.drop_table("medical_records")
    op.drop_table("appointments")
    op.drop_table("days_off")
    op.drop_table("schedules")
    op.drop_table("access_tokens")
    op.drop_table("doctors")
    op.drop_table("specialties")
    op.drop_table("users")
