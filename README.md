# Inventario Peluquería (iPad-ready PWA) 💇📲

Aplicación web (Node.js + Express + SQLite) para controlar inventario en salón, optimizada para uso real en iPad/Safari.

## Qué incluye

✅ Login por usuario (admin/invitado)  
✅ Módulos intactos: **Dashboard, Productos, Movimientos, Alertas/Compras**  
✅ Exportación completa a Excel (`Inventory`, `Movements`, `Alerts`)  
✅ Backup diario automático local (`data/backups/`)  
✅ Bilingüe EN/ES (selector en UI)  
✅ PWA: `manifest.webmanifest` + iconos + service worker (cache de shell)  
✅ Instalación a pantalla de inicio (modo app)  
✅ UI táctil mejorada y estética morado/blanco para iPad  
✅ Layout optimizado para iPad portrait/landscape  
✅ Atajos rápidos de movimiento (registro en pocos toques)  
✅ Ajustes para Safari iPad (meta tags Apple + hint de instalación)

---

## Requisitos

- Node.js 18+
- npm

## Instalación y arranque

```bash
cd /Users/maibe/.openclaw/workspace/salon-inventory-mvp
npm install
cp .env.example .env
npm run seed
npm start
```

Abre:

- http://localhost:3000

Login con la contraseña de `.env` (default: `pelu123`).

---

## Flujo rápido en iPad

En pestaña **Movimientos**:

1. Elige tipo rápido: `Venta -1`, `Uso interno -1` o `Entrada +1`
2. Toca producto sugerido (los más críticos aparecen primero)
3. Registro inmediato con 1 toque o abre formulario detallado

Atajo global en topbar: **+ Movimiento**.

---

## Agregar a pantalla de inicio (iPad Safari)

1. Abrir la app en **Safari**
2. Botón **Compartir** (□↑)
3. Tocar **Agregar a pantalla de inicio**
4. Confirmar nombre e instalar
5. Abrir desde el icono para modo app (standalone)

> Nota: en iPad no aparece el prompt de instalación automático como en Android; se hace manual con compartir.

---

## Despliegue simple

### Opción local (recomendada para pruebas en salón)

1. Mac/PC servidor dentro de la misma red Wi‑Fi
2. Ejecutar `npm start`
3. Encontrar IP local del servidor (ej. `192.168.1.50`)
4. Desde iPad abrir `http://192.168.1.50:3000`

Si no abre, permitir puerto 3000 en firewall local.

### Opción nube recomendada (producción simple): **Railway**

1. Subir proyecto a GitHub
2. Crear proyecto en Railway y conectar repo
3. Variables de entorno:
   - `APP_PASSWORD`
   - `SESSION_SECRET`
   - `PORT` (Railway la inyecta; opcional)
4. Deploy automático
5. Abrir URL HTTPS de Railway en iPad y agregar a pantalla de inicio

> Alternativas similares: Render/Fly.io. Railway suele ser la más rápida para este tipo de app Node.

---

## Estructura

- `server.js`: API + sesión + lógica inventario
- `seed.js`: seed con 20 productos ejemplo
- `public/index.html`: interfaz
- `public/app.js`: frontend + atajos + SW register
- `public/styles.css`: estilos táctiles/iPad
- `public/manifest.webmanifest`: metadata PWA
- `public/sw.js`: service worker cache shell
- `public/icons/*`: iconos app y Apple touch icons

---

## Endpoints

- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/products`, `POST /api/products`, `PUT /api/products/:id`, `DELETE /api/products/:id`
- `GET /api/movements`, `POST /api/movements`
- `GET /api/alerts/low-stock`
- `GET /api/purchases/suggested`
- `GET /api/dashboard`

---

## Comandos útiles

```bash
# instalar dependencias
npm install

# crear/recargar base con productos de muestra
npm run seed

# ejecutar servidor
npm start
```

Listo para operar desde iPad sin romper el flujo actual del MVP.