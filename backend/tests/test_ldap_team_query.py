"""Ayarlar > LDAP sorguları (v3.9.7): kişi hangi Scrum ekibiyle gelir, bir ekipte kimler var.

Yalnız okuma: servis hesabıyla dizin sorgulanır, DB'ye bir şey yazılmaz."""

from app.db.models import Team, User, UserTeam
from app.db.session import SessionLocal
from app.services import ldap_auth
from tests.test_ldap_profile import CFG, _fake_directory, _save

SCRUMS = "OU=ScrumGroups,OU=BTPersonel,DC=firma,DC=local"   # prod'daki gibi çoğul
BBB = f"CN=SY-BBB,{SCRUMS}"
CCC = f"CN=SY-CCC,{SCRUMS}"


def _directory(monkeypatch):
    _fake_directory(monkeypatch)
    conn = ldap_auth._connect(None, CFG, None, None)
    conn.strategy.add_entry("OU=BTPersonel,DC=firma,DC=local", {"objectClass": "organizationalUnit", "ou": "BTPersonel"})
    conn.strategy.add_entry(SCRUMS, {"objectClass": "organizationalUnit", "ou": "ScrumGroups"})
    conn.strategy.add_entry(BBB, {"objectClass": "group", "cn": "SY-BBB"})
    conn.strategy.add_entry(CCC, {"objectClass": "group", "cn": "SY-CCC"})
    conn.strategy.add_entry("CN=Ali Can,OU=Users,DC=firma,DC=local",
                            {"objectClass": "user", "sAMAccountName": "ali.can", "displayName": "Ali Can",
                             "mail": "ali@firma.com.tr", "memberOf": [BBB]})
    conn.strategy.add_entry("CN=Zeynep Ak,OU=Users,DC=firma,DC=local",
                            {"objectClass": "user", "sAMAccountName": "zeynep.ak", "displayName": "Zeynep Ak",
                             "memberOf": [CCC, "CN=VPN,OU=Groups,DC=firma,DC=local"]})
    return conn


def test_lookup_user_shows_team_and_jumbo_account(client, monkeypatch):
    db = SessionLocal()
    try:
        _directory(monkeypatch)
        _save(db, {**CFG, "team_group_ou": "ScrumGroup"})
        team = Team(name="BBB", type="SY")
        user = User(username="ALI.CAN", role="editor", auth_source="ldap", is_active=True)
        db.add_all([team, user])
        db.flush()
        db.add(UserTeam(user_id=user.id, team_id=team.id))
        db.commit()

        r = ldap_auth.lookup_user_team(db, "ali.can")
        assert r["status"] == "ok", r
        assert r["team_groups"] == ["SY-BBB"] and r["name"] == "Ali Can" and r["mail"] == "ali@firma.com.tr"
        assert r["jumbo"]["role"] == "editor" and r["jumbo"]["teams"] == ["BBB"]

        r = ldap_auth.lookup_user_team(db, "zeynep.ak")
        assert r["team_groups"] == ["SY-CCC"] and r["jumbo"] is None
        assert ldap_auth.lookup_user_team(db, "yok.boyle")["status"] == "not_found"
        assert ldap_auth.lookup_user_team(db, " ")["status"] == "error"
    finally:
        db.query(UserTeam).filter(UserTeam.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.query(Team).filter(Team.id == team.id).delete()
        db.commit()
        _save(db, {"enabled": False})
        db.close()


def test_team_list_and_members(client, monkeypatch):
    db = SessionLocal()
    try:
        _directory(monkeypatch)
        _save(db, {**CFG, "team_group_ou": "ScrumGroup"})
        teams = ldap_auth.list_team_groups(db)
        assert teams["status"] == "ok", teams
        assert [g["name"] for g in teams["groups"]] == ["SY-BBB", "SY-CCC"]

        r = ldap_auth.team_members(db, "SY-BBB")
        assert r["status"] == "ok", r
        assert [m["account"] for m in r["members"]] == ["ali.can"]
        assert r["members"][0]["jumbo"] is None
        assert ldap_auth.team_members(db, "SY-YOK")["status"] == "not_found"

        _save(db, {**CFG, "team_group_ou": "BaskaOU"})
        assert ldap_auth.list_team_groups(db)["status"] == "not_found"
    finally:
        _save(db, {"enabled": False})
        db.close()


def test_query_endpoints_admin_only_and_disabled(client, auth_headers):
    db = SessionLocal()
    try:
        _save(db, {"enabled": False})
    finally:
        db.close()
    for url in ("/api/settings/ldap/lookup-user?username=x", "/api/settings/ldap/teams",
                "/api/settings/ldap/team-members?team=SY-BBB"):
        r = client.get(url, headers=auth_headers)
        assert r.status_code == 200 and r.json()["status"] == "disabled", (url, r.text)
        assert client.get(url).status_code == 401

