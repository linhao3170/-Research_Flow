"""ResearchFlow minimal workbench (T0 WP-13) — read-only four views.

The workbench talks to the running REST API only: it never opens the database,
never writes state/evidence and never re-implements a verdict.  When the API is
unreachable it shows the error instead of fabricating data.

Run it with::

    streamlit run researchflow/workbench/app.py

Environment: ``RESEARCHFLOW_API_URL`` (default ``http://127.0.0.1:8000``) and an
optional ``RESEARCHFLOW_TASK_ID`` for the initial selection.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import streamlit as st

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT = float(os.environ.get("RESEARCHFLOW_API_TIMEOUT", "10.0"))


class WorkbenchAPIError(RuntimeError):
    def __init__(self, path: str, status: int, detail: str) -> None:
        self.path = path
        self.status = status
        self.detail = detail
        super().__init__(f"{path} -> HTTP {status}: {detail}")


def api_get(base_url: str, path: str, timeout: float | None = None) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(url, method="GET")
    effective_timeout = DEFAULT_API_TIMEOUT if timeout is None else timeout
    try:
        with urllib.request.urlopen(request, timeout=effective_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best effort detail
            body = ""
        raise WorkbenchAPIError(path, exc.code, body or exc.reason) from exc
    except urllib.error.URLError as exc:
        raise WorkbenchAPIError(path, 0, f"无法连接 API：{exc.reason}") from exc
    except OSError as exc:
        # ``urlopen`` can surface a bare socket timeout instead of URLError when
        # a loopback connection is silently dropped; it is still "unreachable".
        raise WorkbenchAPIError(path, 0, f"无法连接 API：{exc}") from exc


def render_task(task: dict[str, Any]) -> None:
    st.subheader("任务")
    st.write(f"task_id: `{task.get('task_id')}`")
    columns = st.columns(3)
    columns[0].metric("Task 状态", str(task.get("state")))
    columns[1].metric("图版本", str(task.get("graph_version")))
    spec = task.get("spec") or {}
    columns[2].metric("模板", str(spec.get("template_id")))
    st.caption("TaskSpec（只读，来自 API）")
    st.json(spec)


def render_graph(graph: dict[str, Any]) -> None:
    st.subheader("DAG")
    st.write(f"graph_version: `{graph.get('graph_version')}`")
    st.code(str(graph.get("graph_hash")), language=None)
    st.caption("确定性拓扑序：" + " → ".join(graph.get("topology_order", [])))
    rows = [
        {
            "node_id": node["node_id"],
            "node_type": node["node_type"],
            "state": node["state"],
            "attempt_seq": node["attempt_seq"],
            "depends_on": ", ".join(node["depends_on"]),
            "required_checks": ", ".join(node["required_checks"]),
        }
        for node in graph.get("nodes", [])
    ]
    st.dataframe(rows, use_container_width=True)


def render_evidence(evidence: dict[str, Any]) -> None:
    st.subheader("证据")
    chain = evidence.get("chain", {})
    columns = st.columns(3)
    columns[0].metric("证据条数", str(evidence.get("count")))
    columns[1].metric("链校验", "OK" if chain.get("ok") else "BROKEN")
    columns[2].metric("已失效证据", str(len(evidence.get("invalidated_evidence_ids", []))))
    if not chain.get("ok"):
        st.error("证据链校验失败：" + json.dumps(chain.get("issues", []), ensure_ascii=False))
    rows = [
        {
            "event_seq": item["event_seq"],
            "level": item["level"],
            "kind": item["kind"],
            "node_id": item["node_id"],
            "attempt_id": item["attempt_id"],
            "timestamp": item["timestamp"],
            "invalidated": "STALE" if item["invalidated"] else "",
        }
        for item in evidence.get("items", [])
    ]
    st.dataframe(rows, use_container_width=True)


def render_report(
    base_url: str, task_id: str, task: dict[str, Any]
) -> None:
    st.subheader("报告与凭证")
    if task.get("state") not in {"VERIFYING", "COMPLETED", "FAILED", "BLOCKED"}:
        st.info("任务尚未进入验证阶段，暂无报告。")
        return
    try:
        report_body = api_get(base_url, f"/api/v1/tasks/{task_id}/report")
    except WorkbenchAPIError as exc:
        st.info(f"报告尚不可用：HTTP {exc.status}")
        return
    report = report_body.get("report", {})
    columns = st.columns(3)
    columns[0].metric("报告状态", str(report.get("final_state")))
    coverage = report.get("required_check_coverage", {})
    columns[1].metric("必检通过", f"{coverage.get('passed')}/{coverage.get('required')}")
    columns[2].metric("L3 覆盖", str(report.get("l3_coverage")))
    gaps = report_body.get("gaps") or []
    if gaps:
        st.warning("存在缺口")
        st.dataframe(gaps, use_container_width=True)
    st.caption("签名内容（只读）")
    st.json(report)
    try:
        certificate = api_get(base_url, f"/api/v1/tasks/{task_id}/certificate")
    except WorkbenchAPIError as exc:
        st.info(f"凭证不可用：HTTP {exc.status}（仅 VERIFIED 任务签发凭证）")
        return
    st.success("CompletionCertificate")
    st.json(certificate)


def main() -> None:
    st.set_page_config(page_title="ResearchFlow 工作台", layout="wide")
    st.title("ResearchFlow 最小工作台（T0）")
    st.caption("只读：任务 / DAG / 证据 / 报告四视图，全部数据来自 REST API。")
    base_url = os.environ.get("RESEARCHFLOW_API_URL", DEFAULT_API_URL)
    default_task = str(
        st.query_params.get("task_id") or os.environ.get("RESEARCHFLOW_TASK_ID", "")
    )
    requested_view = str(st.query_params.get("view") or "")
    view_labels = {"task": "任务", "dag": "DAG", "evidence": "证据", "report": "报告"}
    task_id = st.sidebar.text_input("Task ID", value=default_task).strip()
    if not task_id:
        st.info("在左侧输入 task_id 以查看真实数据。")
        return
    try:
        task = api_get(base_url, f"/api/v1/tasks/{task_id}")
    except WorkbenchAPIError as exc:
        st.error(f"无法读取任务：{exc}")
        return
    tabs = st.tabs(
        ["任务", "DAG", "证据", "报告"],
        default=view_labels.get(requested_view),
        key="workbench_views",
    )
    with tabs[0]:
        render_task(task)
    with tabs[1]:
        try:
            render_graph(api_get(base_url, f"/api/v1/tasks/{task_id}/graph"))
        except WorkbenchAPIError as exc:
            st.warning(f"DAG 尚不可用：HTTP {exc.status}")
    with tabs[2]:
        try:
            render_evidence(api_get(base_url, f"/api/v1/tasks/{task_id}/evidence?limit=200"))
        except WorkbenchAPIError as exc:
            st.warning(f"证据尚不可用：HTTP {exc.status}")
    with tabs[3]:
        render_report(base_url, task_id, task)


main()