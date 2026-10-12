import os
from pathlib import Path

TEST_DB = Path("test_ontology.db")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_rest_blocks_invalid_relation():
    with TestClient(app) as client:
        feature = client.get("/api/instances?class=Feature").json()[0]
        spec = client.post(
            "/api/workflows/spec-from-feature",
            json={"feature_id": feature["id"]},
        ).json()["spec"]

        target = client.post(
            "/api/instances",
            json={"class_id": spec["class_id"], "title": "Bogus", "status": "draft", "properties": {"goal": "x"}},
        ).json()

        bad_relation = client.post(
            "/api/relations",
            json={"source_id": feature["id"], "target_id": target["id"], "type": "HAS_TASK", "properties": {}},
        )
        assert bad_relation.status_code == 422
        assert "本体关系校验失败" in bad_relation.text


def test_rest_blocks_unknown_field():
    with TestClient(app) as client:
        classes = {item["name"]: item["id"] for item in client.get("/api/classes").json()}
        bad_payload = {
            "class_id": classes["Feature"],
            "title": "演示",
            "status": "idea",
            "properties": {"priority": "ultra"},
        }
        response = client.post("/api/instances", json=bad_payload)
        assert response.status_code == 422
        assert "本体实例校验失败" in response.text


def test_health_and_seed_data():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        classes = client.get("/api/classes")
        assert classes.status_code == 200
        names = {item["name"] for item in classes.json()}
        assert {"Project", "Feature", "Spec", "Plan", "Task"}.issubset(names)

        features = client.get("/api/instances?class=Feature")
        assert features.status_code == 200
        assert any("Neo4j" in item["title"] for item in features.json())


def test_feature_to_devops_workflow():
    with TestClient(app) as client:
        feature = client.get("/api/instances?class=Feature").json()[0]

        spec_result = client.post(
            "/api/workflows/spec-from-feature",
            json={"feature_id": feature["id"]},
        )
        assert spec_result.status_code == 200
        spec = spec_result.json()["spec"]
        assert spec["class_name"] == "Spec"

        plan_result = client.post(
            "/api/workflows/plan-from-spec",
            json={"spec_id": spec["id"]},
        )
        assert plan_result.status_code == 200
        plan = plan_result.json()["plan"]
        assert plan["class_name"] == "Plan"

        tasks_result = client.post(
            "/api/workflows/tasks-from-plan",
            json={"plan_id": plan["id"]},
        )
        assert tasks_result.status_code == 200
        assert len(tasks_result.json()["tasks"]) >= 5

        checklist_result = client.post(
            "/api/workflows/run-checklist",
            json={"root_id": feature["id"]},
        )
        assert checklist_result.status_code == 200
        assert checklist_result.json()["checklist"]["status"] == "passed"

        jenkins_result = client.post(
            "/api/integrations/jenkins/trigger",
            json={"feature_id": feature["id"], "environment": "staging"},
        )
        assert jenkins_result.status_code == 200
        assert jenkins_result.json()["job"]["class_name"] == "JenkinsJob"

        logs_result = client.post(
            "/api/integrations/logs/search",
            json={"service": "ontology-core-service"},
        )
        assert logs_result.status_code == 200
        assert len(logs_result.json()["logs"]) >= 1

        graph = client.get(f"/api/graph?root_id={feature['id']}")
        assert graph.status_code == 200
        assert len(graph.json()["nodes"]) >= 4
