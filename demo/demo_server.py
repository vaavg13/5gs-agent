"""Local demo dashboard for the network slicing experiment.

The server launches the existing Inspect task, discovers the generated Docker
Compose project, and streams live UE collector metrics plus runner/log state to
the browser.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import os
import re
import signal
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from aiohttp import web

from intent_network_slicing.intents import (
    resolve_ue_service,
    target_ue_service,
    validate_intent,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATASET_PATH = ROOT / "intent_network_slicing" / "dataset.yaml"
COMPOSE_PATH = (
    ROOT
    / "intent_network_slicing"
    / "scenarios"
    / "three_slice_service_classes"
    / "compose.yaml"
)
TASK_REF = "intent_network_slicing/network_slicing.py@three_slice_service_classes"
LOG_ROOT = ROOT / "logs" / "demo"
METRICS_CSV_PATH = "/tmp/metrics.csv"
UE_SERVICES = ("ue_premium", "ue_control", "ue_background")
DEFAULT_MODEL = "openai/gpt-5.4"
DEFAULT_SAMPLE_ID = "three_slice_premium_service_demoted"
RUNNER_LINE_LIMIT = 240
TIMELINE_LIMIT = 160


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chart_metric_name(intent_metric: str) -> str | None:
    if intent_metric in {"uplink_throughput_mbps", "downlink_throughput_mbps"}:
        return "throughput_mbps"
    if intent_metric == "max_latency_ms":
        return "latency_ms"
    if intent_metric == "max_jitter_ms":
        return "jitter_ms"
    if intent_metric == "max_packet_loss_pct":
        return "packet_loss_pct"
    return None


def merge_threshold(
    thresholds: dict[str, dict[str, Any]],
    chart_metric: str,
    objective: dict[str, Any],
    section: str,
) -> None:
    value = float(objective["value"])
    existing = thresholds.get(chart_metric)
    if existing:
        if chart_metric == "throughput_mbps":
            # The live collector exports one throughput stream, so mirror the
            # scorer by showing the achievable side of bidirectional intent.
            existing["value"] = min(float(existing["value"]), value)
        elif objective["op"] == "<=":
            existing["value"] = min(float(existing["value"]), value)
        else:
            existing["value"] = max(float(existing["value"]), value)
        existing["source_metrics"].append(objective["metric"])
        return

    thresholds[chart_metric] = {
        "metric": chart_metric,
        "op": objective["op"],
        "value": value,
        "objective": section,
        "source_metrics": [objective["metric"]],
    }


def sample_thresholds(record: dict[str, Any]) -> dict[str, Any]:
    intent = record.get("intent")
    if not intent:
        return {"target_service": "ue_premium", "by_service": {}}

    normalized = validate_intent(intent)
    by_service: dict[str, dict[str, Any]] = {}
    target_service = target_ue_service(normalized)

    for section in ("hard", "soft"):
        for objective in normalized["objectives"][section]:
            metric = str(objective["metric"])
            if "." in metric:
                ue_id, metric_name = metric.split(".", 1)
            else:
                ue_id, metric_name = None, metric
            chart_metric = chart_metric_name(metric_name or metric)
            if not chart_metric:
                continue
            service = resolve_ue_service(normalized, ue_id) if ue_id else target_service
            service_thresholds = by_service.setdefault(service, {})
            merge_threshold(service_thresholds, chart_metric, objective, section)

    return {"target_service": target_service, "by_service": by_service}


def load_samples() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    samples = []
    for record in data.get("samples", []):
        sample_id = str(record.get("id", "")).strip()
        if not sample_id:
            continue
        samples.append(
            {
                "id": sample_id,
                "label": sample_id.replace("three_slice_", "").replace("_", " "),
                "difficulty": str(record.get("metadata", {}).get("difficulty", "")),
                "target": str(record.get("target", "")),
                "intent_thresholds": sample_thresholds(record),
            }
        )
    return samples


SAMPLES = load_samples()
SAMPLE_IDS = {sample["id"] for sample in SAMPLES}


def parse_metric_rows(raw_csv: str) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    reader = csv.DictReader(raw_csv.splitlines())
    for row in reader:
        try:
            rows.append(
                {
                    "timestamp": row["timestamp"],
                    "throughput_mbps": float(row["throughput_mbps"]),
                    "latency_ms": float(row["latency_ms"]),
                    "jitter_ms": float(row["jitter_ms"]),
                    "packet_loss_pct": float(row["packet_loss_pct"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def summarize_rows(rows: list[dict[str, float | str]]) -> dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "rows": [],
            "latest": None,
            "window": None,
            "averages": {},
        }

    window = rows[-30:]

    def avg(key: str) -> float:
        values = [float(row[key]) for row in window]
        return sum(values) / len(values)

    return {
        "available": True,
        "rows": rows[-90:],
        "latest": rows[-1],
        "window": {
            "start": window[0]["timestamp"],
            "end": window[-1]["timestamp"],
            "size": len(window),
        },
        "averages": {
            "throughput_mbps": avg("throughput_mbps"),
            "latency_ms": avg("latency_ms"),
            "jitter_ms": avg("jitter_ms"),
            "packet_loss_pct": avg("packet_loss_pct"),
        },
    }


def event_key(event: dict[str, Any]) -> str:
    return json.dumps(
        [
            event.get("kind"),
            event.get("title"),
            event.get("body"),
        ],
        sort_keys=True,
    )


@dataclass
class RunState:
    id: str
    sample_id: str
    model: str
    status: str = "starting"
    phase: str = "launching"
    started_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    returncode: int | None = None
    project_name: str | None = None
    log_dir: Path = field(default_factory=Path)
    log_path: str | None = None
    command: list[str] = field(default_factory=list)
    stdout_lines: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    seen_timeline_keys: set[str] = field(default_factory=set)
    metrics: dict[str, Any] = field(
        default_factory=lambda: {svc: summarize_rows([]) for svc in UE_SERVICES}
    )
    score: dict[str, Any] | None = None
    error: str | None = None
    process: asyncio.subprocess.Process | None = None
    before_projects: set[str] = field(default_factory=set)

    def add_runner_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self.stdout_lines.append(line)
        self.stdout_lines = self.stdout_lines[-RUNNER_LINE_LIMIT:]
        lower = line.lower()
        if "starting open5gs stack" in lower:
            self.phase = "starting 5g stack"
        elif "waiting" in lower and "stabilize" in lower:
            self.phase = "stabilizing 5g core"
        elif "started iperf3+ping collector" in lower:
            self.phase = "collecting live metrics"
        elif "score" in lower or "scorer" in lower:
            self.phase = "scoring"
        self.add_timeline("runner", "Runner", line)

    def add_timeline(self, kind: str, title: str, body: str) -> None:
        body = body.strip()
        if not body:
            return
        event = {
            "timestamp": utc_now(),
            "kind": kind,
            "title": title,
            "body": body[:2400],
        }
        key = event_key(event)
        # Runner lines include timestamp in the key, so dedupe only parsed logs.
        if kind != "runner" and key in self.seen_timeline_keys:
            return
        if kind != "runner":
            self.seen_timeline_keys.add(key)
        self.timeline.append(event)
        self.timeline = self.timeline[-TIMELINE_LIMIT:]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sample_id": self.sample_id,
            "model": self.model,
            "status": self.status,
            "phase": self.phase,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "returncode": self.returncode,
            "project_name": self.project_name,
            "log_path": self.log_path,
            "command": self.command,
            "stdout_lines": self.stdout_lines,
            "timeline": self.timeline,
            "metrics": self.metrics,
            "score": self.score,
            "error": self.error,
        }


RUNS: dict[str, RunState] = {}


async def run_command(
    args: list[str], timeout: float = 8.0, cwd: Path = ROOT
) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return 124, "", "command timed out"
    except FileNotFoundError as exc:
        return 127, "", str(exc)


async def list_compose_projects() -> set[str]:
    code, stdout, _ = await run_command(
        ["docker", "compose", "ls", "--all", "--format", "json"], timeout=8
    )
    if code != 0 or not stdout.strip():
        return set()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return set()
    return {
        str(item.get("Name", ""))
        for item in payload
        if str(item.get("Name", "")).startswith("inspect-")
    }


async def discover_project(run: RunState) -> None:
    for _ in range(90):
        if run.status in {"complete", "failed", "stopped"}:
            return
        projects = await list_compose_projects()
        new_projects = sorted(projects - run.before_projects)
        if new_projects:
            run.project_name = new_projects[-1]
            run.phase = "polling live containers"
            run.add_timeline("system", "Docker Project", run.project_name)
            return
        inspect_projects = sorted(projects)
        if len(inspect_projects) == 1 and not run.project_name:
            run.project_name = inspect_projects[0]
            run.phase = "polling live containers"
            run.add_timeline("system", "Docker Project", run.project_name)
            return
        await asyncio.sleep(2)


async def read_ue_metrics(project_name: str, service: str) -> list[dict[str, float | str]]:
    code, stdout, _ = await run_command(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "-f",
            str(COMPOSE_PATH),
            "exec",
            "-T",
            service,
            "tail",
            "-n",
            "120",
            METRICS_CSV_PATH,
        ],
        timeout=5,
    )
    if code != 0:
        return []
    return parse_metric_rows(stdout)


async def poll_metrics(run: RunState) -> None:
    while run.status in {"starting", "running"}:
        if not run.project_name:
            await asyncio.sleep(1)
            continue
        for service in UE_SERVICES:
            rows = await read_ue_metrics(run.project_name, service)
            if rows:
                run.metrics[service] = summarize_rows(rows)
                if run.phase in {"launching", "polling live containers"}:
                    run.phase = "live metrics flowing"
        await asyncio.sleep(1)


def compact_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def normalize_sample_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict) and "messages" in payload:
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        # Some Inspect JSON sample files are a one-item array.
        first = payload[0]
        if "messages" in first:
            return first
    return None


def ingest_sample_log(run: RunState, sample: dict[str, Any]) -> None:
    for message in sample.get("messages", []):
        role = message.get("role")
        if role == "assistant":
            text = compact_text(message.get("content"))
            if text:
                run.add_timeline("agent", "Agent", text)
            for call in message.get("tool_calls", []) or []:
                name = call.get("function", "tool")
                args = call.get("arguments", {})
                run.add_timeline("tool-call", str(name), json.dumps(args, indent=2)[:1200])
        elif role == "tool":
            name = str(message.get("function", "tool result"))
            text = compact_text(message.get("content"))
            run.add_timeline("tool-result", name, text[:1200])

    store = sample.get("store") or {}
    actions = store.get("ActionJournal:actions") or []
    for action in actions:
        title = f"{action.get('tool_name', 'action')} -> {action.get('target', '')}"
        body = json.dumps(action, indent=2, sort_keys=True)
        run.add_timeline("action", title, body)

    scores = sample.get("scores") or {}
    if scores:
        scorer = scores.get("sla_compliance_scorer") or next(iter(scores.values()))
        run.score = scorer


def ingest_eval_log(run: RunState, payload: dict[str, Any]) -> None:
    if payload.get("status"):
        run.add_timeline("system", "Inspect Log", f"status: {payload.get('status')}")
    reductions = payload.get("reductions") or []
    if reductions:
        samples = reductions[0].get("samples", [])
        if samples:
            run.score = samples[0]


def parse_json_log_file(run: RunState, path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    run.log_path = str(path)
    sample = normalize_sample_payload(payload)
    if sample:
        ingest_sample_log(run, sample)
    elif isinstance(payload, dict):
        ingest_eval_log(run, payload)
    return True


def parse_logs(run: RunState) -> None:
    if not run.log_dir.exists():
        return
    for path in sorted(run.log_dir.rglob("*.json")):
        parse_json_log_file(run, path)


async def poll_logs(run: RunState) -> None:
    while run.status in {"starting", "running"}:
        parse_logs(run)
        await asyncio.sleep(2)


async def read_stdout(run: RunState) -> None:
    assert run.process is not None
    assert run.process.stdout is not None
    while True:
        line_b = await run.process.stdout.readline()
        if not line_b:
            break
        run.add_runner_line(line_b.decode("utf-8", errors="replace"))


async def read_stderr(run: RunState) -> None:
    assert run.process is not None
    assert run.process.stderr is not None
    while True:
        line_b = await run.process.stderr.readline()
        if not line_b:
            break
        line = line_b.decode("utf-8", errors="replace").rstrip()
        if line:
            run.add_runner_line(line)


async def wait_process(run: RunState) -> None:
    assert run.process is not None
    run.status = "running"
    run.phase = "inspect eval running"
    code = await run.process.wait()
    run.returncode = code
    run.completed_at = utc_now()
    parse_logs(run)
    if code == 0:
        run.status = "complete"
        run.phase = "complete"
    elif run.status == "stopped":
        run.phase = "stopped"
    else:
        run.status = "failed"
        run.phase = "failed"
        run.error = f"inspect eval exited with code {code}"


def validate_start_payload(payload: dict[str, Any]) -> tuple[str, str]:
    sample_id = str(payload.get("sample_id") or DEFAULT_SAMPLE_ID)
    model = str(payload.get("model") or DEFAULT_MODEL)
    if sample_id not in SAMPLE_IDS:
        raise web.HTTPBadRequest(text=f"Unknown sample_id: {sample_id}")
    if not re.fullmatch(r"[A-Za-z0-9_./:@+-]+", model):
        raise web.HTTPBadRequest(text="Model contains unsupported characters")
    return sample_id, model


async def start_run(request: web.Request) -> web.Response:
    payload = await request.json()
    sample_id, model = validate_start_payload(payload)

    run_id = uuid.uuid4().hex[:10]
    log_dir = LOG_ROOT / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    run = RunState(
        id=run_id,
        sample_id=sample_id,
        model=model,
        log_dir=log_dir,
        before_projects=await list_compose_projects(),
    )
    cmd = [
        sys.executable,
        "-m",
        "inspect_ai",
        "eval",
        TASK_REF,
        "--model",
        model,
        "--sample-id",
        sample_id,
        "--max-sandboxes",
        "1",
        "--log-format",
        "json",
        "--log-dir",
        str(log_dir),
        "--display",
        "plain",
        "--log-level",
        "info",
    ]
    run.command = cmd
    RUNS[run_id] = run
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        run.process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as exc:
        run.status = "failed"
        run.phase = "failed"
        run.error = str(exc)
        return web.json_response(run.public(), status=500)

    run.add_timeline("system", "Run Started", f"{sample_id} on {model}")
    asyncio.create_task(read_stdout(run))
    asyncio.create_task(read_stderr(run))
    asyncio.create_task(discover_project(run))
    asyncio.create_task(poll_metrics(run))
    asyncio.create_task(poll_logs(run))
    asyncio.create_task(wait_process(run))
    return web.json_response(run.public())


async def stop_run(request: web.Request) -> web.Response:
    run = RUNS.get(request.match_info["run_id"])
    if not run:
        raise web.HTTPNotFound(text="Run not found")
    run.status = "stopped"
    run.phase = "stopping"
    if run.process and run.process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(run.process.pid, signal.SIGTERM)
    if run.project_name:
        asyncio.create_task(
            run_command(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    run.project_name,
                    "-f",
                    str(COMPOSE_PATH),
                    "down",
                    "--volumes",
                ],
                timeout=60,
            )
        )
    return web.json_response(run.public())


async def list_runs(_: web.Request) -> web.Response:
    return web.json_response([run.public() for run in RUNS.values()])


async def get_run(request: web.Request) -> web.Response:
    run = RUNS.get(request.match_info["run_id"])
    if not run:
        raise web.HTTPNotFound(text="Run not found")
    parse_logs(run)
    return web.json_response(run.public())


async def stream_run(request: web.Request) -> web.StreamResponse:
    run = RUNS.get(request.match_info["run_id"])
    if not run:
        raise web.HTTPNotFound(text="Run not found")

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)
    try:
        while True:
            payload = json.dumps(run.public())
            await response.write(f"data: {payload}\n\n".encode("utf-8"))
            if run.status in {"complete", "failed", "stopped"}:
                break
            await asyncio.sleep(1)
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    return response


async def config(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "samples": SAMPLES,
            "default_model": DEFAULT_MODEL,
            "default_sample_id": DEFAULT_SAMPLE_ID,
            "ue_services": UE_SERVICES,
        }
    )


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/config", config)
    app.router.add_get("/api/runs", list_runs)
    app.router.add_post("/api/runs", start_run)
    app.router.add_get("/api/runs/{run_id}", get_run)
    app.router.add_get("/api/runs/{run_id}/events", stream_run)
    app.router.add_post("/api/runs/{run_id}/stop", stop_run)
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    return app


def main() -> None:
    port = int(os.environ.get("DEMO_PORT", "8787"))
    web.run_app(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
