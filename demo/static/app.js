const state = {
  config: null,
  currentRun: null,
  source: null,
};

const els = {
  sampleSelect: document.getElementById("sampleSelect"),
  modelInput: document.getElementById("modelInput"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
  runStatus: document.getElementById("runStatus"),
  statusDot: document.getElementById("statusDot"),
  phaseValue: document.getElementById("phaseValue"),
  projectValue: document.getElementById("projectValue"),
  scoreValue: document.getElementById("scoreValue"),
  actionValue: document.getElementById("actionValue"),
  lastMetricUpdate: document.getElementById("lastMetricUpdate"),
  ueCards: document.getElementById("ueCards"),
  timeline: document.getElementById("timeline"),
  timelineCount: document.getElementById("timelineCount"),
  runnerOutput: document.getElementById("runnerOutput"),
  throughputChart: document.getElementById("throughputChart"),
  latencyChart: document.getElementById("latencyChart"),
};

function fmt(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function serviceLabel(service) {
  return service.replace("ue_", "").replace("_", " ");
}

function roleFor(service) {
  if (service === "ue_premium") return "target";
  if (service === "ue_control") return "protected";
  return "background";
}

function scoreText(score) {
  if (!score) return "Pending";
  const value = score.value ?? score.score?.value;
  if (value === undefined || value === null) return score.answer || "Available";
  return `${Math.round(Number(value) * 100)}%`;
}

function countActions(run) {
  return (run.timeline || []).filter((item) => item.kind === "action").length;
}

function sampleForRun(run) {
  const sampleId = run?.sample_id || els.sampleSelect.value || state.config?.default_sample_id;
  return state.config?.samples?.find((sample) => sample.id === sampleId);
}

function compactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function thresholdLabel(threshold) {
  const metricLabels = {
    throughput_mbps: "intent throughput",
    latency_ms: "intent latency",
    jitter_ms: "intent jitter",
    packet_loss_pct: "intent loss",
  };
  const units = {
    throughput_mbps: "Mbps",
    latency_ms: "ms",
    jitter_ms: "ms",
    packet_loss_pct: "%",
  };
  return `${metricLabels[threshold.metric] || threshold.metric} ${threshold.op} ${compactNumber(
    threshold.value,
  )} ${units[threshold.metric] || ""}`.trim();
}

function thresholdLines(sample, service, metrics) {
  const serviceThresholds = sample?.intent_thresholds?.by_service?.[service] || {};
  return metrics
    .map((metric) => serviceThresholds[metric])
    .filter(Boolean)
    .map((threshold) => ({
      ...threshold,
      label: thresholdLabel(threshold),
      color: threshold.objective === "soft" ? "#b5c7d9" : "#ff6b6b",
    }));
}

function updateStatus(run) {
  const status = run?.status || "idle";
  els.runStatus.textContent = status;
  els.statusDot.className = "status-dot";
  if (status === "running" || status === "starting") els.statusDot.classList.add("running");
  if (status === "failed" || status === "stopped") els.statusDot.classList.add("failed");
  els.phaseValue.textContent = run?.phase || "Waiting";
  els.projectValue.textContent = run?.project_name || "Not attached";
  els.scoreValue.textContent = scoreText(run?.score);
  els.actionValue.textContent = String(run ? countActions(run) : 0);
  els.stopButton.disabled = !run || !["starting", "running"].includes(run.status);
  els.startButton.disabled = run && ["starting", "running"].includes(run.status);
}

function renderUeCards(metrics) {
  const services = state.config?.ue_services || ["ue_premium", "ue_control", "ue_background"];
  els.ueCards.innerHTML = "";
  let newest = null;

  for (const service of services) {
    const item = metrics?.[service];
    const latest = item?.latest || {};
    if (latest.timestamp && (!newest || latest.timestamp > newest)) newest = latest.timestamp;

    const card = document.createElement("article");
    card.className = "ue-card";
    card.innerHTML = `
      <header>
        <div>
          <div class="ue-title">${serviceLabel(service)}</div>
          <div class="ue-role">${roleFor(service)}</div>
        </div>
        <div class="ue-role">${item?.available ? item.window.size + " samples" : "waiting"}</div>
      </header>
      <div class="metrics-grid">
        ${metricBox("Throughput", fmt(latest.throughput_mbps), "Mbps")}
        ${metricBox("Latency", fmt(latest.latency_ms, 2), "ms")}
        ${metricBox("Jitter", fmt(latest.jitter_ms, 2), "ms")}
        ${metricBox("Loss", fmt(latest.packet_loss_pct, 2), "%")}
      </div>
    `;
    els.ueCards.appendChild(card);
  }

  els.lastMetricUpdate.textContent = newest ? `latest ${newest}` : "No collector data yet";
}

function metricBox(label, value, unit) {
  return `
    <div class="metric-box">
      <span class="metric-label">${label}</span>
      <span class="metric-value">${value}<span class="metric-unit">${unit}</span></span>
    </div>
  `;
}

function renderTimeline(timeline) {
  const items = timeline || [];
  els.timelineCount.textContent = `${items.length} events`;
  if (!items.length) {
    els.timeline.innerHTML = `<div class="empty">Agent and runner events will appear here after launch.</div>`;
    return;
  }

  els.timeline.innerHTML = "";
  for (const item of items.slice().reverse()) {
    const el = document.createElement("article");
    el.className = "timeline-item";
    el.innerHTML = `
      <div class="timeline-meta">
        <span class="timeline-kind ${item.kind}">${item.kind}</span>
        <span>${new Date(item.timestamp).toLocaleTimeString()}</span>
      </div>
      <div class="timeline-title"></div>
      <pre class="timeline-body"></pre>
    `;
    el.querySelector(".timeline-title").textContent = item.title || "";
    el.querySelector(".timeline-body").textContent = item.body || "";
    els.timeline.appendChild(el);
  }
}

function renderRunner(lines) {
  els.runnerOutput.textContent = (lines || []).slice(-160).join("\n");
}

function drawReferenceLine(ctx, line, scale, pad, width) {
  const value = Number(line.value);
  if (!Number.isFinite(value)) return;
  const y = scale(value);
  ctx.save();
  ctx.strokeStyle = line.color;
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 5]);
  ctx.beginPath();
  ctx.moveTo(pad.left, y);
  ctx.lineTo(width - pad.right, y);
  ctx.stroke();

  ctx.font = "11px Inter, system-ui, sans-serif";
  const label = line.label;
  const labelW = ctx.measureText(label).width + 12;
  const labelX = Math.max(pad.left + 6, width - pad.right - labelW - 6);
  const labelY = Math.max(pad.top + 4, y - 18);
  ctx.fillStyle = "rgba(12,17,24,0.86)";
  ctx.fillRect(labelX, labelY, labelW, 16);
  ctx.fillStyle = line.color;
  ctx.fillText(label, labelX + 6, labelY + 12);
  ctx.restore();
}

function drawChart(canvas, rows, series, referenceLines = []) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.scale(dpr, dpr);
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0c1118";
  ctx.fillRect(0, 0, width, height);

  const pad = { left: 46, right: 16, top: 18, bottom: 28 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.fillStyle = "#637083";

  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  const values = (rows || []).flatMap((row) => series.map((s) => Number(row[s.key]) || 0));
  const referenceValues = referenceLines
    .map((line) => Number(line.value))
    .filter((value) => Number.isFinite(value));
  const max = Math.max(...values, ...referenceValues, 1) * 1.12;
  const min = 0;
  const scaleY = (value) => pad.top + plotH - ((value - min) / (max - min)) * plotH;

  ctx.fillStyle = "#637083";
  ctx.fillText(`${Math.round(max)}`, 8, pad.top + 8);
  ctx.fillText("0", 28, pad.top + plotH);

  referenceLines.forEach((line) => drawReferenceLine(ctx, line, scaleY, pad, width));

  if (!rows || rows.length < 2) {
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("Waiting for collector samples", pad.left, pad.top + 22);
    return;
  }

  series.forEach((s) => {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    rows.forEach((row, index) => {
      const x = pad.left + (plotW * index) / (rows.length - 1);
      const y = scaleY(Number(row[s.key]) || 0);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  let legendX = pad.left;
  for (const s of series) {
    ctx.fillStyle = s.color;
    ctx.fillRect(legendX, height - 18, 10, 3);
    ctx.fillStyle = "#94a3b8";
    ctx.fillText(s.label, legendX + 15, height - 14);
    legendX += 105;
  }
}

function renderCharts(run) {
  const sample = sampleForRun(run);
  const service = sample?.intent_thresholds?.target_service || "ue_premium";
  const rows = run?.metrics?.[service]?.rows || [];
  drawChart(els.throughputChart, rows, [
    { key: "throughput_mbps", label: "throughput", color: "#39d0a4" },
  ], thresholdLines(sample, service, ["throughput_mbps"]));
  drawChart(
    els.latencyChart,
    rows,
    [
      { key: "latency_ms", label: "latency", color: "#5ca8ff" },
      { key: "jitter_ms", label: "jitter", color: "#f2bd5c" },
    ],
    thresholdLines(sample, service, ["latency_ms", "jitter_ms"]),
  );
}

function render(run) {
  state.currentRun = run;
  updateStatus(run);
  renderUeCards(run?.metrics);
  renderTimeline(run?.timeline);
  renderRunner(run?.stdout_lines);
  renderCharts(run);
}

async function loadConfig() {
  const res = await fetch("/api/config");
  state.config = await res.json();
  els.modelInput.value = state.config.default_model;
  els.sampleSelect.innerHTML = "";
  for (const sample of state.config.samples) {
    const opt = document.createElement("option");
    opt.value = sample.id;
    opt.textContent = `${sample.label}${sample.difficulty ? " · " + sample.difficulty : ""}`;
    els.sampleSelect.appendChild(opt);
  }
  if (state.config.default_sample_id) {
    els.sampleSelect.value = state.config.default_sample_id;
  }
  render(null);
}

function subscribe(runId) {
  if (state.source) state.source.close();
  state.source = new EventSource(`/api/runs/${runId}/events`);
  state.source.onmessage = (event) => {
    render(JSON.parse(event.data));
  };
  state.source.onerror = () => {
    state.source?.close();
  };
}

async function startRun() {
  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sample_id: els.sampleSelect.value,
      model: els.modelInput.value.trim(),
    }),
  });
  const run = await res.json();
  render(run);
  if (res.ok) subscribe(run.id);
}

async function stopRun() {
  const run = state.currentRun;
  if (!run) return;
  const res = await fetch(`/api/runs/${run.id}/stop`, { method: "POST" });
  render(await res.json());
}

els.startButton.addEventListener("click", startRun);
els.stopButton.addEventListener("click", stopRun);
els.sampleSelect.addEventListener("change", () => renderCharts(state.currentRun));
window.addEventListener("resize", () => renderCharts(state.currentRun));

loadConfig();
