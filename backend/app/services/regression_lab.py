"""Regresyon Testi > Test Hazırlığı (v3.9.28, yalnız admin, yalnız REGRESSION_TOOLS=1 iken).

Eskiden testten önce elle yapılan hazırlığı Jumbo'nun içine alır:
  1) Test sertifikaları: 00–25 numaralı dosyalar ve test sitelerinin sertifikaları, ÜRETİM ANINA göre
     (paketteki sertifika-uret.py'nin aynısı; ad: localhost).
  2) Test siteleri: 9441–9447 TLS siteleri ve 9440'ta iptal listesi (iptal.crl), Jumbo sürecinin
     içinde, localhost'ta. Jumbo bunlara kendi üstünden bağlandığı için ayrı makine/DNS/Docker gerekmez.
     Belirli süre (varsayılan 4 saat) sonra kendiliğinden kapanır.
  3) Test verisi: 4 SY ekibi ve rol/üyelikleri ayarlı 4 yerel test hesabı.
  4) Temizleme: test sertifikaları (O=Jumbo Regresyon Testi), test domainleri (localhost…,
     *.jumbo-test.local, test ekiplerinin domainleri), test ekiplerinin uygulamaları, bu sekmenin
     açtığı ekipler ve hesaplar.

Yeni tablo yok: durum app_settings'te tek satırda (category 'regression_lab') JSON olarak durur.
Bu satırı her süreç (çoklu worker/pod) okur; her süreçteki izleyici iş parçacığı siteleri duruma göre
açar/kapatır. Port başka bir süreçte açıksa o süreç sunar (localhost aynı pod içinde).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import secrets
import socket
import ssl
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppSetting, Team, User, UserTeam

logger = logging.getLogger(__name__)

STATE_KEY = "regression_lab.state"
CATEGORY = "regression_lab"
HOST = "localhost"
PFX_PAROLA = "Jumbo2026!"
TEST_ORG = "Jumbo Regresyon Testi"   # her test sertifikasının Subject O'su (temizlik bununla bulur)
CRL_PORT = 9440
SITE_HOURS = 4

# port → sunucu dosyası (9444: (eski, yeni))
SITES: dict[int, str | tuple[str, str]] = {
    9441: "9441-uyumlu",
    9442: "9442-baska-site",
    9443: "9443-ara-sertifika-eksik",
    9444: ("9444-yenileme-eski", "9444-yenileme-yeni"),
    9445: "9445-20-gun-kala",
    9446: "9446-suresi-gecmis",
    9447: "9447-45-gun-kala",
}
SITE_INFO = {
    9440: "İptal listesi (iptal.crl)",
    9441: "Doğru sertifika ve ara sertifika (sorunsuz site)",
    9442: "Başka sitenin sertifikası (baska-site.jumbo-test.local)",
    9443: "Doğru sertifika, ara sertifikayı göndermez",
    9444: "Yenileme testi: eski sertifika (25 gün kala) ya da yenisi",
    9445: "20 gün kala dolacak sertifika",
    9446: "Süresi 5 gün önce dolmuş sertifika",
    9447: "45 gün kala dolacak sertifika",
}
SITE_DAYS = {9441: 300, 9442: 300, 9443: 280, 9444: 25, 9445: 20, 9446: -5, 9447: 45}

# Dosya → (ne için, kılavuz bölümü)
FILE_INFO: dict[str, tuple[str, str]] = {
    "00-kok-ve-ara-sertifika.pem": ("Root + Intermediate (test CA'ları)", "Bölüm 1"),
    "01-tek-sertifika.pem": ("Tek Leaf, Windows satır sonu", "Bölüm 1"),
    "02-tam-zincir-ters-sira-anahtarli.pem": ("Ters sırada tam zincir + özel anahtar", "Bölüm 1"),
    "03-der-bicimi.cer": ("DER biçimi", "Bölüm 1"),
    "04-p7b-paketi.p7b": ("P7B paketi", "Bölüm 1"),
    "05-parolali-pfx.pfx": (f"Parolalı PFX (parola {PFX_PAROLA})", "Bölüm 1"),
    "06-notepad-unicode-kayit.pem": ("UTF-16 (Notepad Unicode) kayıt", "Bölüm 1"),
    "07-yalniz-ozel-anahtar.key": ("Yalnız özel anahtar (reddedilmeli)", "Bölüm 1"),
    "08-ilgisiz-dosya.txt": ("Sertifika olmayan dosya (reddedilmeli)", "Bölüm 1"),
    "09-cn-siz-ec-sertifika.pem": ("CN'siz EC sertifika (ad yalnız SAN'da)", "Bölüm 1"),
    "10-trusted-20-gun-kala.pem": ("Trusted, 20 gün kala", "Bölüm 1"),
    "11-trusted-suresi-gecmis.pem": ("Trusted, süresi geçmiş", "Bölüm 1"),
    "12-sahipsiz-20-gun-kala.pem": ("Sahipsiz, 20 gün kala", "Bölüm 1"),
    "13-domain-yukleme.xlsx": ("Excel ile domain yükleme", "Bölüm 1"),
    "14-iptal-edilmis.pem": ("İptal edilmiş (CRL'de)", "11. bölüm"),
    "15-iptal-edilmemis.pem": ("İptal edilmemiş", "11. bölüm"),
    "16-iptal-bilgisi-yok.pem": ("İptal bilgisi yok", "11. bölüm"),
    "17-zayif-rsa-1024.pem": ("Zayıf anahtar: RSA 1024", "10. bölüm"),
    "18-zayif-ec-p192.pem": ("Zayıf anahtar: EC P-192", "10. bölüm"),
    "19-sha224-imzali.pem": ("SHA-224 imza", "10. bölüm"),
    "20-omur-399-gun.pem": ("Ömür 399 gün (sınırın üstü)", "10. bölüm"),
    "21-omur-398-gun.pem": ("Ömür 398 gün (sınırda)", "10. bölüm"),
    "22-baska-yayinci.pem": ("İzin listesi dışı CA", "10. bölüm"),
    "23-istanbul-yayinci.pem": ("Türkçe İ'li CA adı", "10. bölüm"),
    "24-trusted-yenisi.pem": ("10'un yenisi (trust store)", "8. bölüm"),
    "25-sunucu-yenisi.pem": ("9446'nın yenisi (dış bağımlılık)", "8. bölüm"),
}

TEST_TEAMS = [  # (ad, mail alanı A/B/C ya da None)
    ("Ödeme Sistemleri SY", "a"),
    ("İletişim Kanalları SY", "b"),
    ("Mobil Uygulamalar SY", "c"),
    ("Mailsiz Test SY", None),
]
TEST_USERS = [  # (kullanıcı adı, rol, ekip) — ilkinin adında "i" var (I/İ testi)
    ("ismail.test", "editor", "Ödeme Sistemleri SY"),
    ("iletisim.test", "editor", "İletişim Kanalları SY"),
    ("izleyici.test", "viewer", "Ödeme Sistemleri SY"),
    ("rolsuz.test", "none", None),
]


def enabled() -> bool:
    return bool(get_settings().regression_tools)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------- durum (app_settings)
def load_state(db: Session) -> dict:
    row = db.get(AppSetting, STATE_KEY)
    if row is None or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except ValueError:
        return {}


def save_state(db: Session, state: dict) -> None:
    row = db.get(AppSetting, STATE_KEY)
    if row is None:
        row = AppSetting(key=STATE_KEY, category=CATEGORY)
        db.add(row)
    row.value = json.dumps(state, ensure_ascii=False)
    db.commit()


# ---------------------------------------------------------------- 1) sertifika üretimi
def generate(host: str = HOST) -> dict:
    """Paketteki sertifika-uret.py ile aynı dosyaları bellekte üretir.
    Dönüş: {"files": {ad: bytes}, "server": {ad: bytes}, "generated_at": iso}"""
    files: dict[str, bytes] = {}
    server: dict[str, bytes] = {}
    now = _now()
    crl_url = f"http://{host}:{CRL_PORT}/iptal.crl"

    def key():
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def name(cn=None, o=TEST_ORG):
        attrs = [x509.NameAttribute(NameOID.ORGANIZATION_NAME, o)]
        if cn:
            attrs.insert(0, x509.NameAttribute(NameOID.COMMON_NAME, cn))
        return x509.Name(attrs)

    def build(subject, issuer_name, pub, sign_key, issuer_pub, start, end, ca=False, path_len=None,
              san=None, crl=False):
        b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name)
             .public_key(pub).serial_number(x509.random_serial_number())
             .not_valid_before(start).not_valid_after(end)
             .add_extension(x509.BasicConstraints(ca=ca, path_length=path_len), critical=True)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_pub), critical=False))
        if ca:
            b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                                critical=True)
        else:
            b = b.add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False),
                                critical=True)
            b = b.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                                critical=False)
        if san:
            b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in san]), critical=False)
        if crl:
            b = b.add_extension(x509.CRLDistributionPoints([x509.DistributionPoint(
                [x509.UniformResourceIdentifier(crl_url)], None, None, None)]), critical=False)
        return b.sign(sign_key, hashes.SHA256())

    def pem(c) -> str:
        return c.public_bytes(serialization.Encoding.PEM).decode()

    def kpem(k) -> str:
        return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()

    root_k = key()
    root = build(name("Jumbo Test Kök SM"), name("Jumbo Test Kök SM"), root_k.public_key(), root_k,
                 root_k.public_key(), now - timedelta(days=30), now + timedelta(days=3650), ca=True)
    ara_k = key()
    ara = build(name("Jumbo Test Ara SM"), root.subject, ara_k.public_key(), root_k, root_k.public_key(),
                now - timedelta(days=30), now + timedelta(days=1825), ca=True, path_len=0)

    def leaf(cn, days_left, san=None, start_days_ago=60, k=None, crl=False):
        k = k or key()
        c = build(name(cn), ara.subject, k.public_key(), ara_k, ara_k.public_key(),
                  now - timedelta(days=start_days_ago), now + timedelta(days=days_left),
                  san=san if san is not None else [cn], crl=crl)
        return c, k

    def site(dosya, c, k, zincir=True):
        server[f"{dosya}.pem"] = (pem(c) + (pem(ara) if zincir else "")).encode()
        server[f"{dosya}.key"] = kpem(k).encode()

    c, k = leaf(host, 300)
    site("9441-uyumlu", c, k)
    c, k = leaf("baska-site.jumbo-test.local", 300)
    site("9442-baska-site", c, k)
    c, k = leaf(host, 280)
    site("9443-ara-sertifika-eksik", c, k, zincir=False)
    eski_k = key()
    c, _ = leaf(host, 25, k=eski_k)
    site("9444-yenileme-eski", c, eski_k)
    c, k = leaf(host, 395, start_days_ago=1)
    site("9444-yenileme-yeni", c, k)
    c, k = leaf(host, 20)
    site("9445-20-gun-kala", c, k)
    c, k = leaf(host, -5, start_days_ago=400)
    site("9446-suresi-gecmis", c, k)
    c, k = leaf(host, 45)
    site("9447-45-gun-kala", c, k)

    files["00-kok-ve-ara-sertifika.pem"] = (pem(root) + pem(ara)).encode()
    c, _ = leaf("tek-sertifika.jumbo-test.local", 200)
    files["01-tek-sertifika.pem"] = pem(c).replace("\n", "\r\n").encode()
    c, k = leaf("tam-zincir.jumbo-test.local", 210)
    files["02-tam-zincir-ters-sira-anahtarli.pem"] = (pem(root) + pem(ara) + pem(c) + kpem(k)).encode()
    c, _ = leaf("der-bicimi.jumbo-test.local", 220)
    files["03-der-bicimi.cer"] = c.public_bytes(serialization.Encoding.DER)
    c, _ = leaf("p7b-paketi.jumbo-test.local", 230)
    files["04-p7b-paketi.p7b"] = pkcs7.serialize_certificates([c, ara], serialization.Encoding.PEM)
    c, k = leaf("parolali-pfx.jumbo-test.local", 240)
    files["05-parolali-pfx.pfx"] = pkcs12.serialize_key_and_certificates(
        b"parolali-pfx", k, c, [ara], serialization.BestAvailableEncryption(PFX_PAROLA.encode()))
    c, _ = leaf("notepad-unicode.jumbo-test.local", 250)
    files["06-notepad-unicode-kayit.pem"] = pem(c).encode("utf-16")
    files["07-yalniz-ozel-anahtar.key"] = kpem(key()).encode()
    files["08-ilgisiz-dosya.txt"] = "Bu bir sertifika değil. Jumbo anlaşılır bir hata vermeli.\n".encode()
    eck = ec.generate_private_key(ec.SECP256R1())
    c = build(name(None), ara.subject, eck.public_key(), ara_k, ara_k.public_key(),
              now - timedelta(days=10), now + timedelta(days=260), san=["cn-siz-ec.jumbo-test.local"])
    files["09-cn-siz-ec-sertifika.pem"] = pem(c).encode()
    c, _ = leaf("trusted-20-gun-kala.jumbo-test.local", 20)
    files["10-trusted-20-gun-kala.pem"] = pem(c).encode()
    c, _ = leaf("trusted-suresi-gecmis.jumbo-test.local", -3, start_days_ago=400)
    files["11-trusted-suresi-gecmis.pem"] = pem(c).encode()
    c, _ = leaf("sahipsiz-20-gun-kala.jumbo-test.local", 20)
    files["12-sahipsiz-20-gun-kala.pem"] = pem(c).encode()

    iptal, _ = leaf("iptal-edilmis.jumbo-test.local", 200, crl=True)
    files["14-iptal-edilmis.pem"] = pem(iptal).encode()
    c, _ = leaf("iptal-edilmemis.jumbo-test.local", 200, crl=True)
    files["15-iptal-edilmemis.pem"] = pem(c).encode()
    c, _ = leaf("iptal-bilgisi-yok.jumbo-test.local", 200)
    files["16-iptal-bilgisi-yok.pem"] = pem(c).encode()
    liste = (x509.CertificateRevocationListBuilder().issuer_name(ara.subject)
             .last_update(now - timedelta(days=1)).next_update(now + timedelta(days=3650))
             .add_revoked_certificate(x509.RevokedCertificateBuilder()
                                      .serial_number(iptal.serial_number)
                                      .revocation_date(now - timedelta(days=1)).build())
             .sign(ara_k, hashes.SHA256()))
    server["iptal.crl"] = liste.public_bytes(serialization.Encoding.DER)

    def uyum(cn, k, days_left=200, start_days_ago=10, hsh=None, issuer=None):
        ik, isub = issuer or (ara_k, ara.subject)
        b = (x509.CertificateBuilder().subject_name(name(cn)).issuer_name(isub)
             .public_key(k.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - timedelta(days=start_days_ago))
             .not_valid_after(now + timedelta(days=days_left))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False))
        return b.sign(ik, hsh or hashes.SHA256())

    files["17-zayif-rsa-1024.pem"] = pem(uyum(
        "zayif-rsa.jumbo-test.local", rsa.generate_private_key(public_exponent=65537, key_size=1024))).encode()
    files["18-zayif-ec-p192.pem"] = pem(uyum(
        "zayif-ec.jumbo-test.local", ec.generate_private_key(ec.SECP192R1()))).encode()
    files["19-sha224-imzali.pem"] = pem(uyum("sha224-imza.jumbo-test.local", key(), hsh=hashes.SHA224())).encode()
    files["20-omur-399-gun.pem"] = pem(uyum("omur-399.jumbo-test.local", key(), days_left=389)).encode()
    files["21-omur-398-gun.pem"] = pem(uyum("omur-398.jumbo-test.local", key(), days_left=388)).encode()
    for dosya, sm_adi, cn in (("22-baska-yayinci", "Bilinmeyen Test SM", "baska-yayinci.jumbo-test.local"),
                              ("23-istanbul-yayinci", "İSTANBUL Test SM", "istanbul-yayinci.jumbo-test.local")):
        sk = key()
        sm = build(name(sm_adi), name(sm_adi), sk.public_key(), sk, sk.public_key(),
                   now - timedelta(days=30), now + timedelta(days=3650), ca=True)
        files[f"{dosya}.pem"] = (pem(uyum(cn, key(), issuer=(sk, sm.subject))) + pem(sm)).encode()
    c, _ = leaf("trusted-20-gun-kala.jumbo-test.local", 300, start_days_ago=1)
    files["24-trusted-yenisi.pem"] = pem(c).encode()
    c, _ = leaf(host, 300, start_days_ago=1)
    files["25-sunucu-yenisi.pem"] = pem(c).encode()

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["domain", "sy", "external_company", "info"])
    ws.append(["excel-bir.jumbo-test.local", "Ödeme Sistemleri SY", "", "Türkçe not: ğüşıöçİ"])
    ws.append(["excel-iki.jumbo-test.local", "İletişim Kanalları SY", "İletişim Hizmetleri A.Ş.", "İkinci ekip"])
    ws.append(["EXCEL-BIR.jumbo-test.local", "Ödeme Sistemleri SY", "", "Büyük harfle ikiz: atlanmalı"])
    ws.append(["", "Ödeme Sistemleri SY", "", "domain boş: hatalı satır"])
    ws.append(["excel-uc.jumbo-test.local", "ODEME SISTEMLERI SY", "", "Türkçe harfsiz ekip adı"])
    buf = io.BytesIO()
    wb.save(buf)
    files["13-domain-yukleme.xlsx"] = buf.getvalue()

    return {"files": dict(sorted(files.items())), "server": server, "generated_at": now.isoformat()}


def _enc(d: dict[str, bytes]) -> dict[str, str]:
    return {k: base64.b64encode(v).decode() for k, v in d.items()}


def _dec(d: dict[str, str]) -> dict[str, bytes]:
    return {k: base64.b64decode(v) for k, v in (d or {}).items()}


def generate_and_store(db: Session, by: str) -> dict:
    g = generate()
    state = load_state(db)
    state["certs"] = {"generated_at": g["generated_at"], "by": by,
                      "files": _enc(g["files"]), "server": _enc(g["server"])}
    sites = state.get("sites") or {}
    sites["version"] = int(sites.get("version") or 0) + 1   # açık siteler yeni sertifikalara geçsin
    state["sites"] = sites
    save_state(db, state)
    return state


def file_bytes(db: Session, name: str) -> bytes | None:
    return _dec((load_state(db).get("certs") or {}).get("files") or {}).get(name)


def zip_bytes(db: Session) -> bytes | None:
    certs = load_state(db).get("certs") or {}
    files = _dec(certs.get("files") or {})
    if not files:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(f"dosyalar/{n}", b)
        z.writestr("BILGI.txt", (
            f"Üretim zamanı (UTC): {certs.get('generated_at', '')}\nTest sitesi adı: {HOST}\n"
            f"PFX parolası: {PFX_PAROLA}\n").encode())
    return buf.getvalue()


# ---------------------------------------------------------------- 2) test siteleri
def start_sites(db: Session, by: str, hours: int = SITE_HOURS) -> dict:
    state = load_state(db)
    if not (state.get("certs") or {}).get("server"):
        raise ValueError("Önce test sertifikalarını üretin")
    sites = state.get("sites") or {}
    sites.update({"running": True, "until": (_now() + timedelta(hours=hours)).isoformat(), "by": by,
                  "version": int(sites.get("version") or 0) + 1})
    state["sites"] = sites
    save_state(db, state)
    sync_now(state)
    return state


def stop_sites(db: Session) -> dict:
    state = load_state(db)
    sites = state.get("sites") or {}
    sites["running"] = False
    state["sites"] = sites
    save_state(db, state)
    sync_now(state)
    return state


def set_renewed(db: Session, renewed: bool) -> dict:
    state = load_state(db)
    sites = state.get("sites") or {}
    sites["renewed"] = bool(renewed)
    state["sites"] = sites
    save_state(db, state)
    sync_now(state)
    return state


def sites_should_run(state: dict) -> bool:
    sites = state.get("sites") or {}
    if not sites.get("running") or not (state.get("certs") or {}).get("server"):
        return False
    try:
        return datetime.fromisoformat(sites["until"]) > _now()
    except (KeyError, ValueError):
        return False


def probe(port: int, timeout: float = 1.5) -> bool:
    """Port bu makinede (bu pod'da) cevap veriyor mu? Hangi süreç açtıysa açsın."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


class _Runner:
    """Bu süreçteki test siteleri. Her port bir dinleyici; sertifikalar geçici klasörde."""

    def __init__(self):
        self.lock = threading.Lock()
        self.socks: dict[int, socket.socket] = {}
        self.crl: ThreadingHTTPServer | None = None
        self.version: int | None = None
        self.renewed = False
        self.ctx: dict[str, ssl.SSLContext] = {}
        self.crl_bytes = b""
        self.tmp: tempfile.TemporaryDirectory | None = None

    def _load(self, server: dict[str, bytes]) -> None:
        if self.tmp:
            self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(prefix="jumbo-lab-")
        d = Path(self.tmp.name)
        for n, b in server.items():
            (d / n).write_bytes(b)
        self.ctx = {}
        for n in server:
            if n.endswith(".pem"):
                base = n[:-4]
                c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                c.load_cert_chain(d / f"{base}.pem", d / f"{base}.key")
                self.ctx[base] = c
        self.crl_bytes = server.get("iptal.crl", b"")

    def _ctx_for(self, port: int) -> ssl.SSLContext:
        f = SITES[port]
        if isinstance(f, tuple):
            return self.ctx[f[1] if self.renewed else f[0]]
        return self.ctx[f]

    def _serve_tls(self, port: int) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:   # başka bir worker açmış: o sunar
            s.close()
            return
        s.listen(50)
        s.settimeout(1.0)   # kapatma bayrağına bakabilmek için accept saniyede bir uyanır
        self.socks[port] = s

        def one(conn):
            try:
                conn.settimeout(10)
                t = self._ctx_for(port).wrap_socket(conn, server_side=True)
                try:
                    t.recv(4096)
                    t.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"
                              b"Jumbo test sitesi\n")
                except OSError:
                    pass
                t.close()
            except (OSError, ssl.SSLError, KeyError):
                conn.close()

        def loop():
            while self.socks.get(port) is s:
                try:
                    conn, _ = s.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break   # kapatıldı
                conn.settimeout(None)
                threading.Thread(target=one, args=(conn,), daemon=True).start()
            try:
                s.close()
            except OSError:
                pass

        threading.Thread(target=loop, daemon=True, name=f"lab-{port}").start()

    def _serve_crl(self) -> None:
        runner = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.path == "/iptal.crl" and bool(runner.crl_bytes)
                self.send_response(200 if ok else 404)
                self.send_header("Content-Type", "application/pkix-crl")
                self.end_headers()
                if ok:
                    self.wfile.write(runner.crl_bytes)

            def log_message(self, *a):
                pass

        try:
            self.crl = ThreadingHTTPServer(("127.0.0.1", CRL_PORT), H)
        except OSError:
            self.crl = None
            return
        threading.Thread(target=self.crl.serve_forever, daemon=True, name="lab-crl").start()

    def stop(self) -> None:
        for s in self.socks.values():
            try:
                s.shutdown(socket.SHUT_RDWR)   # bekleyen accept'i uyandırır
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        self.socks = {}
        if self.crl:
            self.crl.shutdown()
            self.crl.server_close()
            self.crl = None
        self.version = None

    def sync(self, state: dict) -> None:
        with self.lock:
            if not sites_should_run(state):
                if self.socks or self.crl:
                    self.stop()
                    logger.info("Regresyon test siteleri kapatıldı")
                return
            sites = state["sites"]
            self.renewed = bool(sites.get("renewed"))
            ver = int(sites.get("version") or 0)
            if ver != self.version:
                self._load(_dec(state["certs"]["server"]))
                self.version = ver
            for port in SITES:
                if port not in self.socks:
                    self._serve_tls(port)
            if self.crl is None:
                self._serve_crl()


_runner = _Runner()


def sync_now(state: dict) -> None:
    try:
        _runner.sync(state)
    except Exception:   # siteler açılamasa da istek düşmesin
        logger.exception("Regresyon test siteleri güncellenemedi")


def start_watcher(session_factory, interval: float = 10.0) -> None:
    """Her süreçte: durumu periyodik okuyup siteleri açar/kapatır (çoklu worker/pod, süre dolumu)."""
    if not enabled():
        return

    def loop():
        while True:
            try:
                with session_factory() as db:
                    st = load_state(db)
                sync_now(st)
            except Exception:
                logger.exception("Regresyon test sitesi izleyicisi")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="lab-watcher").start()


# ---------------------------------------------------------------- 3) test ekipleri ve hesapları
def prepare_data(db: Session, by: str, emails: dict | None = None) -> dict:
    from app.core.security import hash_password
    emails = {k: (v or "").strip() or None for k, v in (emails or {}).items()}
    state = load_state(db)
    created = state.get("created") or {"team_ids": [], "user_ids": []}
    teams: dict[str, Team] = {}
    for tname, mail_key in TEST_TEAMS:
        t = db.query(Team).filter(Team.name == tname, Team.type == "SY").first()
        if t is None:
            t = Team(name=tname, type="SY")
            db.add(t)
            db.flush()
            created["team_ids"].append(t.id)
        if mail_key and emails.get(mail_key) and (t.id in created["team_ids"] or not t.email):
            t.email = emails[mail_key]
        teams[tname] = t
    password = state.get("password") or ("Test-" + secrets.token_urlsafe(9))
    for uname, role, tname in TEST_USERS:
        u = db.query(User).filter(User.username == uname).first()
        if u is None:
            u = User(username=uname, full_name=f"Regresyon {uname}", auth_source="local", role=role,
                     is_active=True, password_hash=hash_password(password))
            db.add(u)
            db.flush()
            created["user_ids"].append(u.id)
        elif u.id in created["user_ids"]:
            u.role, u.is_active, u.password_hash = role, True, hash_password(password)
        else:
            continue   # aynı adlı gerçek hesaba dokunulmaz
        if tname and not db.query(UserTeam).filter_by(user_id=u.id, team_id=teams[tname].id).first():
            db.add(UserTeam(user_id=u.id, team_id=teams[tname].id))
    db.commit()
    state = load_state(db)
    state["created"] = created
    state["password"] = password
    state["data_at"] = _now().isoformat()
    state["data_by"] = by
    save_state(db, state)
    return state


def data_view(db: Session, state: dict) -> dict:
    created = state.get("created") or {}
    teams = []
    for tname, mail_key in TEST_TEAMS:
        t = db.query(Team).filter(Team.name == tname, Team.type == "SY").first()
        teams.append({"name": tname, "exists": t is not None, "email": t.email if t else None,
                      "mail_key": mail_key.upper() if mail_key else None,
                      "created_here": bool(t and t.id in created.get("team_ids", []))})
    users = []
    for uname, role, tname in TEST_USERS:
        u = db.query(User).filter(User.username == uname).first()
        users.append({"username": uname, "role": role, "team": tname, "exists": u is not None,
                      "created_here": bool(u and u.id in created.get("user_ids", []))})
    return {"teams": teams, "users": users, "password": state.get("password") if users else None,
            "at": state.get("data_at")}


# ---------------------------------------------------------------- 4) temizlik
def _test_domain(name: str) -> bool:
    n = (name or "").lower()
    return n.startswith("localhost") or n.endswith(".jumbo-test.local") or ".jumbo-test.local:" in n


def cleanup_targets(db: Session) -> dict:
    from app.db.models import Application, Certificate, Domain
    state = load_state(db)
    created = state.get("created") or {}
    team_ids = set(created.get("team_ids") or [])
    marker = f"O={TEST_ORG}"
    certs = db.query(Certificate).filter(
        Certificate.subject.contains(marker) | Certificate.issuer.contains(marker)).all()
    domains = [d for d in db.query(Domain).all()
               if _test_domain(d.domain) or (d.sy_team_id in team_ids)]
    dom_ids = {d.id for d in domains}
    apps = [a for a in db.query(Application).all()
            if a.sy_team_id in team_ids or getattr(a, "domain_id", None) in dom_ids]
    users = db.query(User).filter(User.id.in_(created.get("user_ids") or [-1])).all()
    teams = db.query(Team).filter(Team.id.in_(team_ids or {-1})).all()
    return {"certificates": certs, "domains": domains, "applications": apps, "users": users, "teams": teams}


def cleanup_preview(db: Session) -> dict:
    t = cleanup_targets(db)
    return {k: len(v) for k, v in t.items()}


def cleanup(db: Session, admin: User, request=None) -> dict:
    """Test kayıtlarını mevcut silme uçlarının kurallarıyla siler (talepler, bağlar, Audit Log)."""
    from app.api.applications import delete_application
    from app.api.certificates import delete_certificate
    from app.api.domains import delete_domain
    from app.db.models import ScanTarget, TransferProposal
    from app.services.audit import log_action

    stop_sites(db)
    t = cleanup_targets(db)
    counts = {k: len(v) for k, v in t.items()}
    app_ids = [a.id for a in t["applications"]]
    dom_ids = [d.id for d in t["domains"]]
    # Önce kökü olmayanlardan (leaf) başla: üst sertifika silinirken çocuk yeniden bağlanmaya çalışmasın
    certs = sorted(t["certificates"], key=lambda c: {"leaf": 0, "intermediate": 1}.get(c.cert_type or "", 2))
    cert_ids = [c.id for c in certs]
    user_ids = [u.id for u in t["users"]]
    team_ids = [x.id for x in t["teams"]]
    for i in app_ids:
        delete_application(request, i, db=db, user=admin)
    for i in dom_ids:
        delete_domain(request, i, db=db, user=admin)
    from app.db.models import Certificate
    for i in cert_ids:
        if db.get(Certificate, i) is not None:
            delete_certificate(request, i, db=db, user=admin)
    if team_ids:
        db.query(TransferProposal).filter(TransferProposal.sy_team_id.in_(team_ids)).delete(
            synchronize_session=False)
        db.query(ScanTarget).filter(ScanTarget.sy_team_id.in_(team_ids)).update(
            {ScanTarget.sy_team_id: None}, synchronize_session=False)
    db.query(UserTeam).filter(UserTeam.user_id.in_(user_ids or [-1]) | UserTeam.team_id.in_(team_ids or [-1])).delete(
        synchronize_session=False)
    for u in db.query(User).filter(User.id.in_(user_ids or [-1])).all():
        db.delete(u)
    for tm in db.query(Team).filter(Team.id.in_(team_ids or [-1])).all():
        db.delete(tm)
    log_action(db, admin.username, "regression_cleanup", "regression", None, {"counts": counts}, request)
    db.commit()
    state = load_state(db)
    state.pop("created", None)
    state.pop("password", None)
    state.pop("data_at", None)
    save_state(db, state)
    return counts


# ---------------------------------------------------------------- ekran için özet
def status(db: Session) -> dict:
    state = load_state(db)
    certs = state.get("certs") or {}
    sites = state.get("sites") or {}
    files = []
    for n, b64 in (certs.get("files") or {}).items():
        what, sec = FILE_INFO.get(n, ("", ""))
        files.append({"name": n, "what": what, "section": sec, "size": len(base64.b64decode(b64))})
    running = sites_should_run(state)
    site_rows = []
    for port in [CRL_PORT, *SITES]:
        days = SITE_DAYS.get(port)
        if port == 9444 and sites.get("renewed"):
            days = 395
        site_rows.append({"port": port, "address": f"{HOST}:{port}", "what": SITE_INFO[port],
                          "days": days, "up": probe(port, 0.5) if running else False})
    return {
        "enabled": True,
        "host": HOST,
        "pfx_password": PFX_PAROLA,
        "certs": {"generated_at": certs.get("generated_at"), "by": certs.get("by"), "files": files},
        "sites": {"running": running, "until": sites.get("until") if running else None,
                  "renewed": bool(sites.get("renewed")), "rows": site_rows},
        "data": data_view(db, state),
    }
