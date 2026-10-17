"""E-posta adres listesi yardımcıları — TEK KAYNAK.

Ekip e-postası, yedek adres ve kuyruk alıcıları serbest metin olarak tutulur; kullanıcılar
adresleri hem virgülle hem noktalı virgülle ayırır (Outlook alışkanlığı). Ekipler ekranı ikisini
de ayrı adres gösterdiğinden gönderim tarafı da İKİSİNİ de ayırıcı saymalıdır — aksi halde
"a@x; b@y" SMTP'ye tek (geçersiz) adres olarak gider ve mail hiç ulaşmaz.
"""

import re

_ADDR = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+$")


def split_emails(raw: str | None) -> list[str]:
    """'a@x, b@y; c@z' → ['a@x', 'b@y', 'c@z'] (boşlar atılır, sıra korunur, tekrarlar elenir)."""
    out: list[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        addr = part.strip()
        if addr and addr.lower() not in {a.lower() for a in out}:
            out.append(addr)
    return out


def normalize_email_list(raw: str | None) -> str | None:
    """Kaydetmeden önce doğrular ve standart biçime ('a@x, b@y') getirir. Geçersiz bir adres
    varsa ValueError (hangi adres olduğu mesajda). Boş → None."""
    addrs = split_emails(raw)
    bad = [a for a in addrs if not _ADDR.match(a)]
    if bad:
        raise ValueError(f"Geçersiz e-posta adresi: {', '.join(bad)} "
                         "(birden çok adresi virgül ya da noktalı virgülle ayırın)")
    return ", ".join(addrs) or None
