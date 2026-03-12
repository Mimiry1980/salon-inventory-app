require('dotenv').config();
const express = require('express');
const session = require('express-session');
const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');
const XLSX = require('xlsx');

const app = express();
const PORT = process.env.PORT || 3000;
const SESSION_SECRET = process.env.SESSION_SECRET || 'super-secret-mvp-change-me';

const ADMIN_USER = process.env.ADMIN_USER || 'Gisbelys Mituoka';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Gisbe!2026Salon#';
const GUEST_USER = process.env.GUEST_USER || 'Invitado';
const GUEST_PASSWORD = process.env.GUEST_PASSWORD || 'Invitado!2026Salon#';

const dataDir = path.join(__dirname, 'data');
fs.mkdirSync(dataDir, { recursive: true });
const dbPath = path.join(dataDir, 'inventory.db');
const db = new Database(dbPath);

function initDb() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin', 'guest')),
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      brand TEXT,
      category TEXT,
      barcode TEXT,
      unit TEXT DEFAULT 'unidad',
      cost REAL DEFAULT 0,
      sale_price REAL DEFAULT 0,
      min_stock INTEGER DEFAULT 0,
      target_stock INTEGER DEFAULT 0,
      initial_stock INTEGER DEFAULT 0,
      expires_at TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS movements (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      type TEXT NOT NULL CHECK(type IN ('entrada', 'salida_venta', 'salida_uso_interno')),
      qty INTEGER NOT NULL CHECK(qty > 0),
      notes TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      created_by TEXT DEFAULT '',
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );
  `);

  const movementCols = db.prepare(`PRAGMA table_info(movements)`).all();
  if (!movementCols.some((c) => c.name === 'created_by')) {
    db.exec(`ALTER TABLE movements ADD COLUMN created_by TEXT DEFAULT ''`);
  }

  const productCols = db.prepare(`PRAGMA table_info(products)`).all();
  if (!productCols.some((c) => c.name === 'expires_at')) {
    db.exec(`ALTER TABLE products ADD COLUMN expires_at TEXT`);
  }

  const upsertUser = db.prepare(`
    INSERT INTO users (username, password, role)
    VALUES (?, ?, ?)
    ON CONFLICT(username) DO UPDATE SET password=excluded.password, role=excluded.role
  `);

  upsertUser.run(ADMIN_USER, ADMIN_PASSWORD, 'admin');
  upsertUser.run(GUEST_USER, GUEST_PASSWORD, 'guest');
}

function getProductCurrentStock(productId) {
  const row = db
    .prepare(
      `SELECT
         p.initial_stock +
         COALESCE(SUM(CASE WHEN m.type = 'entrada' THEN m.qty ELSE 0 END), 0) -
         COALESCE(SUM(CASE WHEN m.type IN ('salida_venta', 'salida_uso_interno') THEN m.qty ELSE 0 END), 0)
         AS current_stock
       FROM products p
       LEFT JOIN movements m ON p.id = m.product_id
       WHERE p.id = ?
       GROUP BY p.id`
    )
    .get(productId);
  return row ? row.current_stock : 0;
}

function getProductsWithStock() {
  return db
    .prepare(
      `SELECT
         p.*,
         p.initial_stock +
         COALESCE(SUM(CASE WHEN m.type = 'entrada' THEN m.qty ELSE 0 END), 0) -
         COALESCE(SUM(CASE WHEN m.type IN ('salida_venta', 'salida_uso_interno') THEN m.qty ELSE 0 END), 0)
         AS current_stock
       FROM products p
       LEFT JOIN movements m ON p.id = m.product_id
       GROUP BY p.id
       ORDER BY p.name ASC`
    )
    .all();
}

function authRequired(req, res, next) {
  if (req.session && req.session.authenticated) return next();
  return res.status(401).json({ error: 'Not authenticated / No autenticado' });
}

function adminRequired(req, res, next) {
  if (req.session?.role === 'admin') return next();
  return res.status(403).json({ error: 'Admin only / Solo administrador' });
}

function backupDb() {
  try {
    const backupsDir = path.join(__dirname, 'data', 'backups');
    fs.mkdirSync(backupsDir, { recursive: true });

    const now = new Date();
    const stamp = now.toISOString().replace(/[:.]/g, '-');
    const target = path.join(backupsDir, `inventory-backup-${stamp}.db`);

    fs.copyFileSync(dbPath, target);

    const files = fs
      .readdirSync(backupsDir)
      .filter((f) => f.endsWith('.db'))
      .map((f) => ({ name: f, full: path.join(backupsDir, f), mtime: fs.statSync(path.join(backupsDir, f)).mtimeMs }))
      .sort((a, b) => b.mtime - a.mtime);

    files.slice(14).forEach((f) => fs.unlinkSync(f.full));
    console.log(`🗄️ Backup created: ${target}`);
  } catch (error) {
    console.error('Backup failed:', error.message);
  }
}

function msUntilNextLocal(hour = 2, minute = 0) {
  const now = new Date();
  const next = new Date();
  next.setHours(hour, minute, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  return next - now;
}

function scheduleDailyBackup() {
  const wait = msUntilNextLocal(2, 0);
  setTimeout(() => {
    backupDb();
    setInterval(backupDb, 24 * 60 * 60 * 1000);
  }, wait);
}

initDb();
scheduleDailyBackup();

app.use(express.json());
app.use(
  session({
    secret: SESSION_SECRET,
    resave: false,
    saveUninitialized: false,
    cookie: { maxAge: 1000 * 60 * 60 * 10 },
  })
);
app.use(express.static(path.join(__dirname, 'public')));

app.post('/api/login', (req, res) => {
  const { username, password } = req.body;
  if (!username || !password) return res.status(400).json({ error: 'Missing credentials' });

  const user = db.prepare(`SELECT id, username, password, role FROM users WHERE username = ?`).get(String(username).trim());
  if (!user || user.password !== password) return res.status(401).json({ error: 'Invalid credentials' });

  req.session.authenticated = true;
  req.session.userId = user.id;
  req.session.username = user.username;
  req.session.role = user.role;

  return res.json({ ok: true, username: user.username, role: user.role });
});

app.post('/api/logout', (req, res) => {
  req.session.destroy(() => res.json({ ok: true }));
});

app.get('/api/me', (req, res) => {
  res.json({
    authenticated: !!(req.session && req.session.authenticated),
    username: req.session?.username || null,
    role: req.session?.role || null,
  });
});

app.get('/api/users', authRequired, adminRequired, (req, res) => {
  const users = db.prepare(`SELECT id, username, role FROM users ORDER BY role ASC, username ASC`).all();
  res.json(users);
});

app.get('/api/products', authRequired, (req, res) => res.json(getProductsWithStock()));

app.get('/api/products/:id', authRequired, (req, res) => {
  const id = Number(req.params.id);
  const product = db.prepare('SELECT * FROM products WHERE id = ?').get(id);
  if (!product) return res.status(404).json({ error: 'Product not found / Producto no encontrado' });
  product.current_stock = getProductCurrentStock(id);
  res.json(product);
});

app.post('/api/products', authRequired, (req, res) => {
  const { name, brand, category, barcode, unit, cost, sale_price, min_stock, target_stock, initial_stock, expires_at } = req.body;
  if (!name) return res.status(400).json({ error: 'Name is required / Nombre obligatorio' });

  const info = db
    .prepare(
      `INSERT INTO products (name, brand, category, barcode, unit, cost, sale_price, min_stock, target_stock, initial_stock, expires_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      name,
      brand || '',
      category || '',
      barcode || '',
      unit || 'unidad',
      Number(cost || 0),
      Number(sale_price || 0),
      Number(min_stock || 0),
      Number(target_stock || 0),
      Number(initial_stock || 0),
      expires_at || null
    );

  const created = db.prepare('SELECT * FROM products WHERE id = ?').get(info.lastInsertRowid);
  created.current_stock = getProductCurrentStock(created.id);
  res.status(201).json(created);
});

app.put('/api/products/:id', authRequired, (req, res) => {
  const id = Number(req.params.id);
  const existing = db.prepare('SELECT * FROM products WHERE id = ?').get(id);
  if (!existing) return res.status(404).json({ error: 'Product not found / Producto no encontrado' });

  const updated = {
    name: req.body.name ?? existing.name,
    brand: req.body.brand ?? existing.brand,
    category: req.body.category ?? existing.category,
    barcode: req.body.barcode ?? existing.barcode,
    unit: req.body.unit ?? existing.unit,
    cost: Number(req.body.cost ?? existing.cost),
    sale_price: Number(req.body.sale_price ?? existing.sale_price),
    min_stock: Number(req.body.min_stock ?? existing.min_stock),
    target_stock: Number(req.body.target_stock ?? existing.target_stock),
    initial_stock: Number(req.body.initial_stock ?? existing.initial_stock),
    expires_at: req.body.expires_at ?? existing.expires_at,
  };

  db.prepare(
    `UPDATE products
     SET name = ?, brand = ?, category = ?, barcode = ?, unit = ?,
         cost = ?, sale_price = ?, min_stock = ?, target_stock = ?, initial_stock = ?, expires_at = ?,
         updated_at = datetime('now')
     WHERE id = ?`
  ).run(
    updated.name,
    updated.brand,
    updated.category,
    updated.barcode,
    updated.unit,
    updated.cost,
    updated.sale_price,
    updated.min_stock,
    updated.target_stock,
    updated.initial_stock,
    updated.expires_at || null,
    id
  );

  const row = db.prepare('SELECT * FROM products WHERE id = ?').get(id);
  row.current_stock = getProductCurrentStock(id);
  res.json(row);
});

app.delete('/api/products/:id', authRequired, adminRequired, (req, res) => {
  const id = Number(req.params.id);
  const info = db.prepare('DELETE FROM products WHERE id = ?').run(id);
  if (!info.changes) return res.status(404).json({ error: 'Product not found / Producto no encontrado' });
  res.json({ ok: true });
});

app.get('/api/movements', authRequired, (req, res) => {
  const rows = db
    .prepare(
      `SELECT m.*, p.name as product_name
       FROM movements m
       JOIN products p ON p.id = m.product_id
       ORDER BY m.created_at DESC, m.id DESC
       LIMIT 500`
    )
    .all();
  res.json(rows);
});

app.post('/api/movements', authRequired, (req, res) => {
  const { product_id, type, qty, notes } = req.body;
  const productId = Number(product_id);
  const quantity = Number(qty);

  if (!productId || !['entrada', 'salida_venta', 'salida_uso_interno'].includes(type) || quantity <= 0) {
    return res.status(400).json({ error: 'Invalid movement data / Datos inválidos' });
  }

  const product = db.prepare('SELECT * FROM products WHERE id = ?').get(productId);
  if (!product) return res.status(404).json({ error: 'Product not found / Producto no encontrado' });

  const currentStock = getProductCurrentStock(productId);
  if (type !== 'entrada' && quantity > currentStock) {
    return res.status(400).json({ error: `Insufficient stock / Stock insuficiente. ${currentStock}` });
  }

  const info = db
    .prepare('INSERT INTO movements (product_id, type, qty, notes, created_by) VALUES (?, ?, ?, ?, ?)')
    .run(productId, type, quantity, notes || '', req.session?.username || '');

  const movement = db.prepare('SELECT * FROM movements WHERE id = ?').get(info.lastInsertRowid);
  res.status(201).json({ ...movement, current_stock: getProductCurrentStock(productId) });
});

app.delete('/api/movements/:id', authRequired, (req, res) => {
  const id = Number(req.params.id);
  const existing = db.prepare('SELECT id FROM movements WHERE id = ?').get(id);
  if (!existing) return res.status(404).json({ error: 'Movement not found / Movimiento no encontrado' });

  db.prepare('DELETE FROM movements WHERE id = ?').run(id);
  res.json({ ok: true });
});

app.get('/api/alerts/low-stock', authRequired, (req, res) => {
  const rows = getProductsWithStock().filter((p) => p.current_stock <= p.min_stock);
  res.json(rows);
});

app.get('/api/purchases/suggested', authRequired, (req, res) => {
  const suggestions = getProductsWithStock()
    .filter((p) => p.current_stock <= p.min_stock)
    .map((p) => ({
      product_id: p.id,
      name: p.name,
      current_stock: p.current_stock,
      min_stock: p.min_stock,
      target_stock: p.target_stock,
      suggested_qty: Math.max((p.target_stock || p.min_stock || 0) - p.current_stock, 0),
      estimated_cost: Math.max((p.target_stock || p.min_stock || 0) - p.current_stock, 0) * Number(p.cost || 0),
    }))
    .filter((p) => p.suggested_qty > 0)
    .sort((a, b) => b.suggested_qty - a.suggested_qty);

  res.json(suggestions);
});

app.get('/api/alerts/expiring', authRequired, (req, res) => {
  const products = getProductsWithStock().filter((p) => !!p.expires_at);
  const now = new Date();

  const withDays = products
    .map((p) => {
      const d = new Date(p.expires_at);
      if (Number.isNaN(d.getTime())) return null;
      const days = Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
      return { ...p, days_to_expire: days };
    })
    .filter(Boolean)
    .filter((p) => p.days_to_expire >= 0)
    .sort((a, b) => a.days_to_expire - b.days_to_expire);

  const oneMonth = withDays.filter((p) => p.days_to_expire <= 30);
  const twoMonths = withDays.filter((p) => p.days_to_expire > 30 && p.days_to_expire <= 60);

  res.json({ oneMonth, twoMonths });
});

app.get('/api/dashboard', authRequired, (req, res) => {
  const products = getProductsWithStock();
  const lowStock = products.filter((p) => p.current_stock <= p.min_stock);
  const totalProducts = products.length;
  const totalUnits = products.reduce((acc, p) => acc + Number(p.current_stock || 0), 0);
  const totalValueCost = products.reduce((acc, p) => acc + Number(p.current_stock || 0) * Number(p.cost || 0), 0);

  const movementsByType = db
    .prepare(`SELECT type, COUNT(*) as count, COALESCE(SUM(qty),0) as qty FROM movements GROUP BY type`)
    .all();

  const today = db
    .prepare(
      `SELECT type, COALESCE(SUM(qty),0) as qty
       FROM movements
       WHERE date(created_at) = date('now','localtime')
       GROUP BY type`
    )
    .all();

  res.json({ totalProducts, totalUnits, totalValueCost, lowStockCount: lowStock.length, lowStock, movementsByType, today });
});

app.get('/api/export/excel', authRequired, (req, res) => {
  const products = getProductsWithStock().map((p) => ({
    id: p.id,
    name: p.name,
    brand: p.brand,
    category: p.category,
    barcode: p.barcode,
    unit: p.unit,
    cost: Number(p.cost || 0),
    sale_price: Number(p.sale_price || 0),
    min_stock: p.min_stock,
    target_stock: p.target_stock,
    expires_at: p.expires_at || '',
    current_stock: p.current_stock,
    stock_value_cost: Number(p.current_stock || 0) * Number(p.cost || 0),
  }));

  const movements = db
    .prepare(
      `SELECT m.id, m.created_at, p.name as product_name, m.type, m.qty, m.notes, m.created_by
       FROM movements m
       JOIN products p ON p.id = m.product_id
       ORDER BY m.created_at DESC, m.id DESC`
    )
    .all();

  const alerts = products.filter((p) => Number(p.current_stock) <= Number(p.min_stock));

  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(products), 'Inventory');
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(movements), 'Movements');
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(alerts), 'Alerts');

  const file = XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' });
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');

  res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  res.setHeader('Content-Disposition', `attachment; filename="salon-export-${stamp}.xlsx"`);
  res.send(file);
});

app.post('/api/backup/now', authRequired, adminRequired, (req, res) => {
  backupDb();
  res.json({ ok: true });
});

// Download a full SQLite backup (admin only)
app.get('/api/backup/db', authRequired, adminRequired, (req, res) => {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  const filename = `inventory-backup-${stamp}.db`;
  return res.download(dbPath, filename);
});

app.use((req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

app.listen(PORT, () => {
  console.log(`✅ Salon app running on http://localhost:${PORT}`);
});
