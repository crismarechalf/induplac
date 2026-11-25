// Proveedor real: backend FastAPI vía fetch + WebSocket, con el token del usuario.
// Mismo contrato de lectura que mock.js. Se activa con DATA_SOURCE = 'api' en config.js.
// El servidor filtra todo según el rol del token: el frontend nunca filtra datos.
import { API_BASE_URL, WS_URL } from '../config.js';
import { leerSesion, sesionExpirada } from '../sesion.js';

// Petición con el token Bearer. 401 → la sesión venció: de vuelta al login.
async function pedir(ruta, { metodo = 'GET', params = {}, cuerpo } = {}) {
  const url = new URL(API_BASE_URL + ruta, location.href);
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== undefined && valor !== null && valor !== '') url.searchParams.set(clave, valor);
  }
  const headers = { Accept: 'application/json' };
  const token = leerSesion()?.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (cuerpo !== undefined) headers['Content-Type'] = 'application/json';
  const respuesta = await fetch(url, { method: metodo, headers, body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) });
  if (respuesta.status === 401 && token) {
    sesionExpirada();
    throw new Error('Sesión vencida');
  }
  if (!respuesta.ok) {
    const detalle = await respuesta.json().catch(() => ({}));
    throw Object.assign(new Error(mensajeError(detalle, respuesta.status)), { status: respuesta.status });
  }
  return respuesta.json();
}

// FastAPI responde { detail: "texto" } o { detail: [{ msg }] } (validación).
function mensajeError(detalle, status) {
  if (typeof detalle.detail === 'string') return detalle.detail;
  if (Array.isArray(detalle.detail)) return detalle.detail.map((d) => d.msg).join('. ');
  return `El servidor respondió ${status}`;
}

// ---------- Sesión ----------
// POST /api/auth/login → { access_token, usuario: { usuario, nombre, rol, rol_nombre, vista, permisos } }
export async function login(usuario, clave) {
  const r = await pedir('/api/auth/login', { metodo: 'POST', cuerpo: { usuario, clave } });
  return { token: r.access_token, usuario: r.usuario };
}

// GET /api/yo → perfil actualizado del usuario del token
export const yo = () => pedir('/api/yo');

// ---------- Lectura (filtrada por rol en el servidor) ----------
// GET /api/estado → [{ sede, variable, valor, unidad, estado, ts }]
export const getEstado = () => pedir('/api/estado');

// GET /api/alertas?activas=true → [{ id, sede, variable, nivel, mensaje, ts, activa }]
export const getAlertas = ({ activas } = {}) => pedir('/api/alertas', { params: { activas } });

// GET /api/mediciones?sede=&variable=&desde= → [{ sede, variable, valor, unidad, ts }]
export const getMediciones = ({ sede, variable, desde } = {}) =>
  pedir('/api/mediciones', { params: { sede, variable, desde } });

// GET /api/reloj → { hora_simulada, factor }
export const getReloj = () => pedir('/api/reloj');

// ---------- Incidentes ----------
export const getIncidentes = () => pedir('/api/incidentes', { params: { limite: 5 } });
export const registrarIncidente = (datos) => pedir('/api/incidentes', { metodo: 'POST', cuerpo: datos });

// ---------- Exportación CSV ----------
// GET /api/exportar/{recurso}?desde=&hasta=&sede=&variable= → { blob, nombre }
// Lleva el token en la cabecera, por eso no sirve un enlace directo: se baja como blob.
export async function exportar(recurso, params) {
  const url = new URL(`${API_BASE_URL}/api/exportar/${recurso}`, location.href);
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== undefined && valor !== null && valor !== '') url.searchParams.set(clave, valor);
  }
  const token = leerSesion()?.token;
  const respuesta = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (respuesta.status === 401 && token) {
    sesionExpirada();
    throw new Error('Sesión vencida');
  }
  if (!respuesta.ok) {
    const detalle = await respuesta.json().catch(() => ({}));
    throw Object.assign(new Error(mensajeError(detalle, respuesta.status)), { status: respuesta.status });
  }
  const nombre = /filename="([^"]+)"/.exec(respuesta.headers.get('Content-Disposition') ?? '')?.[1] ?? `induplac_${recurso}.csv`;
  return { blob: await respuesta.blob(), nombre };
}

// ---------- Consola de operación (solo admin) ----------
export const consola = {
  obtener: () => pedir('/api/simulacion'),
  cambiar: (sede, cambios) => pedir(`/api/simulacion/${sede}`, { metodo: 'PUT', cuerpo: cambios }),
  restablecer: () => pedir('/api/simulacion/restablecer', { metodo: 'POST' }),
};

// ---------- Tiempo real ----------
// WebSocket con reconexión automática (espera creciente hasta 30 s).
// Eventos: { tipo: 'estado' | 'alerta' | 'incidente', data }, ya filtrados por rol en el servidor.
// onConexion recibe 'conectado' | 'reconectando'; la UI vuelve a pedir el estado al reconectar.
// Cierre 4401 = token inválido o vencido → login.
export function suscribir(callback, onConexion = () => {}) {
  let ws;
  let espera = 1000;
  let temporizador;
  let cancelado = false;

  const conectar = () => {
    ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(leerSesion()?.token ?? '')}`);
    ws.onopen = () => {
      espera = 1000;
      onConexion('conectado');
    };
    ws.onmessage = (e) => {
      try {
        callback(JSON.parse(e.data));
      } catch (err) {
        console.error('Evento WebSocket inválido', err);
      }
    };
    ws.onclose = (e) => {
      if (cancelado) return;
      if (e.code === 4401) return sesionExpirada();
      onConexion('reconectando');
      temporizador = setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30000);
    };
  };

  conectar();
  return () => {
    cancelado = true;
    clearTimeout(temporizador);
    ws?.close();
  };
}
