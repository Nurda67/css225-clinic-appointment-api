from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.errors import DomainError

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "clinic-appointment-api"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=30)
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: int, secret: str) -> str:
    issued_at = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_LIFETIME,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def get_token_user_id(token: str, secret: str) -> int:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["sub", "iss", "iat", "exp"]},
        )
        subject = claims["sub"]
        user_id = int(subject)
        if subject != str(user_id) or not 1 <= user_id <= 2_147_483_647:
            raise ValueError("Invalid user ID.")
    except (InvalidTokenError, TypeError, ValueError, OverflowError):
        raise DomainError(401, "invalid_token", "The bearer token is invalid or expired.") from None
    return user_id
