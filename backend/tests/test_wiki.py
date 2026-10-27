"""Kullanım Kılavuzu (v3.9.16): hazır sayfaların kurulumu, okuma herkese, düzenleme yöneticiye."""

from app.db.models import AppSetting, WikiPage
from app.db.session import SessionLocal
from app.services import wiki
from app.services.wiki_content import BUILTIN_PAGES


def _viewer(client, headers, username="wiki_viewer"):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": "viewer", "auth_source": "local"})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_builtin_pages_are_seeded_in_order(client, auth_headers):
    pages = client.get("/api/wiki", headers=auth_headers).json()
    slugs = [p["slug"] for p in pages]
    assert set(p["slug"] for p in BUILTIN_PAGES) <= set(slugs)
    assert slugs[0] == "jumbo-nedir"
    cats = list(dict.fromkeys(p["category"] for p in pages))
    assert cats[:3] == ["Başlarken", "Sertifikalar", "Domainler"]
    assert all(p["updated_by"] is None for p in pages if p["slug"] in {b["slug"] for b in BUILTIN_PAGES})


def test_builtin_links_point_to_existing_pages():
    import re
    slugs = {p["slug"] for p in BUILTIN_PAGES}
    for p in BUILTIN_PAGES:
        text = re.sub(r"`[^`]*`", "", p["body"])   # yazım örnekleri (kod) sayılmaz
        for target in re.findall(r"\]\(/wiki/([a-z0-9-]+)\)", text):
            assert target in slugs, f"{p['slug']} → {target}"


def test_viewer_reads_but_cannot_edit(client, auth_headers):
    hdr = _viewer(client, auth_headers)
    r = client.get("/api/wiki/domain-ekleme", headers=hdr)
    assert r.status_code == 200 and "Yeni Domain" in r.json()["body"]
    assert client.get("/api/wiki/yok-boyle", headers=hdr).status_code == 404
    r = client.post("/api/wiki", headers=hdr, json={"title": "x", "category": "y", "body": "z"})
    assert r.status_code == 403


def test_admin_creates_edits_deletes_with_audit(client, auth_headers):
    r = client.post("/api/wiki", headers=auth_headers, json={
        "title": "Sertifika Talep Süreci (İç)", "category": "Kurum Prosedürleri", "body": "## Adımlar\n1. Talep aç",
        "sort_order": 900})
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["slug"] == "sertifika-talep-sureci-ic" and page["updated_by"] == "admin"
    # Aynı başlık ikinci kez → farklı adres
    dup = client.post("/api/wiki", headers=auth_headers, json={
        "title": "Sertifika Talep Süreci (İç)", "category": "Kurum Prosedürleri", "body": "x"}).json()
    assert dup["slug"] == "sertifika-talep-sureci-ic-2"
    # Başlık değişse de adres sabit kalır
    r = client.put(f"/api/wiki/{page['id']}", headers=auth_headers, json={
        "title": "Sertifika Talep Süreci", "category": "Kurum Prosedürleri", "body": "yeni metin", "sort_order": 900})
    assert r.status_code == 200 and r.json()["slug"] == page["slug"]
    assert client.post("/api/wiki", headers=auth_headers, json={"title": " ", "category": "x"}).status_code == 400
    assert client.delete(f"/api/wiki/{dup['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/wiki/{dup['slug']}", headers=auth_headers).status_code == 404
    audit = client.get("/api/audit?table_name=wiki_pages", headers=auth_headers).json()["items"]
    assert [a["action"] for a in audit][:3] == ["delete", "update", "create"]
    assert audit[1]["record_label"] == "Sertifika Talep Süreci"


def test_seed_keeps_admin_edits_and_deleted_pages_and_refreshes_untouched(client, auth_headers, monkeypatch):
    pages = {p["slug"]: p for p in client.get("/api/wiki", headers=auth_headers).json()}
    # Yönetici bir sayfayı düzenler, birini siler
    edited = pages["dagitim"]
    client.put(f"/api/wiki/{edited['id']}", headers=auth_headers, json={
        "title": edited["title"], "category": edited["category"], "body": "kurum metni", "sort_order": edited["sort_order"]})
    client.delete(f"/api/wiki/{pages['ayarlar']['id']}", headers=auth_headers)
    # Yeni sürümde hazır metinler değişti ve yeni bir sayfa geldi
    new_pages = [dict(p, body=p["body"] + "\n\nYENİ SÜRÜM") for p in BUILTIN_PAGES]
    new_pages.append({"slug": "yeni-ozellik", "category": "Başlarken", "sort_order": 130,
                      "title": "Yeni özellik", "body": "metin"})
    monkeypatch.setattr(wiki, "BUILTIN_PAGES", new_pages)
    db = SessionLocal()
    try:
        wiki.ensure_wiki_seed(db)
        by_slug = {p.slug: p for p in db.query(WikiPage).all()}
        assert by_slug["dagitim"].body == "kurum metni"            # yöneticinin metni korunur
        assert "ayarlar" not in by_slug                            # silinen geri gelmez
        assert by_slug["jumbo-nedir"].body.endswith("YENİ SÜRÜM")  # el değmemiş sayfa güncellenir
        assert by_slug["yeni-ozellik"].title == "Yeni özellik"     # yeni sayfa eklenir
        assert "yeni-ozellik" in db.get(AppSetting, wiki.SEEDED_KEY).value
    finally:
        db.close()


def test_search_ranks_title_and_folds_turkish():
    db = SessionLocal()
    try:
        hits = wiki.search(db, "DEĞİŞİKLİK TALEBİNİ KİM ONAYLAR")
        assert hits[0][0].slug == "degisiklik-talepleri"
        assert wiki.search(db, "canlı doğrulama sonuçları")[0][0].slug == "canli-dogrulama"
        assert wiki.search(db, "qqqzzz") == []
    finally:
        db.close()
