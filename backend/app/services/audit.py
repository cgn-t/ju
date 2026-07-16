import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models import AuditLog


def log_action(db: Session, username: str, action: str, table_name: str,
               record_id: str | int | None = None, details: dict | list | str | None = None,
               request: Request | None = None) -> None:
    """Mutasyon işlemlerini audit_log tablosuna yazar. Çağıran commit eder."""
    # dict VE list JSON'a serileştirilir — DB sürücüleri (pymssql/sqlite) ham list/dict bind edemez.
    if isinstance(details, (dict, list)):
        details = json.dumps(details, ensure_ascii=False, default=str)
    db.add(AuditLog(
        username=username,
        action=action,
        table_name=table_name,
        # Prod AuditLog.RecordID NOT NULL → kayıt-bağımsız işlemlerde (ör. vault_sync) "" yaz.
        record_id=str(record_id) if record_id is not None else "",
        details=details,
        ip_address=request.client.host if request and request.client else None,
    ))
