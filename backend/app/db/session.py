from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.effective_database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kwargs)
    if eng.dialect.name == "mssql":
        @event.listens_for(eng, "connect")
        def _nocount_off(dbapi_conn, _record):
            # Sunucu/giriş varsayılanında NOCOUNT açıksa UPDATE satır sayısı -1 gelir ve
            # SQLAlchemy StaleDataError atar; her yeni bağlantıda kapatılır.
            cur = dbapi_conn.cursor()
            cur.execute("SET NOCOUNT OFF")
            cur.close()
    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
