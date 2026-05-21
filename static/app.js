const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const state = {
  user: null,
  key: null,
  adminUsers: [],
  selectedAdminUser: null,
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
    throw new Error(text || response.statusText);
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

function formatTraffic(user) {
  const limit = user.traffic_limit_gb ?? "∞";
  return `${user.used_traffic_gb ?? 0} / ${limit} GB`;
}

function renderAdminUsers() {
  $("adminUsersList").innerHTML = state.adminUsers
    .map(
      (user) => `
        <button class="admin-user-row" data-admin-user="${user.id}">
          <strong>${adminName(user)}</strong>
          <span>ID: ${user.telegram_user_id} · ${user.status}</span>
          <span>До: ${formatDate(user.expires_at)} · Трафик: ${formatTraffic(user)}</span>
          <span>Device/key: ${user.device_id || user.key_id || "нет"}</span>
        </button>
      `,
    )
    .join("");
}

function renderAdminDebug() {
  const debug = state.adminDebug;
  if (!debug) {
    $("adminDebug").innerHTML = "";
    return;
  }
  const missing = debug.env?.missing?.length ? debug.env.missing.join(", ") : "none";
  const lastKey = debug.latest_key?.uuid || "none";
  $("adminDebug").innerHTML = `
    <strong>VPN backend</strong>
    <span class="admin-meta">Env complete: ${debug.env?.ok ? "yes" : "no"}</span>
    <span class="admin-meta">Missing: ${missing}</span>
    <span class="admin-meta">Last key/device: ${lastKey}</span>
    <span class="admin-meta">Last error: ${debug.last_provisioning_error || "none"}</span>
  `;
}

function renderAdminUserCard() {
  const user = state.selectedAdminUser;
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
      <button class="secondary" data-admin-action="copy-key">Показать/скопировать VPN ключ</button>
      <button class="secondary danger" data-admin-action="disable">Отключить доступ</button>
      <button class="secondary danger" data-admin-action="delete-key">Удалить VPN ключ/device</button>
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

function deviceText(deviceId) {
  const copy = {
    iphone: {
      app: "FoXray или Streisand",
      text: "Открой приложение, отсканируй QR-код на экране или вставь автоссылку. Затем включи подключение.",
    },
    android: {
      app: "v2rayNG",
      text: "Открой приложение, вставь автоссылку из буфера обмена и включи подключение.",
    },
    windows: {
      app: "Nekoray",
      text: "Открой приложение, добавь автоссылку и нажми подключиться.",
    },
  };
  return copy[deviceId] || copy.iphone;
}

function renderHelp() {
  const devices = state.devices.filter((device) => ["iphone", "android", "windows"].includes(device.id));
  $("deviceTabs").innerHTML = devices
    .map((device) => `<button class="tab ${device.id === state.selectedDevice ? "active" : ""}" data-device="${device.id}">${device.title}</button>`)
    .join("");

  const selected = devices.find((device) => device.id === state.selectedDevice) || devices[0];
  if (!selected) return;

  const info = deviceText(selected.id);
  $("deviceHelp").innerHTML = `
    <p>${info.text}</p>
    <span>Рекомендуемое приложение: ${info.app}</span>
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
  await loadAdminDebug();
  await loadAdminUsers();
}

function closeAdmin() {
  $("adminModal").classList.add("hidden");
  $("adminModal").setAttribute("aria-hidden", "true");
  state.selectedAdminUser = null;
  renderAdminUserCard();
}

async function openAdminUser(userId) {
  const data = await api(`/api/admin/panel/users/${userId}`);
  state.selectedAdminUser = data.user;
  renderAdminUserCard();
}

async function adminAction(action) {
  const user = state.selectedAdminUser;
  if (!user) return;
  if (action === "copy-key") {
    await copyRawText(user.vless_uri, "VPN ключ скопирован");
    return;
  }
  const endpoints = {
    "grant-test": { path: `/api/admin/panel/users/${user.id}/grant-test-access`, method: "POST" },
    "renew-7d": { path: `/api/admin/panel/users/${user.id}/renew-7d`, method: "POST" },
    disable: { path: `/api/admin/panel/users/${user.id}/disable`, method: "POST" },
    "delete-key": { path: `/api/admin/panel/users/${user.id}/key`, method: "DELETE" },
  };
  const endpoint = endpoints[action];
  if (!endpoint) return;
  const data = await api(endpoint.path, { method: endpoint.method });
  state.selectedAdminUser = data.user;
  renderAdminUserCard();
  await loadAdminUsers();
  await loadMe();
  toast("Готово");
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.id === "getKeyBtn") await getKey();
  if (target.id === "openAdminBtn") await openAdmin();
  if (target.id === "copyKeyBtn") await copyText(state.key?.vless_uri, "VPN скопирован");
  if (target.id === "copySubBtn") await copyText(state.key?.subscription_url, "Автоссылка скопирована");
  if (target.id === "helpBtn") openHelp();
  if (target.dataset.closeModal !== undefined) closeHelp();
  if (target.dataset.closePlans !== undefined) closePlans();
  if (target.dataset.closeAdmin !== undefined) closeAdmin();
  if (target.dataset.plan) await buyPlan(target.dataset.plan);
  if (target.dataset.adminUser) await openAdminUser(target.dataset.adminUser);
  if (target.dataset.adminAction) await adminAction(target.dataset.adminAction);
  if (target.dataset.support !== undefined && state.supportUrl) window.open(state.supportUrl, "_blank");
  if (target.dataset.device) {
    state.selectedDevice = target.dataset.device;
    renderHelp();
  }
});

if (state.initData) {
  Promise.all([loadMe(), loadDevices(), loadPlans()]).catch((error) => {
    console.error(error);
    toast("Ошибка загрузки");
  });
}
