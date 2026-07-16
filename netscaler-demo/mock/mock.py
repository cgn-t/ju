#!/usr/bin/env python3
"""NITRO-uyumlu MOCK ADC (gerçek NetScaler DEĞİL — Apple Silicon'da CPX emüle edilemediği için).

İki sunucu:
  * :9080  NITRO REST — systemfile / sslcertkey (add+update) / bindings / save (kabul eder)
  * :443   TLS — o an 'yüklü' leaf cert ile handshake; sslcertkey update olunca SICAK değişir.

Amaç: Vault→(swap script)→NITRO→TLS-uç zincirinin uçtan uca çalıştığını ve cert-swap'ın gözle
görülür olduğunu (fingerprint A→B) yerelde kanıtlamak. Gerçek amd64 CPX'te aynı scriptler çalışır.
"""
import base64, hashlib, json, os, ssl, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"files": {}, "certkeys": {}, "bindings": {}, "ctx": None, "served_fp": None}
LOCK = threading.Lock()
CERT_DIR = tempfile.mkdtemp(prefix="mock-adc-ssl-")


def _fp(pem_bytes):
    try:
        der = ssl.PEM_cert_to_DER_cert(pem_bytes.decode())
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cert_info(pem_bytes):
    """(subject, notAfter) — stdlib ile parse; edilemezse ('', '')."""
    if not pem_bytes:
        return ("", "")
    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
            f.write(pem_bytes)
            path = f.name
        d = ssl._ssl._test_decode_cert(path)  # stdlib: PEM dosyasını çözer
        os.unlink(path)
        subj = ", ".join(f"{k}={v}" for rdn in d.get("subject", ()) for (k, v) in rdn)
        return (subj, d.get("notAfter", ""))
    except Exception:
        return ("", "")


def _dashboard_html():
    """Canlı ADC durum sayfası — certkey'ler, vserver binding, o an sunulan cert. 3 sn'de yenilenir."""
    served_fp = STATE.get("served_fp") or ""
    served_line = "<span class=muted>henüz cert yüklenmedi</span>"
    ck_rows = []
    for name, ck in STATE["certkeys"].items():
        cert_bytes = STATE["files"].get(ck.get("cert"), b"")
        fp = _fp(cert_bytes) or ""
        subj, notafter = _cert_info(cert_bytes)
        served = bool(served_fp and fp == served_fp)
        if served:
            served_line = f"<b>{_esc(subj) or _esc(name)}</b> &nbsp;<span class=mono>sha256:{fp[:32]}…</span>"
        badge = "<span class=served>● SUNULAN</span>" if served else ""
        ck_rows.append(
            f"<tr class='{'srv' if served else ''}'><td class=b>{_esc(name)} {badge}</td>"
            f"<td class=mono>{_esc(ck.get('cert', '-'))}</td><td>{_esc(subj) or '-'}</td>"
            f"<td class=mono>{(fp[:24] + '…') if fp else '-'}</td><td>{_esc(notafter) or '-'}</td></tr>"
        )
    b_rows = [f"<tr><td class=b>{_esc(vs)}</td><td>{_esc(ck)}</td></tr>"
              for vs, ck in STATE["bindings"].items()]
    ck_html = "".join(ck_rows) or "<tr><td colspan=5 class=muted>—</td></tr>"
    b_html = "".join(b_rows) or "<tr><td colspan=2 class=muted>—</td></tr>"
    return f"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta http-equiv=refresh content=3><title>MOCK ADC — NITRO</title><style>
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:#0e1117;color:#e6edf3}}
header{{background:#11557c;color:#fff;padding:14px 24px;display:flex;align-items:center;gap:12px}}
header .dot{{width:10px;height:10px;border-radius:50%;background:#3fb950;box-shadow:0 0 8px #3fb950}}
header h1{{font-size:16px;margin:0;font-weight:700}}header .sub{{opacity:.8;font-size:12px}}
main{{padding:24px;max-width:1000px;margin:0 auto}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 18px;margin-bottom:18px}}
.card h2{{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#8b949e;margin:0 0 12px}}
.served-box{{font-size:15px}}table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #21262d;vertical-align:top}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#8b949e}}
tr.srv{{background:rgba(63,185,80,.08)}}.b{{font-weight:600}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}}
.muted{{color:#8b949e}}.served{{color:#3fb950;font-size:11px;margin-left:6px;font-weight:600}}
footer{{text-align:center;color:#8b949e;font-size:11px;padding:8px}}</style></head><body>
<header><span class=dot></span><div><h1>MOCK ADC — Citrix ADC / NetScaler (NITRO uyumlu)</h1>
<div class=sub>demo — gerçek NetScaler değil · her 3 sn'de yenilenir</div></div></header><main>
<div class="card served-box"><h2>Şu an sunulan sertifika (TLS :443 → host :8443)</h2>{served_line}</div>
<div class=card><h2>SSL Cert-Key Çiftleri</h2><table><thead><tr><th>Cert-Key</th><th>Cert dosyası</th>
<th>Subject</th><th>SHA-256</th><th>Geçerlilik sonu</th></tr></thead><tbody>{ck_html}</tbody></table></div>
<div class=card><h2>SSL vServer Binding</h2><table><thead><tr><th>Virtual Server</th><th>Cert-Key</th></tr>
</thead><tbody>{b_html}</tbody></table></div></main>
<footer>NITRO API: http://localhost:19080/nitro/v1/config · TLS: https://localhost:8443</footer>
</body></html>"""


def rebuild_ctx(name):
    """certkey add/update sonrası 443'te sunulan cert'i (yeniden) yükle."""
    ck = STATE["certkeys"].get(name) or {}
    cert = STATE["files"].get(ck.get("cert"))
    key = STATE["files"].get(ck.get("key"))
    if not cert or not key:
        return
    cp, kp = os.path.join(CERT_DIR, name + ".cer"), os.path.join(CERT_DIR, name + ".key")
    with open(cp, "wb") as f:
        f.write(cert)
    with open(kp, "wb") as f:
        f.write(key)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cp, kp)
    STATE["ctx"] = ctx
    STATE["served_fp"] = _fp(cert)
    print(f"[TLS] '{name}' yüklendi → sunulan fingerprint sha256:{STATE['served_fp'][:16]}…", flush=True)


class Nitro(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code=200, body=None):
        b = json.dumps(body or {"errorcode": 0, "message": "Done", "severity": "NONE"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _send_html(self, html: str):
        b = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/ui", "/status", "/index.html"):
            return self._send_html(_dashboard_html())
        if p.endswith("/nsversion"):
            return self._send(200, {"errorcode": 0, "nsversion": {"version": "MOCK-ADC 1.0 (NITRO-uyumlu)"}})
        if "/sslcertkey/" in p:
            name = p.rsplit("/", 1)[-1]
            ck = STATE["certkeys"].get(name)
            if not ck:
                return self._send(404, {"errorcode": 258, "message": "certkey yok"})
            fp = _fp(STATE["files"].get(ck.get("cert"), b""))
            return self._send(200, {"errorcode": 0, "sslcertkey": [
                {"certkey": name, "cert": ck.get("cert"), "key": ck.get("key"), "fingerprint_sha256": fp}]})
        return self._send(200)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        base = self.path.split("?")[0].rsplit("/", 1)[-1]
        with LOCK:
            if base == "systemfile":
                sf = data.get("systemfile", {})
                fn = sf.get("filename")
                try:
                    STATE["files"][fn] = base64.b64decode(sf.get("filecontent", ""))
                except Exception:
                    return self._send(400, {"errorcode": 1, "message": "bad base64"})
                print(f"[NITRO] systemfile <- {fn} ({len(STATE['files'][fn])} bayt)", flush=True)
                return self._send(201)
            if base == "sslcertkey":
                ck = data.get("sslcertkey", {})
                name = ck.get("certkey")
                STATE["certkeys"].setdefault(name, {})
                if ck.get("cert"):
                    STATE["certkeys"][name]["cert"] = ck["cert"]
                if ck.get("key"):
                    STATE["certkeys"][name]["key"] = ck["key"]
                print(f"[NITRO] sslcertkey add/update {name} (cert={ck.get('cert')})", flush=True)
                rebuild_ctx(name)
                return self._send(200)
            if base == "sslvserver_sslcertkey_binding":
                b = data.get("sslvserver_sslcertkey_binding", {})
                STATE["bindings"][b.get("vservername")] = b.get("certkeyname")
                print(f"[NITRO] bind {b.get('vservername')} <- {b.get('certkeyname')}", flush=True)
                return self._send(201)
            # lbvserver / service / lbvserver_service_binding / nsconfig / nsfeature → kabul
            return self._send(200)


class HotTLS(ThreadingHTTPServer):
    """Her yeni bağlantıyı O ANKİ context ile sarar → cert sıcak değişir."""
    daemon_threads = True

    def get_request(self):
        sock, addr = self.socket.accept()
        ctx = STATE["ctx"]
        if ctx is None:
            sock.close()
            raise OSError("henüz cert yüklenmedi")
        return ctx.wrap_socket(sock, server_side=True), addr


class Hello(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"mock-adc backend\n")


def main():
    threading.Thread(
        target=lambda: ThreadingHTTPServer(("0.0.0.0", 9080), Nitro).serve_forever(),
        daemon=True,
    ).start()
    print("MOCK-ADC hazır: NITRO http://0.0.0.0:9080  ·  TLS https://0.0.0.0:443", flush=True)
    HotTLS(("0.0.0.0", 443), Hello).serve_forever()


if __name__ == "__main__":
    main()
