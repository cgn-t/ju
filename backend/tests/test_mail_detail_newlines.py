"""Detay (domain.info) e-postada satır sonlarını korur; HTML kaçışı bozulmaz (v3.9.31)."""
from types import SimpleNamespace

from app.services import notifier


def _dom(info):
    return SimpleNamespace(domain="a.jumbo.local", external_address=None, ug_team=None, ug_team_name=None,
                           sy_team=None, cert_owner=None, lb_update=None, env_update=None, waf_update=None,
                           external_company=None, expire_date=None, info=info, action_required=None,
                           ssl_pinning=None, keystore=None)


def test_detay_satir_sonlari_br_olur():
    html = notifier._domain_table_html(_dom("1. satır\r\n2. satır\n<b>3</b>"))
    assert "1. satır<br>2. satır<br>&lt;b&gt;3&lt;/b&gt;" in html


def test_tek_satir_ve_bos_degisinmez():
    assert notifier._cell("tek") == "tek"
    assert notifier._cell(None) == "-"


def test_detay_bicim_etiketleri_mailde_guvenli_html():
    html = notifier._domain_table_html(_dom("[b]Önemli[/b] [renk=kirmizi]F5[/renk]\n<script>x</script>"))
    assert "<b>Önemli</b>" in html
    assert 'color:#c62828' in html and ">F5</span>" in html
    assert "&lt;script&gt;" in html and "<script>" not in html


def test_richtext_bozuk_etiketler():
    from app.core import richtext
    assert richtext.to_html("[renk=zehir]a[/renk]") == "[renk=zehir]a[/renk]"
    assert richtext.to_html("[b]açık") == "<b>açık</b>"
    assert richtext.to_html('[b onclick="x"]a[/b]') == '[b onclick=&quot;x&quot;]a[/b]'
    assert richtext.to_plain("[i]a[/i] [u]b[/u]") == "a b"
