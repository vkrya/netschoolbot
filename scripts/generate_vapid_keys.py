#!/usr/bin/env python3
"""Генерация VAPID-ключей для web push мини-приложения.

    python scripts/generate_vapid_keys.py

Полученные значения запишите в .env как NETSCHOOL_VAPID_PUBLIC_KEY
и NETSCHOOL_VAPID_PRIVATE_KEY.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def main() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    print("NETSCHOOL_VAPID_PUBLIC_KEY=" + b64(public_bytes))
    print("NETSCHOOL_VAPID_PRIVATE_KEY=" + b64(private_value.to_bytes(32, "big")))


if __name__ == "__main__":
    main()
