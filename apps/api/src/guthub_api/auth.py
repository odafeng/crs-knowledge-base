"""Supabase access-token verification (D1 #67, ADR-0020).

Tokens arrive only as `Authorization: Bearer`; cookies are never read, so a cross-site request cannot act for a user.
Signatures are checked against the project's Auth JWKS (asymmetric keys only, so a token signed with a shared secret or
`alg: none` is refused). Identity is the `sub` claim; roles never come from user or app metadata (see accounts.py).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request

ALGORITHMS = ["ES256", "RS256"]

type KeyLookup = Callable[[str], Any]


@dataclass(frozen=True)
class User:
    id: UUID


class TokenVerifier:
    def __init__(self, issuer: str, key_for: KeyLookup) -> None:
        self.issuer = issuer
        self._key_for = key_for

    @classmethod
    def for_supabase(cls, supabase_url: str) -> "TokenVerifier":
        issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        # Keys are cached and refetched when a token names an unknown kid, so key rotation needs no restart.
        keys = jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=5)
        return cls(issuer, lambda token: keys.get_signing_key_from_jwt(token).key)

    def verify(self, token: str) -> User:
        try:
            claims = jwt.decode(
                token,
                self._key_for(token),
                algorithms=ALGORITHMS,
                audience="authenticated",
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(status_code=503, detail="Sign-in service unavailable") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
        if claims.get("role") != "authenticated":
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        # Anonymous sign-in is off (ADR-0017); checked anyway so enabling it later cannot grant account rights.
        if claims.get("is_anonymous") is True:
            raise HTTPException(status_code=403, detail="Sign in with an account to continue")
        try:
            return User(UUID(claims["sub"]))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def current_user(request: Request) -> User:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in required")
    verifier: TokenVerifier | None = request.app.state.verifier
    if verifier is None:
        raise HTTPException(status_code=503, detail="Sign-in is not configured")
    return verifier.verify(token.strip())
