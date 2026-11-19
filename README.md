# Induplac · Plataforma IoT de consumos e indicadores

SIY6122 Problemáticas Globales y Prototipado · Duoc UC · Nota 3

```
Medidores (emulados) → Gateway por sede → API REST (HTTPS/JSON + JWT) → Backend FastAPI
  → validación → reglas → PostgreSQL → alertas (WebSocket + correo) → Dashboard
```

| Carpeta | Qué es |
|---|---|
| `gateway/` | Cliente IoT de cada sede. Lee los medidores, arma un lote cada 15 min, lo envía a la API y, si no hay conexión, lo guarda en una cola SQLite en disco para reenviarlo después. Solo Python estándar |
| `backend/` | API REST + WebSocket (FastAPI). Valida, descarta duplicados, guarda en PostgreSQL, evalúa reglas, abre y cierra alertas. Incluye las pruebas automáticas (`backend/tests`) |
| `frontend/` | Dashboard (HTML/JS + Chart.js). Lo sirve la misma API. `js/config.js` → `DATA_SOURCE = 'api'`. Panel **Demo** (tecla D) para manipular los resultados |
| `docker-compose.yml` | PostgreSQL + API; con perfiles, además los 2 gateways y Caddy (HTTPS) |
| `deploy/` | Despliegue en AWS Academy: `user-data.sh`, `verificar.sh` y la [guía paso a paso](deploy/README.md) |
| `.github/workflows/ci.yml` | Pipeline: secretos → SAST → dependencias → pruebas → scripts de despliegue → imágenes Docker |

## Despliegue en AWS (demo de la Nota 3)

Una EC2 con todo adentro (API, base, gateways y HTTPS con Caddy + DuckDNS), creada con un script de User data: ver **[deploy/README.md](deploy/README.md)**.

## Levantar local (PC del equipo)

Requisito: Docker con Docker Compose.

```bash
cp .env.example .env                       # y cambiar los valores CAMBIAR
docker compose up -d --build               # db + api
docker compose --profile gateways up -d    # opcional: + los 2 gateways simulados en contenedores
```

`JWT_SECRET` es obligatorio (32 caracteres o más): sin él la API no arranca. Para generar uno: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

- Dashboard: <http://localhost:8000>. El panel **Demo** pide `DEMO_USUARIO` / `DEMO_CLAVE` del `.env`
- Documentación de la API (Swagger): <http://localhost:8000/docs>
- Salud del sistema: <http://localhost:8000/api/salud>

## Gateways en terminales (alternativa a los contenedores, una por sede)

Requisito: Python 3.10 o superior. En Windows usar `python` en vez de `python3`.

```bash
cd gateway
python3 gateway.py --sede planta     --api http://localhost:8000 --secreto <GATEWAY_PLANTA_SECRET>
python3 gateway.py --sede oficina_rm --api http://localhost:8000 --secreto <GATEWAY_OFICINA_RM_SECRET>
```

La primera vez cada gateway genera 4 semanas de historial (≈ 2.700 lotes) y las envía en bloques de 200. Tarda alrededor de un minuto; después sigue en tiempo acelerado: 3 s reales = 15 min. Para empezar de cero, borrar `cola_*.db` y el volumen de la base (`docker compose down -v`).

## Guion de la demo

En la EC2 se usa el **panel Demo** del dashboard (ver [deploy/README.md](deploy/README.md#panel-demo)). Con los gateways en terminales también sirven estas teclas, que se suman a lo que active el panel:

| Tecla | Escenario | Resultado esperado en el dashboard |
|---|---|---|
| `e` | Pico eléctrico +35% | En 1–4 ciclos la electricidad pasa a **Crítico** y aparece la alerta con el % de exceso |
| `a` | Fuga de agua +60% | Agua pasa a **Crítico** con alerta |
| `u` / `x` | UV 9 / UV 11 | **Advertencia** / **Crítico** (escala OMS) |
| `i` | Incidente | HH sin incidentes vuelve a 0 |
| `n` | Operación normal | En pocos ciclos se cierran las alertas |
| `d` | Cortar enlace | A los 2 ciclos (~6 s) la sede pasa a **Sin datos**; el gateway sigue midiendo y acumula en cola |
| `r` | Reconectar | Llega la cola en orden, sin duplicados, y la sede se normaliza |
| `s` / `q` | Estado / salir | |

También se puede cortar de verdad: apagar el Wi-Fi del notebook donde corre el gateway.

## Pruebas

```bash
cd backend
pip install -r requirements-dev.txt
pytest -v                     # 32 pruebas: reglas, seguridad, validación, ingesta, alertas, sin datos, WebSocket,
                              #             panel Demo, correos de aviso y retención
```

## Contrato de la API

| Método | Ruta | Uso |
|---|---|---|
| POST | `/api/auth/token` | `{gateway_id, secreto}` → token JWT (60 min) |
| POST | `/api/lotes` | Uno o varios lotes `{sede, ts, mediciones:[{variable, valor, unidad}]}`. Requiere `Authorization: Bearer`. Responde `{aceptados, descartados}` |
| GET | `/api/estado` | Último valor y estado de los 8 puntos de medición |
| GET | `/api/alertas?activas=true` | Alertas activas (o el historial con `activas=false`) |
| GET | `/api/mediciones?sede=&variable=&desde=` | Serie para el gráfico |
| GET | `/api/salud` | API, base de datos y última llegada de cada sede |
| GET | `/api/simulacion` | Escenarios de demo activos `{activos, desconectadas}` |
| POST | `/api/simulacion` | `{accion, sede?}`: `normal`, `picoElectrico`, `picoAgua`, `uvAlto`, `desconectar`, `reconectar`, `registrarIncidente`, `restablecer`. Requiere `Authorization: Basic` con `DEMO_USUARIO` / `DEMO_CLAVE` |
| GET | `/api/simulacion/{sede}` | Lo que debe aplicar el gateway en su ciclo. Requiere el Bearer de esa sede |
| WS | `/ws` | Eventos `{tipo: "estado" \| "alerta", data}` |

Códigos: `401` sin token o token inválido (o usuario/contraseña de demo incorrectos) · `403` un gateway intenta enviar datos de otra sede · `422` lote inválido (variable que no existe en la sede, unidad incorrecta, valor fuera de rango, fecha sin zona horaria).

## Reglas

- Electricidad y agua: **Crítico** si el consumo de la última hora supera en 20% el promedio de esa misma hora y día de la semana en las 4 semanas previas.
- UV: **Advertencia** desde 8, **Crítico** desde 11.
- Producción y HH sin incidentes: indicadores.
- Sede sin lotes durante 2 ciclos: todas sus variables en **Sin datos**.
- Correo (Gmail SMTP) al abrirse una alerta crítica que sigue activa al terminar el request, y cuando una sede pasa a sin datos. Máximo 1 por sede y variable cada `ALERTA_ENFRIAMIENTO_MIN` minutos. `ALERTA_DESTINO` vacío = se avisa a `SMTP_USER`.
- Retención: se borran las mediciones con más de `RETENCION_DIAS` (60) días del reloj de las lecturas; nunca menos de las 4 semanas que usa la regla.
