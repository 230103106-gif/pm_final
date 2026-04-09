const state = {
  token: localStorage.getItem("saturnpro_token") || "",
  dashboard: null,
};

const loginSection = document.getElementById("loginSection");
const appSection = document.getElementById("appSection");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const globalMessage = document.getElementById("globalMessage");
const logoutButton = document.getElementById("logoutButton");
const statsGrid = document.getElementById("statsGrid");
const ordersList = document.getElementById("ordersList");
const orderCountLabel = document.getElementById("orderCountLabel");
const orderComposerCard = document.getElementById("orderComposerCard");
const analyticsGrid = document.getElementById("analyticsGrid");
const notificationList = document.getElementById("notificationList");
const userList = document.getElementById("userList");
const auditList = document.getElementById("auditList");
const userBadge = document.getElementById("userBadge");
const welcomeTitle = document.getElementById("welcomeTitle");
const userForm = document.getElementById("userForm");

const statusOptions = [
  "pending",
  "queued_for_warehouse",
  "processing",
  "ready_for_dispatch",
  "delivered",
  "cancelled",
];

function showMessage(message, isError = false) {
  globalMessage.textContent = message;
  globalMessage.classList.remove("hidden");
  globalMessage.classList.toggle("error-message", isError);
  globalMessage.classList.toggle("status-banner", !isError);
}

function clearMessage() {
  globalMessage.textContent = "";
  globalMessage.classList.add("hidden");
  globalMessage.classList.remove("error-message");
  globalMessage.classList.add("status-banner");
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = payload?.detail || payload || "Request failed.";
    throw new Error(detail);
  }

  return payload;
}

function currency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

function prettyRole(role) {
  return role.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function prettyStatus(status) {
  return status.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

async function login(event) {
  event.preventDefault();
  loginError.textContent = "";
  clearMessage();

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    const payload = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    state.token = payload.token;
    localStorage.setItem("saturnpro_token", state.token);
    await loadDashboard();
  } catch (error) {
    loginError.textContent = error.message;
  }
}

async function loadDashboard() {
  try {
    state.dashboard = await api("/api/dashboard");
    render();
  } catch (error) {
    localStorage.removeItem("saturnpro_token");
    state.token = "";
    state.dashboard = null;
    loginSection.classList.remove("hidden");
    appSection.classList.add("hidden");
    loginError.textContent = error.message;
  }
}

async function logout() {
  try {
    if (state.token) {
      await api("/api/auth/logout", { method: "POST" });
    }
  } catch (error) {
    console.warn(error);
  } finally {
    state.token = "";
    state.dashboard = null;
    localStorage.removeItem("saturnpro_token");
    loginSection.classList.remove("hidden");
    appSection.classList.add("hidden");
    clearMessage();
  }
}

function renderStats(stats) {
  const items = [
    { label: "Total Orders", value: stats.total_orders },
    { label: "Queued", value: stats.queued_orders },
    { label: "Processing", value: stats.processing_orders },
    { label: "Delivered", value: stats.delivered_orders },
    { label: "Revenue", value: currency(stats.total_revenue) },
    { label: "Active Regions", value: stats.active_regions },
    { label: "Notifications", value: stats.pending_notifications },
    { label: "Users", value: stats.user_count },
  ];

  statsGrid.innerHTML = items
    .map(
      (item) => `
        <article class="stats-card">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </article>
      `
    )
    .join("");
}

function renderOrderComposer() {
  const role = state.dashboard.user.role;
  if (role === "warehouse_manager") {
    orderComposerCard.innerHTML = `
      <div class="subpanel-header">
        <h3>Warehouse View</h3>
        <p>Warehouse managers review region queues and update fulfillment status.</p>
      </div>
      <p class="muted">Order creation is reserved for customers and admin users in this demo.</p>
    `;
    return;
  }

  const customerSelect = role === "admin"
    ? `
      <label>
        Customer
        <select id="orderCustomerId">
          ${state.dashboard.users
            .filter((user) => user.role === "customer")
            .map((user) => `<option value="${user.id}">${user.full_name} (${user.email})</option>`)
            .join("")}
        </select>
      </label>
    `
    : "";

  orderComposerCard.innerHTML = `
    <div class="subpanel-header">
      <h3>${role === "admin" ? "Create Order for Customer" : "Place a New Order"}</h3>
      <p>Every order is automatically mapped to an H3 hex region.</p>
    </div>
    <form id="orderForm" class="order-form">
      ${customerSelect}
      <div class="location-grid">
        <label>
          Address
          <input type="text" id="orderAddress" value="45 Tole Bi Street" required>
        </label>
        <label>
          City
          <input type="text" id="orderCity" value="Almaty" required>
        </label>
      </div>
      <div class="mini-grid">
        <label>
          Latitude
          <input type="number" id="orderLatitude" step="0.000001" value="43.238949" required>
        </label>
        <label>
          Longitude
          <input type="number" id="orderLongitude" step="0.000001" value="76.889709" required>
        </label>
        <label>
          Priority
          <select id="orderPriority">
            <option value="standard">Standard</option>
            <option value="express">Express</option>
          </select>
        </label>
      </div>
      <label>
        Notes
        <textarea id="orderNotes">Deliver during office hours and call reception on arrival.</textarea>
      </label>
      <div class="subpanel-header">
        <h3>Line Items</h3>
        <button type="button" id="addItemButton" class="inline-button">Add Item</button>
      </div>
      <div id="itemRows" class="order-items-editor"></div>
      <button type="submit" class="primary-button">Submit Order</button>
    </form>
  `;

  const itemRows = document.getElementById("itemRows");
  addItemRow(itemRows, { product_name: "Showroom Sofa", sku: "SF-210", quantity: 1, unit_price: 780 });
  addItemRow(itemRows, { product_name: "Accent Lamp", sku: "LMP-022", quantity: 2, unit_price: 65 });

  document.getElementById("addItemButton").addEventListener("click", () => addItemRow(itemRows));
  document.getElementById("orderForm").addEventListener("submit", submitOrder);
}

function addItemRow(container, defaults = {}) {
  const template = document.getElementById("itemRowTemplate");
  const fragment = template.content.cloneNode(true);
  const row = fragment.querySelector(".item-row");
  row.querySelector(".item-product").value = defaults.product_name || "";
  row.querySelector(".item-sku").value = defaults.sku || "";
  row.querySelector(".item-quantity").value = defaults.quantity || 1;
  row.querySelector(".item-price").value = defaults.unit_price || 100;
  row.querySelector(".remove-item").addEventListener("click", () => row.remove());
  container.appendChild(fragment);
}

function renderOrders() {
  const { orders, user } = state.dashboard;
  orderCountLabel.textContent = `${orders.length} orders visible to ${prettyRole(user.role)}.`;

  if (!orders.length) {
    ordersList.innerHTML = `<p class="muted">No orders yet.</p>`;
    return;
  }

  ordersList.innerHTML = orders
    .map((order) => {
      const items = order.items
        .map((item) => `<li>${item.product_name} · ${item.sku} · ${item.quantity} x ${currency(item.unit_price)}</li>`)
        .join("");

      const controls = user.role === "admin" || user.role === "warehouse_manager"
        ? `
          <div class="order-actions">
            <select class="status-select" data-order-status="${order.id}">
              ${statusOptions
                .map(
                  (option) => `<option value="${option}" ${option === order.status ? "selected" : ""}>${prettyStatus(option)}</option>`
                )
                .join("")}
            </select>
            <button class="inline-button" data-save-status="${order.id}">Save Status</button>
          </div>
        `
        : "";

      return `
        <article class="order-card">
          <header>
            <div>
              <h3>${order.order_number}</h3>
              <p class="muted">${order.customer.full_name} · ${order.customer.email}</p>
            </div>
            <div class="badge-row">
              <span class="chip">${prettyStatus(order.status)}</span>
              <span class="chip accent">${order.priority}</span>
              <span class="chip soft">${order.region_h3}</span>
            </div>
          </header>
          <div class="order-meta">
            <p><strong>Total:</strong> ${currency(order.total_price)}</p>
            <p><strong>Delivery:</strong> ${order.address_line}, ${order.city}</p>
            <p><strong>Coordinates:</strong> ${order.latitude}, ${order.longitude}</p>
            <p><strong>Region center:</strong> ${order.region_center.lat.toFixed(4)}, ${order.region_center.lng.toFixed(4)}</p>
            <p><strong>Notes:</strong> ${order.notes || "No notes"}</p>
          </div>
          <ul class="order-items">${items}</ul>
          ${controls}
        </article>
      `;
    })
    .join("");

  document.querySelectorAll("[data-save-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const orderId = button.getAttribute("data-save-status");
      const select = document.querySelector(`[data-order-status="${orderId}"]`);
      await updateOrder(orderId, { status: select.value });
    });
  });
}

function renderAnalytics() {
  const { analytics, user } = state.dashboard;
  if (user.role === "customer") {
    analyticsGrid.innerHTML = `<p class="muted">Regional analytics are available to admin and warehouse roles.</p>`;
    return;
  }
  if (!analytics.length) {
    analyticsGrid.innerHTML = `<p class="muted">No analytics available yet.</p>`;
    return;
  }

  analyticsGrid.innerHTML = analytics
    .map(
      (item) => `
        <article class="analytics-card">
          <header>
            <div>
              <h3>${item.region_h3}</h3>
              <p class="muted">Center ${item.center.lat.toFixed(4)}, ${item.center.lng.toFixed(4)}</p>
            </div>
            <span class="chip accent">${item.order_count} orders</span>
          </header>
          <div class="order-meta">
            <p><strong>Revenue:</strong> ${currency(item.revenue_total)}</p>
            <p><strong>Queued:</strong> ${item.queued_count}</p>
            <p><strong>Processing:</strong> ${item.processing_count}</p>
            <p><strong>Delivered:</strong> ${item.delivered_count}</p>
          </div>
        </article>
      `
    )
    .join("");
}

function renderNotifications() {
  const { notifications, user } = state.dashboard;
  if (user.role === "customer") {
    notificationList.innerHTML = `<p class="muted">Warehouse notifications are visible to admin and warehouse roles.</p>`;
    return;
  }
  if (!notifications.length) {
    notificationList.innerHTML = `<p class="muted">No notifications have been created yet.</p>`;
    return;
  }

  notificationList.innerHTML = notifications
    .map(
      (note) => `
        <article class="notification-card">
          <header>
            <div>
              <h3>${note.order_number}</h3>
              <p class="muted">${note.warehouse_region}</p>
            </div>
            <span class="chip">${note.status}</span>
          </header>
          <p>${note.message}</p>
          <p class="muted">Order status: ${prettyStatus(note.order_status)} · Created ${new Date(note.created_at).toLocaleString()}</p>
        </article>
      `
    )
    .join("");
}

function renderUsers() {
  const { users, user } = state.dashboard;
  if (user.role !== "admin") {
    userList.innerHTML = `<p class="muted">User management is admin-only.</p>`;
    return;
  }
  userList.innerHTML = users
    .map(
      (member) => `
        <article class="user-card">
          <header>
            <div>
              <h3>${member.full_name}</h3>
              <p class="muted">${member.email}</p>
            </div>
            <span class="chip accent">${prettyRole(member.role)}</span>
          </header>
          <p class="muted">Created ${new Date(member.created_at).toLocaleString()}</p>
        </article>
      `
    )
    .join("");
}

function renderAuditLogs() {
  const { audit_logs: auditLogs, user } = state.dashboard;
  if (user.role !== "admin") {
    auditList.innerHTML = `<p class="muted">Audit logs are admin-only.</p>`;
    return;
  }
  auditList.innerHTML = auditLogs
    .map(
      (entry) => `
        <article class="audit-card">
          <header>
            <div>
              <h3>${entry.action}</h3>
              <p class="muted">${entry.entity_type}${entry.entity_id ? ` #${entry.entity_id}` : ""}</p>
            </div>
            <span class="chip soft">${entry.actor_name || "System"}</span>
          </header>
          <p class="muted">${new Date(entry.created_at).toLocaleString()}</p>
          <pre>${JSON.stringify(entry.detail, null, 2)}</pre>
        </article>
      `
    )
    .join("");
}

function render() {
  loginSection.classList.add("hidden");
  appSection.classList.remove("hidden");
  clearMessage();

  const { user, stats } = state.dashboard;
  userBadge.textContent = `${user.full_name} · ${prettyRole(user.role)}`;
  welcomeTitle.textContent = `${prettyRole(user.role)} Workspace`;

  document.querySelectorAll(".admin-only").forEach((node) => {
    node.classList.toggle("hidden", user.role !== "admin");
  });

  renderStats(stats);
  renderOrderComposer();
  renderOrders();
  renderAnalytics();
  renderNotifications();
  renderUsers();
  renderAuditLogs();
}

async function submitOrder(event) {
  event.preventDefault();
  const role = state.dashboard.user.role;
  const items = [...document.querySelectorAll("#itemRows .item-row")].map((row) => ({
    product_name: row.querySelector(".item-product").value.trim(),
    sku: row.querySelector(".item-sku").value.trim(),
    quantity: Number(row.querySelector(".item-quantity").value),
    unit_price: Number(row.querySelector(".item-price").value),
  }));

  const payload = {
    address_line: document.getElementById("orderAddress").value.trim(),
    city: document.getElementById("orderCity").value.trim(),
    latitude: Number(document.getElementById("orderLatitude").value),
    longitude: Number(document.getElementById("orderLongitude").value),
    priority: document.getElementById("orderPriority").value,
    notes: document.getElementById("orderNotes").value.trim(),
    items,
  };

  if (role === "admin") {
    payload.customer_id = Number(document.getElementById("orderCustomerId").value);
  }

  try {
    await api("/api/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showMessage("Order created successfully. The warehouse queue will publish a notification shortly.");
    await loadDashboard();
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function updateOrder(orderId, payload) {
  try {
    await api(`/api/orders/${orderId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    showMessage("Order updated.");
    await loadDashboard();
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function submitUser(event) {
  event.preventDefault();
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({
        full_name: document.getElementById("userFullName").value.trim(),
        email: document.getElementById("userEmail").value.trim(),
        password: document.getElementById("userPassword").value,
        role: document.getElementById("userRole").value,
      }),
    });
    userForm.reset();
    showMessage("User created.");
    await loadDashboard();
  } catch (error) {
    showMessage(error.message, true);
  }
}

function switchView(targetView) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("hidden", view.id !== `view-${targetView}`);
    view.classList.toggle("active", view.id === `view-${targetView}`);
  });
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === targetView);
  });
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

loginForm.addEventListener("submit", login);
logoutButton.addEventListener("click", logout);

if (userForm) {
  userForm.addEventListener("submit", submitUser);
}

if (state.token) {
  loadDashboard();
}
