"""Etiket (tag) kataloğu — kontrollü, kategorili. Uygulamalar bu etiketlerle etiketlenip
kategori bazında filtrelenir (bkz. applications.py tag_ids). Yetki modeli:
  • okuma: her giriş yapmış kullanıcı,
  • MEVCUT kategoriye etiket ekleme: her kullanıcı (viewer dahil — Ayarlar → Etiketler),
  • YENİ KATEGORİ açma + düzenleme/silme: yalnız admin (taksonomi kontrollü kalsın;
    herkes kategori açabilseydi 'Ürün/Urun/ürünler' gibi kopyalar filtreyi bölerdi)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.schemas import TagCreate, TagOut, TagUpdate
from app.core.security import ROLE_LEVELS, domain_scope_team_ids, require_role
from app.db.models import Application, ApplicationTag, Tag, User
from app.db.session import get_db
from app.services.audit import log_action

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(category: str | None = None, db: Session = Depends(get_db),
              user: User = Depends(require_role("viewer"))):
    """Etiketler (opsiyonel kategori filtresi), kategoriye+isme sıralı.
    KAPSAM: admin/allviewer tüm kataloğu görür; editor/viewer YALNIZ kendi SY ekiplerinin
    uygulamalarına ATANMIŞ etiketleri görür (başka takımın etiket isimleri sızmaz). Bu sayede
    liste dinamiktir — hiçbir uygulamada kalmayan (ör. silinen) etiket kendiliğinden düşer."""
    q = db.query(Tag)
    if category:
        q = q.filter(Tag.category == category)
    scope = domain_scope_team_ids(db, user)
    if scope is not None:
        assigned = (db.query(ApplicationTag.tag_id)
                    .join(Application, Application.id == ApplicationTag.application_id)
                    .filter(Application.sy_team_id.in_(scope or {-1})))
        q = q.filter(Tag.id.in_(assigned))
    return q.order_by(Tag.category, Tag.name).all()


@router.post("", response_model=TagOut)
def create_tag(request: Request, body: TagCreate, db: Session = Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    """Etiket oluştur (Ayarlar → Etiketler veya uygulama formundan anında-ekleme).
    (kategori, ad) zaten varsa MEVCUT olanı döndürür — idempotent (çakışma yerine yeniden
    kullanım). HER kullanıcı MEVCUT bir kategoriye etiket ekleyebilir; YENİ kategori açmak
    yalnız admin (taksonomi tek elden — modül docstring'ine bkz.)."""
    name = (body.name or "").strip()
    category = (body.category or "").strip()
    if not name or not category:
        raise HTTPException(status_code=400, detail="Etiket adı ve kategori zorunlu")
    existing = db.query(Tag).filter(Tag.category == category, Tag.name == name).first()
    if existing is not None:
        return existing
    category_exists = (db.query(Tag.id).filter(Tag.category == category).first() is not None)
    if not category_exists and ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS["admin"]:
        raise HTTPException(status_code=403,
                            detail=f"'{category}' kategorisi tanımlı değil — yeni kategoriyi "
                                   "yalnız yönetici oluşturabilir; mevcut kategorilerden seçin")
    tag = Tag(name=name, category=category, color=(body.color or None))
    db.add(tag)
    db.flush()
    log_action(db, user.username, "create", "tags", tag.id,
               {"name": name, "category": category}, request)
    db.commit()
    return tag


@router.put("/{tag_id}", response_model=TagOut)
def update_tag(request: Request, tag_id: int, body: TagUpdate, db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    """Katalog bakımı: isim/kategori/renk düzelt (yalnız admin)."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Etiket bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "category"):
        if changes.get(key) is not None:
            changes[key] = changes[key].strip()
    new_name = changes.get("name") or tag.name
    new_category = changes.get("category") or tag.category
    # (kategori, ad) benzersizliği: başka etiketle çakışmasın
    clash = (db.query(Tag).filter(Tag.category == new_category, Tag.name == new_name,
                                  Tag.id != tag_id).first())
    if clash is not None:
        raise HTTPException(status_code=409, detail="Bu kategoride aynı adlı etiket zaten var")
    for key, value in changes.items():
        setattr(tag, key, value)
    log_action(db, user.username, "update", "tags", tag.id, changes, request)
    db.commit()
    return tag


@router.delete("/{tag_id}")
def delete_tag(request: Request, tag_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    """Etiketi sil (yalnız admin). Uygulama bağlantıları (application_tags) önce elle silinir —
    dialect-bağımsız (SQLite'ta FK-cascade kapalı olabilir; MSSQL'de zaten CASCADE)."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Etiket bulunamadı")
    db.query(ApplicationTag).filter(
        ApplicationTag.tag_id == tag_id).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "tags", tag.id,
               {"name": tag.name, "category": tag.category}, request)
    db.delete(tag)
    db.commit()
    return {"ok": True}
