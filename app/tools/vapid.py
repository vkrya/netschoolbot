"""Генерация VAPID-ключей для push-уведомлений.

    python -m app.tools.vapid
"""

from __future__ import annotations

import base64


def generate() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()

    private_bytes = private.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = public.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return encode(public_bytes), encode(private_bytes)


def main() -> int:
    public, private = generate()
    print("Добавьте в .env:\n")
    print(f"NETSCHOOL_VAPID_PUBLIC_KEY={public}")
    print(f"NETSCHOOL_VAPID_PRIVATE_KEY={private}")
    print("\nПриватный ключ никому не показывайте.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
