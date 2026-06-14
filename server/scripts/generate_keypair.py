"""Generate RSA keypair for κ-Proof signing.

Run once during setup. Keys go to server/keys/ (gitignored).
In prod: HSM-backed.
"""
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    keys_dir = Path("keys")
    keys_dir.mkdir(exist_ok=True)
    priv_path = keys_dir / "private_key.pem"
    pub_path = keys_dir / "public_key.pem"

    if priv_path.exists() or pub_path.exists():
        print(f"⚠ Keypair already exists at {priv_path} / {pub_path}.")
        print("  Delete them first if you really want to regenerate.")
        return

    print("Generating 2048-bit RSA keypair...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    priv_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    pub_path.write_bytes(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))

    print(f"✓ Private key: {priv_path}")
    print(f"✓ Public key:  {pub_path}")
    print()
    print("⚠ NEVER commit the private key. (.gitignore already excludes *.pem)")


if __name__ == "__main__":
    main()
