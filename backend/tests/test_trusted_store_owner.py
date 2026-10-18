"""Trust store sahiplik ve pasif sertifika kuralları (v3.8.7, sahibin 2026-10-18 kararları).

- Uygulamanın SY ekibi editörü, yalnız KENDİ trust store'unda duran sertifika için değişiklik
  talebi açabilir; talebi onaylar, eskiyi trust store'dan silip yenisini ekleyebilir.
- Başka ekibin editörü aynı talebi açamaz.
- Pasif sertifika trust store'a eklenemez.
"""

from tests import certgen
from tests.test_proposals_auth import _app, _import_pem, _login, _mk_user, _sy_team


def _leaf_id(client, h, pem_text, name):
    r = _import_pem(client, h, pem_text)
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["name"] == name)


def test_trusted_only_team_editor_can_propose_and_replace(client, auth_headers):
    h = auth_headers
    ca, ck = certgen.make_ca("TS Owner CA")
    old, _ = certgen.make_leaf(ca, ck, "ts-owner.example")
    new, _ = certgen.make_leaf(ca, ck, "ts-owner.example")
    old_id = _leaf_id(client, h, certgen.pem(old) + certgen.pem(ca), "ts-owner.example")
    new_id = _leaf_id(client, h, certgen.pem(new), "ts-owner.example")

    team = _sy_team(client, h, "TS Sahip SY")
    other = _sy_team(client, h, "TS Diger SY")
    app_id = _app(client, h, "ts-owner-app", team)
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": old_id}).status_code == 200
    for uname, tid in (("ts_owner_ed", team), ("ts_other_ed", other)):
        uid = _mk_user(client, h, uname)
        assert client.post(f"/api/teams/{tid}/members", headers=h, json={"user_id": uid}).status_code == 200
    owner, outsider = _login(client, "ts_owner_ed"), _login(client, "ts_other_ed")

    assert client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=outsider).status_code == 403
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=owner)
    assert r.status_code == 200 and r.json()["proposed"] == 1, r.text
    pid = next(p["id"] for p in client.get("/api/proposals", headers=owner).json()
               if p["status"] == "pending" and p["kind"] == "trusted_add" and p["app_id"] == app_id)
    assert client.post(f"/api/proposals/{pid}/approve", headers=owner).status_code == 200

    rows = client.get(f"/api/applications/{app_id}/trusted", headers=owner).json()
    assert {t["cert_id"] for t in rows} == {old_id, new_id}
    old_row = next(t["id"] for t in rows if t["cert_id"] == old_id)
    assert client.delete(f"/api/applications/trusted/{old_row}", headers=owner).status_code == 200
    assert [t["cert_id"] for t in client.get(f"/api/applications/{app_id}/trusted",
                                             headers=owner).json()] == [new_id]


def test_passive_certificate_cannot_be_added_to_trust_store(client, auth_headers):
    h = auth_headers
    ca, ck = certgen.make_ca("TS Passive CA")
    leaf, _ = certgen.make_leaf(ca, ck, "ts-passive.example")
    cid = _leaf_id(client, h, certgen.pem(leaf) + certgen.pem(ca), "ts-passive.example")
    assert client.post(f"/api/certificates/{cid}/deactivate", headers=h).status_code == 200
    app_id = _app(client, h, "ts-passive-app", _sy_team(client, h, "TS Pasif SY"))
    r = client.post(f"/api/applications/{app_id}/trusted", headers=h, json={"certificate_id": cid})
    assert r.status_code == 400 and "Pasif" in r.json()["detail"]
