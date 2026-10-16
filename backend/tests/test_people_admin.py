"""Kullanıcı/Ekip yönetim ekranlarının veri desteği: Audit Log'da Ad Soyad (gösterim + arama),
kullanıcı bazlı tam eşleşmeli işlem geçmişi (actor), ekip listesinde üye/domain/uygulama sayıları."""

import csv
import io

from app.db.models import AuditLog, Domain
from app.db.session import SessionLocal


def _user(client, h, username, full_name):
    r = client.post("/api/users", headers=h, json={
        "username": username, "password": "pw12345", "full_name": full_name,
        "auth_source": "local", "role": "viewer"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _log(username, action="update"):
    db = SessionLocal()
    db.add(AuditLog(username=username, action=action, table_name="domains", record_id="1",
                    details='{"domain": "pa.test"}'))
    db.commit()
    db.close()


def test_audit_shows_and_searches_full_name(client, auth_headers):
    _user(client, auth_headers, "pa_ayse", "Ayşe Demirtaş")
    _log("pa_ayse")
    items = client.get("/api/audit", headers=auth_headers, params={"username": "pa_ayse"}).json()["items"]
    assert items and items[0]["user_full_name"] == "Ayşe Demirtaş"

    by_name = client.get("/api/audit", headers=auth_headers, params={"username": "Demirtaş"}).json()["items"]
    assert by_name and all(e["username"] == "pa_ayse" for e in by_name), "Ad Soyad ile aranabilmeli"
    by_q = client.get("/api/audit", headers=auth_headers, params={"q": "Demirtaş"}).json()["items"]
    assert any(e["username"] == "pa_ayse" for e in by_q)

    system = client.get("/api/audit", headers=auth_headers, params={"actor": "system"}).json()["items"]
    assert all(e["user_full_name"] is None for e in system)

    r = client.get("/api/audit/export", headers=auth_headers, params={"username": "pa_ayse"})
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0][1:3] == ["Kullanıcı", "Ad Soyad"] and rows[1][1:3] == ["pa_ayse", "Ayşe Demirtaş"]


def test_actor_is_exact_match(client, auth_headers):
    _user(client, auth_headers, "pa_ali", "Ali Kısa")
    _user(client, auth_headers, "pa_ali2", "Ali Uzun")
    _log("pa_ali")
    _log("pa_ali2")
    like = {e["username"] for e in client.get("/api/audit", headers=auth_headers,
                                                 params={"username": "pa_ali"}).json()["items"]}
    exact = {e["username"] for e in client.get("/api/audit", headers=auth_headers,
                                                  params={"actor": "pa_ali"}).json()["items"]}
    assert {"pa_ali", "pa_ali2"} <= like
    assert exact == {"pa_ali"}, "kullanıcı detayındaki geçmiş başka kullanıcıyı karıştırmamalı"


def test_team_list_has_member_domain_app_counts(client, auth_headers):
    t = client.post("/api/teams", headers=auth_headers, json={"name": "PA Sayaç SY", "type": "SY"}).json()
    u1 = _user(client, auth_headers, "pa_m1", "Üye Bir")
    u2 = _user(client, auth_headers, "pa_m2", "Üye İki")
    for u in (u1, u2):
        assert client.post(f"/api/teams/{t['id']}/members", headers=auth_headers,
                           json={"user_id": u["id"]}).status_code == 200
    db = SessionLocal()
    db.add(Domain(domain="pa-count.test", sy_team_id=t["id"]))
    db.commit()
    db.close()
    rows = {x["id"]: x for x in client.get("/api/teams", headers=auth_headers).json()}
    assert rows[t["id"]]["member_count"] == 2
    assert rows[t["id"]]["domain_count"] == 1
    assert rows[t["id"]]["app_count"] == 0


def test_user_list_has_created_at(client, auth_headers):
    users = client.get("/api/users", headers=auth_headers).json()
    assert all("created_at" in u for u in users)
    assert any(u["created_at"] and u["created_at"].endswith("+03:00") for u in users)


def test_team_counts_hidden_from_non_admin(client, auth_headers):
    _user(client, auth_headers, "pa_viewer", "İzleyen Kişi")
    tok = client.post("/api/auth/login-json", json={"username": "pa_viewer", "password": "pw12345"}).json()["access_token"]
    rows = client.get("/api/teams", headers={"Authorization": f"Bearer {tok}"}).json()
    assert rows and all(r["member_count"] == 0 and r["domain_count"] == 0 for r in rows)
