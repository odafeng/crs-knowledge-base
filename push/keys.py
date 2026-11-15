"""Make the VAPID key pair, once.  python -m push.keys

The public key goes into the site build (PUSH_PUBLIC_KEY, not a secret).
The private key goes into the repository secrets (VAPID_PRIVATE_KEY) and nowhere else.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    """(public key, private key), both base64url as the Web Push libraries expect them."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


if __name__ == "__main__":
    public, private = generate()
    print(f"PUSH_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
