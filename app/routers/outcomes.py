from fastapi import APIRouter, Response, status

from app.dependencies import AdminUser, DatabaseSession, Patient, ResourceId
from app.errors import error_responses
from app.outcome_schemas import CertificateView, DoctorReviews, ReviewInput, ReviewView
from app.services import outcomes
from app.services.certificate_pdf import render_certificate


router = APIRouter()


@router.post(
    "/appointments/{appointment_id}/review",
    tags=["Reviews"],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409),
)
def submit_review(
    appointment_id: ResourceId, data: ReviewInput, patient: Patient, session: DatabaseSession
) -> ReviewView:
    """Submit one review for a completed visit."""
    return outcomes.submit_review(session, appointment_id, patient.id, data.rating, data.comment)


@router.get("/reviews/me", tags=["Reviews"], responses=error_responses(401, 403))
def my_reviews(patient: Patient, session: DatabaseSession) -> list[ReviewView]:
    """List your own reviews, including reviews waiting for moderation."""
    return outcomes.list_patient_reviews(session, patient.id)


@router.get("/admin/reviews", tags=["Reviews"], responses=error_responses(401, 403))
def pending_reviews(_admin: AdminUser, session: DatabaseSession) -> list[ReviewView]:
    """List reviews waiting for staff moderation."""
    return outcomes.pending_reviews(session)


@router.patch(
    "/admin/reviews/{review_id}/publish", tags=["Reviews"], responses=error_responses(401, 403, 404)
)
def publish_review(review_id: ResourceId, _admin: AdminUser, session: DatabaseSession) -> ReviewView:
    """Publish a review so it counts toward the doctor's average rating."""
    return outcomes.publish_review(session, review_id)


@router.get("/doctors/{doctor_id}/reviews", tags=["Reviews"], responses=error_responses(404))
def doctor_reviews(doctor_id: ResourceId, session: DatabaseSession) -> DoctorReviews:
    """Show only published reviews and their average rating."""
    return outcomes.doctor_reviews(session, doctor_id)


@router.post(
    "/appointments/{appointment_id}/certificate",
    tags=["Proof of attendance"],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409),
)
def request_certificate(
    appointment_id: ResourceId, patient: Patient, session: DatabaseSession
) -> CertificateView:
    """Request proof of attendance after completing your visit."""
    return outcomes.request_certificate(session, appointment_id, patient.id)


@router.get("/certificates", tags=["Proof of attendance"], responses=error_responses(401, 403))
def my_certificates(patient: Patient, session: DatabaseSession) -> list[CertificateView]:
    """List your certificate requests and approvals."""
    return outcomes.list_patient_certificates(session, patient.id)


@router.get("/admin/certificates", tags=["Proof of attendance"], responses=error_responses(401, 403))
def pending_certificates(_admin: AdminUser, session: DatabaseSession) -> list[CertificateView]:
    """List certificate requests waiting for staff approval."""
    return outcomes.pending_certificates(session)


@router.patch(
    "/admin/certificates/{appointment_id}/approve",
    tags=["Proof of attendance"],
    responses=error_responses(401, 403, 404),
)
def approve_certificate(
    appointment_id: ResourceId, admin: AdminUser, session: DatabaseSession
) -> CertificateView:
    """Approve a request for proof of attendance."""
    return outcomes.approve_certificate(session, appointment_id, admin.id)


@router.get(
    "/appointments/{appointment_id}/certificate.pdf",
    tags=["Proof of attendance"],
    response_class=Response,
    responses={
        200: {"description": "Approved certificate", "content": {"application/pdf": {}}},
        **error_responses(401, 403, 404, 409),
    },
)
def download_certificate(
    appointment_id: ResourceId, patient: Patient, session: DatabaseSession
) -> Response:
    """Download an approved PDF for your own completed visit."""
    certificate = outcomes.approved_certificate(session, appointment_id, patient.id)
    visit = certificate.appointment
    document = render_certificate(
        visit.id, visit.patient.name, visit.doctor.user.name, visit.starts_at, certificate.approved_at
    )
    return Response(
        content=document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="attendance-{visit.id}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
