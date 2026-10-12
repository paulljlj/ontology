"""Feishu (Lark) API client with mock fallback.

Encapsulates four capabilities exposed as MCP tools:
  - send_message(open_id, content)
  - create_approval(approval_code, user_id, form)
  - get_approval_status(instance_code)
  - approve_task(instance_code, result, comment)

When `lark_oapi` is missing OR credentials are empty, every call transparently
falls back to an in-memory mock so the rest of the platform (MCP tools, WebSocket
listener, ontology writeback) keeps working without network. Each response carries
a `via` field (`feishu_api` or `mock`) so callers can tell which path ran.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.infrastructure.config import settings


# Module-level try/except so the entire app stays importable without lark_oapi.
try:
    from lark_oapi import Client
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    from lark_oapi.api.approval.v4 import (
        ApproveTaskRequestBuilder,
        CreateInstanceRequestBuilder,
        GetInstanceRequestBuilder,
        InstanceCreateBuilder,
        TaskApproveBuilder,
    )

    LARK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without optional dep
    LARK_AVAILABLE = False
    Client = None  # type: ignore[assignment]


_client: Any | None = None
_mock_state: dict[str, list[dict[str, Any]]] = {}
_mock_approvals: dict[str, dict[str, Any]] = {}


def _get_client() -> Any | None:
    """Lazy singleton for the real lark Client. None when credentials missing."""
    global _client
    if _client is not None:
        return _client
    if not LARK_AVAILABLE or not settings.feishu_enabled:
        return None
    _client = Client.builder() \
        .app_id(settings.feishu_app_id) \
        .app_secret(settings.feishu_app_secret) \
        .build()
    return _client


def reset_client() -> None:
    """Test hook: drop the cached client so credential changes take effect."""
    global _client
    _client = None


def send_message(chat_id: str, content: str) -> dict[str, Any]:
    """Send a text message to a Feishu user (by open_id) or chat.

    Returns ``{status, message_id?, via}``. ``via`` is "feishu_api" or "mock".
    """
    client = _get_client()
    if client is not None:
        try:
            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("text") \
                .content(json.dumps({"text": content}, ensure_ascii=False)) \
                .build()
            request = CreateMessageRequest.builder() \
                .receive_id_type("open_id") \
                .request_body(body) \
                .build()
            response = client.im.v1.message.create(request)
            if response.success():
                return {
                    "status": "ok",
                    "message_id": getattr(response.data, "message_id", "") or "",
                    "via": "feishu_api",
                }
            return {
                "status": "error",
                "detail": f"飞书 API 错误: {getattr(response, 'msg', '')}",
                "via": "feishu_api",
            }
        except Exception as exc:  # network or auth issue → fall through to mock
            print(f"[Feishu] send_message 降级 mock: {exc}")

    # mock 降级
    _mock_state.setdefault(chat_id, []).append({"content": content})
    return {
        "status": "ok",
        "message_id": f"mock_msg_{uuid.uuid4().hex[:8]}",
        "via": "mock",
    }


def create_approval(
    approval_code: str,
    user_id: str,
    form: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a Feishu approval instance.

    `form` is a list of ``{id, type, value}`` dicts that matches the approval
    template's widget layout. The caller is responsible for matching the widget
    IDs defined on the Feishu admin console.
    """
    client = _get_client()
    form_json = json.dumps(form, ensure_ascii=False)
    if client is not None and approval_code:
        try:
            instance = InstanceCreateBuilder() \
                .approval_code(approval_code) \
                .open_id(user_id) \
                .form(form_json) \
                .build()
            request = CreateInstanceRequestBuilder().request_body(instance).build()
            response = client.approval.v4.instance.create(request)
            if response.success():
                return {
                    "status": "ok",
                    "instance_code": getattr(response.data, "instance_code", "") or "",
                    "via": "feishu_api",
                }
            return {
                "status": "error",
                "detail": f"飞书审批 API 错误: {getattr(response, 'msg', '')}",
                "via": "feishu_api",
            }
        except Exception as exc:
            print(f"[Feishu] create_approval 降级 mock: {exc}")

    # mock 降级
    instance_code = f"mock_inst_{uuid.uuid4().hex[:10]}"
    _mock_approvals[instance_code] = {
        "approval_code": approval_code,
        "user_id": user_id,
        "form": form,
        "status": "PENDING",
    }
    return {
        "status": "ok",
        "instance_code": instance_code,
        "via": "mock",
    }


def get_approval_status(instance_code: str) -> dict[str, Any]:
    """Query the current status of a Feishu approval instance.

    Useful as a polling fallback when WebSocket events aren't connected.
    Returns ``{status, instance_code, raw_status, via}`` where ``status`` is
    normalised to "PENDING" / "APPROVED" / "REJECTED".
    """
    client = _get_client()
    if client is not None:
        try:
            request = GetInstanceRequestBuilder().instance_id(instance_code).build()
            response = client.approval.v4.instance.get(request)
            if response.success() and response.data:
                raw_status = getattr(response.data, "status", "PENDING") or "PENDING"
                return {
                    "status": _normalise_status(raw_status),
                    "instance_code": instance_code,
                    "raw_status": raw_status,
                    "via": "feishu_api",
                }
        except Exception as exc:
            print(f"[Feishu] get_approval_status 降级 mock: {exc}")

    # mock 降级
    record = _mock_approvals.get(instance_code)
    if record is None:
        return {
            "status": "UNKNOWN",
            "instance_code": instance_code,
            "raw_status": "UNKNOWN",
            "via": "mock",
        }
    return {
        "status": _normalise_status(record["status"]),
        "instance_code": instance_code,
        "raw_status": record["status"],
        "via": "mock",
    }


def approve_task(
    instance_code: str,
    result: str,
    comment: str = "",
) -> dict[str, Any]:
    """Programmatically approve/reject a Feishu approval task.

    Mostly used by web-side admin tools; the canonical user-driven path is the
    Feishu mobile app, which fires the WebSocket event we listen to.
    """
    client = _get_client()
    if client is not None:
        try:
            # Step 1: 拿到 instance 信息以取 task_id
            get_req = GetInstanceRequestBuilder().instance_id(instance_code).build()
            get_resp = client.approval.v4.instance.get(get_req)
            if not get_resp.success():
                return {
                    "status": "error",
                    "detail": f"获取实例失败: {get_resp.msg}",
                    "via": "feishu_api",
                }
            instance_data = get_resp.data
            task_id = None
            task_list = getattr(instance_data, "task_list", None) or []
            for task in task_list:
                if getattr(task, "status", "") == "PENDING":
                    task_id = getattr(task, "id", None)
                    break
            if not task_id:
                return {
                    "status": "ok",
                    "instance_code": instance_code,
                    "result": result,
                    "message": "无待处理任务，跳过同步",
                    "via": "feishu_api",
                }

            # Step 2: 触发审批
            task_body = TaskApproveBuilder() \
                .approval_code(getattr(instance_data, "approval_code", "") or "") \
                .instance_id(instance_code) \
                .task_id(task_id) \
                .comment(comment or f"web 端审批: {result}") \
                .build()
            approve_req = ApproveTaskRequestBuilder() \
                .request_body(task_body) \
                .user_id_type("open_id") \
                .build()
            resp = client.approval.v4.instance.approve_task(approve_req)
            if resp.success():
                return {
                    "status": "ok",
                    "instance_code": instance_code,
                    "result": result,
                    "via": "feishu_api",
                }
            return {
                "status": "error",
                "detail": f"飞书审批 API 错误: {resp.msg}",
                "via": "feishu_api",
            }
        except Exception as exc:
            print(f"[Feishu] approve_task 降级 mock: {exc}")

    # mock 降级
    record = _mock_approvals.get(instance_code)
    if record is not None:
        record["status"] = result.upper()
    return {
        "status": "ok",
        "instance_code": instance_code,
        "result": result,
        "via": "mock",
    }


def build_spec_approval_form(
    spec_title: str,
    spec_goal: str,
    spec_version: str = "",
    spec_background: str = "",
) -> list[dict[str, Any]]:
    """Build the approval-form widget list for a Spec approval.

    Matches the widget IDs configured on the Feishu approval template; tweak
    `settings.feishu_form_title_id` / `feishu_form_content_id` to fit your
    console setup.
    """
    content_lines = [
        f"目标 (goal): {spec_goal}",
    ]
    if spec_version:
        content_lines.append(f"版本 (version): {spec_version}")
    if spec_background:
        content_lines.append(f"背景 (background): {spec_background}")
    return [
        {"id": settings.feishu_form_title_id, "type": "input", "value": f"Spec 评审: {spec_title}"},
        {
            "id": settings.feishu_form_content_id,
            "type": "textarea",
            "value": "\n".join(content_lines),
        },
    ]


def get_mock_state() -> dict[str, list[dict[str, Any]]]:
    """Test/debug hook: inspect the in-memory mock inbox."""
    return dict(_mock_state)


def get_mock_approvals() -> dict[str, dict[str, Any]]:
    """Test/debug hook: inspect the in-memory mock approval ledger."""
    return dict(_mock_approvals)


def _normalise_status(raw: str) -> str:
    raw_upper = (raw or "").upper()
    if raw_upper in ("APPROVED", "PASSED"):
        return "APPROVED"
    if raw_upper in ("REJECTED", "REFUSED", "CANCELED", "CANCELLED"):
        return "REJECTED"
    return "PENDING"
