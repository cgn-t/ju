"""JUMBO — Prod şema TUTARLILIK doğrulaması (READ-ONLY preflight diff).

Bu araç HİÇBİR ŞEY YAZMAZ. Yalnız hedef veritabanının şemasını (INFORMATION_SCHEMA/sys
katalogları üzerinden) okur ve uygulamanın ORM beklentisi (`Base.metadata`) ile kıyaslar.
Amaç: yeni app'i canlıya (prod) bağlamadan ÖNCE, yapıların ne kadar uyuştuğunu tek komutla görmek.

Rapor bölümleri (tablo tablo):
  ✅ Uyanlar        — kolon prod'da app'in beklediği ad/tip/null ile var
  ➕ Additive       — app-yeni kolon; prod'da yok, uygulama açılışta ALTER ADD edecek (NORMAL)
  ⚠️ Uyuşmazlık     — tip (varchar↔nvarchar), nullability, UNIQUE farkı YA DA beklenen prod
                      kolonunun EKSİK olması (ad uyuşmazlığı! — ör. …CertificateCreator yanlış ad)
  ℹ️ Prod-only      — prod'da olup app'in bilmediği kolon/tablo (app yok sayar, prod'da kalır)
  🔎 Özel bulgular  — …CertificateCreator gerçek adı, SerialNumber UNIQUE/NOT NULL, email NOT NULL

Kullanım:
    # Container içinde (pymssql var), MSSQL_* env ile canlıya karşı:
    MSSQL_HOST=<prod-host> MSSQL_DB=TMTKS00 MSSQL_USER=<u> MSSQL_PASSWORD=<p> \
        python -m scripts.check_prod_schema

    # Ya da açık URL ile (sürücü fark etmez; introspection her sürücüde çalışır):
    python scripts/check_prod_schema.py \
        --url "mssql+pyodbc://user:pass@host:1433/TMTKS00?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"

Çıkış kodu: ⚠️ uyuşmazlık varsa 1, temizse 0 (CI-dostu).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

# models import → Base.metadata tüm tablolarla dolar (ayrıca app.db.session'ı da yükler)
import app.db.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.db.session import Base  # noqa: E402

# --- Sınıflandırma: hangi tablo prod'da MEVCUT beklenir, hangisi app-YENİ (create_all kurar) ---
EXPECTED_PROD_TABLES = {
    "SSLCertificates", "domain_certificates", "SSLCertificateDomainMapping",
    "applications", "users", "AuditLog",
}
NEW_APP_TABLES = {
    "teams", "user_teams", "transfer_proposals", "app_dependencies",
    "notifications", "app_settings",
}

# App-YENİ kolonlar (DB adıyla) — prod'da YOK olmaları NORMAL (additive). Bir ORM kolonu prod'da
# eksikse ve bu kümede DEĞİLSE → beklenen prod kolonu eksik = ad uyuşmazlığı şüphesi (⚠️).
APP_NEW_COLUMNS = {
    "SSLCertificates": {"san", "fingerprint_sha256", "parent_id", "superseded_by_id",
                        "is_internal", "source", "vault_path", "auto_renew"},
    "domain_certificates": {"ug_team_id", "sy_team_id", "servers_to_update",
                            "live_check_status", "live_check_detail", "live_check_at",
                            "created_at", "updated_at"},
    "applications": {"domain_id", "sy_team_id", "ug_team_id"},
    "users": {"full_name", "role", "auth_source", "is_active", "last_login"},
    "AuditLog": {"ip_address"},
}


def _family(sa_type) -> str:
    """SQLAlchemy tipini kaba aileye indir: str/int/bool/datetime/other (tip ailesi kıyası için).
    TypeDecorator (ör. LowerStr) → impl'e (String) inilir."""
    seen = 0
    while hasattr(sa_type, "impl") and not isinstance(getattr(sa_type, "impl"), type) and seen < 5:
        sa_type = sa_type.impl
        seen += 1
    try:
        py = sa_type.python_type
    except (NotImplementedError, AttributeError):
        return "other"
    import datetime as _dt
    if py is bool:
        return "bool"
    if py is int:
        return "int"
    if py is str:
        return "str"
    if py in (_dt.datetime, _dt.date):
        return "datetime"
    return py.__name__


def _is_unicode(type_str: str) -> bool:
    """MSSQL nvarchar/nchar/ntext (Unicode) mı? (VARCHAR↔NVARCHAR farkını yakalamak için)."""
    s = type_str.upper()
    return "NVARCHAR" in s or "NCHAR" in s or "NTEXT" in s


def _orm_type_str(col, dialect) -> str:
    """ORM kolonunun hedef dialektte üreteceği DDL tipi (create_all ne yazardı)."""
    try:
        return col.type.compile(dialect=dialect)
    except Exception:
        return str(col.type)


def _length(sa_type):
    return getattr(sa_type, "length", None)


def _clean(type_str: str) -> str:
    """Görüntü için gürültüyü at (COLLATE ...)."""
    return type_str.split(" COLLATE")[0].strip()


def check(url: str) -> tuple[list[str], int]:
    """Şemayı introspect edip rapor satırları + uyuşmazlık sayısını döndürür. WRITE YOK."""
    engine = create_engine(url, pool_pre_ping=True)
    dialect = engine.dialect
    insp = inspect(engine)
    actual_tables = {t.lower(): t for t in insp.get_table_names()}  # ci lookup → gerçek ad

    lines: list[str] = []
    cats = {"kritik": 0, "davranissal": 0, "sadakat": 0}
    additive_cols = 0
    safe_url = make_url(url).render_as_string(hide_password=True)

    def L(s=""):
        lines.append(s)

    L("# JUMBO — Prod Şema Tutarlılık Raporu (READ-ONLY)")
    L()
    L(f"- Hedef : `{safe_url}`")
    L(f"- Dialect: `{dialect.name}`")
    L("- ⚠️ Bu araç HİÇBİR ŞEY YAZMAZ; yalnız şema kataloğunu okur.")
    L("- ℹ️ Bu rapor YALNIZ yukarıdaki hedef içindir. Otorite = canlıya karşı koşmak "
      "(`MSSQL_DB=TMTKS00 …`).")
    L()

    summary_slot = len(lines)  # özet sonradan buraya eklenecek
    L()

    def resolve_actual(tname: str):
        real = actual_tables.get(tname.lower())
        if real is None:
            return None, {}, []
        cols = {c["name"].lower(): c for c in insp.get_columns(real)}
        # NOT: MSSQL dialekti get_unique_constraints'i implement etmez (UNIQUE'ler unique-index
        # olarak yansır) → NotImplementedError'ı yut, index'lerden topla.
        try:
            uniques = insp.get_unique_constraints(real)
        except NotImplementedError:
            uniques = []
        try:
            idx = insp.get_indexes(real)
        except Exception:
            idx = []
        # unique index'leri de unique kaynağı say
        for i in idx:
            if i.get("unique"):
                uniques = uniques + [{"name": i.get("name"), "column_names": i.get("column_names", [])}]
        return real, cols, uniques

    prod_present = 0
    newtab_present = 0

    # ORM metadata tablolarını gez (deterministik sıra)
    for table in Base.metadata.sorted_tables:
        tname = table.name
        is_prod = tname in EXPECTED_PROD_TABLES
        kind = "beklenen prod tablosu" if is_prod else "app-yeni tablo"
        real, acols, uniques = resolve_actual(tname)

        L(f"## {tname}  _({kind})_")
        if real is None:
            if is_prod:
                L("- 🔴 **DB'de YOK** — beklenen prod tablosu bulunamadı (ad uyuşmazlığı? yanlış DB?).")
                cats["kritik"] += 1
            else:
                L("- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).")
            L()
            continue
        if is_prod:
            prod_present += 1
        else:
            newtab_present += 1
        if real != tname:
            L(f"- ℹ️ DB'deki gerçek ad: `{real}` (büyük/küçük harf farkı; MSSQL genelde CI, sorun değil).")

        new_set = APP_NEW_COLUMNS.get(tname, set())
        seen_orm = set()
        for col in table.columns:
            dbname = col.name
            seen_orm.add(dbname.lower())
            a = acols.get(dbname.lower())
            if a is None:
                if dbname in new_set:
                    L(f"  ➕ `{dbname}` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).")
                    additive_cols += 1
                else:
                    L(f"  🔴 `{dbname}` — **beklenen prod kolonu EKSİK!** ad uyuşmazlığı olabilir "
                      f"(ORM `{_clean(_orm_type_str(col, dialect))}`).")
                    cats["kritik"] += 1
                continue
            # kolon var → tip/null kıyası. issues: (şiddet, metin)
            orm_ts = _clean(_orm_type_str(col, dialect))
            act_ts = _clean(str(a["type"]))
            fam_orm, fam_act = _family(col.type), _family(a["type"])
            issues: list[tuple[str, str]] = []
            if fam_orm != fam_act:
                issues.append(("🔴", f"tip ailesi {fam_orm}≠{fam_act}"))
            elif fam_orm == "str" and _is_unicode(orm_ts) != _is_unicode(act_ts):
                issues.append(("🟢", "unicode (VARCHAR↔NVARCHAR)"))
            lo, la = _length(col.type), _length(a["type"])
            if fam_orm == "str" and lo and la and lo != la:
                issues.append(("🟢", f"uzunluk {lo}≠{la}"))
            if not col.primary_key and bool(col.nullable) != bool(a["nullable"]):
                issues.append(("🟡", f"null ORM={'NULL' if col.nullable else 'NOT NULL'}"
                                     f"↔DB={'NULL' if a['nullable'] else 'NOT NULL'}"))
            if issues:
                sev = "🔴" if any(s == "🔴" for s, _ in issues) else \
                      "🟡" if any(s == "🟡" for s, _ in issues) else "🟢"
                for s, _ in issues:
                    cats["kritik" if s == "🔴" else "davranissal" if s == "🟡" else "sadakat"] += 1
                L(f"  {sev} `{dbname}`  ORM `{orm_ts}` ↔ DB `{act_ts}`  → "
                  f"{', '.join(t for _, t in issues)}")
            else:
                L(f"  ✅ `{dbname}`  ({act_ts}, {'NULL' if a['nullable'] else 'NOT NULL'})")

        # prod'da olup ORM'de olmayan kolonlar
        prod_only = [a["name"] for k, a in acols.items() if k not in seen_orm]
        if prod_only:
            L(f"  ℹ️ prod-only (app yok sayar): {', '.join('`%s`' % c for c in prod_only)}")

        # tabloya özel kısıt bulguları
        _special_findings(tname, acols, uniques, L)
        L()

    # DB'de olup ORM'de hiç olmayan tablolar (ör. [group], session_cache)
    orm_names_lower = {t.name.lower() for t in Base.metadata.sorted_tables}
    db_only = sorted(real for k, real in actual_tables.items() if k not in orm_names_lower)
    if db_only:
        L("## ℹ️ DB'de olup ORM'de olmayan tablolar")
        L(f"- {', '.join('`%s`' % t for t in db_only)}  (app yok sayar; prod'da kalır — ör. `[group]`, `session_cache`).")
        L()

    # --- özet başa yerleştir ---
    warn = cats["kritik"]  # çıkış kodu yalnız KRİTİK bulgularda 1 (ad/yapı bloklayıcıları)
    total = cats["kritik"] + cats["davranissal"] + cats["sadakat"]
    summary = [
        "## Özet",
        f"- Beklenen prod tablosu: **{prod_present}/{len(EXPECTED_PROD_TABLES)}** mevcut"
        + ("" if prod_present == len(EXPECTED_PROD_TABLES) else "  🔴"),
        f"- App-yeni tablo: **{newtab_present}/{len(NEW_APP_TABLES)}** mevcut "
        f"(eksikler `create_all` ile kurulur)",
        f"- ➕ Additive kolon (app açılışta ekler): **{additive_cols}**",
        f"- Uyuşmazlık toplam **{total}**:",
        f"    - 🔴 Kritik (eksik prod kolonu/tablosu, tip ailesi): **{cats['kritik']}** "
        "— ad uyuşmazlığı, MUTLAKA düzelt",
        f"    - 🟡 Davranışsal (nullability/UNIQUE): **{cats['davranissal']}** "
        "— app prod kısıtına UYMALI (SerialNumber, email…)",
        f"    - 🟢 Sadakat/bilgi (unicode·uzunluk): **{cats['sadakat']}** "
        "— prod'da kolon ZATEN öyle; app yazarken sorun olmaz, yalnız greenfield/tip-sadakati için",
        "- Sonuç: " + ("🔴 kritik var — İNCELE" if cats["kritik"]
                       else "🔴 kritik YOK ✅; tip/kısıt deltaları Pragmatik/Tam kararına bırakıldı"),
    ]
    lines[summary_slot:summary_slot] = summary
    return lines, warn


def _special_findings(tname, acols, uniques, L):
    """Kritik kısıt/ad sorularını doğrudan yanıtla (Pragmatik/Tam kararının girdisi)."""
    def col_nullable(name):
        a = acols.get(name.lower())
        return None if a is None else a["nullable"]

    def in_unique(name):
        return any(name.lower() in [c.lower() for c in (u.get("column_names") or [])] for u in uniques)

    if tname == "SSLCertificates":
        creators = [a["name"] for k, a in acols.items() if "certificatecreator" in k]
        L(f"  🔎 `%CertificateCreator%` kolon(lar)ı: "
          f"{', '.join('`%s`' % c for c in creators) if creators else '**YOK** (ad farklı olabilir!)'}")
        sn = col_nullable("SerialNumber")
        L(f"  🔎 `SerialNumber`: NOT NULL={sn is False}, UNIQUE={in_unique('SerialNumber')}")
        for c in ("Issuer", "Subject"):
            L(f"  🔎 `{c}`: NOT NULL={col_nullable(c) is False}")
    if tname == "users":
        L(f"  🔎 `email`: NOT NULL={col_nullable('email') is False}, UNIQUE(username)={in_unique('username')}")


def main():
    ap = argparse.ArgumentParser(description="Prod şema tutarlılık doğrulaması (READ-ONLY).")
    ap.add_argument("--url", help="Hedef bağlantı URL'i (varsayılan: MSSQL_* env / effective_database_url).")
    repo_root = Path(__file__).resolve().parents[2]
    default_out = (repo_root / "deploy" / "prod-schema-diff-report.md"
                   if (repo_root / "deploy").is_dir() else Path("prod-schema-diff-report.md"))
    ap.add_argument("--out", default=str(default_out), help=f"Rapor dosyası (varsayılan: {default_out}).")
    ap.add_argument("--no-file", action="store_true", help="Dosyaya yazma, yalnız stdout.")
    args = ap.parse_args()

    url = args.url or get_settings().effective_database_url
    if url.startswith("sqlite"):
        print("UYARI: hedef SQLite görünüyor. Prod (MSSQL) doğrulaması için --url ver ya da MSSQL_* env ayarla.",
              file=sys.stderr)

    lines, warn = check(url)
    report = "\n".join(lines) + "\n"
    print(report)
    if not args.no_file:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"[rapor yazıldı: {args.out}]", file=sys.stderr)
    sys.exit(1 if warn else 0)


if __name__ == "__main__":
    main()
