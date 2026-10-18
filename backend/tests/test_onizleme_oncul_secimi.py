"""İçe aktarma önizlemesi: aynı CN + aynı CA'lı birden çok eski sertifika (v3.8.12).

Jumbo hangi eskinin yerine geçildiğini bilemez; önizleme TÜM adayları bağlantılarıyla
döndürür, arayüz kullanıcıya seçtirir ve talep yalnız seçilen eski için açılır.
"""

from datetime import datetime

from tests import certgen


def _upload(client, h, url, pem_text):
    return client.post(url, headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")})


def _bind(client, h, domain, cert_id):
    did = client.post("/api/domains", headers=h, json={"domain": domain}).json()["id"]
    r = client.post(f"/api/domains/{did}/certificates", headers=h,
                    json={"certificate_id": cert_id, "mapping_type": "server"})
    assert r.status_code == 200, r.text


def test_preview_lists_all_candidates_and_supersede_uses_chosen(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("Coklu Oncul CA")
    # İki sunucu, aynı CN ve CA, farklı anahtar ve bitiş
    a, _ = certgen.make_leaf(ca, ca_key, "coklu.test", not_before=datetime(2026, 1, 1), days=500)
    b, _ = certgen.make_leaf(ca, ca_key, "coklu.test", not_before=datetime(2026, 2, 1), days=200)
    ids = {}
    for name, cert in (("a", a), ("b", b)):
        r = _upload(client, h, "/api/certificates/import", certgen.pem(cert) + certgen.pem(ca))
        assert r.status_code == 200, r.text
        ids[name] = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    _bind(client, h, "coklu-a.test:443", ids["a"])
    _bind(client, h, "coklu-b.test:443", ids["b"])

    new, _ = certgen.make_leaf(ca, ca_key, "coklu.test", not_before=datetime(2026, 6, 1))
    row = _upload(client, h, "/api/certificates/import/preview", certgen.pem(new)).json()[0]
    cands = row["renewal_candidates"]
    assert [c["id"] for c in cands] == [ids["a"], ids["b"]]  # bitişi en geç önce
    assert cands[0]["domains"] == ["coklu-a.test:443 (server)"]
    assert cands[1]["domains"] == ["coklu-b.test:443 (server)"]
    assert all(c["signal"] == "subject" for c in cands)
    assert row["renewal_of_id"] == ids["a"]  # geriye uyum: ilk aday

    # Kullanıcı b'yi seçti: talep yalnız b'nin bağlantısı için açılır
    r = _upload(client, h, "/api/certificates/import", certgen.pem(new))
    new_id = r.json()[0]["id"]
    r = client.post(f"/api/certificates/{new_id}/supersede/{ids['b']}", headers=h)
    assert r.status_code == 200 and r.json()["proposed"] == 1, r.text
    pending = client.get("/api/proposals", headers=h).json()
    pending = pending.get("items", pending) if isinstance(pending, dict) else pending
    mine = [p for p in pending if p.get("new_cert_id") == new_id]
    assert [p["old_cert_id"] for p in mine] == [ids["b"]]


def test_single_candidate_preview_unchanged(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("Tek Oncul CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "tek-oncul.test", key=key, not_before=datetime(2026, 1, 1))
    v1_id = next(c["id"] for c in _upload(client, h, "/api/certificates/import",
                                           certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    v2, _ = certgen.make_leaf(ca, ca_key, "tek-oncul.test", key=key, not_before=datetime(2026, 6, 1))
    row = _upload(client, h, "/api/certificates/import/preview", certgen.pem(v2)).json()[0]
    assert row["renewal_of_id"] == v1_id and row["renewal_signal"] == "ski"
    assert [c["id"] for c in row["renewal_candidates"]] == [v1_id]
    assert row["renewal_also"] == []
