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
