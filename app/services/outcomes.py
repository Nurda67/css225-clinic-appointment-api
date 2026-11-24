from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import now
from app.domain import AppointmentStatus
from app.errors import DomainError
from app.models import Appointment
from app.outcome_schemas import CertificateView, DoctorReviews, PublicReview, ReviewView
from app.services.directory import get_doctor
from app.workflow_models import Review, VisitCertificate


def _completed_visit(session: Session, appointment_id: int, patient_id: int) -> Appointment:
    visit = session.get(Appointment, appointment_id)
    if visit is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")
    if visit.patient_id != patient_id:
        raise DomainError(403, "appointment_forbidden", "You can only use your own visits.")
    if visit.status != AppointmentStatus.DONE:
        raise DomainError(409, "visit_not_completed", "This visit must be completed first.")
    return visit


def _review_view(review: Review) -> ReviewView:
    return ReviewView(
        id=review.id,
        appointment_id=review.appointment_id,
        doctor_id=review.appointment.doctor_id,
        rating=review.rating,
        comment=review.comment,
        status="published" if review.published_at else "pending",
    )


def submit_review(
    session: Session, appointment_id: int, patient_id: int, rating: int, comment: str
) -> ReviewView:
    visit = _completed_visit(session, appointment_id, patient_id)
    existing = session.scalar(select(Review.id).where(Review.appointment_id == visit.id))
    if existing is not None:
        raise DomainError(409, "review_exists", "You have already reviewed this visit.")
    review = Review(appointment=visit, rating=rating, comment=comment)
    session.add(review)
    session.flush()
    return _review_view(review)


def list_patient_reviews(session: Session, patient_id: int) -> list[ReviewView]:
    query = select(Review).join(Review.appointment).where(Appointment.patient_id == patient_id)
    return [_review_view(review) for review in session.scalars(query.order_by(Review.id.desc()))]


def pending_reviews(session: Session) -> list[ReviewView]:
    query = select(Review).where(Review.published_at.is_(None)).order_by(Review.id)
    return [_review_view(review) for review in session.scalars(query)]


def publish_review(session: Session, review_id: int) -> ReviewView:
    review = session.get(Review, review_id, with_for_update=True, populate_existing=True)
    if review is None:
        raise DomainError(404, "review_not_found", "Review not found.")
    if review.published_at is None:
        review.published_at = now(session)
        session.flush()
    return _review_view(review)


def doctor_reviews(session: Session, doctor_id: int) -> DoctorReviews:
    get_doctor(session, doctor_id)
    query = (
        select(Review)
        .join(Review.appointment)
        .where(Appointment.doctor_id == doctor_id, Review.published_at.is_not(None))
        .order_by(Review.published_at.desc(), Review.id.desc())
    )
    reviews = [
        PublicReview(rating=row.rating, comment=row.comment, published_at=row.published_at)
        for row in session.scalars(query)
    ]
    average = round(sum(review.rating for review in reviews) / len(reviews), 2) if reviews else None
    return DoctorReviews(
        doctor_id=doctor_id, average_rating=average, review_count=len(reviews), reviews=reviews
    )


def _certificate_view(certificate: VisitCertificate) -> CertificateView:
    visit = certificate.appointment
    return CertificateView(
        appointment_id=visit.id,
        patient_name=visit.patient.name,
        doctor_name=visit.doctor.user.name,
        starts_at=visit.starts_at,
        status="approved" if certificate.approved_at else "pending",
    )


def request_certificate(
    session: Session, appointment_id: int, patient_id: int
) -> CertificateView:
    visit = _completed_visit(session, appointment_id, patient_id)
    if session.get(VisitCertificate, visit.id) is not None:
        raise DomainError(409, "certificate_exists", "You have already requested proof of attendance.")
    certificate = VisitCertificate(appointment=visit)
    session.add(certificate)
    session.flush()
    return _certificate_view(certificate)


def list_patient_certificates(session: Session, patient_id: int) -> list[CertificateView]:
    query = (
        select(VisitCertificate)
        .join(VisitCertificate.appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(VisitCertificate.requested_at.desc())
    )
    return [_certificate_view(certificate) for certificate in session.scalars(query)]


def pending_certificates(session: Session) -> list[CertificateView]:
    query = (
        select(VisitCertificate)
        .where(VisitCertificate.approved_at.is_(None))
        .order_by(VisitCertificate.requested_at)
    )
    return [_certificate_view(certificate) for certificate in session.scalars(query)]


def approve_certificate(session: Session, appointment_id: int, approved_by: int) -> CertificateView:
    certificate = session.get(
        VisitCertificate, appointment_id, with_for_update=True, populate_existing=True
    )
    if certificate is None:
        raise DomainError(404, "certificate_not_found", "Certificate request not found.")
    if certificate.approved_at is None:
        certificate.approved_at = now(session)
        certificate.approved_by = approved_by
        session.flush()
    return _certificate_view(certificate)


def approved_certificate(
    session: Session, appointment_id: int, patient_id: int
) -> VisitCertificate:
    _completed_visit(session, appointment_id, patient_id)
    certificate = session.get(VisitCertificate, appointment_id)
    if certificate is None:
        raise DomainError(404, "certificate_not_found", "Certificate request not found.")
    if certificate.approved_at is None:
        raise DomainError(409, "certificate_pending", "Proof of attendance is awaiting approval.")
    return certificate
