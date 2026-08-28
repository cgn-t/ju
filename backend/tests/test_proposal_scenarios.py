"""Uçtan uca DEVİR ÖNERİSİ (TransferProposal) YAŞAM DÖNGÜSÜ senaryoları.

Her senaryo GERÇEK HTTP uçları üzerinden yürür: sertifika import → domain/uygulama/bağımlılık
kur → halef (supersede) import → /api/proposals listele → approve/reject/cancel → sonucu hem API
hem DB'den doğrula. Birim testleri (test_renewal / test_proposals_auth / test_trust_store) tekil
yolları kapsar; bu dosya onay hattının GRANÜL KOMBİNASYONLARINI ve tam karar döngülerini kapsar:

  1. Domain server eşlemesi devri — temel yaşam döngüsü (öneri → onay → taşı → eskiyi pasifle).
  2. Çoklu granül tek hat — domain server + mTLS bağımlılık birlikte; eski YALNIZ hepsi bitince pasif.
  3. Devir + trusted birlikte — server devrolur ama eski TRUSTED olduğu için AKTİF kalır.
  4. Red KALICI — otomatik (import) yol reddi yeniden açmaz; yalnız MANUEL supersede yeniden açar.
  5. İptal (cancel) — öneri kapanır, HİÇBİR mutasyon olmaz (eşleme durur, eski aktif kalır).
  6. Çok domainli KISMİ devir — birini onayla, diğerini reddet → eski yalnız reddedilen domainde kalır.
"""

from datetime import datetime

from app.db.models import Certificate
from app.db.session import SessionLocal
from tests import certgen


def _import(client, h, pem_text, *, supersede=False):
    return client.post("/api/certificates/import", headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")},
                       data={"supersede": "true"} if supersede else {})


def _leaf_id(resp):
    assert resp.status_code == 200, resp.text
    return next(c["id"] for c in resp.json() if c["cert_type"] == "leaf")


def _v1v2(cn):
    """Aynı anahtarlı (aynı SKI → halef sinyali) iki nesil: v1 eski, v2 yeni (valid_from sonraki)."""
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, cn, key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, cn, key=key, not_before=datetime(2026, 6, 1))
    return ca, v1, v2


def _domain(client, h, name):
    r = client.post("/api/domains", headers=h, json={"domain": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(client, h, domain_id, cert_id, mapping_type="server"):
    r = client.post(f"/api/domains/{domain_id}/certificates", headers=h,
                    json={"certificate_id": cert_id, "mapping_type": mapping_type})
    assert r.status_code == 200, r.text


def _team(client, h, name):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": f"{name}@t"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _app(client, h, name, sy):
    r = client.post("/api/applications", headers=h,
                    json={"app_name": name, "server_name": name, "sy_team_id": sy})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _dep(client, h, app_id, domain_id):
    """mTLS bağımlılığı: client sertifikası ELLE seçilmez, hedef domainin AKTİF server cert'i izlenir."""
    r = client.post(f"/api/applications/{app_id}/dependencies", headers=h,
                    json={"target_domain_id": domain_id})
    assert r.status_code == 200, r.text
    return r.json()


def _dep_client_id(client, h, app_id, dep_id):
    for d in client.get(f"/api/applications/{app_id}/dependencies", headers=h).json():
        if d["id"] == dep_id:
            return d["client_cert_id"]
    return None


def _trust(client, h, app_id, cert_id):
    r = client.post(f"/api/applications/{app_id}/trusted", headers=h, json={"certificate_id": cert_id})
    assert r.status_code == 200, r.text


def _trusted_ids(client, h, app_id):
    return {t["cert_id"] for t in client.get(f"/api/applications/{app_id}/trusted", headers=h).json()}


def _pending(client, h):
    return client.get("/api/proposals", headers=h, params={"status": "pending"}).json()


def _server_certs(client, h, domain_id):
    dom = client.get(f"/api/domains/{domain_id}", headers=h).json()
    return [c["certificate_id"] for c in dom["certificates"] if c["mapping_type"] == "server"]


def _active(cert_id):
    db = SessionLocal()
    try:
        return db.get(Certificate, cert_id).is_active
    finally:
        db.close()


def _approve(client, h, pid):
    r = client.post(f"/api/proposals/{pid}/approve", headers=h)
    assert r.status_code == 200, r.text


def _reject(client, h, pid):
    r = client.post(f"/api/proposals/{pid}/reject", headers=h)
    assert r.status_code == 200, r.text


# 1 — Domain server eşlemesi devri: temel yaşam döngüsü
def test_scn_domain_transfer_lifecycle(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-life.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-life-dom.test")
    _attach(client, h, dom, v1_id)

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    props = [p for p in _pending(client, h) if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id]
    assert len(props) == 1 and props[0]["kind"] == "transfer" and props[0]["mapping_type"] == "server"

    # onay ÖNCESİ hiçbir mutasyon yok: v1 hâlâ aktif ve eşli
    assert _server_certs(client, h, dom) == [v1_id]
    assert _active(v1_id) is True

    _approve(client, h, props[0]["id"])
    assert _server_certs(client, h, dom) == [v2_id], "onay sonrası eşleme v2'ye taşınmalı"
    assert _active(v1_id) is False, "tüm devri biten eski cert pasife alınmalı"


# 2 — Çoklu granül (domain server + mTLS bağımlılık) tek hatta: eski YALNIZ hepsi bitince pasif
def test_scn_multi_granule_transfer(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-multi.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-multi-dom.test")
    _attach(client, h, dom, v1_id)                     # v1 = domainin server cert'i
    sy = _team(client, h, "SCN-Multi-SY")
    app_id = _app(client, h, "SCN-Multi-App", sy)
    dep = _dep(client, h, app_id, dom)                 # bağımlılık v1'i izler (domainin aktif server'ı)
    assert dep["client_cert_id"] == v1_id

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    props = {p["mapping_type"] or ("dep" if p["app_dependency_id"] else "?"): p
             for p in _pending(client, h) if p["new_cert_id"] == v2_id}
    assert "server" in props and "dep" in props, f"iki granül önerisi bekleniyor: {props.keys()}"

    _approve(client, h, props["server"]["id"])         # önce domain devri
    assert _active(v1_id) is True, "bağımlılık önerisi hâlâ açık → eski pasife ALINMAMALI"

    _approve(client, h, props["dep"]["id"])             # sonra mTLS bağımlılık devri
    assert _dep_client_id(client, h, app_id, dep["id"]) == v2_id, "bağımlılık v2'ye taşınmalı"
    assert _server_certs(client, h, dom) == [v2_id]
    assert _active(v1_id) is False, "son granül de bitince eski pasif"


# 3 — Devir + trusted birlikte: server devrolur ama eski TRUSTED olduğu için AKTİF kalır
def test_scn_transfer_plus_trusted_keeps_old_active(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-trust-mix.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-trustmix-dom.test")
    _attach(client, h, dom, v1_id)
    sy = _team(client, h, "SCN-TrustMix-SY")
    app_id = _app(client, h, "SCN-TrustMix-App", sy)
    _trust(client, h, app_id, v1_id)                    # v1 aynı zamanda uygulamanın trust store'unda

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    props = {p["kind"]: p for p in _pending(client, h) if p["new_cert_id"] == v2_id}
    assert set(props) == {"transfer", "trusted_add"}, f"transfer + trusted_add bekleniyor: {props.keys()}"

    _approve(client, h, props["transfer"]["id"])        # domain server devri
    assert _server_certs(client, h, dom) == [v2_id]
    assert _active(v1_id) is True, "trusted açık önerisi var → eski pasife alınamaz"

    _approve(client, h, props["trusted_add"]["id"])     # trusted EKLEME (devir DEĞİL)
    assert _trusted_ids(client, h, app_id) == {v1_id, v2_id}, "eski+yeni birlikte trusted olmalı"
    assert _active(v1_id) is True, "trusted sertifika ASLA pasife alınmaz (eski+yeni güvenilir kalır)"


# 4 — Red KALICI: otomatik (import) yol reddi yeniden açmaz; yalnız MANUEL supersede açar
def test_scn_reject_is_permanent_manual_reopens(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-reject.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-reject-dom.test")
    _attach(client, h, dom, v1_id)

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    p = next(p for p in _pending(client, h) if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id)
    _reject(client, h, p["id"])
    assert _server_certs(client, h, dom) == [v1_id] and _active(v1_id) is True, "red → eski aktif+eşli kalır"

    # otomatik yol (tekrar import supersede) reddi HORTLATMAMALI
    _import(client, h, certgen.pem(v2), supersede=True)
    assert not [x for x in _pending(client, h) if x["new_cert_id"] == v2_id and x["old_cert_id"] == v1_id], \
        "red kalıcı — otomatik yol yeni öneri açmamalı"

    # MANUEL supersede reddi bilinçli olarak yeniden açar
    r = client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=h)
    assert r.status_code == 200 and r.json()["proposed"] == 1, r.text
    p2 = next(x for x in _pending(client, h) if x["new_cert_id"] == v2_id and x["old_cert_id"] == v1_id)
    _approve(client, h, p2["id"])
    assert _server_certs(client, h, dom) == [v2_id] and _active(v1_id) is False


# 5 — İptal (cancel): öneri kapanır, HİÇBİR mutasyon olmaz
def test_scn_cancel_no_mutation(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-cancel.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-cancel-dom.test")
    _attach(client, h, dom, v1_id)

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    p = next(p for p in _pending(client, h) if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id)
    r = client.post(f"/api/proposals/{p['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text

    assert not [x for x in _pending(client, h) if x["id"] == p["id"]], "iptal → artık pending değil"
    assert _server_certs(client, h, dom) == [v1_id], "iptal hiçbir eşleme taşımamalı"
    assert _active(v1_id) is True


# 6 — Çok domainli KISMİ devir: birini onayla, diğerini reddet
def test_scn_multi_domain_partial_transfer(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-partial.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom_a = _domain(client, h, "scn-partial-a.test")
    dom_b = _domain(client, h, "scn-partial-b.test")
    _attach(client, h, dom_a, v1_id)
    _attach(client, h, dom_b, v1_id)

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    props = {p["domain_name"]: p for p in _pending(client, h) if p["new_cert_id"] == v2_id}
    assert set(props) == {"scn-partial-a.test", "scn-partial-b.test"}, f"iki domain önerisi: {props.keys()}"

    # /group ucu aynı devrin tüm kardeş domain önerilerini listeler (farkındalık)
    grp = client.get(f"/api/proposals/{props['scn-partial-a.test']['id']}/group", headers=h).json()
    assert {g["domain_name"] for g in grp} == {"scn-partial-a.test", "scn-partial-b.test"}

    _reject(client, h, props["scn-partial-b.test"]["id"])
    _approve(client, h, props["scn-partial-a.test"]["id"])
    assert _server_certs(client, h, dom_a) == [v2_id], "A onaylandı → v2"
    assert _server_certs(client, h, dom_b) == [v1_id], "B reddedildi → v1 kalır"
    assert _active(v1_id) is True, "B'ye hâlâ eşli olduğundan eski AKTİF kalmalı (kısmi devir)"


# 7 — Rakip halef önerileri (Bug #1 regresyonu): aynı (domain,server) yuvası için iki açık öneri
#     (v1→v2, v1→v3); ikisi de onaylanınca domain TEK server cert taşımalı (çift eşleme OLMAMALI)
def test_scn_competing_successors_no_double_mapping(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("CA scn-race.test")
    key = certgen.make_key()                            # ortak anahtar → aynı SKI → her ikisi de halef
    v1c, _ = certgen.make_leaf(ca, ca_key, "scn-race.test", key=key, not_before=datetime(2026, 1, 1))
    v2c, _ = certgen.make_leaf(ca, ca_key, "scn-race.test", key=key, not_before=datetime(2026, 6, 1))
    v3c, _ = certgen.make_leaf(ca, ca_key, "scn-race.test", key=key, not_before=datetime(2026, 9, 1))
    v1 = _leaf_id(_import(client, h, certgen.pem(v1c) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-race-dom.test")
    _attach(client, h, dom, v1)
    v2 = _leaf_id(_import(client, h, certgen.pem(v2c), supersede=True))
    v3 = _leaf_id(_import(client, h, certgen.pem(v3c), supersede=True))
    pend = _pending(client, h)
    p2 = next(p for p in pend if p["new_cert_id"] == v2 and p["old_cert_id"] == v1)
    p3 = next(p for p in pend if p["new_cert_id"] == v3 and p["old_cert_id"] == v1)

    _approve(client, h, p2["id"])
    assert _server_certs(client, h, dom) == [v2], "ilk onay → yuva v2'de"
    _approve(client, h, p3["id"])                       # yuva DOLU → ikinci eşleme EKLENMEMELİ (no-op)
    assert _server_certs(client, h, dom) == [v2], \
        "domain TEK server cert taşımalı; rakip halef yuvayı doldurduğundan v3 eklenmez (Bug #1)"


# 8 — Cross-granül: server onayı + dep RED → eski, hâlâ bağımlılığı olduğu için AKTİF kalır.
# Senaryo #2'nin (çoklu granül) ikiz kardeşi ama dep onayı yerine RED ediliyor — bu kombinasyon
# hiçbir testte kapsanmıyordu (_maybe_deactivate_old'daki has_deps kontrolünün tam olarak
# koruduğu durum).
def test_scn_server_approve_dep_reject_old_stays_active(client, auth_headers):
    h = auth_headers
    ca, v1, v2 = _v1v2("scn-cross.test")
    v1_id = _leaf_id(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "scn-cross-dom.test")
    _attach(client, h, dom, v1_id)                      # v1 = domainin server cert'i
    sy = _team(client, h, "SCN-Cross-SY")
    app_id = _app(client, h, "SCN-Cross-App", sy)
    dep = _dep(client, h, app_id, dom)                  # bağımlılık v1'i izler
    assert dep["client_cert_id"] == v1_id

    v2_id = _leaf_id(_import(client, h, certgen.pem(v2), supersede=True))
    props = {p["mapping_type"] or ("dep" if p["app_dependency_id"] else "?"): p
             for p in _pending(client, h) if p["new_cert_id"] == v2_id}
    assert "server" in props and "dep" in props, f"iki granül önerisi bekleniyor: {props.keys()}"

    _approve(client, h, props["server"]["id"])          # domain devri ONAYLANDI
    _reject(client, h, props["dep"]["id"])              # mTLS bağımlılık devri REDDEDİLDİ

    assert _server_certs(client, h, dom) == [v2_id], "server eşlemesi v2'ye taşınmalı"
    # Reddedilen öneri HİÇBİR mutasyon yapmaz — dep hâlâ v1'i izliyor
    assert _dep_client_id(client, h, app_id, dep["id"]) == v1_id, \
        "reddedilen dep önerisi bağımlılığı taşımamalı"
    # Tüm açık öneriler kapandı (biri applied, biri rejected) AMA eski cert hâlâ bir mTLS
    # bağımlılığına bağlı olduğundan PASİFE ALINAMAZ (_maybe_deactivate_old has_deps kontrolü)
    assert _active(v1_id) is True, \
        "eski cert hâlâ bir mTLS bağımlılığına bağlı, tüm önerilerin kapanmasına rağmen aktif kalmalı"
