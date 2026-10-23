"""v3.9.1: büyük listeler sunucu tarafında sayfalanır (Domainler, SSL Sertifikaları, Uygulamalar,
Keşif, Değişiklik Talepleri). Liste davranışı eski istemci-taraflı süzmeyle aynı kalmalı:
aynı arama alanları, aynı durum eşikleri, aynı kapsam (RBAC), Türkçe I/İ duyarsız arama."""
from datetime import timedelta

from app.core.timeutil import utcnow
from app.db.models import Certificate, CertificateDomainMap, Domain, TransferProposal
from app.db.session import SessionLocal
from tests.test_scope_idor import _editor_in, _sy_team


def _cert(db, name, days, parent=None, cert_type="leaf", **kw):
    c = Certificate(name=name, cert_type=cert_type, valid_from=utcnow() - timedelta(days=10),
                    valid_to=utcnow() + timedelta(days=days), is_active=True,
                    parent_id=parent.id if parent else None, pem_certificate="PEM-" + name, **kw)
    db.add(c)
    db.flush()
    return c


def _seed_domains(tag, team_id):
    """tag'li 7 domain: 3 geçerli, 2 yaklaşan, 1 süresi dolmuş, 1 sertifikasız."""
    db = SessionLocal()
    try:
        plan = [("a", 400), ("b", 200), ("c", 90), ("d", 20), ("e", 5), ("f", -3), ("g", None)]
        for letter, days in plan:
            d = Domain(domain=f"{letter}-{tag}.ornek.local", sy_team_id=team_id,
                       lb_update="Evet", waf_update="Hayır")
            db.add(d)
            db.flush()
            if days is not None:
                c = _cert(db, f"{letter}-{tag}-leaf", days)
                db.add(CertificateDomainMap(domain_id=d.id, certificate_id=c.id, mapping_type="server"))
        db.commit()
    finally:
        db.close()


def test_domain_page_counts_filters_sort_and_paging(client, auth_headers):
    team = _sy_team(client, auth_headers, "SayfaSY1")
    _seed_domains("pg1", team)
    r = client.get("/api/domains/page", headers=auth_headers, params={"q": "pg1", "size": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 7 and body["page"] == 0 and body["size"] == 3
    assert [d["domain"][0] for d in body["items"]] == ["a", "b", "c"]
    assert body["counts"] == {"total": 7, "valid": 3, "expiring": 2, "expired": 1, "nocert": 1}
    # İkinci sayfa + aralık dışı sayfa son sayfaya çekilir
    p2 = client.get("/api/domains/page", headers=auth_headers, params={"q": "pg1", "size": 3, "page": 1}).json()
    assert [d["domain"][0] for d in p2["items"]] == ["d", "e", "f"]
    p9 = client.get("/api/domains/page", headers=auth_headers, params={"q": "pg1", "size": 3, "page": 9}).json()
    assert p9["page"] == 2 and [d["domain"][0] for d in p9["items"]] == ["g"]
    # Durum filtresi; kartlar (counts) aramadan sonra, durum filtresinden önce sayılır
    exp = client.get("/api/domains/page", headers=auth_headers, params={"q": "pg1", "status": "expiring"}).json()
    assert {d["domain"][0] for d in exp["items"]} == {"d", "e"} and exp["counts"]["total"] == 7
    # Kalan güne göre sıralama: boşlar her iki yönde de sonda
    asc = client.get("/api/domains/page", headers=auth_headers,
                     params={"q": "pg1", "sort": "server", "dir": "asc"}).json()
    assert [d["domain"][0] for d in asc["items"]] == ["f", "e", "d", "c", "b", "a", "g"]
    desc = client.get("/api/domains/page", headers=auth_headers,
                      params={"q": "pg1", "sort": "server", "dir": "desc"}).json()
    assert [d["domain"][0] for d in desc["items"]] == ["a", "b", "c", "d", "e", "f", "g"]
    # Kolon (huni) filtresi + sayaçları
    col = client.get("/api/domains/page", headers=auth_headers,
                     params={"q": "pg1", "f_server": "nocert"}).json()
    assert [d["domain"][0] for d in col["items"]] == ["g"]
    assert col["facets"]["server"]["valid"] == 3 and col["facets"]["server"]["all"] == 7
    # Sayfadaki kayıt eski listeyle aynı alanları taşır (sertifikalar, kalan gün)
    first = body["items"][0]
    assert first["certificates"][0]["name"] == "a-pg1-leaf" and first["server_days_left"] >= 399
    # all=true (Excel İndir) sayfalamayı kapatır
    allr = client.get("/api/domains/page", headers=auth_headers, params={"q": "pg1", "all": "true"}).json()
    assert len(allr["items"]) == 7


def test_domain_page_turkish_search_and_scope(client, auth_headers):
    own = _sy_team(client, auth_headers, "SayfaOwn2")
    other = _sy_team(client, auth_headers, "SayfaOther2")
    hdr = _editor_in(client, auth_headers, "sayfa_ed2", own)
    db = SessionLocal()
    try:
        db.add(Domain(domain="iletisim-pg2.ornek.local", sy_team_id=own))
        db.add(Domain(domain="islem-pg2.ornek.local", sy_team_id=other))
        db.commit()
    finally:
        db.close()
    # Türkçe I/İ: "İLETİŞİM" yazınca "iletisim" bulunur
    r = client.get("/api/domains/page", headers=auth_headers, params={"q": "İLETİŞİM-PG2"}).json()
    assert [d["domain"] for d in r["items"]] == ["iletisim-pg2.ornek.local"]
    # Editör yalnız kendi ekibinin domainini görür (list_domains ile aynı kapsam)
    r = client.get("/api/domains/page", headers=hdr, params={"q": "pg2"}).json()
    assert [d["domain"] for d in r["items"]] == ["iletisim-pg2.ornek.local"]
    opts = client.get("/api/domains/options", headers=hdr).json()
    names = {o["domain"] for o in opts}
    assert "iletisim-pg2.ornek.local" in names and "islem-pg2.ornek.local" not in names


def test_domain_detail_can_edit_flag(client, auth_headers):
    own = _sy_team(client, auth_headers, "SayfaOwn3")
    hdr = _editor_in(client, auth_headers, "sayfa_ed3", own)
    dom = client.post("/api/domains", headers=auth_headers,
                      json={"domain": "duzenle-pg3.ornek.local", "sy_team_id": own}).json()
    assert client.get(f"/api/domains/{dom['id']}", headers=auth_headers).json()["can_edit"] is True
    assert client.get(f"/api/domains/{dom['id']}", headers=hdr).json()["can_edit"] is True


def test_certificate_page_tree_collapse_and_flat_filter(client, auth_headers):
    db = SessionLocal()
    try:
        root = _cert(db, "pg4 Root CA", 3000, cert_type="root")
        inter = _cert(db, "pg4 Issuing CA", 2000, parent=root, cert_type="intermediate")
        for i in range(5):
            _cert(db, f"pg4-leaf-{i}.ornek.local", 10 + i * 100, parent=inter, environment="prod")
        db.commit()
        root_id, inter_id = root.id, inter.id
    finally:
        db.close()
    r = client.get("/api/certificates/page", headers=auth_headers, params={"q": "pg4", "size": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 7
    rows = [(x["cert"]["name"], x["depth"]) for x in body["items"]]
    assert rows[0] == ("pg4 Root CA", 0) and rows[1] == ("pg4 Issuing CA", 1)
    assert rows[2][1] == 2 and body["items"][0]["has_children"] is True
    assert all(x["root_id"] == root_id for x in body["items"])
    # Liste hafif: PEM gövdesi gelmez
    assert all(x["cert"]["pem_certificate"] is None for x in body["items"])
    # Kart görünümü özeti kökün tüm üyelerini sayar
    assert body["groups"][str(root_id)]["members"] == 7
    assert body["groups"][str(root_id)]["worst_days"] in (9, 10)
    # Kapatılan ara sertifikanın altı sayfalamadan önce çıkar
    col = client.get("/api/certificates/page", headers=auth_headers,
                     params={"q": "pg4", "collapsed": str(inter_id)}).json()
    assert col["total"] == 2
    # Tümünü kapat → yalnız kök; kökü açınca ara sertifika görünür
    allc = client.get("/api/certificates/page", headers=auth_headers,
                      params={"q": "pg4", "collapse_all": "true"}).json()
    assert [x["cert"]["name"] for x in allc["items"]] == ["pg4 Root CA"]
    opened = client.get("/api/certificates/page", headers=auth_headers,
                        params={"q": "pg4", "collapse_all": "true", "expanded": str(root_id)}).json()
    assert [x["cert"]["name"] for x in opened["items"]] == ["pg4 Root CA", "pg4 Issuing CA"]
    # Kolon filtresi → düz liste
    flat = client.get("/api/certificates/page", headers=auth_headers,
                      params={"q": "pg4", "f_valid": "expiring"}).json()
    assert [(x["cert"]["name"], x["depth"]) for x in flat["items"]] == [("pg4-leaf-0.ornek.local", 0)]
    assert flat["facets"]["environment"]["prod"] == 5


def test_certificate_options_search_is_light(client, auth_headers):
    db = SessionLocal()
    try:
        _cert(db, "pg5-secici.ornek.local", 100, subject_key_identifier="AB:CD:PG5")
        db.commit()
    finally:
        db.close()
    r = client.get("/api/certificates/options", headers=auth_headers, params={"q": "ab:cd:pg5"})
    assert r.status_code == 200, r.text
    opts = r.json()
    assert [o["name"] for o in opts] == ["pg5-secici.ornek.local"]
    assert "pem_certificate" not in opts[0] and opts[0]["days_left"] in (99, 100)


def test_certificate_detail_can_edit_for_foreign_team(client, auth_headers):
    own = _sy_team(client, auth_headers, "SayfaOwn6")
    other = _sy_team(client, auth_headers, "SayfaOther6")
    hdr = _editor_in(client, auth_headers, "sayfa_ed6", own)
    db = SessionLocal()
    try:
        d = Domain(domain="yabanci-pg6.ornek.local", sy_team_id=other)
        db.add(d)
        db.flush()
        c = _cert(db, "pg6-yabanci", 100)
        db.add(CertificateDomainMap(domain_id=d.id, certificate_id=c.id, mapping_type="server"))
        free = _cert(db, "pg6-sahipsiz", 100)
        db.commit()
        cid, free_id = c.id, free.id
    finally:
        db.close()
    assert client.get(f"/api/certificates/{cid}", headers=hdr).json()["can_edit"] is False
    assert client.get(f"/api/certificates/{cid}", headers=auth_headers).json()["can_edit"] is True
    assert client.get(f"/api/certificates/{free_id}", headers=hdr).json()["can_edit"] is True


def test_proposal_page_filters_counts_and_single_get(client, auth_headers):
    team = _sy_team(client, auth_headers, "SayfaSY7")
    db = SessionLocal()
    try:
        d1 = Domain(domain="talep-pg7-a.ornek.local", sy_team_id=team)
        d2 = Domain(domain="talep-pg7-b.ornek.local", sy_team_id=team)
        db.add_all([d1, d2])
        db.flush()
        old = _cert(db, "pg7-eski", 10)
        new = _cert(db, "pg7-yeni", 300)
        props = [
            TransferProposal(old_cert_id=old.id, new_cert_id=new.id, domain_id=d1.id, mapping_type="server",
                             kind="transfer", sy_team_id=team, status="pending", via="live-check", live_seen=True),
            TransferProposal(old_cert_id=new.id, new_cert_id=new.id, domain_id=d1.id, kind="date_fix",
                             sy_team_id=team, status="pending", via="live-check"),
            TransferProposal(old_cert_id=old.id, new_cert_id=new.id, domain_id=d2.id, mapping_type="server",
                             kind="transfer", sy_team_id=team, status="rejected", via="manual"),
        ]
        db.add_all(props)
        db.commit()
        d1_id, first_id = d1.id, props[0].id
    finally:
        db.close()
    r = client.get("/api/proposals/page", headers=auth_headers, params={"domain_id": d1_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["domain_name"] == "talep-pg7-a.ornek.local"
    assert {p["kind"] for p in body["items"]} == {"transfer", "date_fix"}
    assert body["counts"]["pending"] == 2 and body["counts"]["rejected"] == 0
    assert body["facets"]["kind"]["date_fix"] == 1
    # Tür filtresi
    k = client.get("/api/proposals/page", headers=auth_headers,
                   params={"domain_id": d1_id, "kind": "date_fix"}).json()
    assert [p["kind"] for p in k["items"]] == ["date_fix"]
    # Metin araması domain adıyla; tüm durumlar
    s = client.get("/api/proposals/page", headers=auth_headers, params={"q": "TALEP-PG7", "status": "all"}).json()
    assert s["total"] == 3 and s["counts"]["rejected"] == 1
    # Canlıda görüldü filtresi
    live = client.get("/api/proposals/page", headers=auth_headers,
                      params={"q": "pg7", "live_seen": "true"}).json()
    assert [p["id"] for p in live["items"]] == [first_id]
    one = client.get(f"/api/proposals/{first_id}", headers=auth_headers)
    assert one.status_code == 200 and one.json()["domain_name"] == "talep-pg7-a.ornek.local"
    counts = client.get("/api/proposals/counts", headers=auth_headers).json()
    assert counts["pending"] >= 2 and counts["decidable"] == counts["pending"]


def test_proposal_page_hidden_from_other_team(client, auth_headers):
    own = _sy_team(client, auth_headers, "SayfaOwn8")
    other = _sy_team(client, auth_headers, "SayfaOther8")
    hdr = _editor_in(client, auth_headers, "sayfa_ed8", own)
    db = SessionLocal()
    try:
        d = Domain(domain="gizli-pg8.ornek.local", sy_team_id=other)
        db.add(d)
        db.flush()
        a, b = _cert(db, "pg8-a", 10), _cert(db, "pg8-b", 200)
        p = TransferProposal(old_cert_id=a.id, new_cert_id=b.id, domain_id=d.id, mapping_type="server",
                             kind="transfer", sy_team_id=other, status="pending")
        db.add(p)
        db.commit()
        pid = p.id
    finally:
        db.close()
    r = client.get("/api/proposals/page", headers=hdr, params={"q": "pg8"}).json()
    assert r["total"] == 0
    assert client.get(f"/api/proposals/{pid}", headers=hdr).status_code == 404


def test_application_and_discovery_pages(client, auth_headers):
    team = _sy_team(client, auth_headers, "SayfaSY9")
    for i in range(3):
        r = client.post("/api/applications", headers=auth_headers,
                        json={"app_name": f"Pg9 Uygulama {i}", "server_name": f"srv-pg9-{i}",
                              "sy_team_id": team, "status": i != 2})
        assert r.status_code == 200, r.text
    r = client.get("/api/applications/page", headers=auth_headers, params={"q": "pg9", "size": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["facets"]["status"] == {"active": 2, "inactive": 1, "all": 3}
    inactive = client.get("/api/applications/page", headers=auth_headers,
                          params={"q": "pg9", "f_status": "inactive"}).json()
    assert [a["app_name"] for a in inactive["items"]] == ["Pg9 Uygulama 2"]
    d = client.get("/api/discovery/findings/page", headers=auth_headers)
    assert d.status_code == 200, d.text
    assert set(d.json()["counts"]) >= {"total", "new", "in_inventory", "adopted", "ignored"}
    assert client.get("/api/discovery/findings/counts", headers=auth_headers).status_code == 200
