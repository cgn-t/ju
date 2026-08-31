"""JenkinsClient — gerçek Jenkins HTTP yanıt şekline karşı testler.

`job_parameters()` daha önce `actions[parameterDefinitions[...]]` sorguluyordu; bu yalnızca
el yapımı sahte Jenkins sunucularında "çalışıyor" görünüyordu çünkü mock'un yanıt şeklini de
BEN yazmıştım (döngüsel doğrulama). Gerçek bir Jenkins'e (Pipeline/WorkflowJob) karşı test
edilince `actions[]` HER ZAMAN boş çıktı — `ParametersDefinitionProperty` gerçekte `property[]`
altında dönüyor. Bu dosya gerçek Jenkins'ten alınmış yanıt şeklini sabitleyip regresyonu önler.
"""

import httpx

from app.db.session import SessionLocal
from app.services.jenkins_client import JenkinsClient


def _client_with_response(monkeypatch, body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    def fake_client(self):
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fake-jenkins")

    monkeypatch.setattr(JenkinsClient, "_client", fake_client)


# Gerçek bir Jenkins Pipeline job'undan (WorkflowJob) alınmış ham yanıt şekli —
# `GET /job/X/api/json?tree=property[parameterDefinitions[...]]`
REAL_PIPELINE_RESPONSE = {
    "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
    "property": [{
        "_class": "hudson.model.ParametersDefinitionProperty",
        "parameterDefinitions": [
            {"_class": "hudson.model.StringParameterDefinition", "name": "CERTKEY", "type": None,
             "defaultParameterValue": {"_class": "hudson.model.StringParameterValue", "value": ""},
             "description": None, "choices": None},
            {"_class": "hudson.model.StringParameterDefinition", "name": "NS_MGMT", "type": None,
             "defaultParameterValue": {"_class": "hudson.model.StringParameterValue",
                                        "value": "jumbo-cpx:9080"},
             "description": None, "choices": None},
        ],
    }],
}


def test_job_parameters_reads_from_property_not_actions(client, monkeypatch):
    db = SessionLocal()
    try:
        _client_with_response(monkeypatch, REAL_PIPELINE_RESPONSE)
        params = JenkinsClient(db).job_parameters("Certificate-deployment/ns-cert-deploy")
    finally:
        db.close()
    assert [p["name"] for p in params] == ["CERTKEY", "NS_MGMT"]
    assert params[0]["default"] == ""
    assert params[1]["default"] == "jumbo-cpx:9080"


def test_job_parameters_empty_when_actions_populated_but_property_missing(client, monkeypatch):
    """actions[] dolu olsa bile (eski/yanlış varsayım) property[] yoksa/boşsa [] dönmeli —
    parametresiz bir job'un gerçek davranışı budur."""
    db = SessionLocal()
    try:
        _client_with_response(monkeypatch, {
            "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
            "actions": [{"parameterDefinitions": [{"name": "SAHTE"}]}],
            "property": [],
        })
        params = JenkinsClient(db).job_parameters("windows-cert-deploy")
    finally:
        db.close()
    assert params == []


def test_job_path_handles_nested_folders():
    assert JenkinsClient._job_path("Certificate-deployment/NetScaler/ns-sub-deploy") == \
        "job/Certificate-deployment/job/NetScaler/job/ns-sub-deploy"
    assert JenkinsClient._job_path("simple-job") == "job/simple-job"
