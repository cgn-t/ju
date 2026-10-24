"""Canlı doğrulamanın ek kontrolleri: DNS kaydı, Çoklu IP, CAA ve OCSP Stapling.

Hepsi yalnız OKUR: DNS'e sorulur, sunucuya bağlanılır; envanterde hiçbir şey değişmez. Sonuçlar
domain'in mevcut canlı doğrulama detayına (live_check_detail JSON) eklenir — yeni kolon/tablo yok.

- dns:        ad DNS'te tanımlı mı, hangi IP'leri gösteriyor (CNAME varsa hedefi)
- multi_ip:   adın arkasındaki HER IP aynı sertifikayı mı sunuyor (yük dengeleyici arkasında bir
              sunucuya yenileme kurulmamışsa yakalanır)
- caa:        DNS'teki CAA kaydı sertifikayı veren CA'ya izin veriyor mu (izin vermiyorsa yenilemede
              sertifika alınamayabilir)
- ocsp_stapling: sunucu iptal durumunu (OCSP yanıtı) el sıkışmada kendisi gönderiyor mu
"""

import ipaddress
import logging
import select
import socket
import time
from datetime import timezone

from cryptography import x509
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from app.core.timeutil import utcnow

logger = logging.getLogger(__name__)

# Testler gerçek DNS/ağ sorgusu yapmasın diye kapatılabilir (bkz. tests/conftest.py)
ENABLED = True
DNS_TIMEOUT = 2.5
CONNECT_TIMEOUT = 4
MAX_IPS = 8

# CAA değerindeki CA alan adı → issuer adında aranacak parçalar (marka değişiklikleri dahil)
_CA_ALIASES: dict[str, tuple[str, ...]] = {
    "letsencrypt.org": ("let's encrypt",),
    "pki.goog": ("google trust services", "gts "),
    "amazon.com": ("amazon",), "amazontrust.com": ("amazon",), "awstrust.com": ("amazon",),
    "amazonaws.com": ("amazon",),
    "sectigo.com": ("sectigo", "comodo", "usertrust"), "comodoca.com": ("sectigo", "comodo", "usertrust"),
    "comodo.com": ("sectigo", "comodo", "usertrust"), "usertrust.com": ("usertrust", "sectigo"),
    "digicert.com": ("digicert", "geotrust", "rapidssl", "thawte", "symantec"),
    "symantec.com": ("digicert", "symantec"), "geotrust.com": ("geotrust", "digicert"),
    "thawte.com": ("thawte", "digicert"), "rapidssl.com": ("rapidssl", "digicert"),
    "globalsign.com": ("globalsign",),
    "godaddy.com": ("go daddy", "godaddy", "starfield"), "starfieldtech.com": ("starfield",),
    "entrust.net": ("entrust",), "entrust.com": ("entrust",),
    "ssl.com": ("ssl.com", "ssl corporation"),
    "buypass.com": ("buypass",), "buypass.no": ("buypass",),
    "zerossl.com": ("zerossl",), "microsoft.com": ("microsoft",),
    "turktrust.com.tr": ("turktrust",), "e-tugra.com.tr": ("e-tugra", "e-tuğra"),
    "e-tugra.com": ("e-tugra", "e-tuğra"), "kamusm.gov.tr": ("kamu sm", "tubitak", "tübitak"),
}


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _checkable_name(host: str) -> bool:
    """Gerçek DNS adı mı? IP, tek etiketli ad (localhost) için DNS kontrolleri yapılmaz."""
    return not _is_ip(host) and "." in host.strip(".")


def _resolver():
    import dns.resolver
    r = dns.resolver.Resolver()
    r.timeout = DNS_TIMEOUT
    r.lifetime = DNS_TIMEOUT
    return r


def check_dns(host: str) -> dict:
    """Adın A/AAAA kayıtları (işletim sistemi çözücüsüyle — uygulamanın kendisi de bunu kullanır)
    ve varsa CNAME hedefi."""
    out: dict = {"ips": []}
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if ip not in out["ips"]:
                out["ips"].append(ip)
    except socket.gaierror:
        pass
    try:
        import dns.exception
        import dns.name
        import dns.resolver
        answer = _resolver().resolve(dns.name.from_text(host), "CNAME", raise_on_no_answer=False)
        if answer.rrset:
            out["cname"] = str(answer.rrset[0].target).rstrip(".")
    except Exception:  # CNAME yalnız bilgi; DNS sunucusu yanıt vermezse atlanır
        pass
    if out["ips"]:
        out["status"] = "ok"
        out["note"] = f"DNS kaydı var: {', '.join(out['ips'])}" + (
            f" (CNAME → {out['cname']})" if out.get("cname") else "")
    else:
        out["status"] = "missing"
        out["note"] = (f"'{host}' DNS'te bulunamadı (A/AAAA kaydı yok). Adres yanlış yazılmış, kayıt "
                       "silinmiş ya da yalnız başka bir ağın DNS'inde tanımlı olabilir.")
    return out


def _fingerprint(cert: x509.Certificate) -> str:
    from app.services.cert_parser import parse_x509
    return parse_x509(cert).fingerprint_sha256


def check_multi_ip(host: str, port: int, ips: list[str], served_fp: str,
                   bound_fps: set[str]) -> dict | None:
    """Adın arkasında birden çok IP varsa her birine bağlanıp sunulan sertifikayı karşılaştırır.
    Tek IP'de karşılaştırılacak bir şey yoktur (None)."""
    if len(ips) < 2:
        return None
    from app.services.cert_parser import parse_x509
    from app.services.live_check import describe_connection_error, fetch_leaf_via

    rows: list[dict] = []
    for ip in ips[:MAX_IPS]:
        row: dict = {"ip": ip}
        try:
            parsed = parse_x509(fetch_leaf_via(ip, host, port, timeout=CONNECT_TIMEOUT))
            row["cert"] = parsed.name
            row["valid_to"] = parsed.valid_to.isoformat()
            if parsed.fingerprint_sha256 == served_fp:
                row["result"] = "same"
            elif parsed.fingerprint_sha256 in bound_fps:
                row["result"] = "other_bound"
            else:
                row["result"] = "different"
        except Exception as exc:
            row["result"] = "unreachable"
            row["error"] = describe_connection_error(exc, ip, port)
        rows.append(row)

    different = [r for r in rows if r["result"] == "different"]
    unreachable = [r for r in rows if r["result"] == "unreachable"]
    if different:
        note = ("Her IP aynı sertifikayı sunmuyor: " + "; ".join(
            f"{r['ip']} → {r['cert']} (bitiş {r['valid_to'][:10]})" for r in different)
            + ". Bu sunucuya güncel sertifika kurulmamış olabilir.")
        status = "different"
    elif unreachable and len(unreachable) == len(rows):
        note, status = "IP'lerin hiçbirine ayrı ayrı bağlanılamadı.", "unknown"
    else:
        reached = len(rows) - len(unreachable)
        note = f"{reached} IP aynı sertifikayı sunuyor" + (
            f"; {len(unreachable)} IP'ye bağlanılamadı" if unreachable else "") + "."
        status = "same"
    if len(ips) > MAX_IPS:
        note += f" (İlk {MAX_IPS} IP kontrol edildi, toplam {len(ips)}.)"
    return {"status": status, "ips": rows, "note": note}


def _caa_lookup(host: str) -> tuple[str | None, list[tuple[int, str, str]], bool]:
    """RFC 8659 ağaç tırmanışı: addan başlayıp üst alanlara doğru ilk CAA kümesini bulur.
    (bulunan_ad, [(flags, tag, value)], dns_ulaşılabildi_mi)"""
    import dns.exception
    import dns.name
    import dns.resolver

    resolver = _resolver()
    labels = host.strip(".").lower().split(".")
    for i in range(len(labels) - 1):  # tek etiketli TLD'ye sorulmaz
        name = ".".join(labels[i:])
        try:
            answer = resolver.resolve(dns.name.from_text(name), "CAA", raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            return None, [], False
        if answer.rrset:
            recs = [(int(r.flags), r.tag.decode().lower(), r.value.decode()) for r in answer.rrset]
            return name, recs, True
    return None, [], True


def _issuer_text(cert: x509.Certificate) -> str:
    parts = [str(a.value) for oid in (NameOID.ORGANIZATION_NAME, NameOID.COMMON_NAME)
             for a in cert.issuer.get_attributes_for_oid(oid)]
    return " / ".join(parts) or cert.issuer.rfc4514_string()


def _ca_matches(ca_domain: str, issuer: str) -> bool:
    issuer = issuer.lower()
    aliases = _CA_ALIASES.get(ca_domain) or (ca_domain.split(".")[0],)
    return any(a in issuer for a in aliases)


def check_caa(host: str, leaf: x509.Certificate) -> dict:
    found_at, records, reachable = _caa_lookup(host)
    issuer = _issuer_text(leaf)
    out: dict = {"issuer": issuer}
    if not reachable:
        out.update(status="unknown", note="CAA kaydı sorgulanamadı: DNS sunucusu yanıt vermedi.")
        return out
    if not records:
        out.update(status="none", note="CAA kaydı yok: her CA bu ad için sertifika verebilir.")
        return out
    out["domain"] = found_at
    out["records"] = [f'{f} {t} "{v}"' for f, t, v in records]
    from app.services.live_check import _cert_names, _dns_match
    dns_names, _ = _cert_names(leaf)
    via_wildcard = not any(n == host.lower() for n in dns_names) and any(
        n.startswith("*.") and _dns_match(n, host.lower()) for n in dns_names)
    issue = [v for _, t, v in records if t == "issue"]
    wild = [v for _, t, v in records if t == "issuewild"]
    allowed_values = wild if (via_wildcard and wild) else issue
    if not allowed_values:
        out.update(status="none", note="CAA kaydında sertifika verme (issue) kuralı yok; CA kısıtı uygulanmıyor.")
        return out
    allowed = [v.split(";")[0].strip().lower() for v in allowed_values]
    allowed = [a for a in allowed if a]
    out["allowed"] = allowed
    if not allowed:
        out.update(status="not_allowed",
                   note=f"CAA kaydı ({found_at}) hiçbir CA'ya izin vermiyor; yenilemede sertifika alınamaz.")
    elif any(_ca_matches(a, issuer) for a in allowed):
        out.update(status="allowed", note=f"Sertifikayı veren CA, CAA kaydında izinli ({', '.join(allowed)}).")
    else:
        out.update(status="not_allowed",
                   note=(f"Sertifikayı veren CA ({issuer}) CAA kaydında yok; izinli: {', '.join(allowed)}. "
                         "Bu CA'dan yenileme alınamayabilir; CAA kaydı ya da CA tercihi gözden geçirilmeli."))
    return out


def _ocsp_url(cert: x509.Certificate) -> str | None:
    try:
        aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
    except x509.ExtensionNotFound:
        return None
    for d in aia:
        if d.access_method == AuthorityInformationAccessOID.OCSP:
            return d.access_location.value
    return None


def _fetch_stapled(host: str, port: int, address: str | None = None) -> bytes:
    """Sunucudan el sıkışmada OCSP yanıtı ister (status_request); gelen ham yanıtı döner (yoksa b'')."""
    from OpenSSL import SSL

    got: list[bytes] = []

    def _cb(conn, data, _ud):
        got.append(bytes(data or b""))
        return True

    ctx = SSL.Context(SSL.TLS_METHOD)
    ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)
    ctx.set_ocsp_client_callback(_cb)
    sock = socket.create_connection((address or host, port), timeout=CONNECT_TIMEOUT)
    try:
        conn = SSL.Connection(ctx, sock)
        if not _is_ip(host):
            conn.set_tlsext_host_name(host.encode("idna"))
        conn.request_ocsp()
        conn.set_connect_state()
        # Zaman aşımlı soket pyOpenSSL'de bloklamayan çalışır: el sıkışma WantRead/WantWrite ile
        # bölünür, süre dolana kadar soket hazır olunca devam edilir.
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while True:
            try:
                conn.do_handshake()
                break
            except (SSL.WantReadError, SSL.WantWriteError) as want:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("OCSP Stapling el sıkışması zaman aşımına uğradı")
                rd, wr = ([sock], []) if isinstance(want, SSL.WantReadError) else ([], [sock])
                select.select(rd, wr, [], left)
        try:
            conn.shutdown()
        except SSL.Error:
            pass
    finally:
        sock.close()
    return got[0] if got else b""


def check_ocsp_stapling(host: str, port: int, leaf: x509.Certificate) -> dict:
    if not _ocsp_url(leaf):
        return {"status": "not_applicable",
                "note": "Sertifikada OCSP adresi yok (çoğu iç CA'da olduğu gibi); OCSP Stapling uygulanamaz."}
    try:
        raw = _fetch_stapled(host, port)
    except Exception as exc:
        return {"status": "unknown", "note": f"OCSP Stapling kontrol edilemedi ({str(exc)[:120] or type(exc).__name__})."}
    if not raw:
        return {"status": "not_stapled",
                "note": ("Sunucu OCSP yanıtını el sıkışmada göndermiyor (OCSP Stapling kapalı). Zorunlu değil; "
                         "açılırsa istemciler iptal kontrolünü CA'ya gitmeden, daha hızlı yapar.")}
    try:
        resp = ocsp.load_der_ocsp_response(raw)
        if resp.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            return {"status": "invalid", "note": f"Sunucunun gönderdiği OCSP yanıtı geçersiz ({resp.response_status.name})."}
        cert_status = resp.certificate_status.name.lower()  # good / revoked / unknown
        nxt = getattr(resp, "next_update_utc", None) or resp.next_update
        out = {"status": "stapled", "cert_status": cert_status}
        if nxt is not None:
            nxt_naive = nxt.astimezone(timezone.utc).replace(tzinfo=None) if nxt.tzinfo else nxt
            out["next_update"] = nxt_naive.isoformat()
            if nxt_naive < utcnow():
                out.update(status="stale", note=("Sunucu OCSP yanıtı gönderiyor ama yanıtın süresi geçmiş "
                                                  f"({nxt_naive:%d.%m.%Y %H:%M}). Sunucu yanıtı yenilemiyor olabilir."))
                return out
        label = {"good": "geçerli (GOOD)", "revoked": "İPTAL EDİLMİŞ (REVOKED)", "unknown": "bilinmiyor (UNKNOWN)"}
        out["note"] = f"Sunucu OCSP yanıtını el sıkışmada gönderiyor: sertifika {label.get(cert_status, cert_status)}."
        return out
    except Exception as exc:
        return {"status": "invalid", "note": f"Sunucunun gönderdiği OCSP yanıtı okunamadı ({str(exc)[:120]})."}


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        logger.exception("Ek canlı kontrol hatası: %s", getattr(fn, "__name__", fn))
        return None


def dns_only(host: str) -> dict | None:
    """Bağlantı kurulamadığında yalnız DNS durumu (adres DNS'te var mı)."""
    if not ENABLED or not _checkable_name(host):
        return None
    return _safe(check_dns, host)


def run_all(host: str, port: int, served_raw: list[x509.Certificate], leaf_served,
            bound_fps: set[str]) -> dict:
    """Dört ek kontrolü çalıştırır; her biri kendi hatasını yutar (ana sonucu bozmaz)."""
    if not ENABLED:
        return {}
    leaf = served_raw[0]
    out: dict = {}
    if _checkable_name(host):
        dns_res = _safe(check_dns, host)
        if dns_res:
            out["dns"] = dns_res
            multi = _safe(check_multi_ip, host, port, dns_res.get("ips") or [],
                          leaf_served.fingerprint_sha256, bound_fps)
            if multi:
                out["multi_ip"] = multi
        caa = _safe(check_caa, host, leaf)
        if caa:
            out["caa"] = caa
    stapling = _safe(check_ocsp_stapling, host, port, leaf)
    if stapling:
        out["ocsp_stapling"] = stapling
    out["extra_checked_at"] = utcnow().replace(tzinfo=timezone.utc).isoformat()
    return out
