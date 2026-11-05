"""Sinh cặp khoá VAPID cho Web Push: python -m tools.gen_vapid

In ra VAPID_PUBLIC_KEY (base64url, dạng applicationServerKey) và VAPID_PRIVATE_KEY để chép vào .env.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_numbers().private_value.to_bytes(32, "big")
    pub = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print(f"VAPID_PUBLIC_KEY={_b64url(pub)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(priv)}")


if __name__ == "__main__":
    main()

