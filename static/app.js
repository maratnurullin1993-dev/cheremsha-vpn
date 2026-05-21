const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const state = {
  key: null,
  devices: [],
  plans: [],
  capacity: null,
  supportUrl: "",
  selectedDevice: "iphone",
  initData: tg?.initData || "",
};

const $ = (id) => document.getElementById(id);

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

function renderPlans() {
  if (state.capacity?.is_full) {
    $("plansList").innerHTML = `
      <div class="no-slots">
        <strong>Свободных мест нет</strong>
        <span>Сервер заполнен. Напиши в поддержку, если нужен доступ.</span>
        <button class="secondary" data-support>Написать в поддержку</button>
      </div>
    `;
    return;
  }
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

async function loadMe() {
  const data = await api("/api/me");
  state.key = data.key;
  state.capacity = data.capacity;
  renderAccess();
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
    state.capacity = { ...(state.capacity || {}), is_full: true };
    renderPlans();
    toast("Свободных мест нет");
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

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.id === "getKeyBtn") await getKey();
  if (target.id === "copyKeyBtn") await copyText(state.key?.vless_uri, "VPN скопирован");
  if (target.id === "copySubBtn") await copyText(state.key?.subscription_url, "Автоссылка скопирована");
  if (target.id === "helpBtn") openHelp();
  if (target.dataset.closeModal !== undefined) closeHelp();
  if (target.dataset.closePlans !== undefined) closePlans();
  if (target.dataset.plan) await buyPlan(target.dataset.plan);
  if (target.dataset.support !== undefined && state.supportUrl) window.open(state.supportUrl, "_blank");
  if (target.dataset.device) {
    state.selectedDevice = target.dataset.device;
    renderHelp();
  }
});

Promise.all([loadMe(), loadDevices(), loadPlans()]).catch((error) => {
  console.error(error);
  toast("Ошибка загрузки");
});
