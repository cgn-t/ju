"""RBAC: rol users.role kolonundan ATANIR (admin 'Kullanıcılar' sekmesinden); kapsam SY üyeliğinden.

Model: admin (global tam yetki) / editor (takım-kapsamlı düzenle — SY üyeliği kapsamı verir) /
viewer (takım-kapsamlı salt-okur) / allviewer (global salt-okur) / none (rol atanmamış → hiçbir şey).
ADMIN/VIEWER takımı üyeliği artık rol VERMEZ; rol yalnız users.role'den gelir.
"""


def _mk_user(client, admin, username, role=None, pw="Parola!123"):
    body = {"username": username, "password": pw}
    if role is not None:
        body["role"] = role
    r = client.post("/api/users", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login(client, username, pw="Parola!123"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def _team(client, admin, name, type_):
    r = client.post("/api/teams", headers=admin, json={"name": name, "type": type_})
    assert r.status_code == 200, r.text
    return r.json()


def _add_member(client, admin, team_id, uid):
    r = client.post(f"/api/teams/{team_id}/members", headers=admin, json={"user_id": uid})
    assert r.status_code == 200, r.text


# --- none: rol atanmamış kullanıcı hiçbir şey göremez ---
def test_no_role_user_sees_nothing(client, auth_headers):
    _mk_user(client, auth_headers, "rbac_none")  # role verilmedi → 'none'
    h, body = _login(client, "rbac_none")
    assert body["role"] == "none"
    for path in ("/api/certificates", "/api/domains", "/api/applications",
                 "/api/dashboard", "/api/cert-map", "/api/relationships"):
        assert client.get(path, headers=h).status_code == 403, path
    assert client.get("/api/auth/me", headers=h).json()["role"] == "none"


# --- allviewer: global salt-okur (eski 'viewer' davranışı) ---
def test_allviewer_global_read_only(client, auth_headers):
    _mk_user(client, auth_headers, "rbac_allviewer", role="allviewer")
    h, body = _login(client, "rbac_allviewer")
    assert body["role"] == "allviewer"
    for path in ("/api/certificates", "/api/domains", "/api/dashboard", "/api/cert-map"):
        assert client.get(path, headers=h).status_code == 200, path
    # salt-okur → yazma yok
    assert client.post("/api/domains", headers=h, json={"domain": "allviewer-yazamaz.com"}).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403  # admin-only


# --- viewer: takım-kapsamlı salt-okur (kendi SY ekibini görür, düzenleyemez) ---
def test_viewer_scoped_read_only(client, auth_headers):
    t_a = _team(client, auth_headers, "SY-VAlpha", "SY")
    t_b = _team(client, auth_headers, "SY-VBeta", "SY")
    uid = _mk_user(client, auth_headers, "rbac_viewer_scoped", role="viewer")
    _add_member(client, auth_headers, t_a["id"], uid)  # kapsam: yalnız alpha
    h, body = _login(client, "rbac_viewer_scoped")
    assert body["role"] == "viewer"

    client.post("/api/domains", headers=auth_headers,
                json={"domain": "vown.alpha.com", "sy_team_id": t_a["id"]})
    client.post("/api/domains", headers=auth_headers,
                json={"domain": "vother.beta.com", "sy_team_id": t_b["id"]})
    names = [d["domain"] for d in client.get("/api/domains", headers=h).json()]
    assert "vown.alpha.com" in names
    assert "vother.beta.com" not in names          # başka SY'nin domaini görünmez
    # salt-okur → yazma yasak (kendi takımında bile)
    assert client.post("/api/domains", headers=h,
                       json={"domain": "viewer-yazamaz.com", "sy_team_id": t_a["id"]}).status_code == 403
    # envanter global → sertifikaları görür
    assert client.get("/api/certificates", headers=h).status_code == 200


# --- editor: yalnız kendi domainleri (izolasyon) + düzenleme yetkisi ---
def test_editor_scoped_to_own_domains(client, auth_headers):
    t_a = _team(client, auth_headers, "SY-EAlpha", "SY")
    t_b = _team(client, auth_headers, "SY-EBeta", "SY")
    ua = _mk_user(client, auth_headers, "rbac_editor_alpha", role="editor")
    _add_member(client, auth_headers, t_a["id"], ua)
    ha, ba = _login(client, "rbac_editor_alpha")
    assert ba["role"] == "editor"

    da = client.post("/api/domains", headers=auth_headers,
                     json={"domain": "eown.alpha.com", "sy_team_id": t_a["id"]}).json()
    db_ = client.post("/api/domains", headers=auth_headers,
                      json={"domain": "eother.beta.com", "sy_team_id": t_b["id"]}).json()

    names = [d["domain"] for d in client.get("/api/domains", headers=ha).json()]
    assert "eown.alpha.com" in names
    assert "eother.beta.com" not in names          # başka SY'nin domaini görünmez
    assert client.get(f"/api/domains/{da['id']}", headers=ha).status_code == 200
    assert client.get(f"/api/domains/{db_['id']}", headers=ha).status_code == 404  # varlık gizli
    # kendi takımına domain OLUŞTURABİLİR (düzenleme yetkisi)
    assert client.post("/api/domains", headers=ha,
                       json={"domain": "editor-yazar.com", "sy_team_id": t_a["id"]}).status_code == 200
    # envanter global → sertifikaları görür; admin-only işlemler yasak
    assert client.get("/api/certificates", headers=ha).status_code == 200
    assert client.get("/api/users", headers=ha).status_code == 403


# --- editor/viewer SY üyeliği YOKSA: rol var ama kapsam boş (kendi domaini yok, sertifika global) ---
def test_scoped_role_without_team_has_empty_scope(client, auth_headers):
    uid = _mk_user(client, auth_headers, "rbac_editor_noteam", role="editor")
    h, body = _login(client, "rbac_editor_noteam")
    assert body["role"] == "editor"
    # SY üyeliği yok → hiçbir domain görmez (boş liste, 403 DEĞİL)
    r = client.get("/api/domains", headers=h)
    assert r.status_code == 200 and r.json() == []
    # sertifika envanteri global → görür
    assert client.get("/api/certificates", headers=h).status_code == 200
    assert uid  # kullanıldı


# --- admin: full ---
def test_admin_role_full_access(client, auth_headers):
    _mk_user(client, auth_headers, "rbac_admin2", role="admin")
    h, body = _login(client, "rbac_admin2")
    assert body["role"] == "admin"
    assert client.get("/api/users", headers=h).status_code == 200
    assert client.get("/api/settings/general", headers=h).status_code == 200
    assert client.get("/api/domains", headers=h).status_code == 200


# --- Rol users API'den atanır/değiştirilir (Kullanıcılar sekmesi) ---
def test_role_assign_and_update_via_users_api(client, auth_headers):
    uid = _mk_user(client, auth_headers, "rbac_promote", role="viewer")
    _, b1 = _login(client, "rbac_promote")
    assert b1["role"] == "viewer"
    # viewer → allviewer yükselt
    assert client.put(f"/api/users/{uid}", headers=auth_headers,
                      json={"role": "allviewer"}).status_code == 200
    _, b2 = _login(client, "rbac_promote")
    assert b2["role"] == "allviewer"
    # Geçersiz rol → 422
    assert client.put(f"/api/users/{uid}", headers=auth_headers,
                      json={"role": "süpervizor"}).status_code == 422
    # none'a (yetkisiz) düşürülebilir — rol geri alma
    assert client.put(f"/api/users/{uid}", headers=auth_headers,
                      json={"role": "none"}).status_code == 200
    _, b3 = _login(client, "rbac_promote")
    assert b3["role"] == "none"


# --- Türetilmiş/normalize rol yazma uçlarında DB'ye geri YAZILMAZ (set_committed_value) ---
def test_role_not_overwritten_by_requests(client, auth_headers):
    from app.db.models import User
    from app.db.session import SessionLocal

    t = _team(client, auth_headers, "SY-Persist", "SY")
    uid = _mk_user(client, auth_headers, "rbac_persist", role="editor")
    _add_member(client, auth_headers, t["id"], uid)
    h, body = _login(client, "rbac_persist")
    assert body["role"] == "editor"
    r = client.post("/api/domains", headers=h,
                    json={"domain": "persist2.example.com", "sy_team_id": t["id"]})
    assert r.status_code == 200, r.text
    s = SessionLocal()
    try:
        db_role = s.query(User).filter_by(username="rbac_persist").first().role
    finally:
        s.close()
    # Yazma ucundaki commit, transient normalize edilmiş rolü kolona GERİ YAZMAMALI
    assert db_role == "editor", f"users.role beklenmedik: {db_role!r}"


# --- Explicit JSON null 'dokunma' demektir — kolona null yazılmaz, break-glass atlanmaz ---
def test_explicit_null_role_and_active_are_noop(client, auth_headers):
    uid = _mk_user(client, auth_headers, "null_noop", role="editor")
    # {"role": null} → role'e DOKUNMA (editor kalır), full_name güncellenir
    r = client.put(f"/api/users/{uid}", headers=auth_headers,
                   json={"role": None, "full_name": "Yeni Ad"})
    assert r.status_code == 200, r.text
    _, b = _login(client, "null_noop")
    assert b["role"] == "editor"  # null kolona yazılmadı → 'none'e düşmedi
    assert next(u for u in client.get("/api/users", headers=auth_headers).json()
                if u["id"] == uid)["full_name"] == "Yeni Ad"
    # {"is_active": null} → is_active'e DOKUNMA (True kalır)
    r = client.put(f"/api/users/{uid}", headers=auth_headers, json={"is_active": None})
    assert r.status_code == 200, r.text
    assert next(u for u in client.get("/api/users", headers=auth_headers).json()
                if u["id"] == uid)["is_active"] is True


# --- Break-glass: son aktif admin'in rolü/erişimi düşürülemez (EN SONDA çalışmalı) ---
def test_zzz_break_glass_last_admin(client, auth_headers):
    # seed 'admin' dışındaki admin rolündeki kullanıcıları viewer'a düşür (her biri son değilken 200)
    for u in client.get("/api/users", headers=auth_headers).json():
        if u["role"] == "admin" and u["username"] != "admin":
            assert client.put(f"/api/users/{u['id']}", headers=auth_headers,
                              json={"role": "viewer"}).status_code == 200
    admins = [u for u in client.get("/api/users", headers=auth_headers).json() if u["role"] == "admin"]
    assert len(admins) == 1 and admins[0]["username"] == "admin"
    seed_id = admins[0]["id"]
    # son admin'in rolünü düşürmek → 400
    assert client.put(f"/api/users/{seed_id}", headers=auth_headers,
                      json={"role": "viewer"}).status_code == 400
    # son admin'i pasife almak → 400
    assert client.put(f"/api/users/{seed_id}", headers=auth_headers,
                      json={"is_active": False}).status_code == 400
