"""Kullanım Kılavuzu (wiki) uçları. Okuma herkese açık; sayfa ekleme, düzenleme ve silme yöneticide.
Her değişiklik Audit Log'a yazılır (tablo: wiki_pages)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User, WikiPage
from app.db.session import get_db
from app.services import wiki
from app.services.audit import diff_fields, log_action

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

MAX_BODY = 100_000


class WikiPageOut(BaseModel):
    id: int
    slug: str
    title: str
    category: str
    body: str
    sort_order: int
    updated_by: str | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}

    @field_serializer("updated_at")
    def _utc(self, v: datetime | None) -> str | None:   # DB naive UTC → tarayıcı yerel saatine çevirsin
        return v.replace(tzinfo=timezone.utc).isoformat() if v else None


class WikiPageIn(BaseModel):
    title: str
    category: str
    body: str = ""
    sort_order: int = 0


def _clean(body: WikiPageIn) -> dict:
    title = (body.title or "").strip()[:255]
    category = (body.category or "").strip()[:100]
    if not title or not category:
        raise HTTPException(status_code=400, detail="Başlık ve kategori zorunlu")
    if len(body.body or "") > MAX_BODY:
        raise HTTPException(status_code=400, detail="İçerik çok uzun (en fazla 100.000 karakter)")
    return {"title": title, "category": category, "body": body.body or "",
            "sort_order": int(body.sort_order or 0)}


def _get(db: Session, page_id: int) -> WikiPage:
    page = db.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Kılavuz sayfası bulunamadı")
    return page


@router.get("", response_model=list[WikiPageOut])
def list_pages(db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    """Tüm sayfalar kılavuz sırasıyla (kategori, sıra). Metinler küçük; ekran içinde arar."""
    return wiki.ordered(db)


@router.get("/{slug}", response_model=WikiPageOut)
def get_page(slug: str, db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    page = db.query(WikiPage).filter(WikiPage.slug == slug).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Kılavuz sayfası bulunamadı")
    return page


@router.post("", response_model=WikiPageOut)
def create_page(request: Request, body: WikiPageIn, db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    data = _clean(body)
    page = WikiPage(slug=wiki.unique_slug(db, data["title"]), updated_by=user.username, **data)
    db.add(page)
    db.flush()
    log_action(db, user.username, "create", "wiki_pages", page.id,
               {"title": page.title, "category": page.category}, request=request)
    db.commit()
    db.refresh(page)
    return page


@router.put("/{page_id}", response_model=WikiPageOut)
def update_page(page_id: int, request: Request, body: WikiPageIn, db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    """Adres (slug) başlık değişse de aynı kalır — sayfaya verilen bağlantılar kırılmaz."""
    page = _get(db, page_id)
    data = _clean(body)
    changes = diff_fields(page, data)
    for field, value in data.items():
        setattr(page, field, value)
    page.updated_by = user.username   # artık el değdi: yeni sürüm metni bu sayfanın üstüne yazılmaz
    if "body" in changes:   # uzun metnin tamamı denetim kaydına yazılmaz
        changes["body"] = {k: (v[:500] + "…" if isinstance(v, str) and len(v) > 500 else v)
                           for k, v in changes["body"].items()}
    if changes:
        log_action(db, user.username, "update", "wiki_pages", page.id,
                   {"title": page.title, "changes": changes}, request=request)
    db.commit()
    db.refresh(page)
    return page


@router.delete("/{page_id}")
def delete_page(page_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    page = _get(db, page_id)
    log_action(db, user.username, "delete", "wiki_pages", page.id,
               {"title": page.title, "category": page.category}, request=request)
    db.delete(page)
    db.commit()
    return {"ok": True}
