const path = require('path');
const Database = require('better-sqlite3');

const db = new Database(path.join(__dirname, 'data', 'inventory.db'));

db.exec(`
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
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
  );
`);

const products = [
  ['Shampoo Hidratante 1L', 'LOréal', 'Shampoo', '750100100001', 'botella', 9.5, 18, 5, 12, 10],
  ['Acondicionador Reparador 1L', 'LOréal', 'Acondicionador', '750100100002', 'botella', 10, 19, 5, 12, 9],
  ['Mascarilla Nutritiva 500ml', 'Kérastase', 'Tratamiento', '750100100003', 'frasco', 18, 35, 3, 8, 6],
  ['Tinte Rubio Cenizo 7.1', 'Wella', 'Coloración', '750100100004', 'caja', 4.2, 9, 8, 20, 15],
  ['Tinte Castaño 5.0', 'Wella', 'Coloración', '750100100005', 'caja', 4.2, 9, 8, 20, 14],
  ['Oxidante 20 vol 1L', 'Wella', 'Coloración', '750100100006', 'botella', 6, 12, 4, 10, 8],
  ['Oxidante 30 vol 1L', 'Wella', 'Coloración', '750100100007', 'botella', 6, 12, 4, 10, 7],
  ['Spray Protector Térmico 250ml', 'Schwarzkopf', 'Styling', '750100100008', 'spray', 7.5, 16, 4, 10, 8],
  ['Mousse Volumen 300ml', 'Schwarzkopf', 'Styling', '750100100009', 'lata', 6.8, 15, 4, 10, 7],
  ['Cera Moldeadora 100g', 'American Crew', 'Styling', '750100100010', 'tarro', 5.5, 13, 5, 14, 10],
  ['Gel Fijador Fuerte 500ml', 'Nioxin', 'Styling', '750100100011', 'botella', 5, 11, 5, 14, 11],
  ['Ampolla Anticaída', 'Keranove', 'Tratamiento', '750100100012', 'unidad', 2.8, 7, 10, 25, 20],
  ['Sérum Puntas 60ml', 'Moroccanoil', 'Tratamiento', '750100100013', 'frasco', 9, 20, 3, 9, 6],
  ['Peine Carbono Corte', 'Eurostil', 'Herramientas', '750100100014', 'unidad', 1.2, 4, 6, 15, 12],
  ['Guantes Nitrilo Talla M (100)', 'ProSafe', 'Desechables', '750100100015', 'caja', 6.5, 14, 3, 8, 5],
  ['Toallas Desechables (50)', 'CleanPro', 'Desechables', '750100100016', 'paquete', 4, 9, 4, 10, 8],
  ['Alcohol Isopropílico 500ml', 'CleanPro', 'Higiene', '750100100017', 'botella', 3.2, 8, 4, 10, 7],
  ['Champú Matizante Violeta 300ml', 'Fanola', 'Shampoo', '750100100018', 'botella', 8, 17, 4, 10, 8],
  ['Aceite Argan 100ml', 'Moroccanoil', 'Tratamiento', '750100100019', 'frasco', 11, 24, 3, 8, 5],
  ['Laca Fijación Extra 400ml', 'Taft', 'Styling', '750100100020', 'spray', 4.8, 10, 5, 14, 10],
];

const count = db.prepare('SELECT COUNT(*) as c FROM products').get().c;
if (count > 0) {
  console.log('Seed omitido: ya existen productos.');
  process.exit(0);
}

const insert = db.prepare(`
  INSERT INTO products (name, brand, category, barcode, unit, cost, sale_price, min_stock, target_stock, initial_stock)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
`);

const insertMove = db.prepare(`
  INSERT INTO movements (product_id, type, qty, notes)
  VALUES (?, ?, ?, ?)
`);

const tx = db.transaction(() => {
  for (const p of products) {
    const info = insert.run(...p);
    const id = info.lastInsertRowid;
    insertMove.run(id, 'entrada', Math.floor(Math.random() * 5) + 1, 'Reposición inicial');
    if (Math.random() > 0.35) insertMove.run(id, 'salida_venta', Math.floor(Math.random() * 4) + 1, 'Venta mostrador');
    if (Math.random() > 0.6) insertMove.run(id, 'salida_uso_interno', 1, 'Uso en servicio');
  }
});

tx();
console.log('✅ Seed completado con 20 productos de peluquería.');