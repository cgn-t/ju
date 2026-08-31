"""Dağıtım akışı (Jenkins DAG editörü) uçları. Görme (flows/runs listesi-detayı) mevcut
Dağıtım sayfası kuralıyla aynı: `require_page_access("deployments")`. Akış TASARIMI
(oluşturma/düzenleme/silme) o uygulamanın SY ekibine açık — `can_manage_team_resource`,
Applications düzenleme yetkisiyle AYNI kapsam kuralı. Akışı ÇALIŞTIRMA (gerçek Jenkins
tetikleme) mevcut `/api/jenkins/trigger` konvansiyonuyla tutarlı şekilde HER ZAMAN admin-only.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    DeploymentFlowCreate, DeploymentFlowOut, DeploymentFlowSummaryOut, DeploymentFlowUpdate,
    DeploymentRunOut, DeploymentRunSummaryOut,
)
from app.core.security import can_manage_team_resource, require_page_access, require_role
from app.core.timeutil import utcnow
from app.db.models import Application, DeploymentFlow, DeploymentRun, DeploymentRunStep, User
from app.db.session import get_db
from app.services.audit import log_action
from app.services.deployment_engine import rerun_run, retry_step, start_run

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _validate_dag(nodes: list[dict], edges: list[dict]) -> None:
    if not nodes:
        raise HTTPException(status_code=400, detail="Akışta en az bir düğüm olmalı")
    ids: set[str] = set()
    for n in nodes:
        nid = n.get("id")
        if not nid or nid in ids:
            raise HTTPException(status_code=400, detail="Düğüm id'leri benzersiz ve dolu olmalı")
        ids.add(nid)
    indegree = {nid: 0 for nid in ids}
    adjacency: dict[str, list[str]] = {nid: [] for nid in ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src not in ids or tgt not in ids:
            raise HTTPException(status_code=400, detail=f"Geçersiz bağlantı: {src} → {tgt}")
        adjacency[src].append(tgt)
        indegree[tgt] += 1
    queue = [nid for nid, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for nxt in adjacency[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(ids):
        raise HTTPException(status_code=400, detail="Akışta döngü tespit edildi — DAG olmalı")


def _get_flow_or_404(db: Session, flow_id: int) -> DeploymentFlow:
    flow = db.get(DeploymentFlow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Akış bulunamadı")
    return flow


def _require_design_access(db: Session, user: User, app_row: Application | None) -> None:
    if not can_manage_team_resource(db, user, app_row.sy_team_id if app_row else None):
        raise HTTPException(status_code=403,
                            detail="Bu uygulamanın dağıtım akışını yalnız sahibi SY ekibi veya admin yönetir")


# ---- Flows ----
@router.get("/flows", response_model=list[DeploymentFlowSummaryOut])
def list_flows(app_id: int | None = Query(None), db: Session = Depends(get_db),
               _: User = Depends(require_page_access("deployments"))):
    q = db.query(DeploymentFlow).options(joinedload(DeploymentFlow.app))
    if app_id is not None:
        q = q.filter(DeploymentFlow.app_id == app_id)
    return q.order_by(DeploymentFlow.name).all()


@router.get("/flows/{flow_id}", response_model=DeploymentFlowOut)
def get_flow(flow_id: int, db: Session = Depends(get_db),
            _: User = Depends(require_page_access("deployments"))):
    flow = (db.query(DeploymentFlow).options(joinedload(DeploymentFlow.app))
            .filter(DeploymentFlow.id == flow_id).first())
    if flow is None:
        raise HTTPException(status_code=404, detail="Akış bulunamadı")
    return flow


@router.post("/flows", response_model=DeploymentFlowOut)
def create_flow(request: Request, body: DeploymentFlowCreate, db: Session = Depends(get_db),
                user: User = Depends(require_role("editor"))):
    app_row = db.get(Application, body.app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    _require_design_access(db, user, app_row)
    nodes = body.definition.get("nodes") or []
    edges = body.definition.get("edges") or []
    _validate_dag(nodes, edges)
    exists = (db.query(DeploymentFlow)
              .filter(DeploymentFlow.app_id == body.app_id, DeploymentFlow.name == body.name).first())
    if exists is not None:
        raise HTTPException(status_code=409, detail="Bu uygulamada aynı adlı bir akış zaten var")
    flow = DeploymentFlow(
        app_id=body.app_id, name=body.name, description=body.description,
        definition=json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False),
        created_by=user.username, updated_by=user.username,
    )
    db.add(flow)
    db.flush()
    log_action(db, user.username, "create", "deployment_flows", flow.id,
               {"app_id": body.app_id, "name": body.name}, request)
    db.commit()
    return (db.query(DeploymentFlow).options(joinedload(DeploymentFlow.app))
            .filter(DeploymentFlow.id == flow.id).first())


@router.put("/flows/{flow_id}", response_model=DeploymentFlowOut)
def update_flow(request: Request, flow_id: int, body: DeploymentFlowUpdate,
                db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    flow = _get_flow_or_404(db, flow_id)
    _require_design_access(db, user, flow.app)
    if body.name is not None:
        exists = (db.query(DeploymentFlow)
                  .filter(DeploymentFlow.app_id == flow.app_id, DeploymentFlow.name == body.name,
                          DeploymentFlow.id != flow_id).first())
        if exists is not None:
            raise HTTPException(status_code=409, detail="Bu uygulamada aynı adlı bir akış zaten var")
        flow.name = body.name
    if body.description is not None:
        flow.description = body.description
    if body.definition is not None:
        nodes = body.definition.get("nodes") or []
        edges = body.definition.get("edges") or []
        _validate_dag(nodes, edges)
        flow.definition = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    flow.updated_by = user.username
    log_action(db, user.username, "update", "deployment_flows", flow.id, {"app_id": flow.app_id}, request)
    db.commit()
    return (db.query(DeploymentFlow).options(joinedload(DeploymentFlow.app))
            .filter(DeploymentFlow.id == flow_id).first())


@router.delete("/flows/{flow_id}")
def delete_flow(request: Request, flow_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_role("editor"))):
    flow = _get_flow_or_404(db, flow_id)
    _require_design_access(db, user, flow.app)
    # Run geçmişi flow silinse de KORUNUR (flow_id → SET NULL, definition_snapshot donmuş kalır)
    db.query(DeploymentRun).filter(DeploymentRun.flow_id == flow_id).update(
        {DeploymentRun.flow_id: None}, synchronize_session=False)
    log_action(db, user.username, "delete", "deployment_flows", flow.id, {"app_id": flow.app_id}, request)
    db.delete(flow)
    db.commit()
    return {"ok": True}


@router.post("/flows/{flow_id}/run", response_model=DeploymentRunOut)
def run_flow(request: Request, flow_id: int, db: Session = Depends(get_db),
            user: User = Depends(require_role("admin"))):
    """Akışı çalıştırır: kök düğümleri hemen tetikler, orkestrasyon motoru gerisini
    (ardışık/paralel ilerletme) arka planda yürütür. Tetikleme HER ZAMAN admin-only.

    Bu flow için hâlâ devam eden (pending/running) bir run varsa REDDEDİLİR — aksi halde
    "Dağıt"a iki kez basılırsa (ör. ilk run'ın Jenkins job'ı dakikalarca sürerken) aynı kök
    job'lar İKİNCİ kez tetiklenir. Poll döngüsü zaten yalnız durum SORGULAR, yeniden tetiklemez
    (bkz. deployment_engine.poll_running_runs); asıl çift-tetikleme riski buradaydı."""
    flow = _get_flow_or_404(db, flow_id)
    active = (db.query(DeploymentRun)
              .filter(DeploymentRun.flow_id == flow_id, DeploymentRun.status.in_(("pending", "running")))
              .first())
    if active is not None:
        raise HTTPException(status_code=409,
                            detail=f"Bu akış için zaten devam eden bir dağıtım var (#{active.id})")
    run = start_run(db, flow, triggered_by=user.username)
    log_action(db, user.username, "trigger", "deployment_run", run.id,
               {"flow_id": flow.id, "flow_name": flow.name}, request)
    db.commit()
    return (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
            .filter(DeploymentRun.id == run.id).first())


# ---- Runs ----
@router.get("/runs", response_model=list[DeploymentRunSummaryOut])
def list_runs(app_id: int | None = Query(None), flow_id: int | None = Query(None),
             q: str | None = Query(None),
             limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
             _: User = Depends(require_page_access("deployments"))):
    query = db.query(DeploymentRun)
    if app_id is not None:
        query = query.filter(DeploymentRun.app_id == app_id)
    if flow_id is not None:
        query = query.filter(DeploymentRun.flow_id == flow_id)
    if q:
        # Akış adı/tetikleyen VEYA herhangi bir adımın job'u/parametreleri (ör. "CERTKEY=jumbo.local_2026")
        # eşleşirse run listelenir — hangi geçmiş run'ın belirli bir parametreyle çalıştığını bulmak için.
        like = f"%{q}%"
        matching_run_ids = (db.query(DeploymentRunStep.run_id)
                            .filter(DeploymentRunStep.jenkins_job.ilike(like)
                                    | DeploymentRunStep.params_snapshot.ilike(like))
                            .distinct())
        query = query.filter(DeploymentRun.flow_name_snapshot.ilike(like)
                             | DeploymentRun.triggered_by.ilike(like)
                             | DeploymentRun.id.in_(matching_run_ids))
    return query.order_by(DeploymentRun.created_at.desc()).limit(limit).all()


@router.get("/runs/{run_id}", response_model=DeploymentRunOut)
def get_run(run_id: int, db: Session = Depends(get_db),
           _: User = Depends(require_page_access("deployments"))):
    run = (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
           .filter(DeploymentRun.id == run_id).first())
    if run is None:
        raise HTTPException(status_code=404, detail="Çalıştırma bulunamadı")
    return run


@router.post("/runs/{run_id}/steps/{step_id}/retry", response_model=DeploymentRunOut)
def retry_run_step(request: Request, run_id: int, step_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    """Başarısız TEK bir adımı yeniden tetikler — tüm akışı yeniden başlatmaz. Tetikleme HER
    ZAMAN admin-only (run_flow ile aynı kural)."""
    run = (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
           .filter(DeploymentRun.id == run_id).first())
    if run is None:
        raise HTTPException(status_code=404, detail="Çalıştırma bulunamadı")
    step = db.get(DeploymentRunStep, step_id)
    if step is None or step.run_id != run_id:
        raise HTTPException(status_code=404, detail="Adım bulunamadı")
    if step.status != "failed":
        raise HTTPException(status_code=409, detail="Yalnız 'başarısız' adımlar yeniden denenebilir")
    retry_step(db, run, step)
    log_action(db, user.username, "retry", "deployment_run_step", step.id,
               {"run_id": run.id, "node_id": step.node_id, "jenkins_job": step.jenkins_job}, request)
    db.commit()
    return run


@router.post("/runs/{run_id}/rerun", response_model=DeploymentRunOut)
def rerun_run_endpoint(request: Request, run_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_role("admin"))):
    """Geçmiş bir run'ı AYNI parametrelerle yeniden tetikler (rollback) — YENİ bir run oluşturur,
    mevcut run'ı değiştirmez. Tetikleme HER ZAMAN admin-only (run_flow/retry ile aynı kural).

    Yalnız BAŞARILI run'lar yeniden tetiklenebilir — kısmi/başarısız durumlar zaten adım bazlı
    'Yeniden Dene' ile ele alınıyor (retry_run_step)."""
    run = (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
           .filter(DeploymentRun.id == run_id).first())
    if run is None:
        raise HTTPException(status_code=404, detail="Çalıştırma bulunamadı")
    if run.status != "success":
        raise HTTPException(status_code=409, detail="Yalnız başarılı bir dağıtım yeniden tetiklenebilir")
    if run.flow_id is not None:
        active = (db.query(DeploymentRun)
                  .filter(DeploymentRun.flow_id == run.flow_id, DeploymentRun.status.in_(("pending", "running")))
                  .first())
        if active is not None:
            raise HTTPException(status_code=409,
                                detail=f"Bu akış için zaten devam eden bir dağıtım var (#{active.id})")
    new_run = rerun_run(db, run, triggered_by=user.username)
    log_action(db, user.username, "rerun", "deployment_run", new_run.id,
               {"source_run_id": run.id, "flow_id": run.flow_id}, request)
    db.commit()
    return (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
            .filter(DeploymentRun.id == new_run.id).first())


@router.post("/runs/{run_id}/cancel", response_model=DeploymentRunOut)
def cancel_run(request: Request, run_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    """Yalnız JUMBO'nun downstream tetiklemesini durdurur — Jenkins build'ini DURDURMAZ."""
    run = (db.query(DeploymentRun).options(joinedload(DeploymentRun.steps))
           .filter(DeploymentRun.id == run_id).first())
    if run is None:
        raise HTTPException(status_code=404, detail="Çalıştırma bulunamadı")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Yalnız çalışan bir dağıtım iptal edilebilir")
    for step in run.steps:
        if step.status in ("pending", "running"):
            step.status = "cancelled"
    run.status = "cancelled"
    run.finished_at = utcnow()
    log_action(db, user.username, "cancel", "deployment_run", run.id, {"flow_id": run.flow_id}, request)
    db.commit()
    return run
