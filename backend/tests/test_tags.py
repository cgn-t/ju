"""Etiket (tag) kataloğu + uygulama etiketleme/filtreleme testleri."""


def test_tag_crud_and_idempotent(client, auth_headers):
    r = client.post("/api/tags", headers=auth_headers,
                    json={"name": "Ödeme", "category": "TestÜrün", "color": "#123456"})
    assert r.status_code == 200, r.text
    tag = r.json()
    assert tag["name"] == "Ödeme" and tag["category"] == "TestÜrün" and tag["color"] == "#123456"
    # Anında-ekleme idempotent: aynı (kategori, ad) → AYNI id, yeni satır üretmez
    r2 = client.post("/api/tags", headers=auth_headers,
                     json={"name": "Ödeme", "category": "TestÜrün"})
    assert r2.status_code == 200 and r2.json()["id"] == tag["id"]
    # Kategori filtresi yalnız o kategoriyi döndürür
    lst = client.get("/api/tags", headers=auth_headers, params={"category": "TestÜrün"}).json()
    assert [t["id"] for t in lst] == [tag["id"]]


def test_application_tag_assign_filter_sync(client, auth_headers):
    a = client.post("/api/tags", headers=auth_headers,
                    json={"name": "Kart", "category": "TestEksen"}).json()
    b = client.post("/api/tags", headers=auth_headers,
                    json={"name": "ProdX", "category": "TestEksen"}).json()
    # Oluştururken etiket ata
    app = client.post("/api/applications", headers=auth_headers,
                      json={"app_name": "Etiketli Uygulama", "server_name": "srv-etiketli",
                            "tag_ids": [a["id"], b["id"]]}).json()
    got = client.get(f"/api/applications/{app['id']}", headers=auth_headers).json()
    assert sorted(t["id"] for t in got["tags"]) == sorted([a["id"], b["id"]])

    # Yalnız 'a' etiketli ikinci uygulama
    other = client.post("/api/applications", headers=auth_headers,
                        json={"app_name": "Tek Etiket", "server_name": "srv-tek",
                              "tag_ids": [a["id"]]}).json()

    # AND/kesişim: iki etiketle de filtre → yalnız iki etiketli app gelir, tek etiketli GELMEZ
    both = client.get("/api/applications", headers=auth_headers,
                      params=[("tag_ids", a["id"]), ("tag_ids", b["id"])]).json()
    both_ids = {x["id"] for x in both}
    assert app["id"] in both_ids and other["id"] not in both_ids

    # Tek etiket filtresi ikisini de getirir
    single_ids = {x["id"] for x in client.get("/api/applications", headers=auth_headers,
                                               params={"tag_ids": a["id"]}).json()}
    assert app["id"] in single_ids and other["id"] in single_ids

    # update senkron: yalnız 'b' bırak
    client.put(f"/api/applications/{app['id']}", headers=auth_headers, json={"tag_ids": [b["id"]]})
    assert [t["id"] for t in client.get(f"/api/applications/{app['id']}",
                                        headers=auth_headers).json()["tags"]] == [b["id"]]
    # tag_ids GÖNDERMEYEN update etikete DOKUNMAZ
    client.put(f"/api/applications/{app['id']}", headers=auth_headers, json={"app_user": "svc"})
    assert [t["id"] for t in client.get(f"/api/applications/{app['id']}",
                                        headers=auth_headers).json()["tags"]] == [b["id"]]
    # tag_ids=[] tümünü kaldırır
    client.put(f"/api/applications/{app['id']}", headers=auth_headers, json={"tag_ids": []})
    assert client.get(f"/api/applications/{app['id']}", headers=auth_headers).json()["tags"] == []


def test_tag_admin_only_and_cascade(client, auth_headers):
    uid = client.post("/api/users", headers=auth_headers,
                      json={"username": "tageditor", "password": "sifre123",
                            "role": "editor"}).json()["id"]
    team = client.post("/api/teams", headers=auth_headers,
                       json={"name": "TagSY", "type": "SY"}).json()
    client.post(f"/api/teams/{team['id']}/members", headers=auth_headers, json={"user_id": uid})
    r = client.post("/api/auth/login-json", json={"username": "tageditor", "password": "sifre123"})
    editor_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # YENİ kategoriyi yalnız ADMIN açabilir; editör denerse 403
    assert client.post("/api/tags", headers=editor_headers,
                       json={"name": "X", "category": "TestBakim"}).status_code == 403
    assert client.post("/api/tags", headers=auth_headers,
                       json={"name": "Kurucu", "category": "TestBakim"}).status_code == 200

    # Editör MEVCUT kategoriye etiket OLUŞTURABİLİR (form içi anında-ekleme)
    created = client.post("/api/tags", headers=editor_headers,
                          json={"name": "Geçici", "category": "TestBakim"})
    assert created.status_code == 200, created.text
    tag_id = created.json()["id"]

    # Global salt-okur (allviewer) da mevcut kategoriye ekleyebilir ('her kullanıcı')
    client.post("/api/users", headers=auth_headers,
                json={"username": "tagviewer", "password": "sifre123", "role": "allviewer"})
    r = client.post("/api/auth/login-json", json={"username": "tagviewer", "password": "sifre123"})
    viewer_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post("/api/tags", headers=viewer_headers,
                       json={"name": "İzleyiciEtiketi", "category": "TestBakim"}).status_code == 200
    assert client.post("/api/tags", headers=viewer_headers,
                       json={"name": "Y", "category": "İzleyiciKategori"}).status_code == 403

    # Editör DÜZENLEYEMEZ / SİLEMEZ (katalog bakımı yalnız admin)
    assert client.put(f"/api/tags/{tag_id}", headers=editor_headers,
                      json={"name": "X"}).status_code == 403
    assert client.delete(f"/api/tags/{tag_id}", headers=editor_headers).status_code == 403

    # Bir uygulamaya bağla; admin silince bağlantı düşer, uygulama etiketsiz kalır (cascade)
    app = client.post("/api/applications", headers=auth_headers,
                      json={"app_name": "Silinecek Etiketli", "server_name": "srv-silinecek",
                            "tag_ids": [tag_id]}).json()
    assert client.delete(f"/api/tags/{tag_id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/applications/{app['id']}", headers=auth_headers).json()["tags"] == []


def test_tag_scope_by_team(client, auth_headers):
    """KAPSAM: editor/viewer YALNIZ kendi SY ekiplerinin uygulamalarına atanmış etiketleri
    görür; admin tüm kataloğu görür. (Kullanıcı isteği: başka takımın etiket isimleri sızmasın.)"""
    # Ortak kategori + iki etiket (admin açar)
    a = client.post("/api/tags", headers=auth_headers,
                    json={"name": "KapEtiketA", "category": "KapKategori"}).json()
    b = client.post("/api/tags", headers=auth_headers,
                    json={"name": "KapEtiketB", "category": "KapKategori"}).json()
    # İki SY takımı + birer uygulama (her biri farklı etiketle)
    t_own = client.post("/api/teams", headers=auth_headers,
                        json={"name": "TagKapOwn", "type": "SY"}).json()
    t_other = client.post("/api/teams", headers=auth_headers,
                          json={"name": "TagKapOther", "type": "SY"}).json()
    client.post("/api/applications", headers=auth_headers,
                json={"app_name": "TagKapAppOwn", "server_name": "srv-own",
                      "sy_team_id": t_own["id"], "tag_ids": [a["id"]]})
    client.post("/api/applications", headers=auth_headers,
                json={"app_name": "TagKapAppOther", "server_name": "srv-other",
                      "sy_team_id": t_other["id"], "tag_ids": [b["id"]]})
    # own ekibinin editörü
    client.post("/api/users", headers=auth_headers, json={
        "username": "tagkap_ed", "password": "x", "role": "editor", "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=auth_headers).json()
               if u["username"] == "tagkap_ed")
    client.post(f"/api/teams/{t_own['id']}/members", headers=auth_headers, json={"user_id": uid})
    hed = {"Authorization": f"Bearer {client.post('/api/auth/login-json', json={'username':'tagkap_ed','password':'x'}).json()['access_token']}"}

    # Admin: iki etiketi de görür
    admin_names = {t["name"] for t in client.get("/api/tags", headers=auth_headers,
                                                 params={"category": "KapKategori"}).json()}
    assert {"KapEtiketA", "KapEtiketB"} <= admin_names
    # Editör: yalnız kendi ekibinin uygulamasına atanmış etiketi (A) görür, B görünmez
    ed_names = {t["name"] for t in client.get("/api/tags", headers=hed,
                                              params={"category": "KapKategori"}).json()}
    assert "KapEtiketA" in ed_names
    assert "KapEtiketB" not in ed_names


def test_search_matches_tag_name(client, auth_headers):
    """Genel arama ETİKET adıyla da eşleşir — ayrı etiket kutusu yerine tek arama (kullanıcı isteği)."""
    tag = client.post("/api/tags", headers=auth_headers,
                      json={"name": "AramaEtiketi", "category": "Ortam"}).json()
    team = client.post("/api/teams", headers=auth_headers,
                       json={"name": "AramaSY", "type": "SY"}).json()
    client.post("/api/applications", headers=auth_headers,
                json={"app_name": "EtiketliUyg", "server_name": "srv-e",
                      "sy_team_id": team["id"], "tag_ids": [tag["id"]]})
    client.post("/api/applications", headers=auth_headers,
                json={"app_name": "EtiketsizUyg", "server_name": "srv-s", "sy_team_id": team["id"]})
    # Etiket adıyla ara → yalnız etiketli uygulama gelir
    names = {a["app_name"] for a in client.get("/api/applications", headers=auth_headers,
                                               params={"search": "AramaEtiket"}).json()}
    assert "EtiketliUyg" in names
    assert "EtiketsizUyg" not in names
    # app_name ile ara → mevcut davranış korunur (etiket eşleşmesi eskiyi bozmaz)
    names2 = {a["app_name"] for a in client.get("/api/applications", headers=auth_headers,
                                                params={"search": "Etiketsiz"}).json()}
    assert "EtiketsizUyg" in names2
    assert "EtiketliUyg" not in names2
