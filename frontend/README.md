# Induplac · Frontend del dashboard IoT

Proyecto académico SIY6122 (Duoc UC). Es solo el frontend: HTML, CSS y JavaScript con módulos ES, sin framework ni paso de compilación. Por ahora usa datos simulados. En la EVA 3 se conectará al backend FastAPI sin cambiar la interfaz.

## Cómo correrlo

Desde esta carpeta (`frontend/`):

```bash
python3 -m http.server 8000
```

En Windows, si `python3` no existe, usa `python -m http.server 8000`.

Abre <http://localhost:8000>, elige un perfil y el dashboard empezará a actualizarse solo. Cada 3 segundos reales equivalen a 15 minutos simulados.

> Debe abrirse con un servidor. Si se abre el archivo directo (`file://`), los módulos ES no cargan.

## Perfiles (demo, sin contraseña)

| Perfil | Ve |
|---|---|
| Jefatura de operaciones | Ambas sedes, todas las variables |
| Prevención de riesgos | HH sin incidentes de ambas sedes + UV de la planta |
| Personal Oficina RM | Solo Oficina RM |
| Personal Planta | Solo Planta Valparaíso |

## Panel de demo

Se abre con el botón **Demo** (esquina inferior derecha) o con la tecla **D**, y se cierra con **Esc**. Solo aparece cuando `DATA_SOURCE = 'mock'`.

| Escenario | Qué pasa |
|---|---|
| Operación normal | Apaga los picos y el UV alto; en pocos ciclos se cierran las alertas |
| Pico eléctrico en la Planta | +35% por intervalo. Como la regla mira el consumo de la última hora, pasa a **Crítico** en 3–4 ciclos (~10 s) y genera alerta |
| Pico de agua en la Oficina RM | +60% (fuga simulada). Pasa a **Crítico** en ~2 ciclos y genera alerta |
| UV alto en la Planta | El índice llega a 9 y pasa a **Advertencia**, con alerta |
| Registrar incidente | Deja en 0 el contador de HH sin incidentes de la sede elegida |
| Desconectar sede | El gateway de la sede elegida deja de enviar lotes. A los 2 ciclos (~6 s) toda la sede muestra **Sin datos** con la hora del último lote |
| Reconectar | Llegan en orden los lotes acumulados, sin duplicados, y el estado se normaliza |

Los picos y el UV alto se pueden combinar.

## Estructura

```
index.html          Entrada: marca + selección de perfil
dashboard.html      Dashboard
css/styles.css
js/config.js        DATA_SOURCE, API_BASE_URL, WS_URL, TICK_MS
js/data/index.js    Exporta el proveedor según DATA_SOURCE
js/data/mock.js     Proveedor simulado (usa simulator.js)
js/data/api.js      Proveedor real: fetch + WebSocket (listo para la EVA 3)
js/simulator.js     Lecturas, reglas, alertas y escenarios de la demo
js/perfiles.js      Nombres visibles y perfiles
js/app.js, js/ui/   Solo dibujan la interfaz, sin reglas de negocio
```

La UI nunca calcula estados: pinta el campo `estado` que le entrega el proveedor. Las reglas viven en `simulator.js`, que imita al backend.

## Contrato de datos (mock y api son iguales)

| Función | Endpoint | Respuesta |
|---|---|---|
| `getEstado()` | `GET /api/estado` | `[{ sede, variable, valor, unidad, estado, ts }]` |
| `getAlertas({ activas: true })` | `GET /api/alertas?activas=true` | `[{ id, sede, variable, nivel, mensaje, ts, activa }]` |
| `getMediciones({ sede, variable, desde })` | `GET /api/mediciones?sede=&variable=&desde=` | `[{ sede, variable, valor, unidad, ts }]` |
| `suscribir(callback)` | WebSocket `WS_URL` | eventos `{ tipo: "estado" \| "alerta", data }` |

- `sede`: `"oficina_rm"` o `"planta"`
- `estado`: `"normal"`, `"advertencia"`, `"critico"` o `"sin_datos"`
- `ts`: fecha y hora en ISO 8601
- En los eventos, `data` puede ser un objeto o una lista. Una alerta con `activa: false` sale del panel.
- Campos opcionales en `/api/estado` que la tarjeta muestra como subtítulo:
  - `uv`: `max_dia` (máximo del día)
  - `produccion`: `acumulado_dia` y `acumulado_mes`

### Lotes del gateway (entrada del backend)

Cada sede envía un lote por ciclo (cada 15 min):

```json
{ "sede": "planta", "ts": "2026-10-14T18:00:00.000Z",
  "mediciones": [{ "variable": "electricidad", "valor": 142.3, "unidad": "kWh" }, ...] }
```

El backend descarta los lotes duplicados o atrasados: solo acepta el lote si su `ts` es más nuevo que el último recibido de esa sede.

## Paso de 'mock' a 'api' (EVA 3)

1. En `js/config.js`, cambia `DATA_SOURCE` a `'api'`.
2. Si FastAPI sirve este frontend desde el mismo dominio, deja `API_BASE_URL = ''` y el `WS_URL` por defecto (`/ws` en el mismo host). Si la API está en otro dominio, pon ahí su URL (y habilita CORS en FastAPI).
3. Ejemplo para servir el frontend desde FastAPI:

   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
   ```

   Monta los estáticos **después** de declarar las rutas `/api/*` y `/ws`.
4. El backend debe respetar el contrato de arriba y aplicar las reglas que hoy están en `simulator.js`:
   - Electricidad y agua: crítico si el consumo de la última hora supera en 20% el promedio de esa misma hora y día de la semana en las 4 semanas previas.
   - UV: advertencia si es ≥ 8 y crítico si es ≥ 11; incluir `max_dia`.
   - Producción: solo indicador; incluir `acumulado_dia` y `acumulado_mes`.
   - HH sin incidentes: solo indicador; se actualiza una vez al día y vuelve a 0 al registrar un incidente.
   - Sin lotes de una sede durante 2 ciclos: todas sus variables pasan a `sin_datos`.

Con `'api'`, el simulador no se carga y el panel de demo no aparece. El indicador del header muestra **En línea** o **Reconectando…**. Cada vez que el WebSocket se reconecta, la UI vuelve a pedir el estado y las alertas.
