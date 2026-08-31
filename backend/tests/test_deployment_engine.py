"""Dağıtım akışı (Jenkins DAG) orkestrasyon motoru + API — paralel/ardışık/AND tetikleme,
hata→skip yayılımı, zaman aşımı, snapshot değişmezliği, döngü reddi, RBAC."""

from datetime import timedelta

from app.core.timeutil import utcnow
from app.db.models import DeploymentRunStep
from app.db.session import SessionLocal
from app.services.jenkins_client import JenkinsClient


def _sy_team(client, h, name):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _app(client, h, name, sy_team_id):
    r = client.post("/api/applications", headers=h,
                    json={"app_name": name, "server_name": name, "sy_team_id": sy_team_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _editor_in(client, h, username, team_id):
    client.post("/api/users", headers=h, json={
        "username": username, "password": "x", "role": "editor", "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=h).json()
               if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=h, json={"user_id": uid})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _node(node_id, job, params=None):
    return {"id": node_id, "position": {"x": 0, "y": 0},
            "data": {"label": node_id, "jenkins_job": job, "params": params or []}}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


def _create_flow(client, h, app_id, name, nodes, edges):
    return client.post("/api/deployments/flows", headers=h,
                       json={"app_id": app_id, "name": name,
                             "definition": {"nodes": nodes, "edges": edges}})


def _install_jenkins_fake(monkeypatch, results: dict):
    """results: job adı → 'SUCCESS'|'FAILURE'|None (None = hâlâ building/kuyrukta).
    Bir job results'ta yoksa da 'building' (None) davranır."""

    def fake_trigger(self, job, params):
        return True, f"'{job}' tetiklendi", f"queue/{job}"

    def fake_resolve(self, queue_url):
        return 1  # her zaman hemen build #1'e çözülür

    def fake_status(self, job, number):
        result = results.get(job)
        return {"result": result, "building": result is None}

    monkeypatch.setattr(JenkinsClient, "trigger_job_tracked", fake_trigger)
    monkeypatch.setattr(JenkinsClient, "resolve_queue_item", fake_resolve)
    monkeypatch.setattr(JenkinsClient, "build_status", fake_status)


def _steps_by_node(run_json):
    return {s["node_id"]: s for s in run_json["steps"]}


def test_parallel_roots_trigger_together(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {})
    tid = _sy_team(client, h, "SY-Dep-Par")
    app_id = _app(client, h, "DepApp-Par", tid)
    r = _create_flow(client, h, app_id, "paralel-akis",
                     [_node("a", "job-a"), _node("b", "job-b")], [])
    assert r.status_code == 200, r.text
    flow_id = r.json()["id"]

    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)
    assert run.status_code == 200, run.text
    steps = _steps_by_node(run.json())
    assert steps["a"]["status"] == "running"
    assert steps["b"]["status"] == "running"
    assert run.json()["status"] == "running"


def test_sequential_waits_for_previous_success(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "SUCCESS"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-Seq")
    app_id = _app(client, h, "DepApp-Seq", tid)
    r = _create_flow(client, h, app_id, "ardisik-akis",
                     [_node("a", "job-a"), _node("b", "job-b")], [_edge("a", "b")])
    flow_id = r.json()["id"]

    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    steps = _steps_by_node(run)
    assert steps["a"]["status"] == "running"
    assert steps["b"]["status"] == "pending"  # A bitmeden B tetiklenmemeli

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()

    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps2 = _steps_by_node(run2)
    assert steps2["a"]["status"] == "success"
    assert steps2["b"]["status"] == "running"  # A success olunca B otomatik tetiklendi


def test_and_dependency_waits_for_all_parents(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "SUCCESS", "job-b": None}  # B hâlâ çalışıyor
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-And")
    app_id = _app(client, h, "DepApp-And", tid)
    r = _create_flow(client, h, app_id, "and-akisi",
                     [_node("a", "job-a"), _node("b", "job-b"), _node("c", "job-c")],
                     [_edge("a", "c"), _edge("b", "c")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps2 = _steps_by_node(run2)
    assert steps2["a"]["status"] == "success"
    assert steps2["b"]["status"] == "running"
    assert steps2["c"]["status"] == "pending"  # yalnız A bitti, B beklemede — C tetiklenmemeli

    results["job-b"] = "SUCCESS"
    poll_running_runs()
    run3 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps3 = _steps_by_node(run3)
    assert steps3["b"]["status"] == "success"
    assert steps3["c"]["status"] == "running"  # ikisi de bitince C tetiklendi


def test_failure_skips_downstream(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "FAILURE"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-Fail")
    app_id = _app(client, h, "DepApp-Fail", tid)
    r = _create_flow(client, h, app_id, "hata-akisi",
                     [_node("a", "job-a"), _node("b", "job-b"), _node("c", "job-c")],
                     [_edge("a", "b"), _edge("b", "c")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps2 = _steps_by_node(run2)
    assert steps2["a"]["status"] == "failed"
    assert steps2["b"]["status"] == "skipped"
    assert steps2["c"]["status"] == "skipped"
    assert run2["status"] == "failed"


def test_step_timeout_marks_failed(client, auth_headers, monkeypatch):
    h = auth_headers

    def fake_trigger(self, job, params):
        return True, f"'{job}' tetiklendi", f"queue/{job}"

    def fake_resolve_never(self, queue_url):
        return None  # sonsuza dek kuyrukta kalır

    monkeypatch.setattr(JenkinsClient, "trigger_job_tracked", fake_trigger)
    monkeypatch.setattr(JenkinsClient, "resolve_queue_item", fake_resolve_never)

    tid = _sy_team(client, h, "SY-Dep-Timeout")
    app_id = _app(client, h, "DepApp-Timeout", tid)
    r = _create_flow(client, h, app_id, "zaman-asimi-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    db = SessionLocal()
    try:
        step = db.query(DeploymentRunStep).filter(
            DeploymentRunStep.run_id == run["id"], DeploymentRunStep.node_id == "a").first()
        step.started_at = utcnow() - timedelta(minutes=200)
        db.commit()
    finally:
        db.close()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    step2 = _steps_by_node(run2)["a"]
    assert step2["status"] == "failed"
    assert "aşım" in (step2["error_message"] or "")


def test_run_snapshot_immutable_after_flow_edit(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {})
    tid = _sy_team(client, h, "SY-Dep-Snap")
    app_id = _app(client, h, "DepApp-Snap", tid)
    r = _create_flow(client, h, app_id, "snapshot-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    assert _steps_by_node(run)["a"]["jenkins_job"] == "job-a"

    upd = client.put(f"/api/deployments/flows/{flow_id}", headers=h,
                     json={"definition": {"nodes": [_node("a", "job-a-YENİ")], "edges": []}})
    assert upd.status_code == 200, upd.text

    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    assert _steps_by_node(run2)["a"]["jenkins_job"] == "job-a"  # run DEĞİŞMEDİ


def test_retry_single_failed_step(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "FAILURE"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-Retry")
    app_id = _app(client, h, "DepApp-Retry", tid)
    r = _create_flow(client, h, app_id, "retry-akisi",
                     [_node("a", "job-a"), _node("b", "job-b"), _node("c", "job-c")],
                     [_edge("a", "b"), _edge("b", "c")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps2 = _steps_by_node(run2)
    assert steps2["a"]["status"] == "failed"
    assert steps2["b"]["status"] == "skipped"
    assert steps2["c"]["status"] == "skipped"
    a_step_id = steps2["a"]["id"]

    # A'yı düzelt (Jenkins tarafında iş düzeldi varsayımı) ve YALNIZ o adımı yeniden dene
    results["job-a"] = "SUCCESS"
    retry = client.post(f"/api/deployments/runs/{run['id']}/steps/{a_step_id}/retry", headers=h)
    assert retry.status_code == 200, retry.text
    steps3 = _steps_by_node(retry.json())
    assert steps3["a"]["status"] == "running"          # yeniden tetiklendi
    assert steps3["b"]["status"] == "pending"           # A'nın hatası yüzünden skip'liydi — geri açıldı
    assert steps3["c"]["status"] == "pending"
    assert retry.json()["status"] == "running"          # run terminal DEĞİL artık

    poll_running_runs()
    run4 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps4 = _steps_by_node(run4)
    assert steps4["a"]["status"] == "success"
    assert steps4["b"]["status"] == "running"           # A success olunca B normal akışla tetiklendi


def test_retry_and_dependency_partial_failure(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "FAILURE", "job-b": "SUCCESS"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-RetryAnd")
    app_id = _app(client, h, "DepApp-RetryAnd", tid)
    r = _create_flow(client, h, app_id, "retry-and-akisi",
                     [_node("a", "job-a"), _node("b", "job-b"), _node("c", "job-c")],
                     [_edge("a", "c"), _edge("b", "c")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps2 = _steps_by_node(run2)
    assert steps2["a"]["status"] == "failed"
    assert steps2["b"]["status"] == "success"
    assert steps2["c"]["status"] == "skipped"           # A başarısız olduğu için C atlandı

    results["job-a"] = "SUCCESS"
    retry = client.post(f"/api/deployments/runs/{run['id']}/steps/{steps2['a']['id']}/retry", headers=h)
    assert retry.status_code == 200, retry.text
    steps3 = _steps_by_node(retry.json())
    assert steps3["a"]["status"] == "running"
    # B zaten success'ti — C'nin diğer bağımlılığı sağlam, tek eksik A'ydı → C pending'e açıldı
    assert steps3["c"]["status"] == "pending"

    poll_running_runs()
    run4 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    steps4 = _steps_by_node(run4)
    assert steps4["a"]["status"] == "success"
    assert steps4["c"]["status"] == "running"           # ikisi de success → C tetiklendi


def test_retry_requires_admin_and_failed_status(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "FAILURE"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-RetryRbac")
    app_id = _app(client, h, "DepApp-RetryRbac", tid)
    owner_editor = _editor_in(client, h, "dep_retry_owner_ed", tid)
    r = _create_flow(client, h, app_id, "retry-rbac-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    a_step_id = _steps_by_node(run)["a"]["id"]

    # Editör (tasarım yetkisi olan ama admin olmayan) retry YAPAMAZ
    r = client.post(f"/api/deployments/runs/{run['id']}/steps/{a_step_id}/retry", headers=owner_editor)
    assert r.status_code == 403, r.text

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()

    # 'failed' OLMAYAN bir adımı yeniden denemek 409 döner (A henüz 'running', poll'dan sonra 'failed' oldu)
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    assert _steps_by_node(run2)["a"]["status"] == "failed"

    retry = client.post(f"/api/deployments/runs/{run['id']}/steps/{a_step_id}/retry", headers=h)
    assert retry.status_code == 200, retry.text
    # Az önce yeniden tetiklendi → şimdi 'running', tekrar retry denemek 409 vermeli
    again = client.post(f"/api/deployments/runs/{run['id']}/steps/{a_step_id}/retry", headers=h)
    assert again.status_code == 409, again.text


def test_run_flow_rejects_when_already_running(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": None}  # 'building' — uzun süren bir job simülasyonu
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-DoubleRun")
    app_id = _app(client, h, "DepApp-DoubleRun", tid)
    r = _create_flow(client, h, app_id, "cift-tetik-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]

    first = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "running"

    # A hâlâ Jenkins'te çalışıyorken (building) ikinci "Dağıt" REDDEDİLMELİ — aksi halde aynı
    # kök job iki kez tetiklenir.
    second = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)
    assert second.status_code == 409, second.text

    # Job bitince (SUCCESS) run terminal olur — artık yeni bir run başlatılabilir.
    results["job-a"] = "SUCCESS"
    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run1 = client.get(f"/api/deployments/runs/{first.json()['id']}", headers=h).json()
    assert run1["status"] == "success"

    third = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)
    assert third.status_code == 200, third.text


def test_rerun_uses_source_run_params_not_live_flow(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "SUCCESS"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-Rerun")
    app_id = _app(client, h, "DepApp-Rerun", tid)
    r = _create_flow(client, h, app_id, "rerun-akisi",
                     [_node("a", "job-a", [{"key": "CERTKEY", "value": "jumbo.local_2027"}])], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    run1 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    assert run1["status"] == "success"

    # Flow'un canlı parametresi DEĞİŞTİ — ama rerun eski run'ın dondurulmuş halini kullanmalı
    upd = client.put(f"/api/deployments/flows/{flow_id}", headers=h,
                     json={"definition": {"nodes": [
                         _node("a", "job-a", [{"key": "CERTKEY", "value": "jumbo.local_2026"}])],
                         "edges": []}})
    assert upd.status_code == 200, upd.text

    rerun = client.post(f"/api/deployments/runs/{run['id']}/rerun", headers=h)
    assert rerun.status_code == 200, rerun.text
    new_step = _steps_by_node(rerun.json())["a"]
    assert new_step["params_snapshot"] == {"CERTKEY": "jumbo.local_2027"}  # eski değer, YENİ değer değil
    assert new_step["status"] == "running"


def test_rerun_sets_trigger_type_and_source_run_id(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-a": "SUCCESS"})
    tid = _sy_team(client, h, "SY-Dep-RerunMeta")
    app_id = _app(client, h, "DepApp-RerunMeta", tid)
    r = _create_flow(client, h, app_id, "rerun-meta-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    assert run["trigger_type"] == "manual"
    assert run["source_run_id"] is None

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()

    rerun = client.post(f"/api/deployments/runs/{run['id']}/rerun", headers=h)
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["trigger_type"] == "rerun"
    assert rerun.json()["source_run_id"] == run["id"]


def test_rerun_requires_success_status(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": None}  # building — henüz terminal değil
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-RerunStatus")
    app_id = _app(client, h, "DepApp-RerunStatus", tid)
    r = _create_flow(client, h, app_id, "rerun-status-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    still_running = client.post(f"/api/deployments/runs/{run['id']}/rerun", headers=h)
    assert still_running.status_code == 409, still_running.text

    results["job-a"] = "FAILURE"
    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    failed = client.post(f"/api/deployments/runs/{run['id']}/rerun", headers=h)
    assert failed.status_code == 409, failed.text


def test_rerun_rejects_when_flow_already_running(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": "SUCCESS"}
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-RerunDouble")
    app_id = _app(client, h, "DepApp-RerunDouble", tid)
    r = _create_flow(client, h, app_id, "rerun-double-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run1 = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    assert client.get(f"/api/deployments/runs/{run1['id']}", headers=h).json()["status"] == "success"

    # Aynı akış için hâlâ devam eden (building) ikinci bir run var
    results["job-a"] = None
    client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)

    rerun = client.post(f"/api/deployments/runs/{run1['id']}/rerun", headers=h)
    assert rerun.status_code == 409, rerun.text


def test_rerun_requires_admin(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-a": "SUCCESS"})
    tid = _sy_team(client, h, "SY-Dep-RerunRbac")
    app_id = _app(client, h, "DepApp-RerunRbac", tid)
    owner_editor = _editor_in(client, h, "dep_rerun_owner_ed", tid)
    r = _create_flow(client, h, app_id, "rerun-rbac-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()

    forbidden = client.post(f"/api/deployments/runs/{run['id']}/rerun", headers=owner_editor)
    assert forbidden.status_code == 403, forbidden.text


def test_cyclic_definition_rejected(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Dep-Cycle")
    app_id = _app(client, h, "DepApp-Cycle", tid)
    r = _create_flow(client, h, app_id, "dongu-akisi",
                     [_node("a", "job-a"), _node("b", "job-b")],
                     [_edge("a", "b"), _edge("b", "a")])
    assert r.status_code == 400, r.text


def test_rbac_design_scoped_to_owning_team_and_run_is_admin_only(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {})
    own = _sy_team(client, h, "SY-Dep-RbacOwn")
    other = _sy_team(client, h, "SY-Dep-RbacOther")
    app_id = _app(client, h, "DepApp-Rbac", own)
    owner_editor = _editor_in(client, h, "dep_rbac_owner_ed", own)
    outside_editor = _editor_in(client, h, "dep_rbac_outside_ed", other)

    # Ekip-dışı editör bu app için akış OLUŞTURAMAZ
    r = _create_flow(client, outside_editor, app_id, "rbac-akisi", [_node("a", "job-a")], [])
    assert r.status_code == 403, r.text

    # Sahibi ekibin editörü OLUŞTURABİLİR
    r = _create_flow(client, owner_editor, app_id, "rbac-akisi", [_node("a", "job-a")], [])
    assert r.status_code == 200, r.text
    flow_id = r.json()["id"]

    # Sahibi ekibin editörü bile ÇALIŞTIRAMAZ (tetikleme her zaman admin-only)
    r = client.post(f"/api/deployments/flows/{flow_id}/run", headers=owner_editor)
    assert r.status_code == 403, r.text

    # admin çalıştırabilir
    r = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h)
    assert r.status_code == 200, r.text

    # Görüntüleme varsayılan admin+allviewer-only — editor Ayarlar>Erişim açılmadan GÖRMEZ
    r = client.get(f"/api/deployments/flows/{flow_id}", headers=owner_editor)
    assert r.status_code == 403, r.text

    # access.deployments_all_roles açılınca editor da görebilir (page-access'i olan herkes GET)
    acc = client.get("/api/settings/access", headers=h).json()
    acc["deployments_all_roles"] = True
    assert client.put("/api/settings/access", headers=h, json=acc).status_code == 200
    r = client.get(f"/api/deployments/flows/{flow_id}", headers=owner_editor)
    assert r.status_code == 200, r.text


def test_missing_jenkins_job_fails_immediately_and_skips_downstream(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {})
    tid = _sy_team(client, h, "SY-Dep-NoJob")
    app_id = _app(client, h, "DepApp-NoJob", tid)
    r = _create_flow(client, h, app_id, "job-yok-akisi",
                     [_node("a", ""), _node("b", "job-b")], [_edge("a", "b")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    steps = _steps_by_node(run)
    assert steps["a"]["status"] == "failed"
    assert steps["a"]["error_message"] == "Jenkins job tanımlı değil"
    assert steps["b"]["status"] == "skipped"  # senkron tetikleme hatası ANINDA yayıldı, poll gerekmedi
    assert run["status"] == "failed"


def test_cancel_run_stops_pending_and_running_steps(client, auth_headers, monkeypatch):
    h = auth_headers
    results = {"job-a": None}  # building — uzun süren bir job simülasyonu
    _install_jenkins_fake(monkeypatch, results)
    tid = _sy_team(client, h, "SY-Dep-Cancel")
    app_id = _app(client, h, "DepApp-Cancel", tid)
    r = _create_flow(client, h, app_id, "iptal-akisi",
                     [_node("a", "job-a"), _node("b", "job-b")], [_edge("a", "b")])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()
    steps = _steps_by_node(run)
    assert steps["a"]["status"] == "running"
    assert steps["b"]["status"] == "pending"

    cancel = client.post(f"/api/deployments/runs/{run['id']}/cancel", headers=h)
    assert cancel.status_code == 200, cancel.text
    body = cancel.json()
    assert body["status"] == "cancelled"
    steps2 = _steps_by_node(body)
    assert steps2["a"]["status"] == "cancelled"
    assert steps2["b"]["status"] == "cancelled"

    # İptalden SONRA zamanlayıcı bu run'ı bir daha İLERLETMEMELİ (terminal, poll filtresi dışında)
    from app.services.deployment_engine import poll_running_runs
    results["job-a"] = "SUCCESS"
    poll_running_runs()
    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    assert run2["status"] == "cancelled"
    assert _steps_by_node(run2)["a"]["status"] == "cancelled"


def test_cancel_run_requires_running_status(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-a": "SUCCESS"})
    tid = _sy_team(client, h, "SY-Dep-CancelStatus")
    app_id = _app(client, h, "DepApp-CancelStatus", tid)
    r = _create_flow(client, h, app_id, "iptal-durum-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    from app.services.deployment_engine import poll_running_runs
    poll_running_runs()
    assert client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()["status"] == "success"

    cancel = client.post(f"/api/deployments/runs/{run['id']}/cancel", headers=h)
    assert cancel.status_code == 409, cancel.text


def test_cancel_run_requires_admin(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-a": None})
    tid = _sy_team(client, h, "SY-Dep-CancelRbac")
    app_id = _app(client, h, "DepApp-CancelRbac", tid)
    owner_editor = _editor_in(client, h, "dep_cancel_owner_ed", tid)
    r = _create_flow(client, h, app_id, "iptal-rbac-akisi", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    forbidden = client.post(f"/api/deployments/runs/{run['id']}/cancel", headers=owner_editor)
    assert forbidden.status_code == 403, forbidden.text


def test_flow_update_rejects_duplicate_name(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Dep-Rename")
    app_id = _app(client, h, "DepApp-Rename", tid)
    _create_flow(client, h, app_id, "isim-a", [_node("a", "job-a")], [])
    r2 = _create_flow(client, h, app_id, "isim-b", [_node("a", "job-a")], [])
    flow2_id = r2.json()["id"]

    upd = client.put(f"/api/deployments/flows/{flow2_id}", headers=h, json={"name": "isim-a"})
    assert upd.status_code == 409, upd.text


def test_flow_delete_preserves_run_history(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-a": "SUCCESS"})
    tid = _sy_team(client, h, "SY-Dep-DeleteHist")
    app_id = _app(client, h, "DepApp-DeleteHist", tid)
    r = _create_flow(client, h, app_id, "silinecek-akis", [_node("a", "job-a")], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    delete = client.delete(f"/api/deployments/flows/{flow_id}", headers=h)
    assert delete.status_code == 200, delete.text

    run2 = client.get(f"/api/deployments/runs/{run['id']}", headers=h).json()
    assert run2["flow_id"] is None                        # SET NULL
    assert run2["flow_name_snapshot"] == "silinecek-akis"  # donmuş kopya korunuyor
    assert _steps_by_node(run2)["a"]["jenkins_job"] == "job-a"


def test_dag_validation_rejects_empty_and_dangling_edges(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Dep-Validate")
    app_id = _app(client, h, "DepApp-Validate", tid)

    empty = _create_flow(client, h, app_id, "bos-akis", [], [])
    assert empty.status_code == 400, empty.text

    dangling = _create_flow(client, h, app_id, "sarkik-akis",
                            [_node("a", "job-a")], [_edge("a", "yok-boyle-bir-dugum")])
    assert dangling.status_code == 400, dangling.text


def test_list_runs_search_matches_flow_name_job_and_param_value(client, auth_headers, monkeypatch):
    h = auth_headers
    _install_jenkins_fake(monkeypatch, {"job-search-a": "SUCCESS"})
    tid = _sy_team(client, h, "SY-Dep-Search")
    app_id = _app(client, h, "DepApp-Search", tid)
    r = _create_flow(client, h, app_id, "arama-akisi",
                     [_node("a", "job-search-a", params=[{"key": "CERTKEY", "value": "jumbo.local_search123"}])], [])
    flow_id = r.json()["id"]
    run = client.post(f"/api/deployments/flows/{flow_id}/run", headers=h).json()

    by_flow_name = client.get("/api/deployments/runs", headers=h, params={"q": "arama-akisi"}).json()
    assert any(x["id"] == run["id"] for x in by_flow_name)

    by_param_value = client.get("/api/deployments/runs", headers=h, params={"q": "jumbo.local_search123"}).json()
    assert any(x["id"] == run["id"] for x in by_param_value)

    by_job = client.get("/api/deployments/runs", headers=h, params={"q": "job-search-a"}).json()
    assert any(x["id"] == run["id"] for x in by_job)

    no_match = client.get("/api/deployments/runs", headers=h, params={"q": "boyle-bir-sey-yok"}).json()
    assert all(x["id"] != run["id"] for x in no_match)


def test_jenkins_console_url_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr(JenkinsClient, "is_available", lambda self: True)
    monkeypatch.setattr(JenkinsClient, "_base", lambda self: "http://fake-jenkins")
    r = client.get("/api/jenkins/job/Certificate-deployment/ns-cert-deploy/console-url",
                   headers=auth_headers, params={"build": 5})
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "http://fake-jenkins/job/Certificate-deployment/job/ns-cert-deploy/5/console"

    monkeypatch.setattr(JenkinsClient, "is_available", lambda self: False)
    r2 = client.get("/api/jenkins/job/job-a/console-url", headers=auth_headers, params={"build": 5})
    assert r2.status_code == 404
