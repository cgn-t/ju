import pytest

from app.services import cert_parser


def test_parse_fullchain_pem(fixtures_dir):
    data = (fixtures_dir / "fullchain.pem").read_bytes()
    parsed = cert_parser.parse_upload(data)
    assert len(parsed) == 3
    types = {p.cert_type for p in parsed}
    assert types == {"root", "intermediate", "leaf"}
    leaf = next(p for p in parsed if p.cert_type == "leaf")
    assert leaf.name == "*.jumbo-test.com"
    assert leaf.serial_number
    assert leaf.subject_key_identifier
    assert leaf.authority_key_identifier
    assert "serverAuth" in (leaf.extended_key_usage or "")
    assert "*.jumbo-test.com" in (leaf.san or "")
    assert len(leaf.fingerprint_sha256.split(":")) == 32  # SHA-256 = 32 bayt
    # Fingerprint her sertifika için farklı olmalı
    assert len({p.fingerprint_sha256 for p in parsed}) == 3


def test_parse_der(fixtures_dir):
    data = (fixtures_dir / "leaf.der").read_bytes()
    parsed = cert_parser.parse_upload(data)
    assert len(parsed) == 1
    assert parsed[0].cert_type == "leaf"


def test_chain_linking_via_ski_aki(fixtures_dir):
    data = (fixtures_dir / "fullchain.pem").read_bytes()
    parsed = cert_parser.parse_upload(data)
    root = next(p for p in parsed if p.cert_type == "root")
    inter = next(p for p in parsed if p.cert_type == "intermediate")
    leaf = next(p for p in parsed if p.cert_type == "leaf")
    assert inter.authority_key_identifier == root.subject_key_identifier
    assert leaf.authority_key_identifier == inter.subject_key_identifier


def test_parse_p7b_pem_and_der(fixtures_dir):
    for name in ("chain.p7b", "chain-der.p7b"):
        parsed = cert_parser.parse_upload((fixtures_dir / name).read_bytes())
        assert {p.cert_type for p in parsed} == {"root", "intermediate", "leaf"}, name


def test_invalid_data_raises():
    with pytest.raises(ValueError):
        cert_parser.parse_upload(b"bu bir sertifika degil")
