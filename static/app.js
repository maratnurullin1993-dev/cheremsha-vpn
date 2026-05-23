const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const state = {
  user: null,
  key: null,
  adminUsers: [],
  selectedAdminUser: null,
  adminLoadingUserId: null,
  adminDebug: null,
  devices: [],
  plans: [],
  capacity: null,
  supportUrl: "",
  selectedDevice: "iphone",
  initData: tg?.initData || "",
};

const $ = (id) => document.getElementById(id);

if (!state.initData) {
  document.title = "ClubRU Access";
  $("appShell")?.remove();
  fetch("/api/public-config")
    .then((response) => (response.ok ? response.json() : null))
    .then((config) => {
      if (config?.telegram_open_url) {
        $("telegramOpenLink").href = config.telegram_open_url;
      } else {
        $("telegramOpenLink").classList.add("hidden");
        $("telegramLinkNote").classList.remove("hidden");
      }
    })
    .catch(() => {
      $("telegramOpenLink").classList.add("hidden");
      $("telegramLinkNote").classList.remove("hidden");
    });
} else {
  $("landingPage")?.remove();
  $("browserPlaceholder")?.remove();
  $("appShell").classList.remove("hidden");
}

function headers(extra = {}) {
  return state.initData ? { "X-Telegram-Init-Data": state.initData, ...extra } : extra;
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...headers(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const data = JSON.parse(text);
      message = data.detail || data.message || JSON.stringify(data);
    } catch (error) {
      message = text;
    }
    throw new Error(message || response.statusText);
  }
  return response.json();
}

function formatDate(value) {
  if (!value) return "не создан";
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

function hasAccess() {
  return state.key?.status === "active";
}

function statusLabel() {
  if (state.key?.status === "expired") return "Доступ истёк";
  if (state.key?.status === "traffic_exhausted") return "Трафик закончился";
  return hasAccess() ? "Доступ активен" : "Доступ не активен";
}

function setVisible(id, visible) {
  $(id).classList.toggle("hidden", !visible);
}

function renderAccess() {
  const active = hasAccess();
  const remaining = state.key?.remaining_traffic_gb;
  document.querySelector(".status-orbit").classList.toggle("inactive", !active);
  $("statusText").textContent = statusLabel();
  $("expiryLine").textContent = `Доступ до: ${formatDate(state.key?.expires_at)}`;
  $("expiryLine").classList.toggle("hidden", !active);
  $("trafficLine").textContent = `Осталось трафика: ${remaining ?? "∞"} GB`;
  $("trafficLine").classList.toggle("hidden", !active);
  if (state.capacity) {
    $("capacityLine").textContent = `Мест занято: ${state.capacity.active} / ${state.capacity.max}`;
  }

  setVisible("accessActions", active);
  $("getKeyBtn").classList.toggle("hidden", active);
  $("qrImage").closest(".key-panel").classList.toggle("hidden", !active);

  const qr = $("qrImage");
  if (active) {
    qr.src = `/api/keys/${state.key.id}/qr${state.initData ? `?initData=${encodeURIComponent(state.initData)}` : ""}`;
    qr.style.display = "block";
  } else {
    qr.removeAttribute("src");
    qr.style.display = "none";
  }
}

function renderAdmin() {
  setVisible("adminPanel", Boolean(state.user?.is_admin));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function adminName(user) {
  return escapeHtml(user.username || user.first_name || `telegram ${user.telegram_user_id}`);
}

function formatTrafficAmount(value, empty = "0 MB") {
  if (value === null || value === undefined) return empty;
  const gb = Number(value);
  if (!Number.isFinite(gb)) return empty;
  if (gb > 0 && gb < 1) return `${Math.round(gb * 1024)} MB`;
  if (gb === 0) return "0 MB";
  const rounded = gb >= 10 || Number.isInteger(gb) ? Math.round(gb) : Math.round(gb * 10) / 10;
  return `${rounded} GB`;
}

function formatTraffic(user) {
  return `${formatTrafficAmount(user.used_traffic_gb)} / ${formatTrafficAmount(user.traffic_limit_gb, "∞")}`;
}

function renderAdminUsers() {
  $("adminUsersList").innerHTML = state.adminUsers
    .map(
      (user) => `
        <button class="admin-user-row ${state.adminLoadingUserId === user.id ? "loading" : ""}" data-admin-user="${user.id}" type="button" ${state.adminLoadingUserId === user.id ? "disabled" : ""}>
          <strong>${adminName(user)}</strong>
          <span>ID: ${user.telegram_user_id} · ${user.status}</span>
          <span>До: ${formatDate(user.expires_at)} · Трафик: ${formatTraffic(user)}</span>
          <span>Device/key: ${user.device_id || user.key_id || "нет"}</span>
          ${state.adminLoadingUserId === user.id ? '<span class="admin-row-loader">Загрузка...</span>' : ""}
        </button>
      `,
    )
    .join("");
}

function renderAdminDebug() {
  const debug = state.adminDebug;
  if (!debug) {
    $("adminDebug").innerHTML = "";
    setVisible("adminDebug", true);
    return;
  }
  const missing = debug.env?.missing?.length ? debug.env.missing.join(", ") : "none";
  const lastKey = debug.latest_key?.uuid || "none";
  const system = debug.system || {};
  const disk = system.disk?.total_gb ? `${system.disk.used_gb} / ${system.disk.total_gb} GB` : system.disk?.message || "TODO";
  const ram = system.ram?.total_mb ? `${system.ram.used_mb} / ${system.ram.total_mb} MB` : system.ram?.message || "TODO";
  const cpu = system.cpu?.load_1m !== undefined ? `${system.cpu.load_1m}, ${system.cpu.load_5m}, ${system.cpu.load_15m}` : system.cpu?.message || "TODO";
  const uptime = system.app_uptime_seconds ? `${Math.floor(system.app_uptime_seconds / 60)} мин` : "меньше минуты";
  $("adminDebug").innerHTML = `
    <details class="diagnostics">
      <summary>Диагностика</summary>
      <div class="diagnostics-grid">
        <span class="admin-meta">VPN backend status: ${system.vpn_backend_status || (debug.env?.ok ? "ok" : "config error")}</span>
        <span class="admin-meta">x-ui API status: ${system.xui_api_status || "unknown"}</span>
        <span class="admin-meta">xray status: ${system.xray_status || "unknown"}</span>
        <span class="admin-meta">Last error: ${debug.last_provisioning_error || "none"}</span>
        <span class="admin-meta">Last key/device UUID: ${lastKey}</span>
        <span class="admin-meta">Active users count: ${debug.active_users_count ?? 0}</span>
        <span class="admin-meta">Occupied slots: ${debug.occupied_slots || `${debug.capacity?.active ?? 0} / ${debug.capacity?.max ?? 20}`}</span>
        <span class="admin-meta">Users in DB: ${debug.users_count ?? "unknown"}</span>
        <span class="admin-meta">CPU: ${cpu}</span>
        <span class="admin-meta">RAM: ${ram}</span>
        <span class="admin-meta">Disk: ${disk}</span>
        <span class="admin-meta">Uptime: ${uptime}</span>
        <span class="admin-meta">Missing env: ${missing}</span>
      </div>
    </details>
  `;
  setVisible("adminDebug", true);
}

function renderAdminUserCard() {
  const user = state.selectedAdminUser;
  if (state.adminLoadingUserId && !user) {
    $("adminUserCard").innerHTML = `
      <strong>Загрузка пользователя...</strong>
      <div class="admin-card-loader"></div>
    `;
    setVisible("adminUserCard", true);
    return;
  }
  if (!user) {
    setVisible("adminUserCard", false);
    return;
  }
  $("adminUserCard").innerHTML = `
    <strong>${adminName(user)}</strong>
    <div class="admin-meta">Telegram ID: ${user.telegram_user_id}</div>
    <div class="admin-meta">Статус: ${user.status}</div>
    <div class="admin-meta">До: ${formatDate(user.expires_at)}</div>
    <div class="admin-meta">Трафик: ${formatTraffic(user)}</div>
    <div class="admin-meta">Device/key: ${user.device_id || user.key_id || "нет"}</div>
    <div class="admin-actions">
      <button class="secondary" data-admin-action="grant-test">Выдать тестовый доступ</button>
      <button class="secondary" data-admin-action="renew-7d">Продлить на 7 дней</button>
      <button class="secondary danger" data-admin-action="disable">Отключить доступ</button>
      <button class="secondary danger" data-admin-action="delete-key">Удалить VPN ключ/device</button>
      <button class="secondary danger" data-admin-action="recreate-key">Сбросить ключ</button>
    </div>
  `;
  setVisible("adminUserCard", true);
}

function renderPlans() {
  $("plansList").innerHTML = state.plans
    .map(
      (plan) => `
        <button class="plan-button" data-plan="${plan.id}">
          <span>${plan.title} · ${plan.traffic_limit_gb} GB</span>
          <strong>${plan.stars} Stars</strong>
        </button>
      `,
    )
    .join("");
}

function renderHelp() {
  const appButtons = state.devices
    .flatMap((device) => [
      { title: device.app, url: device.app_url },
      { title: device.secondary_app, url: device.secondary_app_url },
    ])
    .filter((item) => item.title)
    .map((item) =>
      item.url
        ? `<a class="app-link" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>`
        : `<button class="app-link placeholder" type="button" disabled>${escapeHtml(item.title)} · URL не задан</button>`,
    )
    .join("");
  $("deviceTabs").innerHTML = "";
  $("deviceHelp").innerHTML = `
    <div class="app-links">${appButtons}</div>
    <h3>Основной способ</h3>
    <ol>
      <li>Скачай V2Box.</li>
      <li>Нажми «Автоссылка».</li>
      <li>Открой ссылку в V2Box.</li>
      <li>Нажми импорт.</li>
      <li>Включи VPN.</li>
    </ol>
    <h3>Запасной способ QR</h3>
    <ol>
      <li>Открой V2Box.</li>
      <li>Нажми сканер QR.</li>
      <li>Наведи на QR-код в мини-приложении.</li>
      <li>Импортируй и включи.</li>
    </ol>
    <h3>Если не получилось</h3>
    <ol>
      <li>Нажми «Скопировать VPN».</li>
      <li>Открой V2Box.</li>
      <li>Нажми «+».</li>
      <li>Выбери импорт из буфера/clipboard.</li>
      <li>Включи VPN.</li>
    </ol>
  `;
}

async function copyText(value, okMessage) {
  if (!value || !hasAccess()) {
    toast("Доступ не создан");
    return;
  }
  await navigator.clipboard.writeText(value);
  toast(okMessage);
}

async function copyRawText(value, okMessage) {
  if (!value) {
    toast("Ключ не создан");
    return;
  }
  await navigator.clipboard.writeText(value);
  toast(okMessage);
}

async function loadMe() {
  const data = await api("/api/me");
  state.user = data.user;
  state.key = data.key;
  state.capacity = data.capacity;
  renderAccess();
  renderAdmin();
}

async function loadDevices() {
  const data = await api("/api/devices");
  state.devices = data.devices;
  renderHelp();
}

async function loadPlans() {
  const data = await api("/api/payments/plans");
  state.plans = data.plans;
  state.capacity = data.capacity;
  state.supportUrl = data.support_url;
  renderPlans();
  renderAccess();
}

async function getKey() {
  renderPlans();
  $("plansModal").classList.remove("hidden");
  $("plansModal").setAttribute("aria-hidden", "false");
}

function closePlans() {
  $("plansModal").classList.add("hidden");
  $("plansModal").setAttribute("aria-hidden", "true");
}

async function buyPlan(planId) {
  let data;
  try {
    data = await api("/api/payments/invoice", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId }),
    });
  } catch (error) {
    toast("Ошибка оплаты");
    return;
  }

  const afterPayment = async (status) => {
    if (status !== "paid") return;
    closePlans();
    toast("Оплата прошла");
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 900));
      await loadMe();
      if (hasAccess()) return;
    }
    toast("Оплата принята, доступ скоро появится");
  };

  if (tg?.openInvoice) {
    tg.openInvoice(data.invoice_link, afterPayment);
  } else {
    window.open(data.invoice_link, "_blank");
    closePlans();
  }
}

function openHelp() {
  renderHelp();
  $("helpModal").classList.remove("hidden");
  $("helpModal").setAttribute("aria-hidden", "false");
}

function closeHelp() {
  $("helpModal").classList.add("hidden");
  $("helpModal").setAttribute("aria-hidden", "true");
}

async function loadAdminUsers() {
  const data = await api("/api/admin/panel/users");
  state.adminUsers = data.users;
  renderAdminUsers();
}

async function loadAdminDebug() {
  const data = await api("/api/admin/panel/debug");
  state.adminDebug = data;
  renderAdminDebug();
}

async function openAdmin() {
  if (!state.user?.is_admin) return;
  $("adminModal").classList.remove("hidden");
  $("adminModal").setAttribute("aria-hidden", "false");
  await loadAdminUsers();
  await loadAdminDebug();
}

function closeAdmin() {
  $("adminModal").classList.add("hidden");
  $("adminModal").setAttribute("aria-hidden", "true");
  state.selectedAdminUser = null;
  renderAdminUserCard();
}

async function openAdminUser(userId) {
  const numericUserId = Number(userId);
  state.adminLoadingUserId = numericUserId;
  state.selectedAdminUser = null;
  renderAdminUsers();
  renderAdminUserCard();
  try {
    const data = await api(`/api/admin/panel/users/${numericUserId}`);
    state.selectedAdminUser = data.user;
  } catch (error) {
    console.error(error);
    toast(error.message || "Ошибка");
  } finally {
    state.adminLoadingUserId = null;
    renderAdminUsers();
    renderAdminUserCard();
  }
}

async function adminAction(action) {
  const user = state.selectedAdminUser;
  if (!user) return;
  try {
    const endpoints = {
      "grant-test": { path: `/api/admin/panel/users/${user.id}/grant-test-access`, method: "POST" },
      "renew-7d": { path: `/api/admin/panel/users/${user.id}/renew-7d`, method: "POST" },
      disable: { path: `/api/admin/panel/users/${user.id}/disable`, method: "POST" },
      "delete-key": { path: `/api/admin/panel/users/${user.id}/key`, method: "DELETE" },
      "recreate-key": { path: `/api/admin/panel/users/${user.id}/recreate-key`, method: "POST" },
    };
    const endpoint = endpoints[action];
    if (!endpoint) return;
    const data = await api(endpoint.path, { method: endpoint.method });
    state.selectedAdminUser = data.user;
    renderAdminUserCard();
    await loadMe();
    await loadDevices();
    await loadAdminUsers();
    await openAdminUser(user.id);
    await loadAdminDebug();
    toast("Готово");
  } catch (error) {
    console.error(error);
    toast(error.message || "Ошибка");
  }
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const planButton = target.closest("[data-plan]");
  const adminUserButton = target.closest("[data-admin-user]");
  const adminActionButton = target.closest("[data-admin-action]");
  const deviceButton = target.closest("[data-device]");

  if (target.id === "getKeyBtn") await getKey();
  if (target.id === "openAdminBtn") await openAdmin();
  if (target.id === "copyKeyBtn") await copyText(state.key?.vpn_config, "VPN скопирован");
  if (target.id === "copySubBtn") await copyText(state.key?.subscription_url, "Автоссылка скопирована");
  if (target.id === "helpBtn") openHelp();
  if (target.dataset.closeModal !== undefined) closeHelp();
  if (target.dataset.closePlans !== undefined) closePlans();
  if (target.dataset.closeAdmin !== undefined) closeAdmin();
  if (planButton) await buyPlan(planButton.dataset.plan);
  if (adminUserButton) await openAdminUser(adminUserButton.dataset.adminUser);
  if (adminActionButton) await adminAction(adminActionButton.dataset.adminAction);
  if (target.dataset.support !== undefined && state.supportUrl) window.open(state.supportUrl, "_blank");
  if (deviceButton) {
    state.selectedDevice = deviceButton.dataset.device;
    renderHelp();
  }
});

if (state.initData) {
  Promise.all([loadMe(), loadDevices(), loadPlans()]).catch((error) => {
    console.error(error);
    toast("Ошибка загрузки");
  });
}
