// Proveedor real (EVA 3): backend FastAPI vía fetch + WebSocket.
// Mismo contrato que mock.js. Aún no se usa: se activa con DATA_SOURCE = 'api' en config.js.
import { API_BASE_URL, WS_URL } from '../config.js';

// GET con parámetros de consulta; omite los que vienen vacíos.
async function obtener(ruta, params = {}) {
  const url = new URL(API_BASE_URL + ruta, location.href);
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== undefined && valor !== null && valor !== '') url.searchParams.set(clave, valor);
  }
  const respuesta = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!respuesta.ok) throw new Error(`${ruta} respondió ${respuesta.status}`);
  return respuesta.json();
}

// GET /api/estado → [{ sede, variable, valor, unidad, estado, ts }]
export const getEstado = () => obtener('/api/estado');

// GET /api/alertas?activas=true → [{ id, sede, variable, nivel, mensaje, ts, activa }]
export const getAlertas = ({ activas } = {}) => obtener('/api/alertas', { activas });

// GET /api/mediciones?sede=&variable=&desde= → [{ sede, variable, valor, unidad, ts }]
export const getMediciones = ({ sede, variable, desde } = {}) =>
  obtener('/api/mediciones', { sede, variable, desde });

// WebSocket con reconexión automática (espera creciente hasta 30 s).
// Cada mensaje del servidor debe ser JSON: { tipo: 'estado' | 'alerta', data }.
// onConexion recibe 'conectado' | 'reconectando' para el indicador del header;
// la UI vuelve a pedir el estado completo al reconectar, por si se perdieron eventos.
export function suscribir(callback, onConexion = () => {}) {
  let ws;
  let espera = 1000;
  let temporizador;
  let cancelado = false;

  const conectar = () => {
    ws = new WebSocket(WS_URL);
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
    ws.onclose = () => {
      if (cancelado) return;
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

// ---------- Panel "Demo" (manipular resultados durante la presentación) ----------
// Misma interfaz que `escenarios` del simulador (mock.js), más el manejo de credenciales.
// POST /api/simulacion exige usuario y contraseña (DEMO_USUARIO / DEMO_CLAVE del servidor),
// que viajan en la cabecera Authorization: Basic y se guardan solo en sessionStorage.

const CLAVE_SESION = 'induplac.demo';
let credencialesEnMemoria = null; // respaldo si el navegador bloquea sessionStorage
let ultimoResumen = { activos: [], desconectadas: [] };

function leerCredenciales() {
  try {
    return sessionStorage.getItem(CLAVE_SESION) ?? credencialesEnMemoria;
  } catch {
    return credencialesEnMemoria;
  }
}

function borrarCredenciales() {
  credencialesEnMemoria = null;
  try {
    sessionStorage.removeItem(CLAVE_SESION);
  } catch {
    /* sin almacenamiento: basta con la memoria */
  }
}

async function simular(accion, sede) {
  const respuesta = await fetch(new URL(API_BASE_URL + '/api/simulacion', location.href), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Basic ${leerCredenciales() ?? ''}` },
    body: JSON.stringify(sede ? { accion, sede } : { accion }),
  });
  if (respuesta.status === 401) {
    borrarCredenciales();
    // demo.js reconoce este nombre y vuelve a mostrar el formulario.
    throw Object.assign(new Error('Usuario o contraseña incorrectos'), { name: 'CredencialesInvalidas' });
  }
  if (!respuesta.ok) throw new Error(`/api/simulacion respondió ${respuesta.status}`);
  ultimoResumen = await respuesta.json();
  return ultimoResumen;
}

export const escenarios = {
  requiereCredenciales: true,
  tieneCredenciales: () => Boolean(leerCredenciales()),
  guardarCredenciales(usuario, clave) {
    // btoa solo acepta latin-1: se pasa por UTF-8 para admitir tildes y ñ.
    const bytes = new TextEncoder().encode(`${usuario}:${clave}`);
    credencialesEnMemoria = btoa(String.fromCharCode(...bytes));
    try {
      sessionStorage.setItem(CLAVE_SESION, credencialesEnMemoria);
    } catch {
      /* queda en memoria mientras la página esté abierta */
    }
  },
  // Trae el resumen al abrir el panel; resumen() lo devuelve de forma síncrona.
  async actualizar() {
    ultimoResumen = await obtener('/api/simulacion');
    return ultimoResumen;
  },
  resumen: () => ultimoResumen,
  normal: () => simular('normal'),
  picoElectrico: () => simular('picoElectrico'),
  picoAgua: () => simular('picoAgua'),
  uvAlto: () => simular('uvAlto'),
  desconectar: (sede) => simular('desconectar', sede),
  registrarIncidente: (sede) => simular('registrarIncidente', sede),
  reconectar: () => simular('reconectar'),
  restablecer: () => simular('restablecer'),
};
