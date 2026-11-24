"""Add clinic appointment workflows.

Revision ID: 0003_clinic_workflows
Revises: 0002_user_credentials
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_clinic_workflows"
down_revision = "0002_user_credentials"
branch_labels = None
depends_on = None


def _reference(name: str, target: str, *, nullable: bool = False, primary_key: bool = False):
    return sa.Column(
        name, sa.Integer(), sa.ForeignKey(target, ondelete="RESTRICT"),
        nullable=nullable, primary_key=primary_key, autoincrement=False,
    )


def upgrade() -> None:
    op.add_column(
        "days_off",
        sa.Column("closed_for_replacement", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("appointments", sa.Column("arrived_at", sa.DateTime(timezone=True)))
    op.add_column("appointments", sa.Column("previous_appointment_id", sa.Integer()))
    op.create_foreign_key(
        "fk_appointments_previous", "appointments", "appointments",
        ["previous_appointment_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_appointments_previous", "appointments", ["previous_appointment_id"])
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.create_check_constraint(
        "ck_appointments_status", "appointments", "status IN ('booked', 'cancelled', 'done', 'no_show')"
    )

    op.create_table(
        "intake_forms",
        _reference("appointment_id", "appointments.id", primary_key=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("questions", sa.String(1000), nullable=False),
    )
    op.create_table(
        "follow_up_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        _reference("original_appointment_id", "appointments.id"),
        _reference("doctor_id", "doctors.id"),
        _reference("patient_id", "users.id"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        _reference("booked_appointment_id", "appointments.id", nullable=True),
        sa.UniqueConstraint("original_appointment_id", name="uq_follow_ups_original"),
        sa.UniqueConstraint("booked_appointment_id", name="uq_follow_ups_booking"),
        sa.CheckConstraint("end_date >= start_date", name="ck_follow_up_date_range"),
    )
    op.create_index("ix_follow_up_recommendations_doctor_id", "follow_up_recommendations", ["doctor_id"])
    op.create_index("ix_follow_up_recommendations_patient_id", "follow_up_recommendations", ["patient_id"])

    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        _reference("doctor_id", "doctors.id"),
        _reference("patient_id", "users.id"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="waiting"),
        sa.Column("offered_start", sa.DateTime(timezone=True)),
        _reference("appointment_id", "appointments.id", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('waiting', 'offered', 'booked', 'expired')", name="ck_waitlist_status"
        ),
        sa.CheckConstraint(
            "status != 'offered' OR offered_start IS NOT NULL", name="ck_waitlist_offer"
        ),
    )
    op.create_index("ix_waitlist_doctor_day", "waitlist_entries", ["doctor_id", "day"])
    op.create_index("ix_waitlist_entries_patient_id", "waitlist_entries", ["patient_id"])
    op.create_index(
        "uq_waitlist_active", "waitlist_entries", ["patient_id", "doctor_id", "day"],
        unique=True, postgresql_where=sa.text("status IN ('waiting', 'offered')"),
    )

    op.create_table(
        "replacement_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        _reference("appointment_id", "appointments.id"),
        _reference("original_doctor_id", "doctors.id"),
        _reference("replacement_doctor_id", "doctors.id"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'stale')", name="ck_replacement_status"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_replacement_window"),
        sa.CheckConstraint(
            "replacement_doctor_id != original_doctor_id", name="ck_replacement_distinct_doctors"
        ),
    )
    op.create_index("ix_replacement_offers_appointment_id", "replacement_offers", ["appointment_id"])
    op.create_index(
        "uq_pending_replacement", "replacement_offers", ["appointment_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        _reference("user_id", "users.id"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("message", sa.String(240), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        _reference("appointment_id", "appointments.id"),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("appointment_id", name="uq_review_appointment"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )
    op.create_table(
        "visit_certificates",
        _reference("appointment_id", "appointments.id", primary_key=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        _reference("approved_by", "users.id", nullable=True),
        sa.CheckConstraint(
            "(approved_at IS NULL) = (approved_by IS NULL)", name="ck_certificate_approval"
        ),
    )


def downgrade() -> None:
    op.drop_table("visit_certificates")
    op.drop_table("reviews")
    op.drop_table("notifications")
    op.drop_table("replacement_offers")
    op.drop_table("waitlist_entries")
    op.drop_table("follow_up_recommendations")
    op.drop_table("intake_forms")
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.execute("UPDATE appointments SET status = 'cancelled' WHERE status = 'no_show'")
    op.create_check_constraint(
        "ck_appointments_status", "appointments", "status IN ('booked', 'cancelled', 'done')"
    )
    op.drop_constraint("uq_appointments_previous", "appointments", type_="unique")
    op.drop_constraint("fk_appointments_previous", "appointments", type_="foreignkey")
    op.drop_column("appointments", "previous_appointment_id")
    op.drop_column("appointments", "arrived_at")
    op.drop_column("days_off", "closed_for_replacement")
