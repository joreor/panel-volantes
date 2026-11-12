# Panel de Rutas — Repartidores de Volantes

Panel web propio para ver **en vivo** dónde están los repartidores, su **ruta del día**,
los **kilómetros recorridos** y para **crear/gestionar repartidores**.

Usa la app móvil **OwnTracks** (gratis, Play Store / App Store) como emisor de GPS en modo HTTP.
No requiere MQTT ni servidores intermedios.

```
Celular (OwnTracks, HTTP POST /pub)
        ↓  HTTPS
Panel Flask (Render)  →  SQLite  →  Mapa Leaflet en el navegador
```

## Qué incluye

| Función | Detalle |
|---|---|
| Mapa en vivo | OpenStreetMap + Leaflet, se actualiza cada 10 s |
| Ruta del día | Línea de recorrido por repartidor, con selector de fecha |
| Kilómetros | Distancia calculada del día (filtra saltos y lecturas imprecisas) |
| Estado | EN VIVO / última conexión, batería, puntos enviados |
| Alta de repartidores | Botón “+ Repartidor” con instrucciones listas para el celular |
| Seguridad | Usuario/contraseña del panel con `PANEL_PASSWORD` (HTTP Basic) |
| Historial | Endpoint `/api/history?username=X&date=YYYY-MM-DD` |

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `PORT` | `8080` | Puerto del servidor (Render lo asigna) |
| `DATA_DIR` | `/data` | Carpeta de la base SQLite |
| `TZ_OFFSET` | `-5` | Offset horario local (Colombia = -5) |
| `ONLINE_SECONDS` | `600` | Segundos sin reportar para marcar “desconectado” |
| `PANEL_PASSWORD` | *(vacío)* | Si se define, el panel pide usuario `admin` + esta clave |

## Desplegar en Render

1. Sube este proyecto a GitHub:
   ```powershell
   cd "C:\proyectos phyton\panel-volantes"
   git init
   git add .
   git commit -m "Panel de rutas de repartidores"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/panel-volantes.git
   git push -u origin main
   ```
2. Render → **New +** → **Blueprint** (detecta `render.yaml`) o **Web Service** con runtime **Docker**.
3. Define `PANEL_PASSWORD` en el dashboard (Environment).
4. Deploy. Health check: `/health`.

## Configurar el celular del repartidor

En la app **OwnTracks** → *Preferencias → Conexión / Identificación*:

| Campo | Valor |
|---|---|
| Modo | `HTTP` |
| Host | `tu-servicio.onrender.com` |
| Puerto | `443` |
| TLS / HTTPS | Activado |
| Usuario | el `username` que muestra el panel (ej. `carlos`) |
| Contraseña | `volantes2026` (no se valida, pero la app la exige) |
| Device ID | `phone` |
| Tracker ID | 2 letras (ej. `CA`) |

Luego pulsar **▶** para iniciar el seguimiento. En Android:
- Permiso de ubicación: **“Permitir todo el tiempo”**.
- Batería: **sin restricciones** para OwnTracks.

El repartidor aparece en el panel con el primer envío (cada ~30–60 s o al moverse).

## Probar localmente

```powershell
cd "C:\proyectos phyton\panel-volantes"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
# abrir http://localhost:5000
```

Simular un envío:

```powershell
curl -X POST "http://localhost:5000/pub?u=carlos&d=phone" `
  -H "Content-Type: application/json" `
  -d '{\"_type\":\"location\",\"lat\":4.65,\"lon\":-74.05,\"tst\":1794516000,\"acc\":10,\"batt\":80}'
```

## Limitaciones de Render Free

- **Disco efímero**: `DATA_DIR=/data` se borra en cada redeploy/reinicio. Sirve para el día;
  para histórico permanente hace falta disco de pago o VPS.
- **Sleep** tras ~15 min sin tráfico: mientras los celulares envían datos se mantiene despierto.
  Para mantenerlo siempre activo, apunta un monitor gratuito (UptimeRobot) a `/health` cada 5 min.

## API

| Método | Ruta | Uso |
|---|---|---|
| `POST` | `/pub` | Recibe ubicaciones de OwnTracks (soporta `?u=`/`?d=` y headers `X-Limit-U/D`) |
| `POST` | `/pub/<token>` | Igual, identificando al repartidor por token |
| `GET` | `/api/state?date=YYYY-MM-DD` | Estado, última posición, tracks y km |
| `GET` | `/api/history?username=X&date=YYYY-MM-DD` | Puntos crudos del día |
| `POST` | `/api/reps` | Crear repartidor `{name, phone}` |
| `DELETE` | `/api/reps/<username>` | Eliminar repartidor e historial |
| `GET` | `/health` | Health check |
