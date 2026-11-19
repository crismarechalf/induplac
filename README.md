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
| `frontend/` | Dashboard (HTML/JS + Chart.js). Lo sirve la misma API. `js/config.js` → `DATA_SOURCE = 'api'`. Login con roles, **Consola de operación** (admin) y **Registrar incidente** (prevención) |
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

- Dashboard: <http://localhost:8000>. Usuarios: `admin` (`ADMIN_CLAVE`) y `jefatura`, `prevencion`, `personal_rm`, `personal_planta` (`USUARIOS_CLAVE`). Ver [deploy/README.md](deploy/README.md#usuarios)
- Documentación de la API (Swagger): <http://localhost:8000/docs>
- Salud del sistema: <http://localhost:8000/api/salud>

## Gateways en terminales (alternativa a los contenedores, una por sede)

Requisito: Python 3.10 o superior. En Windows usar `python` en vez de `python3`.

```bash
cd gateway
python3 gateway.py --sede planta     --api http://127.0.0.1:8000 --secreto <GATEWAY_PLANTA_SECRET>
python3 gateway.py --sede oficina_rm --api http://127.0.0.1:8000 --secreto <GATEWAY_OFICINA_RM_SECRET>
```

La primera vez cada gateway genera 4 semanas de historial (≈ 2.700 lotes) y las envía en bloques de 200. Tarda alrededor de un minuto; después sigue en tiempo acelerado: 3 s reales = 15 min. Para empezar de cero, borrar `cola_*.db` y el volumen de la base (`docker compose down -v`).

## Guion de la demo

En la EC2 se usa la **Consola de operación** del dashboard (usuario `admin`, ver [deploy/README.md](deploy/README.md#consola-de-operación-solo-admin)). Con los gateways en terminales también sirven estas teclas, que se suman a lo que active la consola:

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
pytest -v                     # 48 pruebas: reglas (incluye piso del agua y línea detenida), seguridad, validación,
                              #   ingesta, alertas, sin datos, WebSocket, login y roles, consola, incidentes,
                              #   reloj único, auditoría, correos de aviso y retención
```

## Contrato de la API

| Método | Ruta | Uso |
|---|---|---|
| POST | `/api/auth/token` | Gateway: `{gateway_id, secreto}` → token JWT tipo `gateway` (60 min) |
| POST | `/api/auth/login` | Usuario: `{usuario, clave}` → token JWT tipo `usuario` (8 h) + perfil (rol, vista, permisos). 5 fallos en 5 min → 429 |
| GET | `/api/yo` | Perfil del usuario del token |
| POST | `/api/lotes` | Uno o varios lotes `{sede, ts, mediciones:[{variable, valor, unidad}]}`. Requiere `Authorization: Bearer`. Responde `{aceptados, descartados}` |
| GET | `/api/estado` | Último valor y estado de los puntos que el rol puede ver (token de usuario) |
| GET | `/api/alertas?activas=true` | Alertas del rol (o el historial con `activas=false`) |
| GET | `/api/mediciones?sede=&variable=&desde=` | Serie para el gráfico, filtrada por rol |
| GET | `/api/incidentes` | Últimos incidentes (prevención, jefatura, admin) |
| POST | `/api/incidentes` | `{sede, ts, tipo, descripcion}` (prevención, admin). Reinicia las HH de la sede, correo y evento WS |
| GET | `/api/reloj` | Hora simulada única `{hora_simulada, factor}` (cualquier token) |
| GET | `/api/salud` | Público: API, base de datos y última llegada de cada sede (sin datos de negocio) |
| GET | `/api/simulacion` | Consola (admin): estado de las 2 sedes, controles de cada una y registro de acciones |
| PUT | `/api/simulacion/{sede}` | Consola (admin): `{electricidad_pct, agua_pct, produccion_pct, uv_forzado, enlace_cortado}`, todos opcionales |
| POST | `/api/simulacion/restablecer` | Consola (admin): todo en "Automático" |
| GET | `/api/simulacion/{sede}` | Gateway (Bearer de esa sede): lo que aplica en su ciclo + `incidente_id` |
| GET | `/api/auditoria?limite=` | Admin: logins, cambios de la consola e incidentes |
| WS | `/ws?token=` | Eventos `{tipo: "estado" \| "alerta" \| "incidente", data}` filtrados por rol. Sin token válido → cierre 4401 |

Códigos: `401` sin token, token inválido o de otro tipo (usuario ↔ gateway) · `403` el rol no tiene permiso · `403` un gateway intenta enviar datos de otra sede · `422` lote inválido (variable que no existe en la sede, unidad incorrecta, valor fuera de rango, fecha sin zona horaria).

## Reglas

- Electricidad y agua: **Crítico** si el consumo de la última hora supera en 20% el promedio de esa misma hora y día de la semana en las 4 semanas previas **y** el exceso absoluto llega al piso de la sede (10% del consumo horario típico en turno: electricidad RM 9 kWh, Planta 56 kWh; agua RM 48 L, Planta 360 L). Evita falsos positivos con consumos bajos.
- UV: **Advertencia** desde 8, **Crítico** desde 11.
- Producción: **Advertencia** "Línea de producción detenida desde hh:mm" si es 0 en 2 lecturas seguidas dentro del turno (L–S 6–22 h). Se cierra sola al volver a producir.
- HH sin incidentes: indicador; vuelve a 0 al registrar un incidente en la sede.
- Sede sin lotes durante 2 ciclos: todas sus variables en **Sin datos**.
- Correo (Gmail SMTP) al abrirse una alerta crítica que sigue activa al terminar el request, y cuando una sede pasa a sin datos. Máximo 1 por sede y variable cada `ALERTA_ENFRIAMIENTO_MIN` minutos. `ALERTA_DESTINO` vacío = se avisa a `SMTP_USER`.
- Retención: se borran las mediciones con más de `RETENCION_DIAS` (60) días del reloj de las lecturas; nunca menos de las 4 semanas que usa la regla.
