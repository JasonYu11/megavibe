const state = {
  status: null,
  orders: [],
  conditionalOrders: [],
  targets: [],
  events: [],
  positions: [],
  settings: null,
};

const views = {
  overview: "总览",
  trade: "交易指令",
  orders: "订单管理",
  copy: "跟单管理",
  positions: "跟单仓位",
};

const DEMO_TRADE_CARD_TEXT = `市价单确认
━━━━━━━━━━━━
类型: 即时市价 swap
订单编号: ord_c99b88564e4c49e9b1d54993ae0cdc80
模式: 买入 / OKX
────────────
买入: 使用 0.1 USDC 买入 GITLAWB
支付: 0.1 USDC
获得: GITLAWB
预计获得: 853.53318581208386526 GITLAWB
价格影响: -1.07%
最大滑点: 1%
风控结果: APPROVED
────────────
下一步: 确认后提交执行`;

const $ = (selector) => document.querySelector(selector);

function shortAddress(value) {
  if (!value) return "-";
  const text = String(value);
  return text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function oklinkTxUrl(txHash) {
  const text = String(txHash || "").trim();
  return text ? `https://www.oklink.com/base/tx/${encodeURIComponent(text)}` : "";
}

function oklinkAddressUrl(address) {
  const text = String(address || "").trim();
  return text ? `https://www.oklink.com/base/address/${encodeURIComponent(text)}` : "";
}

function explorerLink(value, type = "tx", label = null) {
  const text = String(value || "").trim();
  if (!text) return `<span class="muted">-</span>`;
  const href = type === "address" ? oklinkAddressUrl(text) : oklinkTxUrl(text);
  return `<a class="explorer-link mono" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(text)}">${escapeHtml(label || shortAddress(text))}</a>`;
}

function statusText(status) {
  const map = {
    DRAFT: "草稿",
    RISK_CHECKED: "风控通过",
    PENDING_CONFIRMATION: "待确认",
    APPROVED: "已确认",
    QUOTED: "已报价",
    SIGNING: "签名中",
    SIGNED_NOT_BROADCASTED: "已签未广播",
    BROADCASTED: "已广播",
    FILLED: "完成",
    FAILED: "未完成",
    CANCELLED: "已取消",
    DRY_RUN_COMPLETED: "模拟完成",
    REJECTED_BY_USER: "已拒绝",
    ACTIVE: "运行中",
    PAUSED: "已暂停",
    REMOVED: "已移除",
  };
  return map[status] || status || "-";
}

function sideText(side) {
  const map = { buy: "买入", sell: "卖出", swap: "兑换" };
  return map[String(side || "").toLowerCase()] || side || "兑换";
}

function pill(text, cls) {
  return `<span class="pill ${cls || ""}">${escapeHtml(text)}</span>`;
}

function statusPill(status) {
  return pill(statusText(status), `status-${String(status || "").toLowerCase().replaceAll("_", "-")}`);
}

function sidePill(side) {
  const normalized = String(side || "swap").toLowerCase();
  return pill(sideText(normalized), `side-${normalized}`);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function routeText(order) {
  return order.route || `${order.amount || "?"} ${order.token_in?.symbol || "?"} -> ${order.token_out?.symbol || "?"}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function refreshAll() {
  const [status, orders, targets, events, positions] = await Promise.all([
    api("/api/status"),
    api("/api/orders?limit=80"),
    api("/api/copy-targets"),
    api("/api/copy-events?limit=60"),
    api("/api/copy-positions"),
  ]);
  const settings = await api("/api/settings");
  state.status = status;
  state.orders = orders.orders || [];
  state.conditionalOrders = orders.conditional_orders || [];
  state.targets = targets.targets || [];
  state.events = events.events || [];
  state.positions = positions.positions || [];
  state.settings = settings;
  render();
}

function render() {
  renderStatus();
  renderMetrics();
  renderSettings();
  renderRecentOrders();
  renderOrdersTable();
  renderCopyTargets();
  renderCopyEvents();
  renderPositions();
}

function renderSettings() {
  const settings = state.settings || {};
  const conditional = settings.conditional_watcher_interval_seconds ?? 30;
  const copy = settings.copy_watcher_interval_seconds ?? 30;
  const conditionalInput = document.querySelector("[name='conditional_watcher_interval_seconds']");
  const copyInput = document.querySelector("[name='copy_watcher_interval_seconds']");
  if (conditionalInput && conditionalInput !== document.activeElement) conditionalInput.value = conditional;
  if (copyInput && copyInput !== document.activeElement) copyInput.value = copy;
  const estimates = settings.daily_estimates || {};
  $("#settings-estimates").innerHTML = `
    <div class="estimate-item">
      <span>单个限价单价格查询</span>
      <strong>${escapeHtml(estimates.conditional_order_calls_per_day ?? "-")} 次/天</strong>
    </div>
    <div class="estimate-item">
      <span>单个跟单地址历史查询</span>
      <strong>${escapeHtml(estimates.copy_target_calls_per_day ?? "-")} 次/天</strong>
    </div>
  `;
}

function renderStatus() {
  const status = state.status || {};
  $("#wallet-line").textContent = `wallet: ${shortAddress(status.wallet_address)} | db: ${status.db_path || "-"}`;
  $("#mode-pill").textContent = `${status.execution_mode || "unknown"} · ${status.live_enabled ? "LIVE" : "DRY"}`;
  $("#mode-pill").className = `mode-pill ${status.live_enabled ? "mode-live" : "mode-dry"}`;
}

function renderMetrics() {
  const status = state.status || {};
  const items = [
    { label: "订单总数", value: status.orders ?? 0, tone: "neutral", hint: "全部订单" },
    { label: "完成订单", value: status.filled_orders ?? 0, tone: "success", hint: "已成交" },
    { label: "未完成订单", value: status.failed_orders ?? 0, tone: "danger", hint: "失败或拒绝" },
    { label: "跟单地址", value: status.copy_targets ?? 0, tone: "info", hint: "已配置" },
    { label: "限价监控", value: boolStatus(status.watcher_last_ok), tone: statusTone(status.watcher_last_ok), hint: "价格 watcher" },
    { label: "跟单监控", value: boolStatus(status.copy_watcher_ok), tone: statusTone(status.copy_watcher_ok), hint: "历史轮询" },
    { label: "回执追踪", value: boolStatus(status.receipt_last_ok), tone: statusTone(status.receipt_last_ok), hint: "链上回执" },
    { label: "心跳", value: status.heartbeat_at ? formatTime(Number(status.heartbeat_at) * 1000) : "-", tone: "neutral", hint: "最近运行" },
  ];
  $("#metrics").innerHTML = items
    .map(
      (item) => `
        <div class="metric metric-${item.tone}">
          <div class="metric-top">
            <div class="label">${escapeHtml(item.label)}</div>
            <span class="metric-dot"></span>
          </div>
          <div class="value">${escapeHtml(item.value)}</div>
          <div class="metric-hint">${escapeHtml(item.hint)}</div>
        </div>`,
    )
    .join("");
}

function boolStatus(value) {
  if (value === true || value === "true" || value === "1" || value === 1) return "正常";
  if (value === false || value === "false" || value === "0" || value === 0) return "异常";
  return value || "-";
}

function statusTone(value) {
  if (value === true || value === "true" || value === "1" || value === 1) return "success";
  if (value === false || value === "false" || value === "0" || value === 0) return "danger";
  return "neutral";
}

function renderRecentOrders() {
  const rows = state.orders.slice(0, 6);
  $("#recent-orders").innerHTML = rows.length ? rows.map(orderCard).join("") : empty("暂无订单");
}

function orderCard(order) {
  const reason = latestReason(order);
  return `
    <article class="order-item">
      <div>
        <div class="order-title">
          ${sidePill(order.side)}
          <span>${escapeHtml(routeText(order))}</span>
          ${statusPill(order.status)}
        </div>
        <div class="order-meta">
          来源: ${escapeHtml(order.source)} · 时间: ${formatTime(order.created_at)} · 订单: <span class="mono">${escapeHtml(order.id)}</span>
          ${order.last_tx_hash ? `<br>Tx: ${explorerLink(order.last_tx_hash, "tx")}` : ""}
          ${reason ? `<br>原因: ${escapeHtml(reason)}` : ""}
        </div>
      </div>
      <div class="order-actions">${orderActions(order)}</div>
    </article>
  `;
}

function orderActions(order) {
  if (order.status !== "PENDING_CONFIRMATION") return "";
  return `<span class="muted">请回到交易对话中确认</span>`;
}

function latestReason(order) {
  const execution = order.latest_execution || {};
  if (execution.payload_json) {
    try {
      const payload = JSON.parse(execution.payload_json);
      if (payload.reason) return payload.reason;
      if (payload.error) return payload.error;
    } catch {
      return "";
    }
  }
  const risk = order.risk || [];
  const lastRisk = risk[risk.length - 1];
  return lastRisk?.reason || "";
}

function renderOrdersTable() {
  const rows = state.orders;
  if (!rows.length) {
    $("#orders-table").innerHTML = empty("暂无市价订单");
    return;
  }
  $("#orders-table").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>方向</th><th>路径</th><th>状态</th><th>来源</th><th>Tx</th><th>时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (order) => `
          <tr>
            <td>${sidePill(order.side)}</td>
            <td>${escapeHtml(routeText(order))}<br><span class="muted mono">${escapeHtml(order.id)}</span></td>
            <td>${statusPill(order.status)}${latestReason(order) ? `<br><span class="muted">${escapeHtml(latestReason(order))}</span>` : ""}</td>
            <td>${escapeHtml(order.source)}</td>
            <td>${explorerLink(order.last_tx_hash, "tx")}</td>
            <td>${formatTime(order.created_at)}</td>
            <td><div class="order-actions">${orderActions(order)}</div></td>
          </tr>`,
          )
          .join("")}
      </tbody>
    </table>
    ${renderConditionalOrders()}
  `;
}

function renderConditionalOrders() {
  if (!state.conditionalOrders.length) return "";
  return `
    <h3 class="subsection-title">限价单</h3>
    <table>
      <thead>
        <tr><th>触发条件</th><th>状态</th><th>动作</th><th>时间</th></tr>
      </thead>
      <tbody>
        ${state.conditionalOrders
          .map((order) => {
            const trigger = order.trigger || {};
            const action = order.action || {};
            const token = trigger.token || {};
            return `
              <tr>
                <td>${escapeHtml(token.symbol || shortAddress(token.address))} ${escapeHtml(trigger.operator || "")} ${escapeHtml(trigger.target_price_usd || "")} USD<br><span class="muted mono">${escapeHtml(order.id)}</span></td>
                <td>${statusPill(order.status)}</td>
                <td>${escapeHtml(action.side || "swap")} · ${escapeHtml(action.amount_value || action.amount || "")}</td>
                <td>${formatTime(order.created_at)}</td>
              </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function renderCopyTargets() {
  const el = $("#copy-targets");
  if (!state.targets.length) {
    el.innerHTML = empty("暂无跟单地址");
    return;
  }
  el.innerHTML = state.targets
    .map(
      (target) => `
      <article class="target-card" data-target="${escapeHtml(target.address)}">
        <h4>${explorerLink(target.address, "address", target.address)}</h4>
        <div class="order-meta">
          状态: ${statusPill(target.status)} · 事件: ${escapeHtml(target.recent_events)}
          ${target.latest_reason ? `<br>最近原因: ${escapeHtml(target.latest_reason)}` : ""}
        </div>
        <div class="target-controls">
          <select name="status">
            ${["PENDING_CONFIRMATION", "ACTIVE", "PAUSED", "REMOVED"]
              .map((value) => `<option value="${value}" ${value === target.status ? "selected" : ""}>${statusText(value)}</option>`)
              .join("")}
          </select>
          <input name="copy_ratio" value="${escapeHtml(target.copy_ratio)}" />
          <input name="max_copy_trade_usd" value="${escapeHtml(target.max_copy_trade_usd)}" />
          <input name="max_age_seconds" value="${escapeHtml(target.max_age_seconds)}" />
          <button class="primary" data-save-target="${escapeHtml(target.address)}">保存</button>
        </div>
      </article>`,
    )
    .join("");
}

function renderCopyEvents() {
  const el = $("#copy-events");
  if (!state.events.length) {
    el.innerHTML = empty("暂无跟单事件");
    return;
  }
  el.innerHTML = state.events
    .map((event) => {
      const actions = Array.isArray(event.actions) ? event.actions : [];
      return `
        <article class="event-item">
          <div class="order-title">
            ${statusPill(event.status)}
            ${explorerLink(event.target_address, "address")}
            <span>${escapeHtml(event.kind || "")}</span>
          </div>
          <div class="event-meta">
            Tx: ${explorerLink(event.tx_hash, "tx")} · 估算: ${escapeHtml(event.estimated_usd_value || "-")} USD · ${formatTime(event.created_at)}
            ${actions.length ? `<br>${actions.map(actionText).join("<br>")}` : ""}
          </div>
        </article>
      `;
    })
    .join("");
}

function actionText(action) {
  const label = action.label || sideText(action.side);
  const amount = action.amount || action.order?.amount?.value || "";
  const inSymbol = action.token_in?.symbol || action.order?.token_in?.symbol || "";
  const outSymbol = action.token_out?.symbol || action.order?.token_out?.symbol || "";
  return `${escapeHtml(label)}: ${escapeHtml(amount)} ${escapeHtml(inSymbol)} -> ${escapeHtml(outSymbol)} · ${statusText(action.order_status || action.status)}`;
}

function renderPositions() {
  const rows = state.positions;
  if (!rows.length) {
    $("#positions-table").innerHTML = empty("暂无跟单仓位");
    return;
  }
  $("#positions-table").innerHTML = `
    <table>
      <thead>
        <tr><th>跟单地址</th><th>Token</th><th>累计买入</th><th>累计卖出</th><th>净持仓</th></tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `
          <tr>
            <td>${explorerLink(row.target_address, "address")}</td>
            <td>${escapeHtml(row.token_symbol)}<br>${explorerLink(row.token_address, "address")}</td>
            <td>${escapeHtml(row.total_bought_amount)}</td>
            <td>${escapeHtml(row.total_sold_amount)}</td>
            <td>${escapeHtml(row.net_amount)}</td>
          </tr>`,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function empty(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function showView(name) {
  document.querySelectorAll("nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $("#page-title").textContent = views[name] || "Dashboard";
}

function showToolPanel(name) {
  document.querySelectorAll("[data-tool-panel]").forEach((button) => {
    button.classList.toggle("active", button.dataset.toolPanel === name);
  });
  document.querySelectorAll("[data-tool-panel-page]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.toolPanelPage === name);
  });
}

async function submitCommand(event) {
  event.preventDefault();
  const input = $("#command-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  updateCommandInputMode();
  if (isStandardCommand(text)) {
    await sendCommand(text);
    return;
  }
  await parseNaturalLanguageCommand(text);
}

function isStandardCommand(text) {
  return String(text || "").trim().startsWith("/");
}

function updateCommandInputMode() {
  const input = $("#command-input");
  const mode = $("#command-input-mode");
  const text = input.value.trim();
  const standard = isStandardCommand(text);
  mode.textContent = text ? (standard ? "标准命令" : "自然语言") : "标准 / 自然语言";
  mode.classList.toggle("mode-standard", standard && Boolean(text));
  mode.classList.toggle("mode-natural", !standard && Boolean(text));
}

async function sendCommand(text) {
  appendCommandLog("user", text);
  try {
    const result = await api("/api/commands", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    appendCommandLog("assistant", result.text || JSON.stringify(result.payload, null, 2), result.reply_markup);
    await refreshAll();
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function parseNaturalLanguageCommand(text) {
  appendCommandLog("user", text);
  const pending = appendNlCommandResult({ status: "loading", summary: "正在识别标准命令和自然语言意图..." });
  try {
    const payload = await api("/api/nl-commands/parse", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    appendNlCommandResult(payload.result || payload, pending);
  } catch (error) {
    appendNlCommandResult({ status: "error", summary: error.message }, pending);
  }
}

function appendNlCommandResult(result, existingItem = null) {
  const el = existingItem || document.createElement("div");
  el.className = "chat-item assistant nl-preview-item";
  el.innerHTML = `
    <div class="chat-avatar">M</div>
    <div class="chat-bubble nl-chat-bubble">
      <div class="chat-role">Megawave</div>
      ${renderNlCommandResult(result)}
    </div>
  `;
  if (!existingItem) $("#command-log").appendChild(el);
  $("#command-log").scrollTop = $("#command-log").scrollHeight;
  return el;
}

function renderNlCommandResult(result) {
  const status = result.status || "unmapped";
  const command = result.command || "";
  const missing = Array.isArray(result.missing_fields) ? result.missing_fields : [];
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const canSend = status === "mapped" && command;
  const isLoading = status === "loading";
  return `
    <div class="nl-result ${escapeHtml(status)}">
      <div class="nl-result-head">
        <div>
          <strong>${escapeHtml(nlDecisionTitle(status, canSend))}</strong>
          <span>${escapeHtml(nlDecisionSubtitle(result, canSend))}</span>
        </div>
        ${result.confidence ? `<span class="pill">${Math.round(Number(result.confidence) * 100)}%</span>` : ""}
      </div>
      ${command ? `<pre class="nl-command-text">${escapeHtml(command)}</pre>` : ""}
      ${result.summary ? `<p>${escapeHtml(result.summary)}</p>` : ""}
      ${missing.length ? `<p>还需要补充：${missing.map((item) => escapeHtml(item)).join("、")}</p>` : ""}
      ${warnings.length ? `<ul>${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      ${isLoading ? "" : `
        <div class="nl-result-actions">
          ${canSend ? `<button type="button" class="primary" data-nl-send="${escapeHtml(command)}">是</button>` : ""}
          <button type="button" data-nl-dismiss="1">否</button>
        </div>
      `}
    </div>
  `;
}

function nlDecisionTitle(status, canSend) {
  if (status === "loading") return "正在判断";
  if (canSend) return "是否发送这条指令？";
  if (status === "clarification_required") return "信息不足";
  if (status === "blocked_manual_only") return "不能执行";
  if (status === "invalid_command") return "不能执行";
  if (status === "configuration_error") return "模型配置不可用";
  if (status === "error") return "解析失败";
  if (status === "unmapped") return "不能执行";
  return nlStatusLabel(status);
}

function nlDecisionSubtitle(result, canSend) {
  const status = result.status || "unmapped";
  if (status === "loading") return "先判断是否能映射到白名单命令";
  if (canSend && result.risk === "trade_draft") return "交易草稿 · 仍需手动确认";
  if (canSend) return nlRiskLabel(result.risk);
  if (status === "clarification_required") return "补齐信息后再试";
  if (status === "blocked_manual_only") return "确认、拒绝、取消等操作只允许手动点击";
  if (status === "configuration_error") return "请检查 DeepSeek 环境变量";
  return "未生成可发送命令";
}

function nlStatusLabel(status) {
  const map = {
    mapped: "已生成命令预览",
    clarification_required: "需要补充信息",
    blocked_manual_only: "需要手动操作",
    invalid_command: "命令校验失败",
    configuration_error: "模型配置不可用",
    error: "解析失败",
    unmapped: "无法安全映射",
  };
  return map[status] || status;
}

function nlRiskLabel(risk) {
  const map = { read_only: "只读", quote: "报价", trade_draft: "交易草稿" };
  return map[risk] || "无命令";
}

async function sendParsedNlCommand(command) {
  await sendCommand(command);
}

async function submitMarketForm(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const token = requiredText(data.token, "Token 合约地址");
    const amount = requiredText(data.amount, "数量");
    const counter = optionalText(data.counter_token);
    const command = data.side === "sell"
      ? `/sell ${token} ${amount}${counter ? ` --to ${counter}` : ""}`
      : `/buy ${token} ${amount}${counter ? ` --with ${counter}` : ""}`;
    await sendCommand(command);
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function submitLimitForm(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const token = requiredText(data.token, "Token 合约地址");
    const amount = requiredText(data.amount, "数量");
    const targetPrice = requiredText(data.target_price, "目标价格");
    const counter = optionalText(data.counter_token);
    const command = data.side === "limit_sell"
      ? `/limit_sell ${token} ${amount} at ${targetPrice}${counter ? ` --to ${counter}` : ""}`
      : `/limit_buy ${token} ${amount} at ${targetPrice}${counter ? ` --with ${counter}` : ""}`;
    await sendCommand(command);
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function submitQuoteForm(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    await sendCommand(`/quote ${requiredText(data.token_in, "支付 Token")} ${requiredText(data.token_out, "获得 Token")} ${requiredText(data.amount, "支付数量")}`);
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function submitOrderCommandForm(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    await sendCommand(`/${data.action} ${requiredText(data.order_id, "订单编号")}`);
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function submitCopyCommandForm(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const address = requiredText(data.address, "跟单地址");
    if (data.action === "copy_set") {
      await sendCommand(`/copy_set ${address} ratio ${requiredText(data.copy_ratio, "跟单比例")} max ${requiredText(data.max_copy_trade_usd, "最大单笔 USD")}`);
      return;
    }
    await sendCommand(`/${data.action} ${address}`);
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

function requiredText(value, label) {
  const text = optionalText(value);
  if (!text) throw new Error(`${label}不能为空`);
  return text;
}

function optionalText(value) {
  return String(value || "").trim();
}

function appendCommandLog(role, text, replyMarkup = null) {
  const el = $("#command-log");
  const item = document.createElement("div");
  item.className = `chat-item ${role}`;
  const content = renderCommandContent(role, text, replyMarkup);
  item.innerHTML = `
    <div class="chat-avatar">${roleLabel(role).slice(0, 1)}</div>
    ${content}
  `;
  el.appendChild(item);
  el.scrollTop = el.scrollHeight;
}

function renderCommandContent(role, text, replyMarkup = null) {
  if (role === "assistant") {
    const tradeCard = renderTradeMessageCard(text, replyMarkup);
    if (tradeCard) return tradeCard;
  }
  return `
    <div class="chat-bubble">
      <div class="chat-role">${roleLabel(role)}</div>
      <pre>${escapeHtml(text)}</pre>
      ${renderInlineKeyboard(replyMarkup)}
    </div>
  `;
}

function roleLabel(role) {
  if (role === "user") return "你";
  if (role === "error") return "错误";
  return "Megawave";
}

function renderInlineKeyboard(replyMarkup) {
  const rows = replyMarkup?.inline_keyboard;
  if (!Array.isArray(rows) || rows.length === 0) return "";
  return `
    <div class="chat-actions">
      ${rows
        .map((row) =>
          row
            .map((button) => {
              const text = button.text || "操作";
              const callback = button.callback_data || "";
              const tone = callback.startsWith("confirm:") || callback.startsWith("copy_confirm:") || callback === "trade:confirm" ? "primary" : "";
              const danger = callback.startsWith("reject:") || callback.startsWith("cancel:") || callback.startsWith("copy_cancel:");
              return `<button class="${danger ? "danger" : tone}" data-callback="${escapeHtml(callback)}">${escapeHtml(text)}</button>`;
            })
            .join(""),
        )
        .join("")}
    </div>
  `;
}

function renderTradeMessageCard(text, replyMarkup = null) {
  const parsed = parseTradeMessage(text);
  if (!parsed) return "";
  const txLink = parsed.txHash ? explorerLink(parsed.txHash, "tx", shortAddress(parsed.txHash)) : "";
  const orderId = parsed.fields["订单编号"] || parsed.fields["市价单"] || parsed.fields["订单"];
  const status = parsed.fields["状态"] || parsed.fields["执行状态"] || "PENDING_CONFIRMATION";
  const submitTime = parsed.fields["提交时间"] || "";
  const method = parsed.fields["类型"] || parsed.fields["模式"] || parsed.title;
  const provider = parsed.provider || "OKX DEX";
  const debit = parsed.payment ? `-${parsed.payment}` : "";
  const credit = parsed.received ? `+${parsed.received}` : "";
  const balanceNote = parsed.fields["余额"] || "";
  return `
    <div class="chat-bubble trade-card-bubble">
      <div class="trade-card">
        <div class="trade-card-left">
          <div class="trade-time">${escapeHtml(submitTime ? formatTime(submitTime) : "刚刚")}</div>
          <div class="trade-status ${escapeHtml(statusTone(status))}">${escapeHtml(statusText(status))}</div>
          ${orderId ? `<div class="trade-address mono">${escapeHtml(shortAddress(orderId))}</div>` : ""}
        </div>
        <div class="trade-card-main">
          <div class="trade-title-row">
            <span class="protocol-mark">${escapeHtml(provider.slice(0, 1))}</span>
            <div>
              <div class="trade-title">${escapeHtml(parsed.title)}</div>
              <div class="trade-subtitle">${escapeHtml(method)} · ${escapeHtml(provider)}</div>
            </div>
          </div>
          <div class="trade-meta-grid">
            ${orderId ? `<span>订单</span><strong class="mono">${escapeHtml(shortAddress(orderId))}</strong>` : ""}
            ${txLink ? `<span>Tx</span><strong>${txLink}</strong>` : ""}
            ${parsed.fields["价格影响"] ? `<span>价格影响</span><strong>${escapeHtml(parsed.fields["价格影响"])}</strong>` : ""}
            ${parsed.fields["风控结果"] ? `<span>风控</span><strong>${escapeHtml(parsed.fields["风控结果"])}</strong>` : ""}
          </div>
          ${balanceNote ? `<div class="trade-note">${escapeHtml(balanceNote)}</div>` : ""}
        </div>
        <div class="trade-card-flow">
          ${debit ? renderAssetLine(debit, parsed.paymentSymbol, "debit") : ""}
          ${credit ? renderAssetLine(credit, parsed.receivedSymbol, "credit", parsed.receivedIsEstimated) : ""}
          ${!debit && !credit ? `<span class="muted">等待链上回执</span>` : ""}
        </div>
      </div>
      ${renderInlineKeyboard(replyMarkup)}
    </div>
  `;
}

function renderAssetLine(value, symbol, tone, estimated = false) {
  return `
    <div class="asset-flow-line ${tone}">
      <span class="asset-icon ${tokenIconClass(symbol)}">${escapeHtml((symbol || "?").slice(0, 1))}</span>
      <span>${estimated ? "预计 " : ""}${escapeHtml(compactAssetText(value))}</span>
    </div>
  `;
}

function compactAssetText(value) {
  const text = String(value || "").trim();
  const match = text.match(/^([+-]?)(\d+(?:\.\d+)?)(.*)$/);
  if (!match) return text;
  const sign = match[1];
  const number = Number(match[2]);
  if (!Number.isFinite(number)) return text;
  const suffix = match[3].trim();
  const fixed = number >= 100 ? number.toLocaleString("en-US", { maximumFractionDigits: 4 }) : number.toLocaleString("en-US", { maximumFractionDigits: 6 });
  return `${sign}${fixed}${suffix ? ` ${suffix}` : ""}`;
}

function parseTradeMessage(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^[-━]+$/.test(line));
  const title = lines[0] || "";
  if (!["市价单确认", "交易结果", "限价单已自动执行"].includes(title)) return null;
  const fields = {};
  for (const line of lines.slice(1)) {
    const match = line.match(/^([^:：]+)[:：]\s*(.*)$/);
    if (match) fields[match[1].trim()] = match[2].trim();
  }
  const mode = fields["模式"] || "";
  const provider = mode.includes("OKX") ? "OKX DEX" : "OKX DEX";
  const txHash = extractTxHash(text);
  const payment = fields["支付"] || "";
  const receivedRaw = fields["预计获得"] || fields["预计成交量"] || fields["获得"] || "";
  const receivedIsEstimated = Boolean(fields["预计获得"] || fields["预计成交量"]);
  return {
    title,
    fields,
    provider,
    txHash,
    payment,
    paymentSymbol: extractTrailingSymbol(payment),
    received: receivedRaw,
    receivedSymbol: extractTrailingSymbol(receivedRaw),
    receivedIsEstimated,
  };
}

function extractTxHash(text) {
  const match = String(text || "").match(/0x[a-fA-F0-9]{64}/);
  return match ? match[0] : "";
}

function extractTrailingSymbol(value) {
  const match = String(value || "").trim().match(/([A-Za-z][A-Za-z0-9]*)$/);
  return match ? match[1].toUpperCase() : "";
}

function tokenIconClass(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  if (normalized.includes("USDC") || normalized === "U") return "usdc";
  if (normalized.includes("ETH")) return "eth";
  return "generic";
}

function isLocalTradeCardDemo() {
  const local = ["127.0.0.1", "localhost", "::1"].includes(window.location.hostname);
  return local && new URLSearchParams(window.location.search).get("demo") === "trade-card";
}

async function handleChatCallback(data) {
  if (!data) return;
  try {
    const result = await api("/api/callbacks", {
      method: "POST",
      body: JSON.stringify({ data }),
    });
    appendCommandLog("assistant", result.text || JSON.stringify(result.payload, null, 2), result.reply_markup);
    await refreshAll();
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function confirmOrder(orderId) {
  const result = await api(`/api/orders/${encodeURIComponent(orderId)}/confirm`, { method: "POST", body: "{}" });
  appendCommandLog("assistant", result.text || `已确认 ${orderId}`, result.reply_markup);
  await refreshAll();
}

async function rejectOrder(orderId) {
  const result = await api(`/api/orders/${encodeURIComponent(orderId)}/reject`, { method: "POST", body: "{}" });
  appendCommandLog("assistant", result.text || `已拒绝 ${orderId}`, result.reply_markup);
  await refreshAll();
}

async function submitCopyTarget(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    await api("/api/copy-targets", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    form.copy_ratio.value = "0.1";
    form.max_copy_trade_usd.value = "0.01";
    form.max_age_seconds.value = "300";
    await refreshAll();
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function submitSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    state.settings = await api("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    appendCommandLog("assistant", `运行参数已保存\n限价单更新时间: ${state.settings.conditional_watcher_interval_seconds}s\n跟单 API 更新时间: ${state.settings.copy_watcher_interval_seconds}s`);
    renderSettings();
  } catch (error) {
    appendCommandLog("error", error.message);
  }
}

async function saveCopyTarget(address) {
  const card = document.querySelector(`[data-target="${CSS.escape(address)}"]`);
  const payload = {
    status: card.querySelector("[name='status']").value,
    copy_ratio: card.querySelector("[name='copy_ratio']").value,
    max_copy_trade_usd: card.querySelector("[name='max_copy_trade_usd']").value,
    max_age_seconds: card.querySelector("[name='max_age_seconds']").value,
  };
  await api(`/api/copy-targets/${address}`, { method: "PATCH", body: JSON.stringify(payload) });
  await refreshAll();
}

function bindEvents() {
  document.querySelectorAll("nav button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.querySelectorAll("[data-tool-panel]").forEach((button) => {
    button.addEventListener("click", () => showToolPanel(button.dataset.toolPanel));
  });
  $("#command-form").addEventListener("submit", submitCommand);
  $("#command-input").addEventListener("input", updateCommandInputMode);
  $("#market-form").addEventListener("submit", submitMarketForm);
  $("#limit-form").addEventListener("submit", submitLimitForm);
  $("#quote-form").addEventListener("submit", submitQuoteForm);
  $("#order-command-form").addEventListener("submit", submitOrderCommandForm);
  $("#copy-command-form").addEventListener("submit", submitCopyCommandForm);
  $("#copy-form").addEventListener("submit", submitCopyTarget);
  $("#settings-form").addEventListener("submit", submitSettings);
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#command-input").value = button.dataset.prompt || "";
      updateCommandInputMode();
      $("#command-input").focus();
    });
  });
  ["#refresh-overview", "#refresh-orders", "#refresh-copy", "#refresh-positions"].forEach((selector) => {
    $(selector).addEventListener("click", refreshAll);
  });
  document.body.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.dataset.nlSend) {
      await sendParsedNlCommand(target.dataset.nlSend);
      return;
    }
    if (target.dataset.nlDismiss) {
      target.closest(".chat-item")?.remove();
      return;
    }
    if (target.dataset.callback) await handleChatCallback(target.dataset.callback);
    if (target.dataset.confirm) await confirmOrder(target.dataset.confirm);
    if (target.dataset.reject) await rejectOrder(target.dataset.reject);
    if (target.dataset.saveTarget) await saveCopyTarget(target.dataset.saveTarget);
  });
  updateCommandInputMode();
}

bindEvents();
appendCommandLog("assistant", "你可以直接输入交易指令。我会在这里展示订单详情，并把确认或拒绝按钮放在当前对话里。");
if (isLocalTradeCardDemo()) {
  appendCommandLog("assistant", DEMO_TRADE_CARD_TEXT, {
    inline_keyboard: [[
      { text: "确认", callback_data: "confirm:ord_c99b88564e4c49e9b1d54993ae0cdc80" },
      { text: "拒绝", callback_data: "reject:ord_c99b88564e4c49e9b1d54993ae0cdc80" },
    ]],
  });
}
refreshAll().catch((error) => appendCommandLog("error", error.message));
window.setInterval(() => refreshAll().catch(() => {}), 10000);
