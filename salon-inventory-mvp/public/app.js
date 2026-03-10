const state = { products: [], movements: [], scanner: null, quickType: 'salida_venta', lang: 'es', me: null };

const I18N = {
  es: {
    who: (u, r) => `${u} (${r === 'admin' ? 'Administrador' : 'Invitado'})`,
    installHint: 'Instalar en iPad: Safari → compartir (□↑) → Agregar a pantalla de inicio.',
    exporting: 'Exportando Excel...',
    tab: { dashboard: 'Dashboard', products: 'Productos', movements: 'Movimientos', alerts: 'Alertas' },
    common: { save: 'Guardar', clear: 'Limpiar', edit: 'Editar', del: 'Eliminar', yesDelete: '¿Eliminar producto?' },
    kpi: { products: 'Productos', units: 'Unidades', low: 'Stock bajo', today: 'Mov. hoy', value: 'Valor inventario' },
    movementType: { entrada: 'Entrada', salida_venta: 'Salida venta', salida_uso_interno: 'Uso interno' },
    labels: {
      quickBtn: '+ Movimiento',
      logout: 'Salir',
      search: 'Buscar por nombre/marca/categoría',
      qty: 'Cantidad',
      notes: 'Notas',
      noProducts: 'No hay productos todavía. Crea uno en la pestaña Productos.',
      export: 'Export Excel'
    }
  },
  en: {
    who: (u, r) => `${u} (${r === 'admin' ? 'Admin' : 'Guest'})`,
    installHint: 'Install on iPad: Safari → Share (□↑) → Add to Home Screen.',
    exporting: 'Exporting Excel...',
    tab: { dashboard: 'Dashboard', products: 'Products', movements: 'Movements', alerts: 'Alerts' },
    common: { save: 'Save', clear: 'Clear', edit: 'Edit', del: 'Delete', yesDelete: 'Delete product?' },
    kpi: { products: 'Products', units: 'Units', low: 'Low stock', today: 'Moves today', value: 'Inventory value' },
    movementType: { entrada: 'Stock In', salida_venta: 'Sale Out', salida_uso_interno: 'Internal Use' },
    labels: {
      quickBtn: '+ Movement',
      logout: 'Logout',
      search: 'Search by name/brand/category',
      qty: 'Quantity',
      notes: 'Notes',
      noProducts: 'No products yet. Create one in the Products tab.',
      export: 'Export Excel'
    }
  },
};

const $ = (id) => document.getElementById(id);
const t = () => I18N[state.lang];

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Error');
  return data;
}

function showTab(tabId) {
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabId));
  document.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('active', p.id === tabId));
}

function money(v) {
  return Number(v || 0).toLocaleString(state.lang === 'es' ? 'es-MX' : 'en-US', { style: 'currency', currency: 'USD' });
}

function formatDate(v) {
  const d = new Date(v.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(state.lang === 'es' ? 'es-MX' : 'en-US', { dateStyle: 'short', timeStyle: 'short' });
}

function setLang(lang) {
  state.lang = lang;
  localStorage.setItem('salon_lang', lang);
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const keys = el.dataset.i18n.split('.');
    let value = I18N[lang];
    keys.forEach((k) => (value = value?.[k]));
    if (typeof value === 'string') el.textContent = value;
  });

  $('openQuickMovement').textContent = t().labels.quickBtn;
  $('logoutBtn').textContent = t().labels.logout;
  $('searchProduct').placeholder = t().labels.search;
  $('movement_qty').placeholder = t().labels.qty;
  $('movement_notes').placeholder = t().labels.notes;
  $('exportExcelBtn').textContent = t().labels.export;

  const mt = $('movement_type');
  mt.querySelector('option[value="entrada"]').textContent = t().movementType.entrada;
  mt.querySelector('option[value="salida_venta"]').textContent = t().movementType.salida_venta;
  mt.querySelector('option[value="salida_uso_interno"]').textContent = t().movementType.salida_uso_interno;

  if (state.me) $('whoami').textContent = t().who(state.me.username, state.me.role);
  $('iosInstallHint').textContent = t().installHint;
  renderProducts(state.products);
  renderMovements(state.movements);
  renderQuickProducts(state.products);
}

async function refreshAll() {
  state.products = await api('/api/products');
  state.movements = await api('/api/movements');
  const dashboard = await api('/api/dashboard');
  const alerts = await api('/api/alerts/low-stock');
  const suggestions = await api('/api/purchases/suggested');

  renderDashboard(dashboard);
  renderProducts(state.products);
  renderProductsSelect(state.products);
  renderMovements(state.movements);
  renderAlerts(alerts);
  renderSuggestions(suggestions);
  renderQuickProducts(state.products);
}

function renderDashboard(d) {
  $('dashboard').innerHTML = `
    <div class="kpis">
      <div class="kpi"><h4>${t().kpi.products}</h4><p>${d.totalProducts}</p></div>
      <div class="kpi"><h4>${t().kpi.units}</h4><p>${d.totalUnits}</p></div>
      <div class="kpi"><h4>${t().kpi.low}</h4><p>${d.lowStockCount}</p></div>
      <div class="kpi"><h4>${t().kpi.today}</h4><p>${d.today.reduce((a, x) => a + Number(x.qty), 0)}</p></div>
    </div>
    <div class="card" style="margin-top:1rem">
      <h3>${t().kpi.value}: ${money(d.totalValueCost)}</h3>
      <ul>${d.movementsByType.map((m) => `<li><b>${t().movementType[m.type] || m.type}</b>: ${m.count} / ${m.qty}</li>`).join('') || '<li>-</li>'}</ul>
    </div>
  `;
}

function renderProducts(products) {
  const search = $('searchProduct').value?.toLowerCase() || '';
  const rows = products.filter((p) => `${p.name} ${p.brand} ${p.category}`.toLowerCase().includes(search));
  $('productsTable').innerHTML = `
    <tr><th>Producto</th><th>Categoría</th><th>Stock</th><th>Min</th><th>Objetivo</th><th></th></tr>
    ${rows
      .map(
        (p) => `<tr>
      <td>${p.name}<br><small>${p.brand || ''}</small></td>
      <td>${p.category || '-'}</td>
      <td class="${p.current_stock <= p.min_stock ? 'stock-low' : ''}">${p.current_stock}</td>
      <td>${p.min_stock}</td>
      <td>${p.target_stock}</td>
      <td>
        <button onclick='editProduct(${JSON.stringify(p)})' class='secondary'>${t().common.edit}</button>
        ${state.me?.role === 'admin' ? `<button onclick='deleteProduct(${p.id})'>${t().common.del}</button>` : ''}
      </td>
    </tr>`
      )
      .join('')}
  `;
}

function renderProductsSelect(products) {
  const sel = $('movement_product_id');
  if (!products.length) {
    sel.innerHTML = `<option value="">${t().labels.noProducts}</option>`;
    sel.disabled = true;
    $('movement_qty').disabled = true;
    $('movement_notes').disabled = true;
    $('movementForm').querySelector('button[type="submit"]').disabled = true;
    return;
  }

  sel.disabled = false;
  $('movement_qty').disabled = false;
  $('movement_notes').disabled = false;
  $('movementForm').querySelector('button[type="submit"]').disabled = false;
  sel.innerHTML = products.map((p) => `<option value="${p.id}">${p.name} (stock: ${p.current_stock})</option>`).join('');
}

function renderMovements(rows) {
  $('movementsTable').innerHTML = `
    <tr><th>Fecha</th><th>Producto</th><th>Tipo</th><th>Cant.</th><th>User</th><th>Notas</th></tr>
    ${rows.map((m) => `<tr><td>${formatDate(m.created_at)}</td><td>${m.product_name}</td><td><span class='badge'>${t().movementType[m.type] || m.type}</span></td><td>${m.qty}</td><td>${m.created_by || '-'}</td><td>${m.notes || ''}</td></tr>`).join('')}
  `;
}

function renderAlerts(rows) {
  $('alertsTable').innerHTML = `<tr><th>Producto</th><th>Stock</th><th>Mínimo</th></tr>${rows.map((p) => `<tr><td>${p.name}</td><td class='stock-low'>${p.current_stock}</td><td>${p.min_stock}</td></tr>`).join('') || '<tr><td colspan="3">Sin alertas ✅</td></tr>'}`;
}

function renderSuggestions(rows) {
  const total = rows.reduce((a, x) => a + Number(x.estimated_cost || 0), 0);
  $('suggestionsTable').innerHTML = `
    <tr><th>Producto</th><th>Sugerido</th><th>Stock</th><th>Costo</th></tr>
    ${rows.map((s) => `<tr><td>${s.name}</td><td>${s.suggested_qty}</td><td>${s.current_stock}</td><td>${money(s.estimated_cost)}</td></tr>`).join('') || '<tr><td colspan="4">Sin compras sugeridas ✅</td></tr>'}
    <tr><td colspan="3"><b>Total</b></td><td><b>${money(total)}</b></td></tr>
  `;
}

function renderQuickProducts(products) {
  const top = [...products].sort((a, b) => (a.current_stock - a.min_stock) - (b.current_stock - b.min_stock)).slice(0, 8);
  $('quickMovement').innerHTML = `
    <button class="${state.quickType === 'salida_venta' ? '' : 'secondary'}" onclick="setQuickType('salida_venta')">${state.lang === 'es' ? 'Venta -1' : 'Sale -1'}</button>
    <button class="${state.quickType === 'salida_uso_interno' ? '' : 'secondary'}" onclick="setQuickType('salida_uso_interno')">${state.lang === 'es' ? 'Uso -1' : 'Internal -1'}</button>
    <button class="${state.quickType === 'entrada' ? '' : 'secondary'}" onclick="setQuickType('entrada')">${state.lang === 'es' ? 'Entrada +1' : 'In +1'}</button>
  `;

  if (!top.length) {
    $('quickProducts').innerHTML = `<div class="quick-product"><small>${t().labels.noProducts}</small></div>`;
    return;
  }

  $('quickProducts').innerHTML = top
    .map(
      (p) => `<div class="quick-product"><h4>${p.name}</h4><small>Stock: ${p.current_stock} | Min: ${p.min_stock}</small><div class="quick-actions"><button onclick="quickMove(${p.id}, 1)">${state.quickType === 'entrada' ? '+1' : '-1'}</button><button class="secondary" onclick="openMovementFor(${p.id})">${state.lang === 'es' ? 'Abrir' : 'Open'}</button></div></div>`
    )
    .join('');
}

window.setQuickType = (type) => {
  state.quickType = type;
  renderQuickProducts(state.products);
};

window.quickMove = async (productId, qty) => {
  try {
    await api('/api/movements', { method: 'POST', body: JSON.stringify({ product_id: productId, type: state.quickType, qty, notes: 'Quick move' }) });
    await refreshAll();
  } catch (err) {
    alert(err.message);
  }
};

window.openMovementFor = (productId) => {
  showTab('movements');
  $('movement_product_id').value = String(productId);
  $('movement_qty').focus();
  $('movementCard').scrollIntoView({ behavior: 'smooth', block: 'center' });
};

window.editProduct = (p) => {
  Object.keys(p).forEach((k) => {
    const el = $(k);
    if (el) el.value = p[k] ?? '';
  });
  showTab('products');
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

window.deleteProduct = async (id) => {
  if (!confirm(t().common.yesDelete)) return;
  await api(`/api/products/${id}`, { method: 'DELETE' });
  await refreshAll();
};

$('searchProduct').addEventListener('input', () => renderProducts(state.products));
document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
$('langSelect').addEventListener('change', (e) => setLang(e.target.value));

$('openQuickMovement').addEventListener('click', () => {
  showTab('movements');
  $('movement_qty').focus();
});

$('exportExcelBtn').addEventListener('click', async () => {
  $('exportExcelBtn').textContent = t().exporting;
  window.location.href = '/api/export/excel';
  setTimeout(() => ($('exportExcelBtn').textContent = 'Export Excel'), 1000);
});

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/login', { method: 'POST', body: JSON.stringify({ username: $('username').value, password: $('password').value }) });
    const me = await api('/api/me');
    state.me = me;
    $('whoami').textContent = t().who(me.username, me.role);
    $('loginView').classList.add('hidden');
    $('appView').classList.remove('hidden');
    await refreshAll();
    maybeShowIosInstallHint();
  } catch (err) {
    alert(err.message);
  }
});

$('logoutBtn').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' });
  location.reload();
});

$('productForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    name: $('name').value,
    brand: $('brand').value,
    category: $('category').value,
    barcode: $('barcode').value,
    unit: $('unit').value,
    cost: $('cost').value,
    sale_price: $('sale_price').value,
    initial_stock: $('initial_stock').value,
    min_stock: $('min_stock').value,
    target_stock: $('target_stock').value,
  };

  const id = $('product_id').value;
  if (id) await api(`/api/products/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
  else await api('/api/products', { method: 'POST', body: JSON.stringify(payload) });

  $('productForm').reset();
  $('unit').value = 'unidad';
  $('product_id').value = '';
  await refreshAll();
});

$('clearProduct').addEventListener('click', () => {
  $('productForm').reset();
  $('unit').value = 'unidad';
  $('product_id').value = '';
});

$('movementForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!state.products.length) return;
  await api('/api/movements', {
    method: 'POST',
    body: JSON.stringify({
      product_id: $('movement_product_id').value,
      type: $('movement_type').value,
      qty: $('movement_qty').value,
      notes: $('movement_notes').value,
    }),
  });
  $('movement_qty').value = '';
  $('movement_notes').value = '';
  await refreshAll();
});

$('scanBtn').addEventListener('click', async () => {
  $('scannerWrap').classList.remove('hidden');
  if (!window.Html5Qrcode) return alert('Scanner no disponible');
  const scanner = new Html5Qrcode('reader');
  state.scanner = scanner;
  try {
    await scanner.start({ facingMode: 'environment' }, { fps: 10, qrbox: 250 }, (decodedText) => {
      $('barcode').value = decodedText;
      stopScanner();
    });
  } catch {
    alert('No se pudo iniciar cámara.');
  }
});

async function stopScanner() {
  if (state.scanner) {
    try { await state.scanner.stop(); } catch {}
    try { await state.scanner.clear(); } catch {}
    state.scanner = null;
  }
  $('scannerWrap').classList.add('hidden');
}

$('closeScanner').addEventListener('click', stopScanner);

function maybeShowIosInstallHint() {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (isIOS && !isStandalone) $('iosInstallHint').classList.remove('hidden');
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try { await navigator.serviceWorker.register('/sw.js'); } catch {}
}

(async function init() {
  await registerServiceWorker();
  setLang(localStorage.getItem('salon_lang') || 'es');
  $('langSelect').value = state.lang;
  try {
    const me = await api('/api/me');
    if (me.authenticated) {
      state.me = me;
      $('whoami').textContent = t().who(me.username, me.role);
      $('loginView').classList.add('hidden');
      $('appView').classList.remove('hidden');
      await refreshAll();
      maybeShowIosInstallHint();
    }
  } catch {}
})();
