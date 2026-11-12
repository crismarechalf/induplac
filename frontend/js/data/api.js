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
