"""mTLS bağımlılıklarının izlediği sertifika — TEK KAYNAK (uygulama API'si, domain eşleme ve
süre uyarısı taraması aynı kuralı kullanır)."""

from sqlalchemy.orm import Session

from app.core.certtype import cert_type_filter
from app.db.models import AppDependency, Certificate, CertificateDomainMap


def domain_server_cert_id(db: Session, domain_id: int) -> int | None:
    """Hedef domain'in AKTİF 'server' LEAF sertifikasının id'si (en geç biteni). mTLS için
    izlenen kimlik her zaman leaf'tir (TLS el sıkışmasında sunulan sertifika) — "server"
    eşlemesi artık zinciri (intermediate/root dahil) da taşıyabildiğinden burada cert_type
    LEAF'e sabitlenir, aksi halde çok daha uzun ömürlü bir root/intermediate yanlışlıkla
    seçilebilirdi. O leaf yenilendiğinde renewal.propose bu bağımlılık için uygulama
    sahibi SY ekibine devir önerisi üretir."""
    row = (db.query(CertificateDomainMap)
           .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
           .filter(CertificateDomainMap.domain_id == domain_id,
                   CertificateDomainMap.mapping_type == "server",
                   cert_type_filter(Certificate.cert_type, "leaf"),
                   Certificate.is_active == True)
           .order_by(Certificate.valid_to.desc())
           .first())
    return row.certificate_id if row else None


def fill_unwatched_dependencies(db: Session, domain_id: int | None = None) -> int:
    """İzlediği sertifikası BOŞ olan mTLS bağımlılıklarını hedef domainin güncel server
    leaf'ine bağlar. Bağımlılık, hedef domainde henüz sertifika yokken eklenmişse boş kalır;
    domaine sonradan sertifika bağlanınca (elle, zincir içe aktarma, canlı doğrulama, devir)
    burada doldurulur — aksi halde uygulama sahibi süre uyarısı hiç almazdı. Dolu bağımlılığa
    DOKUNMAZ (sertifika değişimi devir önerisiyle, onayla olur). Commit çağırana aittir.
    Döner: doldurulan bağımlılık sayısı."""
    db.flush()  # oturum autoflush'suz olabilir — yeni eklenen eşlemeler sorguda görünsün
    q = db.query(AppDependency).filter(AppDependency.client_cert_id.is_(None))
    if domain_id is not None:
        q = q.filter(AppDependency.target_domain_id == domain_id)
    filled = 0
    for dep in q.all():
        cid = domain_server_cert_id(db, dep.target_domain_id)
        if cid is not None:
            dep.client_cert_id = cid
            filled += 1
    return filled
