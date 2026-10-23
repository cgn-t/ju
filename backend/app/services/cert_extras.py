"""Kayıtlı PEM'den, DB'de kolonu olmayan ek teknik bilgileri okur (sertifika detay ekranı için).

Hiçbir şey yazılmaz; her istekte PEM'den hesaplanır. Bu yüzden eski kayıtlarda da çalışır,
PEM'i olmayan kayıtta None döner.
"""

import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

# CA/Browser Forum doğrulama tipi politika OID'leri
_VALIDATION_OIDS = {
    "2.23.140.1.1": "EV",
    "2.23.140.1.2.3": "IV",
    "2.23.140.1.2.2": "OV",
    "2.23.140.1.2.1": "DV",
}

_KEY_USAGE_FLAGS = [
    ("digital_signature", "digitalSignature"), ("content_commitment", "nonRepudiation"),
    ("key_encipherment", "keyEncipherment"), ("data_encipherment", "dataEncipherment"),
    ("key_agreement", "keyAgreement"), ("key_cert_sign", "keyCertSign"), ("crl_sign", "cRLSign"),
]


def _ext(cert: x509.Certificate, oid):
    try:
        return cert.extensions.get_extension_for_oid(oid)
    except x509.ExtensionNotFound:
        return None
    except ValueError:  # bozuk/desteklenmeyen uzantı: o alanı boş geç
        return None


def _key_usage(ku: x509.KeyUsage) -> list[str]:
    out = [label for attr, label in _KEY_USAGE_FLAGS if getattr(ku, attr)]
    if ku.key_agreement:  # encipher/decipher_only yalnız keyAgreement açıkken okunabilir
        if ku.encipher_only:
            out.append("encipherOnly")
        if ku.decipher_only:
            out.append("decipherOnly")
    return out


def pem_extras(pem: str | None) -> dict | None:
    if not pem:
        return None
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
    except ValueError:
        return None

    spki = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    out: dict = {
        "spki_pin_sha256": base64.b64encode(hashlib.sha256(spki).digest()).decode(),
        "signature_algorithm": getattr(cert.signature_algorithm_oid, "_name", None)
                               or cert.signature_algorithm_oid.dotted_string,
        "validation_type": None, "policy_oids": [],
        "ocsp_urls": [], "ca_issuers_urls": [], "crl_urls": [],
        "key_usage": [], "basic_constraints_ca": None, "basic_constraints_path_length": None,
        "sct_count": None,
    }

    pol = _ext(cert, ExtensionOID.CERTIFICATE_POLICIES)
    if pol:
        oids = [p.policy_identifier.dotted_string for p in pol.value]
        out["policy_oids"] = oids
        for oid, label in _VALIDATION_OIDS.items():  # en güçlü tip önce
            if oid in oids:
                out["validation_type"] = label
                break

    aia = _ext(cert, ExtensionOID.AUTHORITY_INFORMATION_ACCESS)
    if aia:
        for d in aia.value:
            if not isinstance(d.access_location, x509.UniformResourceIdentifier):
                continue
            if d.access_method == AuthorityInformationAccessOID.OCSP:
                out["ocsp_urls"].append(d.access_location.value)
            elif d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
                out["ca_issuers_urls"].append(d.access_location.value)

    cdp = _ext(cert, ExtensionOID.CRL_DISTRIBUTION_POINTS)
    if cdp:
        for dp in cdp.value:
            for n in dp.full_name or []:
                if isinstance(n, x509.UniformResourceIdentifier):
                    out["crl_urls"].append(n.value)

    ku = _ext(cert, ExtensionOID.KEY_USAGE)
    if ku:
        out["key_usage"] = _key_usage(ku.value)

    bc = _ext(cert, ExtensionOID.BASIC_CONSTRAINTS)
    if bc:
        out["basic_constraints_ca"] = bc.value.ca
        out["basic_constraints_path_length"] = bc.value.path_length

    sct = _ext(cert, ExtensionOID.PRECERT_SIGNED_CERTIFICATE_TIMESTAMPS)
    out["sct_count"] = len(sct.value) if sct else 0
    return out
