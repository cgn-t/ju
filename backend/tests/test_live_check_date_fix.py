"""v3.8.16: canlı doğrulama, sunulan sertifika envanterdeki kayıtla AYNI (fingerprint eşit) ama
kayıttaki tarih sertifikanınkinden farklıysa (eski uygulamadan kalan kayıt) "SÜRESİ DOLMUŞ"
demez; durumu sertifikanın kendi tarihine göre verir ve SY onayına TARİH GÜNCELLEME talebi açar."""
import json
from datetime import datetime

from app.db.models import Certificate, TransferProposal
from app.db.session import SessionLocal
from app.main import backfill_certificate_fields
from tests import certgen
from tests.test_renewal import _attach, _make_domain, _tls_server


def _legacy_row(name, cert, valid_from, valid_to):
    """Eski uygulamanın yazdığı gibi: PEM yeni sertifikanın, tarihler eskisinin."""
    db = SessionLocal()
    try:
        row = Certificate(name=name, pem_certificate=certgen.pem(cert), cert_type="leaf",
                          valid_from=valid_from, valid_to=valid_to, is_active=True)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _row(cid):
    db = SessionLocal()
    try:
        return db.get(Certificate, cid)
    finally:
        db.close()


def _date_props(cid):
    db = SessionLocal()
    try:
        return [(p.status, p.domain_id) for p in db.query(TransferProposal)
                .filter(TransferProposal.kind == "date_fix", TransferProposal.old_cert_id == cid)]
    finally:
        db.close()


def _setup(client, h, cn):
    ca, ca_key = certgen.make_ca(f"{cn} CA")
    leaf, key = certgen.make_leaf(ca, ca_key, cn, san=["localhost", "127.0.0.1"], days=2500)
    cid = _legacy_row(cn, leaf, datetime(2020, 6, 4), datetime(2022, 6, 4))
    backfill_certificate_fields()  # prod açılışı: fingerprint PEM'den dolar, tarih dokunulmaz
    return ca, leaf, key, cid


def _check(client, h, did):
    r = client.post(f"/api/domains/{did}/live-check", headers=h).json()
    return r["live_check_status"], json.loads(r["live_check_detail"])


def test_wrong_record_date_opens_date_fix_and_approval_fixes_it(client, auth_headers):
    h = auth_headers
    ca, leaf, key, cid = _setup(client, h, "tarih.example.com")
    real_to = leaf.not_valid_after_utc.replace(tzinfo=None)
    with _tls_server(certgen.pem(leaf) + certgen.pem(ca), certgen.key_pem(key)) as port:
        did = _make_domain(client, h, f"localhost:{port}(tarih)")
        assert _attach(client, h, did, cid).status_code == 200

        status, d = _check(client, h, did)
        # Sertifika gerçekte geçerli: "SÜRESİ DOLMUŞ" denmez
        assert "expired_served" not in d and "SÜRESİ DOLMUŞ" not in json.dumps(d, ensure_ascii=False)
        assert status != "mismatch"
        assert d["date_mismatch"][0]["record_valid_to"] == "04.06.2022"
        assert d["date_mismatch"][0]["cert_valid_to"] == real_to.strftime("%d.%m.%Y")
        assert "SY onayında" in d["date_note"]
        assert _date_props(cid) == [("pending", did)]

        # Tekrar doğrulama yeni talep açmaz
        _check(client, h, did)
        assert len(_date_props(cid)) == 1

        props = [p for p in client.get("/api/proposals", headers=h).json() if p["kind"] == "date_fix"
                 and p["new_cert_id"] == cid]
        assert len(props) == 1 and props[0]["domain_id"] == did
        assert props[0]["record_valid_to"].startswith("2022-06-04")
        assert props[0]["cert_valid_to"].startswith(real_to.strftime("%Y-%m-%d"))

        r = client.post(f"/api/proposals/{props[0]['id']}/approve", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "applied"
        assert _row(cid).valid_to == real_to
        assert _row(cid).valid_from == leaf.not_valid_before_utc.replace(tzinfo=None)
        assert _row(cid).is_active  # devir değil: sertifika pasife alınmaz, bağlantı yerinde

        status, d = _check(client, h, did)
        assert "date_mismatch" not in d and status == "match"

    items = client.get("/api/audit", headers=h, params={"action": "date_fix_apply"}).json()["items"]
    assert any(int(a["record_id"]) == cid for a in items)


def test_rejected_date_fix_is_not_reopened(client, auth_headers):
    h = auth_headers
    ca, leaf, key, cid = _setup(client, h, "tarih-red.example.com")
    with _tls_server(certgen.pem(leaf) + certgen.pem(ca), certgen.key_pem(key)) as port:
        did = _make_domain(client, h, f"localhost:{port}(tarih-red)")
        assert _attach(client, h, did, cid).status_code == 200
        _check(client, h, did)
        pid = next(p["id"] for p in client.get("/api/proposals", headers=h).json()
                   if p["kind"] == "date_fix" and p["new_cert_id"] == cid)
        assert client.post(f"/api/proposals/{pid}/reject", headers=h).status_code == 200
        status, d = _check(client, h, did)
        assert _date_props(cid) == [("rejected", did)]
        assert "reddedilmişti" in d["date_note"]
        assert _row(cid).valid_to == datetime(2022, 6, 4)  # red: hiçbir şey değişmez
        assert status != "mismatch"


def test_date_fix_reminder_mail_rows():
    from app.services.notifier import _proposal_label, _proposal_rows
    ca, ca_key = certgen.make_ca("Mail CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "tarih-mail.example.com", days=2500)
    cid = _legacy_row("tarih-mail.example.com", leaf, datetime(2020, 6, 4), datetime(2022, 6, 4))
    db = SessionLocal()
    try:
        p = TransferProposal(old_cert_id=cid, new_cert_id=cid, kind="date_fix", status="pending",
                             via="live-check", created_by="system")
        db.add(p)
        db.flush()
        rows = dict(_proposal_rows(p))
        assert _proposal_label(p) == "Tarih güncelleme: tarih-mail.example.com"
        assert rows["Talep Türü"] == "Tarih Güncelleme"
        assert rows["Kayıttaki Bitiş"] == datetime(2022, 6, 4)
        assert rows["Sertifikadaki Bitiş"] == leaf.not_valid_after_utc.replace(tzinfo=None)
        db.rollback()
    finally:
        db.close()
