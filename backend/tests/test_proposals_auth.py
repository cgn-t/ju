"""SY ekip üyeliği ve devir önerisi onay yetkisi testleri.

İlke: bir devir önerisini yalnız domain sahibi SY ekibinin ÜYESİ veya admin
onaylar. Sahipsiz domain önerisi yalnız admin. Editör öneri üretebilir ama
kendi ekibi olmayan domainin devrini onaylayamaz.
"""

from datetime import datetime

from tests import certgen


def _import_pem(client, headers, pem_text, extra=None):
    files = {"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")}
    return client.post("/api/certificates/import", headers=headers, files=files, data=extra or {})


def _mk_user(client, admin, username, role="editor"):
    r = client.post("/api/users", headers=admin, json={
        "username": username, "password": "pw12345", "role": role, "auth_source": "local"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login(client, username, password="pw12345"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sy_team(client, admin, name):
    r = client.post("/api/teams", headers=admin, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _domain_with_sy(client, admin, name, sy_team_id):
    r = client.post("/api/domains", headers=admin, json={"domain": name, "sy_team_id": sy_team_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _setup_pending_proposal(client, admin, cn, sy_team_id):
    """Bir domain için v1 eşle, v2 import et → manuel supersede ile öneri üret. (proposal_id, v1, v2)."""
    ca, ca_key = certgen.make_ca(f"{cn} CA")
    v1, _ = certgen.make_leaf(ca, ca_key, cn, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, cn, not_before=datetime(2026, 4, 1))
    v1_id = next(c["id"] for c in _import_pem(client, admin, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    v2_id = _import_pem(client, admin, certgen.pem(v2)).json()[0]["id"]
    domain_id = _domain_with_sy(client, admin, cn, sy_team_id)
    client.post(f"/api/domains/{domain_id}/certificates", headers=admin,
                json={"certificate_id": v1_id, "mapping_type": "server"})
    r = client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=admin)
    assert r.json()["proposed"] == 1
    props = client.get("/api/proposals", headers=admin,
                       params={"status": "pending"}).json()
    prop = next(p for p in props if p["new_cert_id"] == v2_id and p["domain_id"] == domain_id)
    return prop["id"], v1_id, v2_id, domain_id


def test_membership_management(client, auth_headers):
    """Admin kullanıcıyı SY ekibine ekler/çıkarır; UserOut ekip bilgisini taşır."""
    uid = _mk_user(client, auth_headers, "member1")
    team_id = _sy_team(client, auth_headers, "TeamAlpha")
    # başta üye yok
    assert client.get(f"/api/teams/{team_id}/members", headers=auth_headers).json() == []
    # ekle
    r = client.post(f"/api/teams/{team_id}/members", headers=auth_headers, json={"user_id": uid})
    assert r.status_code == 200
    assert any(m["id"] == uid for m in r.json())
    # UserOut ekip bilgisi
    users = client.get("/api/users", headers=auth_headers).json()
    me = next(u for u in users if u["id"] == uid)
    assert team_id in me["sy_team_ids"] and "TeamAlpha" in me["sy_team_names"]
    # çıkar
    assert client.delete(f"/api/teams/{team_id}/members/{uid}",
                         headers=auth_headers).status_code == 200
    assert client.get(f"/api/teams/{team_id}/members", headers=auth_headers).json() == []
    # UG ekibine üyelik artık serbest (yalnız roster/bilgi amaçlı, rol vermez — bkz. test_rbac_derivation.py)
    r = client.post("/api/teams", headers=auth_headers, json={"name": "UGX", "type": "UG"})
    ug_id = r.json()["id"]
    assert client.post(f"/api/teams/{ug_id}/members", headers=auth_headers,
                       json={"user_id": uid}).status_code == 200


def test_non_member_cannot_approve_but_admin_and_member_can(client, auth_headers):
    team_id = _sy_team(client, auth_headers, "TeamBeta")
    prop_id, v1_id, v2_id, domain_id = _setup_pending_proposal(
        client, auth_headers, "beta.example.com", team_id)

    # Ekip üyesi OLMAYAN editör onaylayamaz (403)
    outsider = _mk_user(client, auth_headers, "outsider")
    oh = _login(client, "outsider")
    assert client.post(f"/api/proposals/{prop_id}/approve", headers=oh).status_code == 403
    # Görünürlük: hiçbir SY ekibine üye olmayan editör Devir Önerileri sayfasını hiç göremez
    # (varsayılan admin+allviewer-only; bkz. test_page_visibility.py)
    assert client.get("/api/proposals", headers=oh).status_code == 403

    # Ekibe üye edilen editör onaylayabilir
    member = _mk_user(client, auth_headers, "beta_member")
    client.post(f"/api/teams/{team_id}/members", headers=auth_headers, json={"user_id": member})
    mh = _login(client, "beta_member")
    visible = client.get("/api/proposals", headers=mh).json()
    assert any(p["id"] == prop_id and p["can_decide"] for p in visible)
    r = client.post(f"/api/proposals/{prop_id}/approve", headers=mh)
    assert r.status_code == 200, r.text
    # devir uygulandı
    assert client.get(f"/api/certificates/{v1_id}",
                      headers=auth_headers).json()["is_active"] is False


def test_ownerless_domain_proposal_admin_only(client, auth_headers):
    """SY sahibi olmayan domain önerisini yalnız admin onaylar."""
    # sy_team_id yok → sahipsiz
    ca, ca_key = certgen.make_ca("Ownerless CA")
    v1, _ = certgen.make_leaf(ca, ca_key, "ownerless.example.com", not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "ownerless.example.com", not_before=datetime(2026, 4, 1))
    v1_id = next(c["id"] for c in _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    v2_id = _import_pem(client, auth_headers, certgen.pem(v2)).json()[0]["id"]
    r = client.post("/api/domains", headers=auth_headers, json={"domain": "ownerless.example.com"})
    domain_id = r.json()["id"]
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": v1_id, "mapping_type": "server"})
    client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=auth_headers)
    prop = next(p for p in client.get("/api/proposals", headers=auth_headers).json()
                if p["domain_id"] == domain_id)
    assert prop["sy_team_id"] is None

    editor = _mk_user(client, auth_headers, "plain_editor")
    eh = _login(client, "plain_editor")
    assert client.post(f"/api/proposals/{prop['id']}/approve", headers=eh).status_code == 403
    # admin onaylayabilir
    assert client.post(f"/api/proposals/{prop['id']}/approve",
                       headers=auth_headers).status_code == 200


def test_deleting_certificate_clears_its_proposals(client, auth_headers):
    """Sertifika silinince ilgili devir önerileri de düşer (orphan öneri kalmaz)."""
    team_id = _sy_team(client, auth_headers, "TeamDelta")
    prop_id, v1_id, v2_id, domain_id = _setup_pending_proposal(
        client, auth_headers, "delta.example.com", team_id)
    assert any(p["id"] == prop_id for p in client.get("/api/proposals", headers=auth_headers).json())
    # yeni sertifikayı sil → öneri de gitmeli
    assert client.delete(f"/api/certificates/{v2_id}", headers=auth_headers).status_code == 200
    assert all(p["id"] != prop_id for p in client.get("/api/proposals", headers=auth_headers).json())
    # eski aktif kalır (devir hiç uygulanmadı)
    assert client.get(f"/api/certificates/{v1_id}",
                      headers=auth_headers).json()["is_active"] is True


def test_bypass_gates_detach_attach_and_ownership(client, auth_headers):
    """BAYPAS KAPATMA: SY sahibi domainin eşlemesini ekip-dışı editör ne detach/attach
    edebilir ne de sahipliği kendine geçirebilir (onay hattı atlanamaz)."""
    team_id = _sy_team(client, auth_headers, "TeamEpsilon")
    ca, ca_key = certgen.make_ca("Gate CA")
    a, _ = certgen.make_leaf(ca, ca_key, "gate.example.com", not_before=datetime(2026, 1, 1))
    b, _ = certgen.make_leaf(ca, ca_key, "gate.example.com", not_before=datetime(2026, 4, 1))
    a_id = next(c["id"] for c in _import_pem(client, auth_headers, certgen.pem(a) + certgen.pem(ca)).json()
                if c["cert_type"] == "leaf")
    b_id = _import_pem(client, auth_headers, certgen.pem(b)).json()[0]["id"]
    domain_id = _domain_with_sy(client, auth_headers, "gate.example.com", team_id)
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": a_id, "mapping_type": "server"})

    outsider = _mk_user(client, auth_headers, "gate_outsider")
    oh = _login(client, "gate_outsider")
    # ekip-dışı editör: detach 403
    assert client.delete(f"/api/domains/{domain_id}/certificates/{a_id}",
                         headers=oh, params={"mapping_type": "server"}).status_code == 403
    # ekip-dışı editör: attach 403
    assert client.post(f"/api/domains/{domain_id}/certificates", headers=oh,
                       json={"certificate_id": b_id, "mapping_type": "server"}).status_code == 403
    # ekip-dışı editör: sahipliği kendine geçirmeye çalışmak → 404 (kapsam kontrolü
    # sahiplik kontrolünden ÖNCE devreye girer: kapsam dışı kaydın varlığı dahi sızmaz)
    other_team = _sy_team(client, auth_headers, "TeamZeta")
    client.post(f"/api/teams/{other_team}/members", headers=auth_headers, json={"user_id": outsider})
    assert client.put(f"/api/domains/{domain_id}", headers=oh,
                      json={"domain": "gate.example.com", "sy_team_id": other_team}).status_code == 404
    # domain hâlâ a'ya eşli, sahibi değişmedi
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [a_id]
    assert dom["sy_team"]["id"] == team_id


def test_ownerless_manual_mutation_admin_only_matches_approval(client, auth_headers):
    """Sahipsiz domainde elle eşleme mutasyonu da (onay yoluyla tutarlı) yalnız admin;
    editör detach/attach ile sahipsiz devrin admin-onayını atlayamaz."""
    ca, ca_key = certgen.make_ca("Ownerless Gate CA")
    a, _ = certgen.make_leaf(ca, ca_key, "own-gate.example.com", not_before=datetime(2026, 1, 1))
    a_id = next(c["id"] for c in _import_pem(client, auth_headers, certgen.pem(a) + certgen.pem(ca)).json()
                if c["cert_type"] == "leaf")
    # sy_team_id YOK → sahipsiz
    domain_id = client.post("/api/domains", headers=auth_headers,
                            json={"domain": "own-gate.example.com"}).json()["id"]
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": a_id, "mapping_type": "server"})
    editor = _mk_user(client, auth_headers, "own_editor")
    eh = _login(client, "own_editor")
    # sahipsiz domainde editör detach edemez (admin şartı — onay yoluyla tutarlı)
    assert client.delete(f"/api/domains/{domain_id}/certificates/{a_id}",
                         headers=eh, params={"mapping_type": "server"}).status_code == 403


def test_pause_plus_attach_still_creates_proposal(client, auth_headers):
    """pause+attach baypası: eski cert pasife alınsa bile eşli olduğu sürece yeni
    eşleme çakışma sayılır ve öneri üretir (is_active filtresi yok)."""
    team_id = _sy_team(client, auth_headers, "TeamEta")
    ca, ca_key = certgen.make_ca("Pause CA")
    a, _ = certgen.make_leaf(ca, ca_key, "pause.example.com", not_before=datetime(2026, 1, 1))
    b, _ = certgen.make_leaf(ca, ca_key, "pause.example.com", not_before=datetime(2026, 4, 1))
    a_id = next(c["id"] for c in _import_pem(client, auth_headers, certgen.pem(a) + certgen.pem(ca)).json()
                if c["cert_type"] == "leaf")
    b_id = _import_pem(client, auth_headers, certgen.pem(b)).json()[0]["id"]
    domain_id = _domain_with_sy(client, auth_headers, "pause.example.com", team_id)
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": a_id, "mapping_type": "server"})
    # A'yı pasife al (pause) — hâlâ eşli
    client.put(f"/api/certificates/{a_id}", headers=auth_headers, json={"is_active": False})
    # B'yi eklemek yine DEVİR → 202 öneri (is_active filtresi yok)
    r = client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                    json={"certificate_id": b_id, "mapping_type": "server"})
    assert r.status_code == 202 and r.json()["status"] == "proposal_created"


def test_reject_keeps_old_active_and_double_decision_conflicts(client, auth_headers):
    team_id = _sy_team(client, auth_headers, "TeamGamma")
    prop_id, v1_id, v2_id, domain_id = _setup_pending_proposal(
        client, auth_headers, "gamma.example.com", team_id)
    # reddet → hiçbir devir olmaz, eski aktif kalır
    assert client.post(f"/api/proposals/{prop_id}/reject", headers=auth_headers).status_code == 200
    assert client.get(f"/api/certificates/{v1_id}",
                      headers=auth_headers).json()["is_active"] is True
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [v1_id]
    # ikinci karar (approve) çakışır: zaten karara bağlanmış
    assert client.post(f"/api/proposals/{prop_id}/approve",
                       headers=auth_headers).status_code == 409


def test_cancel_cannot_override_decided_proposal(client, auth_headers):
    """Bug #3 regresyonu: karara bağlanmış (applied/rejected) öneri CANCEL ile EZİLEMEZ (409).
    cancel artık approve/reject gibi atomik CAS kullanır (WHERE status IN pending/approved).
    (Gerçek eşzamanlı yarış SQLite tek-bağlantıda deterministik test edilemez — bu, sözleşmeyi
    ve status-guard'ı korur; yarış güvenliği yapısaldır.)"""
    h = auth_headers
    # (a) approve → applied: cancel 409 döner ve devir mutasyonu bozulmaz
    ta = _sy_team(client, h, "TeamCancelA")
    pid, v1, v2, dom = _setup_pending_proposal(client, h, "cancel-a.example.com", ta)
    assert client.post(f"/api/proposals/{pid}/approve", headers=h).status_code == 200
    assert client.post(f"/api/proposals/{pid}/cancel", headers=h).status_code == 409
    d = client.get(f"/api/domains/{dom}", headers=h).json()
    assert [c["certificate_id"] for c in d["certificates"] if c["mapping_type"] == "server"] == [v2]
    assert client.get(f"/api/certificates/{v1}", headers=h).json()["is_active"] is False

    # (b) reject → rejected: cancel 409 döner ve durum 'rejected' KALIR (red-kalıcılığı ezilmez)
    tb = _sy_team(client, h, "TeamCancelB")
    pid2, _, _, _ = _setup_pending_proposal(client, h, "cancel-b.example.com", tb)
    assert client.post(f"/api/proposals/{pid2}/reject", headers=h).status_code == 200
    assert client.post(f"/api/proposals/{pid2}/cancel", headers=h).status_code == 409
    rejected = client.get("/api/proposals", headers=h, params={"status": "rejected"}).json()
    assert any(p["id"] == pid2 for p in rejected), "öneri 'rejected' kalmalı (cancel ezmemeli)"


def test_out_of_team_editor_cannot_cancel_auto_proposal(client, auth_headers):
    """Bug #6 regresyonu: import(supersede) ile OTOMATİK üretilen öneride created_by tetikleyen
    editördür ama kapsam yoktur. Kapsam-dışı editör bu öneriyi (created_by=kendisi olsa da)
    İPTAL EDEMEZ — created_by istisnası yalnız via='manual'da geçerli."""
    team_y = _sy_team(client, auth_headers, "TeamY6")
    ca, ca_key = certgen.make_ca("Bug6 CA")
    key = certgen.make_key()                                   # ortak anahtar → halef sinyali
    v1, _ = certgen.make_leaf(ca, ca_key, "bug6.example.com", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "bug6.example.com", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import_pem(client, auth_headers,
                 certgen.pem(v1) + certgen.pem(ca)).json() if c["cert_type"] == "leaf")
    dom_id = _domain_with_sy(client, auth_headers, "bug6.example.com", team_y)
    client.post(f"/api/domains/{dom_id}/certificates", headers=auth_headers,
                json={"certificate_id": v1_id, "mapping_type": "server"})

    # kapsam-dışı editör E: v2'yi supersede ile import → öneri created_by=E, sy_team=Y, via=import
    _mk_user(client, auth_headers, "e_outsider6")
    eh = _login(client, "e_outsider6")
    v2_id = _import_pem(client, eh, certgen.pem(v2), extra={"supersede": "true"}).json()[0]["id"]
    prop = next(p for p in client.get("/api/proposals", headers=auth_headers,
                                      params={"status": "pending"}).json()
                if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id)
    assert prop["created_by"] == "e_outsider6" and prop["via"] == "import"

    # E, created_by=kendisi olsa da iptal EDEMEZ (403) — otomatik öneri, kapsam yok
    assert client.post(f"/api/proposals/{prop['id']}/cancel", headers=eh).status_code == 403
    still = client.get("/api/proposals", headers=auth_headers, params={"status": "pending"}).json()
    assert any(p["id"] == prop["id"] for p in still), "öneri iptal edilmemeli"


def test_manual_creator_can_cancel_own_cross_team_proposal(client, auth_headers):
    """Fix aşırı-kısıtlamamalı: MANUEL supersede oluşturanı, ÜYE OLMADIĞI bir granülün önerisini de
    (via='manual' + created_by) iptal edebilir — kendi tetiklediği hatalı öneriyi geri alma korunur."""
    ty = _sy_team(client, auth_headers, "TeamY6b")
    tz = _sy_team(client, auth_headers, "TeamZ6b")
    ca, ca_key = certgen.make_ca("Bug6b CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "bug6b.example.com", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "bug6b.example.com", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import_pem(client, auth_headers,
                 certgen.pem(v1) + certgen.pem(ca)).json() if c["cert_type"] == "leaf")
    v2_id = _import_pem(client, auth_headers, certgen.pem(v2)).json()[0]["id"]
    dy = _domain_with_sy(client, auth_headers, "dy6b.example.com", ty)
    dz = _domain_with_sy(client, auth_headers, "dz6b.example.com", tz)
    for d in (dy, dz):                                          # v1 iki domaine de server eşli
        client.post(f"/api/domains/{d}/certificates", headers=auth_headers,
                    json={"certificate_id": v1_id, "mapping_type": "server"})

    uid = _mk_user(client, auth_headers, "e_member6b")          # yalnız TeamY üyesi
    client.post(f"/api/teams/{ty}/members", headers=auth_headers, json={"user_id": uid})
    eh = _login(client, "e_member6b")
    # E manuel supersede tetikler (v1 TeamY'ye bağlı → yetkili) → P_Y ve P_Z (via=manual, created_by=E)
    assert client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=eh).status_code == 200
    props = client.get("/api/proposals", headers=auth_headers, params={"status": "pending"}).json()
    p_z = next(p for p in props if p["new_cert_id"] == v2_id and p["domain_id"] == dz)
    assert p_z["sy_team_id"] == tz and p_z["via"] == "manual" and p_z["created_by"] == "e_member6b"
    # E TeamZ üyesi DEĞİL ama KENDİ manuel önerisini iptal edebilir (200)
    assert client.post(f"/api/proposals/{p_z['id']}/cancel", headers=eh).status_code == 200
