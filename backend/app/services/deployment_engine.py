"""Dağıtım akışı (Jenkins DAG) orkestrasyon motoru.

Bir DeploymentFlow (nodes+edges+params) çalıştırıldığında (start_run) bağımsız/kök düğümler
hemen tetiklenir; ardışık düğümler önceki adımın Jenkins build'i SUCCESS olana kadar
tetiklenmez. poll_running_runs, notifier.py'deki "kendi SessionLocal()'ını açan arka plan
fonksiyonu + cron-sarmalayıcıdan bağımsız çekirdek fonksiyon" desenini izleyerek APScheduler'dan
periyodik çağrılır, RUNNING adımların Jenkins durumunu kontrol edip DAG'ı ilerletir.
"""

import json
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import DeploymentFlow, DeploymentRun, DeploymentRunStep
from app.db.session import SessionLocal
from app.services.jenkins_client import JenkinsClient

logger = logging.getLogger(__name__)

# Bir adım bu süreden uzun 'running' kalırsa (Jenkins erişilemez/asılı kaldıysa) failed işaretlenir
# — aksi hâlde run sonsuza dek 'running' kalır.
STEP_TIMEOUT = timedelta(minutes=120)

TERMINAL_STATUSES = {"success", "failed", "skipped", "cancelled"}


def _params_dict(node: dict) -> dict:
    rows = (node.get("data") or {}).get("params") or []
    return {str(r.get("key", "")).strip(): str(r.get("value", ""))
            for r in rows if str(r.get("key", "")).strip()}


def _trigger_step(client: JenkinsClient, step: DeploymentRunStep) -> None:
    """Bir adımı Jenkins'te tetikler, sonucu step üzerine yazar (commit çağıran sorumluluğunda)."""
    if not step.jenkins_job:
        step.status = "failed"
        step.error_message = "Jenkins job tanımlı değil"
        step.started_at = utcnow()
        step.finished_at = utcnow()
        return
    params = json.loads(step.params_snapshot or "{}")
    ok, message, queue_url = client.trigger_job_tracked(step.jenkins_job, params)
    step.started_at = utcnow()
    if ok:
        step.status = "running"
        step.jenkins_queue_url = queue_url
    else:
        step.status = "failed"
        step.error_message = message
        step.finished_at = utcnow()


def _start_run(db: Session, *, flow_id: int | None, app_id: int | None, flow_name: str,
               definition_json: str, triggered_by: str, trigger_type: str = "manual",
               source_run_id: int | None = None) -> DeploymentRun:
    """start_run/rerun_run'ın ortak gövdesi: bir tanımdan (canlı flow VEYA donmuş bir run
    snapshot'ından) yeni run oluşturur, her node için bir step açar, kök step'leri hemen
    tetikler. Çağıran commit eder."""
    definition = json.loads(definition_json)
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []

    incoming: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e.get("target") in incoming and e.get("source") in incoming:
            incoming[e["target"]].append(e["source"])

    run = DeploymentRun(
        flow_id=flow_id, app_id=app_id, flow_name_snapshot=flow_name,
        definition_snapshot=definition_json, status="running",
        triggered_by=triggered_by, trigger_type=trigger_type, source_run_id=source_run_id,
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()

    steps: dict[str, DeploymentRunStep] = {}
    for n in nodes:
        data = n.get("data") or {}
        step = DeploymentRunStep(
            run_id=run.id, node_id=n["id"], node_label=data.get("label") or n["id"],
            jenkins_job=data.get("jenkins_job") or "",
            params_snapshot=json.dumps(_params_dict(n), ensure_ascii=False),
            depends_on=json.dumps(incoming.get(n["id"], []), ensure_ascii=False),
            status="pending",
        )
        db.add(step)
        steps[n["id"]] = step
    db.flush()

    client = JenkinsClient(db)
    for node_id, step in steps.items():
        if incoming.get(node_id):
            continue
        _trigger_step(client, step)
        if step.status == "failed":
            # Kök düğüm ANINDA (senkron) tetikleme hatasıyla başarısız oldu — poll_running_runs
            # bu step'i bir daha GÖRMEZ (zaten terminal), o yüzden downstream skip'i burada tetikle.
            _advance(db, run, definition, step)

    db.flush()
    _sync_run_status(run)
    return run


def start_run(db: Session, flow: DeploymentFlow, triggered_by: str) -> DeploymentRun:
    """Flow tanımından yeni bir run başlatır (trigger_type='manual')."""
    return _start_run(db, flow_id=flow.id, app_id=flow.app_id, flow_name=flow.name,
                      definition_json=flow.definition, triggered_by=triggered_by)


def rerun_run(db: Session, source_run: DeploymentRun, triggered_by: str) -> DeploymentRun:
    """Geçmiş bir run'ı AYNI parametrelerle yeniden tetikler (rollback) — canlı flow tanımı
    sonradan değişmiş/silinmiş olsa bile source_run.definition_snapshot kullanılır, yani o an
    ne tetiklendiyse tam olarak onu tekrarlar. Çağıran (source_run.status == 'success' vb.)
    ön koşulları doğrular; burası yalnız oluşturur."""
    return _start_run(db, flow_id=source_run.flow_id, app_id=source_run.app_id,
                      flow_name=source_run.flow_name_snapshot,
                      definition_json=source_run.definition_snapshot, triggered_by=triggered_by,
                      trigger_type="rerun", source_run_id=source_run.id)


def _downstream_ids(edges: list[dict], start: str) -> set[str]:
    """start'tan yönlü kenarlar üzerinden ulaşılabilen TÜM node id'leri (BFS)."""
    adjacency: dict[str, list[str]] = {}
    for e in edges:
        adjacency.setdefault(e.get("source"), []).append(e.get("target"))
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        for nxt in adjacency.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _advance(db: Session, run: DeploymentRun, definition: dict, completed_step: DeploymentRunStep) -> None:
    """completed_step terminal bir duruma ulaştıktan sonra DAG'ı ilerletir: başarılıysa TÜM
    bağımlılıkları success olan pending adımları tetikler (AND semantiği); başarısızsa
    transitif downstream'i skipped yapar."""
    steps_by_node = {s.node_id: s for s in run.steps}
    client = JenkinsClient(db)

    if completed_step.status == "success":
        for step in run.steps:
            if step.status != "pending":
                continue
            deps = json.loads(step.depends_on or "[]")
            if completed_step.node_id not in deps:
                continue
            if all(steps_by_node.get(d) is not None and steps_by_node[d].status == "success" for d in deps):
                _trigger_step(client, step)
    else:
        edges = definition.get("edges") or []
        for node_id in _downstream_ids(edges, completed_step.node_id):
            step = steps_by_node.get(node_id)
            if step is not None and step.status == "pending":
                step.status = "skipped"
                step.finished_at = utcnow()


def retry_step(db: Session, run: DeploymentRun, step: DeploymentRunStep) -> None:
    """Başarısız TEK bir adımı yeniden tetikler — tüm akışı değil. Bu adımın hatası yüzünden
    'skipped' kalmış transitif downstream'i de (başka bir bağımlılığı hâlâ başarısız/atlanmış
    DEĞİLSE) 'pending'e döndürür ki adım bu kez başarılı olursa normal _advance akışıyla devam
    etsin. step.status 'failed' olmalı (çağıran doğrular). Çağıran commit eder."""
    definition = json.loads(run.definition_snapshot)
    edges = definition.get("edges") or []
    steps_by_node = {s.node_id: s for s in run.steps}
    downstream = _downstream_ids(edges, step.node_id)

    def _reset(s: DeploymentRunStep) -> None:
        s.status = "pending"
        s.error_message = None
        s.jenkins_queue_url = None
        s.jenkins_build_number = None
        s.started_at = None
        s.finished_at = None
        s.last_poll_at = None

    _reset(step)

    # Sabit nokta (fixed-point): bir adımın TÜM bağımlılıkları success/pending olduğunda pending'e
    # çevrilir; bu başka bir skipped adımı da uygun hale getirebileceğinden değişiklik kalmayana
    # kadar tekrarlanır (graf küçük olduğundan maliyeti önemsiz).
    changed = True
    while changed:
        changed = False
        for node_id in downstream:
            s = steps_by_node.get(node_id)
            if s is None or s.status != "skipped":
                continue
            deps = json.loads(s.depends_on or "[]")
            if all(steps_by_node.get(d) is not None and steps_by_node[d].status in ("success", "pending")
                   for d in deps):
                _reset(s)
                changed = True

    run.status = "running"
    run.finished_at = None
    client = JenkinsClient(db)
    _trigger_step(client, step)
    if step.status == "failed":
        _advance(db, run, definition, step)
    _sync_run_status(run)


def _sync_run_status(run: DeploymentRun) -> None:
    if not run.steps:
        run.status = "failed"
        run.finished_at = utcnow()
        return
    if all(s.status in TERMINAL_STATUSES for s in run.steps):
        run.status = "failed" if any(s.status == "failed" for s in run.steps) else "success"
        run.finished_at = utcnow()


def _poll_step(client: JenkinsClient, step: DeploymentRunStep) -> bool:
    """Step'in Jenkins durumunu günceller; TERMİNAL bir duruma geçtiyse True döner (advance
    tetiklenmeli demektir). Geçici ağ hatasında step'e DOKUNMAZ (bir sonraki pollde tekrar dener)."""
    step.last_poll_at = utcnow()

    if step.jenkins_build_number is None:
        if not step.jenkins_queue_url:
            return False
        number = client.resolve_queue_item(step.jenkins_queue_url)
        if number is None:
            if step.started_at and utcnow() - step.started_at > STEP_TIMEOUT:
                step.status = "failed"
                step.error_message = "Zaman aşımı (Jenkins kuyruğunda)"
                step.finished_at = utcnow()
                return True
            return False
        if number == -1:
            step.status = "failed"
            step.error_message = "Jenkins kuyruğu iptal etti"
            step.finished_at = utcnow()
            return True
        step.jenkins_build_number = number

    try:
        status = client.build_status(step.jenkins_job, step.jenkins_build_number)
    except Exception as exc:  # noqa: BLE001 — geçici ağ hatası, dokunma
        logger.warning("build_status hata (job=%s, build=%s): %s",
                       step.jenkins_job, step.jenkins_build_number, exc)
        return False

    if status.get("building"):
        if step.started_at and utcnow() - step.started_at > STEP_TIMEOUT:
            step.status = "failed"
            step.error_message = "Zaman aşımı (Jenkins build)"
            step.finished_at = utcnow()
            return True
        return False

    result = status.get("result")
    if result == "SUCCESS":
        step.status = "success"
        step.finished_at = utcnow()
        return True
    if result in ("FAILURE", "UNSTABLE", "ABORTED"):
        step.status = "failed"
        step.error_message = f"Jenkins build sonucu: {result}"
        step.finished_at = utcnow()
        return True
    return False


def poll_running_runs() -> None:
    """APScheduler'dan periyodik çağrılan çekirdek fonksiyon (bkz. notifier.start_scheduler).
    Tüm RUNNING run'ların RUNNING adımlarını kontrol eder, bitenleri ilerletir. Kendi DB
    session'ını açar — istek bağlamı (get_db) dışında çalışır."""
    db: Session = SessionLocal()
    try:
        client = JenkinsClient(db)
        runs = db.query(DeploymentRun).filter(DeploymentRun.status.in_(("pending", "running"))).all()
        for run in runs:
            definition = json.loads(run.definition_snapshot)
            for step in list(run.steps):
                if step.status != "running":
                    continue
                if _poll_step(client, step):
                    _advance(db, run, definition, step)
            _sync_run_status(run)
        db.commit()
    except Exception:
        logger.exception("poll_running_runs hata")
        db.rollback()
    finally:
        db.close()
