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
pytest -v                     # 64 pruebas (incluye exportación CSV y carga manual): reglas (incluye piso del agua y línea detenida), seguridad, validación,
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
| GET | `/api/auditoria?limite=` | Admin: logins, cambios de la consola, incidentes y exportaciones |
| GET | `/api/carga-manual/plantilla?sede=` | Plantilla CSV de la sede (admin, jefatura, prevencion). Ver [Carga manual](#carga-manual-por-contingencia) |
| POST | `/api/carga-manual/validar` | Multipart, campo `archivo`: revisa el CSV sin guardar y devuelve el resumen y un `id_carga` (15 min) |
| POST | `/api/carga-manual/confirmar` | `{id_carga}`: guarda las filas válidas y no duplicadas → `{guardadas, descartadas}` |
| GET | `/api/exportar/{recurso}?desde=&hasta=&sede=&variable=` | CSV de `mediciones`, `alertas` (todos los roles, con su filtro), `incidentes` (admin, jefatura, prevencion) o `auditoria` (admin). Ver [Exportación CSV](#exportación-csv) |
| WS | `/ws?token=` | Eventos `{tipo: "estado" \| "alerta" \| "incidente", data}` filtrados por rol. Sin token válido → cierre 4401 |

Códigos: `401` sin token, token inválido o de otro tipo (usuario ↔ gateway) · `403` el rol no tiene permiso · `403` un gateway intenta enviar datos de otra sede · `422` lote inválido (variable que no existe en la sede, unidad incorrecta, valor fuera de rango, fecha sin zona horaria).

## Exportación CSV

`GET /api/exportar/{recurso}` entrega solo lo que el usuario ya puede ver en pantalla (mismo filtro por rol que la consulta). En el dashboard: **Descargar CSV** (histórico del gráfico), **Exportar alertas**, **Exportar incidentes** y, en la consola del admin, **Exportar auditoría**.

- `desde` y `hasta`: obligatorios, ISO 8601 con zona horaria, período de 90 días como máximo. Mediciones y alertas usan la hora de las lecturas (simulada en la demo); incidentes y auditoría, la hora real.
- `sede` (`oficina_rm` o `planta`) opcional; `variable` opcional, solo para mediciones y alertas.
- Formato para Excel en Chile: UTF-8 con BOM, separador `;`, decimales con coma y fechas `YYYY-MM-DD HH:MM` en hora de Chile. Las celdas de texto que empiezan con `=`, `+`, `-`, `@`, tabulación o retorno de carro llevan un `'` al inicio (protección contra inyección CSV).
- Respuestas: `401` sin token o con token de gateway · `403` recurso, sede o variable fuera del rol · `422` período faltante, invertido o mayor a 90 días, o variable que no existe en la sede.
- Cada exportación queda en la auditoría (usuario, recurso, período, sede y cantidad de filas).

Ejemplo con `curl` (token del login):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json'   -d '{"usuario":"jefatura","clave":"<USUARIOS_CLAVE>"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -G -OJ http://localhost:8000/api/exportar/mediciones -H "Authorization: Bearer $TOKEN"   --data-urlencode "desde=2026-11-18T00:00:00-03:00" --data-urlencode "hasta=2026-11-25T00:00:00-03:00"   -d sede=planta -d variable=electricidad
```

`-OJ` guarda el archivo con el nombre que indica la API (`induplac_mediciones_planta_2026-11-18_2026-11-25.csv`).

## Carga manual por contingencia

Para cuando una sede no puede enviar datos automáticamente (gateway o medidor caído, corte largo de Internet). Si la plataforma completa está caída, la plantilla se llena sin conexión y se sube cuando vuelve.

1. **Anotar** las lecturas a mano durante la contingencia (cada 15 minutos: 00, 15, 30 y 45).
2. **Descargar la plantilla**: botón **Carga manual** del header → elegir la sede → **Descargar plantilla**.
3. **Llenarla**: una fila por variable y hora, `fecha_hora;sede;variable;valor;unidad`, con la hora de Chile (`AAAA-MM-DD HH:MM`) y decimales con coma. Las líneas que empiezan con `#` (instrucciones y ejemplos) se ignoran. Es el mismo formato de la exportación de mediciones: un CSV exportado se puede volver a cargar.
4. **Validar**: **Subir archivo**. Muestra cuántas filas son válidas, cuáles tienen error (fila y motivo) y cuántas ya existían. No guarda nada.
5. **Confirmar**: **Confirmar carga** (antes de 15 minutos). Guarda solo las filas válidas y no duplicadas.

Reglas: las mismas validaciones del gateway (variable de la sede, unidad, rango físico), minutos del ciclo, ni en el futuro ni con más de 90 días según el reloj de la plataforma, archivo de máximo 1 MB y 5.000 filas. Admin y jefatura cargan todo; prevención solo HH sin incidentes. Las lecturas atrasadas completan el historial (la regla del +20% las usa como referencia) pero no cambian el estado actual, no abren alertas y no envían correos. Cada validación y confirmación queda en la auditoría.

Ejemplo con `curl`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json'   -d '{"usuario":"jefatura","clave":"<USUARIOS_CLAVE>"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -OJ "http://localhost:8000/api/carga-manual/plantilla?sede=planta" -H "Authorization: Bearer $TOKEN"
# … llenar el CSV …
ID=$(curl -s http://localhost:8000/api/carga-manual/validar -H "Authorization: Bearer $TOKEN"   -F "archivo=@induplac_plantilla_carga_planta.csv" | python3 -c 'import json,sys;r=json.load(sys.stdin);print(r);print(r["id_carga"])' | tail -n 1)
curl -s http://localhost:8000/api/carga-manual/confirmar -H "Authorization: Bearer $TOKEN"   -H 'Content-Type: application/json' -d "{\"id_carga\":\"$ID\"}"
```

## Reglas

- Electricidad y agua: **Crítico** si el consumo de la última hora supera en 20% el promedio de esa misma hora y día de la semana en las 4 semanas previas **y** el exceso absoluto llega al piso de la sede (10% del consumo horario típico en turno: electricidad RM 9 kWh, Planta 56 kWh; agua RM 48 L, Planta 360 L). Evita falsos positivos con consumos bajos.
- UV: **Advertencia** desde 8, **Crítico** desde 11.
- Producción: **Advertencia** "Línea de producción detenida desde hh:mm" si es 0 en 2 lecturas seguidas dentro del turno (L–S 6–22 h). Se cierra sola al volver a producir.
- HH sin incidentes: indicador; vuelve a 0 al registrar un incidente en la sede.
- Sede sin lotes durante 2 ciclos: todas sus variables en **Sin datos**.
- Correo (Gmail SMTP) al abrirse una alerta crítica que sigue activa al terminar el request, y cuando una sede pasa a sin datos. Máximo 1 por sede y variable cada `ALERTA_ENFRIAMIENTO_MIN` minutos. `ALERTA_DESTINO` vacío = se avisa a `SMTP_USER`.
- Retención: se borran las mediciones con más de `RETENCION_DIAS` (60) días del reloj de las lecturas; nunca menos de las 4 semanas que usa la regla.
