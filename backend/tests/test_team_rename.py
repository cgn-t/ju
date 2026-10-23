"""Ekip adı değişince sertifikaların 'Oluşturan Ekip' alanı da yeni adı alır (v3.9.4).

'Oluşturan Ekip' SY ekibinin ADINI metin olarak tutar; sahiplik maili ve düzenleme yetkisi bu adla
eşleşir. Ad değişip sertifikalar eski adda kalsaydı ekip kendi sertifikasından kopardı."""

from app.db.models import AuditLog, Certificate, Team
from app.db.session import SessionLocal


def _team(db, name):
    t = Team(name=name, type="SY")
    db.add(t)
    db.commit()
    return t.id


def _cert(db, name, creator):
    c = Certificate(name=name, creator=creator, serial_number=name, is_active=True)
    db.add(c)
    db.commit()
    return c.id


def test_rename_moves_certificate_creator(client, auth_headers):
    db = SessionLocal()
    try:
        team_id = _team(db, "BBB")
        own = _cert(db, "bbb-sertifika", "BBB")
        other = _cert(db, "baska-sertifika", "BAŞKA")
    finally:
        db.close()
    r = client.put(f"/api/teams/{team_id}", headers=auth_headers, json={"name": "SY-BBB"})
    assert r.status_code == 200, r.text and r.json()["name"] == "SY-BBB"
    db = SessionLocal()
    try:
        assert db.get(Certificate, own).creator == "SY-BBB"
        assert db.get(Certificate, other).creator == "BAŞKA"
        log = (db.query(AuditLog).filter(AuditLog.table_name == "teams", AuditLog.record_id == team_id)
               .order_by(AuditLog.id.desc()).first())
        assert "certificates_creator_renamed" in (log.details or "")
    finally:
        db.close()


def test_rename_to_existing_or_empty_name_is_rejected(client, auth_headers):
    db = SessionLocal()
    try:
        a = _team(db, "Ekip-A")
        _team(db, "Ekip-B")
    finally:
        db.close()
    r = client.put(f"/api/teams/{a}", headers=auth_headers, json={"name": "ekip-b"})
    assert r.status_code == 400 and "zaten var" in r.json()["detail"]
    assert client.put(f"/api/teams/{a}", headers=auth_headers, json={"name": "  "}).status_code == 400
    # yalnız e-posta değişimi adı ellemez
    assert client.put(f"/api/teams/{a}", headers=auth_headers, json={"email": "a@x.local"}).json()["name"] == "Ekip-A"
