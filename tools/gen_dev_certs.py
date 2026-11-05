"""Sinh CA tự ký và chứng chỉ server cho Mosquitto TLS ở môi trường dev (đa nền tảng).

Dùng:
    python -m tools.gen_dev_certs [LAN_IP]

Kết quả: deploy/certs/{ca.crt, ca.key, server.crt, server.key}.
"""

import ipaddress
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _gen_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    path.write_bytes(pem)


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    lan_ip = args[0] if args else None

    certs_dir = Path(__file__).resolve().parents[1] / "deploy" / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)

    ca_key_path = certs_dir / "ca.key"
    ca_crt_path = certs_dir / "ca.crt"

    if ca_key_path.exists() and ca_crt_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        assert isinstance(ca_key, rsa.RSAPrivateKey)
        ca_cert = x509.load_pem_x509_certificate(ca_crt_path.read_bytes())
    else:
        ca_key = _gen_key()
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GreenHub Dev CA")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        _write_key(ca_key_path, ca_key)
        _write_cert(ca_crt_path, ca_cert)

    sans: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName("mosquitto"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if lan_ip:
        sans.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))

    srv_key = _gen_key()
    srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(srv_name)
        .issuer_name(ca_cert.subject)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(certs_dir / "server.key", srv_key)
    _write_cert(certs_dir / "server.crt", srv_cert)
    print(f"Đã tạo chứng chỉ dev trong {certs_dir}")


if __name__ == "__main__":
    main()
