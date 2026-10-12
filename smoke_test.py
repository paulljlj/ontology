"""快速冒烟测试：跑通完整工作流"""
import json

import httpx

BASE = "http://localhost:8000/api"
client = httpx.Client(timeout=30)


def get_class_id(name: str) -> str:
    classes = client.get(f"{BASE}/classes").json()
    for c in classes:
        if c["name"] == name:
            return c["id"]
    raise ValueError(f"Class {name} not found")


def main():
    feature_class_id = get_class_id("Feature")
    print(f"Feature class id: {feature_class_id}")

    # 创建 Feature
    feature = client.post(
        f"{BASE}/instances",
        json={
            "class_id": feature_class_id,
            "title": f"用户登录功能-{__import__('uuid').uuid4().hex[:6]}",
            "status": "idea",
            "properties": {
                "description": "支持邮箱密码登录，未来要加 OAuth 登录，密码要求至少8位包含大小写",
                "priority": "high",
                "tags": ["auth", "security", "v2.0"],
            },
        },
    ).json()
    print(f"[OK] Feature created: {feature['title']} (id={feature['id'][:8]}...)")
    feature_id = feature["id"]

    # 跑工作流第一步：Spec
    spec_result = client.post(
        f"{BASE}/workflows/spec-from-feature", json={"feature_id": feature_id}
    ).json()
    print(f"[OK] Spec: {spec_result['spec']['title']}")
    print(f"   Stories: {len(spec_result['stories'])}")
    print(f"   Acceptance: {len(spec_result['acceptance'])}")
    if spec_result["stories"]:
        print(f"   First story: {spec_result['stories'][0]['title']}")

    # 跑工作流第二步：Plan
    spec_id = spec_result["spec"]["id"]
    plan_result = client.post(
        f"{BASE}/workflows/plan-from-spec", json={"spec_id": spec_id}
    ).json()
    print(f"\n[OK] Plan: {plan_result['plan']['title']}")
    print(f"   DataModels: {len(plan_result['data_models'])}")
    print(f"   Contracts: {len(plan_result['contracts'])}")
    print(f"   ADRs: {len(plan_result['adrs'])}")
    if plan_result["contracts"]:
        print(f"   First contract: {plan_result['contracts'][0]['title']}")

    # 跑工作流第三步：Tasks
    plan_id = plan_result["plan"]["id"]
    tasks_result = client.post(
        f"{BASE}/workflows/tasks-from-plan", json={"plan_id": plan_id}
    ).json()
    print(f"\n[OK] Tasks: {len(tasks_result['tasks'])}")
    for t in tasks_result["tasks"][:3]:
        layer = t["properties"].get("layer", "—")
        print(f"   - {t['title']} (layer={layer})")

    # 跑工作流第四步：Checklist
    checklist_result = client.post(
        f"{BASE}/workflows/run-checklist", json={"root_id": feature_id}
    ).json()
    checklist_props = checklist_result["checklist"]["properties"]
    print(f"\n[OK] Checklist: passed={len(checklist_props.get('passed', []))}, failed={len(checklist_props.get('failed', []))}")

    # 跑工作流第五步：Jenkins
    jenkins_result = client.post(
        f"{BASE}/integrations/jenkins/trigger", json={"feature_id": feature_id, "environment": "staging"}
    ).json()
    print(f"[OK] Jenkins: {jenkins_result['job']['title']}")

    # 看图谱
    graph = client.get(f"{BASE}/graph?root_id={feature_id}").json()
    print(f"\n[GRAPH] {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    class_counts = {}
    for n in graph["nodes"]:
        class_counts[n["class_name"]] = class_counts.get(n["class_name"], 0) + 1
    for cls, cnt in sorted(class_counts.items()):
        print(f"   {cls}: {cnt}")

    print("\n[DONE] Full workflow OK!")


if __name__ == "__main__":
    main()