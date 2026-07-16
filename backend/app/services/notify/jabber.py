"""Jabber/XMPP kanalı — on-prem XMPP sunucusuna (ejabberd / Openfire / Cisco Jabber) mesaj yollar.

connect-send-close: her bildirimde kısa ömürlü bir oturum açılır, hedefe (tekil JID veya MUC oda JID'i)
mesaj gönderilir, kapatılır. slixmpp asyncio tabanlıdır → senkron dispatcher'dan geçici bir event loop
(asyncio.run) ile çalıştırılır. Genelde İÇ AĞ (egress'siz).

slixmpp YALNIZ _send_xmpp içinde (lazy) import edilir → paket kurulmamış ortamda (test/CI) modül yine
yüklenir; gerçek gönderim yalnız imaj rebuild'inden sonra çalışır. Testler _send_xmpp'i monkeypatch eder.
"""

from __future__ import annotations

import asyncio

from app.services.notify.base import NotificationChannel, NotifyEvent


def _send_xmpp(cfg: dict, body: str) -> None:
    """Tek seferlik XMPP gönderimi. Başarısızsa istisna FIRLATIR (dispatcher/test yakalar)."""
    import slixmpp  # lazy: bağımlılık yalnız çalışma anında gerekir

    jid = cfg["jid"]
    password = cfg.get("password") or ""
    target = cfg["target"]
    is_muc = bool(cfg.get("is_muc"))
    host = cfg.get("host") or None
    port = int(cfg.get("port") or 5222)
    timeout = float(cfg.get("timeout_seconds") or 10)

    class _OneShot(slixmpp.ClientXMPP):
        def __init__(self) -> None:
            super().__init__(jid, password)
            self.register_plugin("xep_0045")   # Çok Kullanıcılı Sohbet (MUC)
            self.add_event_handler("session_start", self._on_start)

        async def _on_start(self, _event) -> None:
            self.send_presence()
            await self.get_roster()
            if is_muc:
                # MUC'a mesaj atmadan önce odaya katıl (nick = JID kullanıcı adı)
                self.plugin["xep_0045"].join_muc(target, self.boundjid.user)
                self.send_message(mto=target, mbody=body, mtype="groupchat")
            else:
                self.send_message(mto=target, mbody=body, mtype="chat")
            self.disconnect()

    async def _run() -> None:
        xmpp = _OneShot()
        if cfg.get("skip_cert_verify"):
            import ssl
            xmpp.ssl_context.check_hostname = False
            xmpp.ssl_context.verify_mode = ssl.CERT_NONE
        # host verilirse ona bağlan; yoksa JID alanından DNS SRV ile çözülür.
        xmpp.connect((host, port) if host else ())
        await asyncio.wait_for(xmpp.disconnected, timeout=timeout)

    asyncio.run(_run())


class JabberChannel(NotificationChannel):
    name = "jabber"

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        if not (cfg.get("jid") and cfg.get("target")):
            return False
        _send_xmpp(cfg, f"{event.title}\n{event.text}")
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        if not (cfg.get("jid") and cfg.get("target")):
            return False, "Jabber JID / hedef tanımlı değil"
        try:
            _send_xmpp(cfg, "✅ JUMBO test bildirimi (Jabber/XMPP)")
            return True, "Jabber hedefine test mesajı gönderildi"
        except Exception as exc:
            return False, f"Gönderilemedi: {str(exc)[:200]}"
