"""Detay / Notlar alanlarındaki basit biçim etiketleri (v3.9.37).

Ekrandaki araç çubuğu metni düz yazı olarak, şu etiketlerle saklar:
  [b]kalın[/b]  [i]italik[/i]  [u]altı çizili[/u]  [renk=kirmizi]renkli[/renk]
Renkler sabit bir listeden seçilir (kirmizi, turuncu, yesil, mavi, mor). HTML saklanmaz;
e-postada etiketler burada güvenli HTML'e çevrilir, metin her zaman kaçışlanır.
Eşleşmeyen kapanış etiketi düz metin kalır, kapanmamış etiket metin sonunda kapanır.
"""
from __future__ import annotations

import html
import re

COLORS: dict[str, str] = {
    "kirmizi": "#c62828",
    "turuncu": "#e65100",
    "yesil": "#2e7d32",
    "mavi": "#1565c0",
    "mor": "#6a1b9a",
}

_TAG = re.compile(r"\[(/?)(b|i|u|renk)(?:=([a-z]+))?\]")
_HTML_OPEN = {"b": "<b>", "i": "<i>", "u": "<u>"}
_HTML_CLOSE = {"b": "</b>", "i": "</i>", "u": "</u>", "renk": "</span>"}


def _tokens(text: str):
    """(tür, değer) dizisi: ('text', s) | ('open', (ad, renk)) | ('close', ad)."""
    pos = 0
    stack: list[str] = []
    out: list[tuple] = []
    for m in _TAG.finditer(text):
        closing, name, arg = m.group(1) == "/", m.group(2), m.group(3)
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        pos = m.end()
        if not closing:
            if name == "renk" and arg not in COLORS:
                out.append(("text", m.group(0)))
                continue
            if name != "renk" and arg:
                out.append(("text", m.group(0)))
                continue
            stack.append(name)
            out.append(("open", (name, arg)))
        elif name in stack:
            # Araya giren açık etiketleri kapatıp yeniden açma yerine en yakın eşi kapatırız.
            while stack:
                top = stack.pop()
                out.append(("close", top))
                if top == name:
                    break
        else:
            out.append(("text", m.group(0)))
    if pos < len(text):
        out.append(("text", text[pos:]))
    while stack:
        out.append(("close", stack.pop()))
    return out


def to_plain(text: str | None) -> str | None:
    """Etiketleri atılmış düz metin (Excel, AI, arama için)."""
    if text is None:
        return None
    return "".join(v for k, v in _tokens(text) if k == "text")


def has_markup(text: str | None) -> bool:
    return bool(text) and any(k != "text" for k, _ in _tokens(text))


def to_html(text: str | None) -> str:
    """Kaçışlı HTML; satır sonları <br>, etiketler <b>/<i>/<u>/<span style=color>."""
    if not text:
        return ""
    parts: list[str] = []
    for kind, val in _tokens(text):
        if kind == "text":
            s = html.escape(val).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
            parts.append(s)
        elif kind == "open":
            name, arg = val
            parts.append(f'<span style="color:{COLORS[arg]};font-weight:600">' if name == "renk" else _HTML_OPEN[name])
        else:
            parts.append(_HTML_CLOSE[val])
    return "".join(parts)
