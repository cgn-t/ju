"""SY kapsam kısıtı — MUTASYON uçları (IDOR koruması).

Kural: SY editör yalnız KENDİ ekiplerinin domain/uygulamasını görür VE değiştirir.
Kapsam dışı kayda PUT/DELETE, GET detail ile aynı 404'ü döndürür (varlık dahi sızmaz).
Sahiplik (sy/ug ekip) değişimi ve kapsam dışı bağımlılık hedefi ayrıca kilitlidir.
"""


def _sy_team(client, headers, name):
    r = client.post("/api/teams", headers=headers, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _editor_in(client, headers, username, team_id):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": "editor", "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=headers).json()
               if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=headers, json={"user_id": uid})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _setup(client, auth_headers, tag):
    """İki SY ekibi + her birine bir domain ve bir uygulama; 1. ekibe bir editör."""
    own = _sy_team(client, auth_headers, f"KapsamOwn{tag}")
    other = _sy_team(client, auth_headers, f"KapsamOther{tag}")
    hdr = _editor_in(client, auth_headers, f"kapsam_ed_{tag}", own)
    ids = {}
    for key, team in (("own", own), ("other", other)):
        r = client.post("/api/domains", headers=auth_headers,
                        json={"domain": f"kapsam-{key}-{tag}.local", "sy_team_id": team})
        assert r.status_code == 200, r.text
        ids[f"dom_{key}"] = r.json()["id"]
        r = client.post("/api/applications", headers=auth_headers,
                        json={"app_name": f"KapsamApp-{key}-{tag}",
                              "server_name": f"srv-{key}-{tag}", "sy_team_id": team})
        assert r.status_code == 200, r.text
        ids[f"app_{key}"] = r.json()["id"]
    return own, other, hdr, ids


def test_editor_cannot_update_or_delete_foreign_domain(client, auth_headers):
    own, other, hdr, ids = _setup(client, auth_headers, "d1")

    # Kapsam dışı domain: boş PUT bile 404 — veri okunamaz (IDOR read)
    r = client.put(f"/api/domains/{ids['dom_other']}", headers=hdr, json={})
    assert r.status_code == 404, r.text
    r = client.put(f"/api/domains/{ids['dom_other']}", headers=hdr, json={"info": "ele geçti"})
    assert r.status_code == 404, r.text
    r = client.delete(f"/api/domains/{ids['dom_other']}", headers=hdr)
    assert r.status_code == 404, r.text

    # Kendi domaini: güncelleyebilir ve silebilir
    r = client.put(f"/api/domains/{ids['dom_own']}", headers=hdr, json={"info": "kendi notu"})
    assert r.status_code == 200, r.text
    assert r.json()["info"] == "kendi notu"
    r = client.delete(f"/api/domains/{ids['dom_own']}", headers=hdr)
    assert r.status_code == 200, r.text

    # Admin kapsamsız: yabancı kaydı yönetebilir
    r = client.put(f"/api/domains/{ids['dom_other']}", headers=auth_headers, json={"info": "admin"})
    assert r.status_code == 200, r.text


def test_editor_cannot_update_or_delete_foreign_application(client, auth_headers):
    own, other, hdr, ids = _setup(client, auth_headers, "a1")

    r = client.put(f"/api/applications/{ids['app_other']}", headers=hdr, json={})
    assert r.status_code == 404, r.text
    r = client.delete(f"/api/applications/{ids['app_other']}", headers=hdr)
    assert r.status_code == 404, r.text

    # Kendi uygulaması: içerik alanları serbest
    r = client.put(f"/api/applications/{ids['app_own']}", headers=hdr, json={"notes": "not"})
    assert r.status_code == 200, r.text

    # SAHİPLİK değişimi editöre kapalı (kendi uygulamasında bile)
    r = client.put(f"/api/applications/{ids['app_own']}", headers=hdr,
                   json={"sy_team_id": other})
    assert r.status_code == 403, r.text
    # Değişmeyen sy_team_id göndermek serbest (form her alanı yollar)
    r = client.put(f"/api/applications/{ids['app_own']}", headers=hdr,
                   json={"sy_team_id": own, "notes": "yine ben"})
    assert r.status_code == 200, r.text

    # Admin sahipliği değiştirebilir
    r = client.put(f"/api/applications/{ids['app_own']}", headers=auth_headers,
                   json={"sy_team_id": other})
    assert r.status_code == 200, r.text


def test_editor_creates_app_only_for_own_team(client, auth_headers):
    own, other, hdr, _ = _setup(client, auth_headers, "c1")

    r = client.post("/api/applications", headers=hdr,
                    json={"app_name": "KendiEkibime", "server_name": "srv-kendi", "sy_team_id": own})
    assert r.status_code == 200, r.text
    r = client.post("/api/applications", headers=hdr,
                    json={"app_name": "BaskaEkibe", "server_name": "srv-baska", "sy_team_id": other})
    assert r.status_code == 403, r.text


def test_dependency_target_scoped_for_editor(client, auth_headers):
    own, other, hdr, ids = _setup(client, auth_headers, "t1")

    # Yabancı ekibin domainini hedef veremez → 404 (ad sızmaz, varlık orakılı kapalı)
    r = client.post(f"/api/applications/{ids['app_own']}/dependencies", headers=hdr,
                    json={"target_domain_id": ids["dom_other"]})
    assert r.status_code == 404, r.text

    # Kendi kapsamındaki hedefe ekleyebilir
    r = client.post(f"/api/applications/{ids['app_own']}/dependencies", headers=hdr,
                    json={"target_domain_id": ids["dom_own"], "note": "iç bağımlılık"})
    assert r.status_code == 200, r.text

    # Admin kapsamsız: yabancı hedefe ekleyebilir (takımlar-arası bağımlılık admin işi)
    r = client.post(f"/api/applications/{ids['app_own']}/dependencies", headers=auth_headers,
                    json={"target_domain_id": ids["dom_other"]})
    assert r.status_code == 200, r.text


def test_relationships_global_but_team_filterable(client, auth_headers):
    """Harita GLOBAL: editor de tüm ekiplerin ilişkilerini görebilir. Ancak sy_team_id
    filtresiyle YALNIZ o takımın uygulamalarına daraltılabilir (kullanıcı isteği: harita
    herkese açık ama takım-filtrelenebilir)."""
    own, other, hdr, ids = _setup(client, auth_headers, "r1")
    # ilişkisiz uygulamalar haritada görünmeyebilir — bağımlılık ekleyerek görünür kıl
    client.post(f"/api/applications/{ids['app_own']}/dependencies", headers=auth_headers,
                json={"target_domain_id": ids["dom_own"]})
    client.post(f"/api/applications/{ids['app_other']}/dependencies", headers=auth_headers,
                json={"target_domain_id": ids["dom_other"]})

    # Admin: filtresiz iki uygulamayı da görür
    r = client.get("/api/relationships", headers=auth_headers)
    admin_labels = {n["label"] for n in r.json()["nodes"] if n["node_type"] == "app"}
    assert {"KapsamApp-own-r1", "KapsamApp-other-r1"} <= admin_labels

    # Editör (filtresiz): harita GLOBAL → o da iki uygulamayı görür
    r = client.get("/api/relationships", headers=hdr)
    assert r.status_code == 200, r.text
    labels = {n["label"] for n in r.json()["nodes"] if n["node_type"] == "app"}
    assert {"KapsamApp-own-r1", "KapsamApp-other-r1"} <= labels

    # Editör (kendi takımı filtreli): yalnız kendi ekibinin uygulaması
    r = client.get("/api/relationships", headers=hdr, params={"sy_team_id": own})
    scoped = {n["label"] for n in r.json()["nodes"] if n["node_type"] == "app"}
    assert "KapsamApp-own-r1" in scoped
    assert "KapsamApp-other-r1" not in scoped
