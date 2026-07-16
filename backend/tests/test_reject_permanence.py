"""Red kalıcılığı + manuel devir sahiplik/granül-onay kuralları.

1) SY'nin REDDETTİĞİ granül otomatik yollarla (backfill vb.) yeniden pending olamaz;
   yalnız bilinçli MANUEL tetik (supersede ucu) reddi yeniden açar.
2) Manuel devri yalnız sertifikanın bağlı olduğu domain/uygulamaların SY ekibi üyesi
   (veya admin) tetikler; her bağlantı granülünün onayı KENDİ sahibi ekibe gider.
"""

from datetime import datetime

from tests import certgen


def _import_pem(client, headers, pem_text, name="chain.pem"):
    files = {"file": (name, pem_text.encode(), "application/x-pem-file")}
    r = client.post("/api/certificates/import", headers=headers, files=files, data={})
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _sy_team(client, headers, name):
    r = client.post("/api/teams", headers=headers, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user_in(client, headers, username, team_id, role):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": role, "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=headers).json()
               if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=headers, json={"user_id": uid})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _editor_in(client, headers, username, team_id):
    return _user_in(client, headers, username, team_id, "editor")


def _domain(client, headers, name, team_id=None):
    r = client.post("/api/domains", headers=headers,
                    json={"domain": name, "sy_team_id": team_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(client, headers, domain_id, cert_id):
    r = client.post(f"/api/domains/{domain_id}/certificates", headers=headers,
                    json={"certificate_id": cert_id, "mapping_type": "server"})
    assert r.status_code == 200, r.text


def _pending(client, headers, old_id, new_id):
    return [p for p in client.get("/api/proposals", headers=headers,
                                  params={"status": "pending"}).json()
            if p["old_cert_id"] == old_id and p["new_cert_id"] == new_id]


def _cert_pair(cn):
    """Aynı anahtarla (SKI sinyali) eski+yeni leaf çifti."""
    ca, ca_key = certgen.make_ca(f"Red CA {cn}")
    key = certgen.make_key()
    old, _ = certgen.make_leaf(ca, ca_key, cn, key=key, not_before=datetime(2026, 1, 1))
    new, _ = certgen.make_leaf(ca, ca_key, cn, key=key, not_before=datetime(2026, 2, 1))
    return certgen.pem(old), certgen.pem(new)


def test_rejected_granule_not_resurrected_by_backfill(client, auth_headers):
    """BUG düzeltmesi: kısmi devirde (biri onaylı, biri reddedilmiş) superseded_by dolu +
    eski aktif kalır; açılış backfill'i reddedilen granülü YENİDEN pending yapmamalı."""
    old_pem, new_pem = _cert_pair("redkalici1.example.com")
    old_id = _import_pem(client, auth_headers, old_pem)
    new_id = _import_pem(client, auth_headers, new_pem)
    d1 = _domain(client, auth_headers, "redkalici1-a.example.com")
    d2 = _domain(client, auth_headers, "redkalici1-b.example.com")
    _attach(client, auth_headers, d1, old_id)
    _attach(client, auth_headers, d2, old_id)

    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 2, r.text
    props = _pending(client, auth_headers, old_id, new_id)
    p_d1 = next(p for p in props if p["domain_id"] == d1)
    p_d2 = next(p for p in props if p["domain_id"] == d2)

    # d1 onaylanır → superseded_by dolar; d2 REDDEDİLİR → eski, d2 için aktif kalır
    assert client.post(f"/api/proposals/{p_d1['id']}/approve",
                       headers=auth_headers).status_code == 200
    assert client.post(f"/api/proposals/{p_d2['id']}/reject",
                       headers=auth_headers).status_code == 200
    old_row = client.get(f"/api/certificates/{old_id}", headers=auth_headers).json()
    assert old_row["is_active"] is True and old_row["superseded_by_id"] == new_id

    # Açılış backfill'i (bug: her restart'ta reddedileni yeniden öneriyordu)
    from app.main import backfill_transfer_proposals
    backfill_transfer_proposals()
    assert _pending(client, auth_headers, old_id, new_id) == [], \
        "reddedilen granül backfill ile hortladı"

    # İkinci koşu da (idempotent) üretmemeli
    backfill_transfer_proposals()
    assert _pending(client, auth_headers, old_id, new_id) == []

    # Bilinçli MANUEL tetik ise reddi yeniden açar (tek kaçış yolu)
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 1, r.text
    reopened = _pending(client, auth_headers, old_id, new_id)
    assert [p["domain_id"] for p in reopened] == [d2]


def test_rejected_granule_not_resurrected_by_attach_collision(client, auth_headers):
    """BUG düzeltmesi (inceleme bulgusu): reddedilen granül, attach çakışması yoluyla da
    hortlamamalı — propose_attach_transfer rutin bir yoldur, redde saygı duyar (409)."""
    old_pem, new_pem = _cert_pair("redattach.example.com")
    old_id = _import_pem(client, auth_headers, old_pem)
    new_id = _import_pem(client, auth_headers, new_pem)
    d = _domain(client, auth_headers, "redattach.example.com")
    _attach(client, auth_headers, d, old_id)

    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 1
    p = _pending(client, auth_headers, old_id, new_id)[0]
    assert client.post(f"/api/proposals/{p['id']}/reject",
                       headers=auth_headers).status_code == 200

    # Aynı devri elle attach çakışmasıyla tetiklemek: red kalıcı → 409, yeni pending YOK
    r = client.post(f"/api/domains/{d}/certificates", headers=auth_headers,
                    json={"certificate_id": new_id, "mapping_type": "server"})
    assert r.status_code == 409, r.text
    assert _pending(client, auth_headers, old_id, new_id) == [], \
        "reddedilen granül attach çakışmasıyla hortladı"
    # Eski eşleme değişmedi (attach reddedildi, doğrudan taşınmadı)
    dom = client.get(f"/api/domains/{d}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [old_id]

    # Bilinçli manuel supersede hâlâ reddi yeniden açabilir (tek kaçış yolu korunur)
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 1


def test_manual_supersede_requires_binding_team_membership(client, auth_headers):
    """Editör devri yalnız KENDİ ekibinin kullandığı sertifika için tetikler."""
    team_a = _sy_team(client, auth_headers, "RedEkipA")
    team_b = _sy_team(client, auth_headers, "RedEkipB")
    hdr_a = _editor_in(client, auth_headers, "red_ed_a", team_a)
    hdr_b = _editor_in(client, auth_headers, "red_ed_b", team_b)

    old_pem, new_pem = _cert_pair("redsahip.example.com")
    old_id = _import_pem(client, auth_headers, old_pem)
    new_id = _import_pem(client, auth_headers, new_pem)
    d_a = _domain(client, auth_headers, "redsahip-a.example.com", team_a)
    _attach(client, auth_headers, d_a, old_id)

    # B ekibi üyesi: sertifikanın hiçbir bağlantısı B'ye ait değil → 403
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=hdr_b)
    assert r.status_code == 403, r.text
    # A ekibi üyesi: bağlantı kendi ekibinde → tetikler
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=hdr_a)
    assert r.status_code == 200 and r.json()["proposed"] == 1, r.text

    # Bağlantısız sertifika: editör 403 (devredilecek şey de yok), admin serbest (0 öneri)
    o2_pem, n2_pem = _cert_pair("redbos.example.com")
    o2 = _import_pem(client, auth_headers, o2_pem)
    n2 = _import_pem(client, auth_headers, n2_pem)
    assert client.post(f"/api/certificates/{n2}/supersede/{o2}",
                       headers=hdr_a).status_code == 403
    r = client.post(f"/api/certificates/{n2}/supersede/{o2}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 0


def test_manual_supersede_grants_go_to_each_owner_team(client, auth_headers):
    """Tetik SONRASI onaylar granül granül SAHİBİ ekiplere gider: A tetikler ama B'nin
    domain/uygulama granüllerini yalnız B (veya admin) onaylayabilir."""
    team_a = _sy_team(client, auth_headers, "RedGranulA")
    team_b = _sy_team(client, auth_headers, "RedGranulB")
    hdr_a = _editor_in(client, auth_headers, "red_gr_a", team_a)
    hdr_b = _editor_in(client, auth_headers, "red_gr_b", team_b)

    old_pem, new_pem = _cert_pair("redgranul.example.com")
    old_id = _import_pem(client, auth_headers, old_pem)
    new_id = _import_pem(client, auth_headers, new_pem)
    d_a = _domain(client, auth_headers, "redgranul-a.example.com", team_a)
    d_b = _domain(client, auth_headers, "redgranul-b.example.com", team_b)
    _attach(client, auth_headers, d_a, old_id)
    _attach(client, auth_headers, d_b, old_id)
    # B ekibinin uygulaması, d_b'ye client bağımlı → izlenen sertifika = old (d_b'nin server'ı)
    r = client.post("/api/applications", headers=auth_headers,
                    json={"app_name": "RedGranulApp", "server_name": "srv-redgranul",
                          "sy_team_id": team_b})
    app_id = r.json()["id"]
    r = client.post(f"/api/applications/{app_id}/dependencies", headers=auth_headers,
                    json={"target_domain_id": d_b})
    assert r.status_code == 200 and r.json()["client_cert_id"] == old_id, r.text

    # A üyesi tetikler (kendi bağlantısı var) → 3 granül: d_a(A), d_b(B), mTLS(B)
    r = client.post(f"/api/certificates/{new_id}/supersede/{old_id}", headers=hdr_a)
    assert r.status_code == 200 and r.json()["proposed"] == 3, r.text
    props = _pending(client, auth_headers, old_id, new_id)
    by_team = {team_a: [], team_b: []}
    for p in props:
        by_team[p["sy_team_id"]].append(p)
    assert len(by_team[team_a]) == 1 and len(by_team[team_b]) == 2

    # A, B'nin granülünü ONAYLAYAMAZ; kendi granülünü onaylar
    assert client.post(f"/api/proposals/{by_team[team_b][0]['id']}/approve",
                       headers=hdr_a).status_code == 403
    assert client.post(f"/api/proposals/{by_team[team_a][0]['id']}/approve",
                       headers=hdr_a).status_code == 200
    # B kendi granüllerini onaylar → devir tamamlanır, eski pasifleşir
    for p in by_team[team_b]:
        assert client.post(f"/api/proposals/{p['id']}/approve",
                           headers=hdr_b).status_code == 200
    old_row = client.get(f"/api/certificates/{old_id}", headers=auth_headers).json()
    assert old_row["is_active"] is False


def test_viewer_sy_member_cannot_approve_or_reject(client, auth_headers):
    """KRİTİK güvenlik: SY ekibine KAPSAM için eklenen 'viewer' (Ekip İzleyici, salt-okur)
    devir önerisini ONAYLAYAMAZ/REDDEDEMEZ — onay sertifika devrini uygular (yazma). Yalnız
    editor+/admin. can_decide de False dönmeli (UI butonu gizlensin)."""
    team = _sy_team(client, auth_headers, "ViewerApproveSY")
    # viewer + SY üyesi (kapsam için) — UI'nın önerdiği yapılandırma
    hv = _user_in(client, auth_headers, "vw_approver", team, "viewer")

    old_pem, new_pem = _cert_pair("vwapprove.example.com")
    old_id = _import_pem(client, auth_headers, old_pem)
    new_id = _import_pem(client, auth_headers, new_pem)
    d = _domain(client, auth_headers, "vwapprove.example.com", team)
    _attach(client, auth_headers, d, old_id)
    assert client.post(f"/api/certificates/{new_id}/supersede/{old_id}",
                       headers=auth_headers).json()["proposed"] == 1
    p = _pending(client, auth_headers, old_id, new_id)[0]

    # viewer onaylayamaz/reddedemez → 403
    assert client.post(f"/api/proposals/{p['id']}/approve", headers=hv).status_code == 403
    assert client.post(f"/api/proposals/{p['id']}/reject", headers=hv).status_code == 403
    # UI göstergesi: can_decide False
    seen = [x for x in client.get("/api/proposals", headers=hv,
                                  params={"status": "pending"}).json() if x["id"] == p["id"]]
    assert seen and seen[0]["can_decide"] is False
    # öneri hâlâ pending (viewer hiçbir şey uygulayamadı)
    assert _pending(client, auth_headers, old_id, new_id)

    # Aynı takımın EDİTÖRÜ onaylayabilir → 200 (devir uygulanır)
    he = _editor_in(client, auth_headers, "ed_approver", team)
    assert client.post(f"/api/proposals/{p['id']}/approve", headers=he).status_code == 200
