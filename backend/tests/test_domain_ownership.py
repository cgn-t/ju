"""Domain sahipliği: /auth/me üyelikleri + create sırasında SY ekip ataması politikası.

Kural: bir editör domaini yalnız ÜYE OLDUĞU SY ekibine atayabilir (auto-fill'in
sunucu tarafı güvencesi). Admin her ekibe atar; sahipsiz domain serbest.
"""


def _sy_team(client, headers, name):
    r = client.post("/api/teams", headers=headers, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _editor(client, headers, username):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": "editor", "auth_source": "local"})
    return client.post("/api/auth/login-json",
                       json={"username": username, "password": "x"}).json()["access_token"]


def test_me_returns_sy_team_memberships(client, auth_headers):
    team_id = _sy_team(client, auth_headers, "MeTakim")
    tok = _editor(client, auth_headers, "me_user")
    uid = next(u["id"] for u in client.get("/api/users", headers=auth_headers).json()
               if u["username"] == "me_user")
    client.post(f"/api/teams/{team_id}/members", headers=auth_headers, json={"user_id": uid})

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200, me.text
    assert team_id in me.json()["sy_team_ids"]
    assert "MeTakim" in me.json()["sy_team_names"]


def test_non_admin_assigns_only_own_team_on_create(client, auth_headers):
    own = _sy_team(client, auth_headers, "SahipTakim")
    other = _sy_team(client, auth_headers, "YabanciTakim")
    tok = _editor(client, auth_headers, "dom_editor")
    uid = next(u["id"] for u in client.get("/api/users", headers=auth_headers).json()
               if u["username"] == "dom_editor")
    client.post(f"/api/teams/{own}/members", headers=auth_headers, json={"user_id": uid})
    hdr = {"Authorization": f"Bearer {tok}"}

    # Üye olunan ekibe atama → OK
    r = client.post("/api/domains", headers=hdr,
                    json={"domain": "kendi.local", "sy_team_id": own})
    assert r.status_code == 200, r.text
    assert r.json()["sy_team_id"] == own

    # Üye OLUNMAYAN ekibe atama → 403
    r = client.post("/api/domains", headers=hdr,
                    json={"domain": "baskasi.local", "sy_team_id": other})
    assert r.status_code == 403, r.text

    # Sahipsiz (SY yok) domain → serbest
    r = client.post("/api/domains", headers=hdr, json={"domain": "sahipsiz.local"})
    assert r.status_code == 200, r.text
    assert r.json()["sy_team_id"] is None

    # Admin her ekibe atayabilir
    r = client.post("/api/domains", headers=auth_headers,
                    json={"domain": "admin-atadi.local", "sy_team_id": other})
    assert r.status_code == 200, r.text
    assert r.json()["sy_team_id"] == other
