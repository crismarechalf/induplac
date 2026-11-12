// Simulador de Induplac. Tiene dos mitades que imitan al sistema real:
//   1. Gateway de cada sede: genera un lote de mediciones por ciclo.
//   2. Backend: recibe lotes, evalúa estados, crea alertas y emite eventos.
// Todas las reglas de negocio viven aquí (y en EVA 3, en el backend); la UI solo pinta.
import { TICK_MS } from './config.js';

const PASO_MS = 15 * 60 * 1000;            // cada ciclo avanza 15 minutos simulados
const HORA_MS = 60 * 60 * 1000;
const DIA_MS = 24 * HORA_MS;
const SEMANA_MS = 7 * DIA_MS;
const SEMANAS_REFERENCIA = 4;              // semanas previas para el promedio de consumo
const UMBRAL_CONSUMO = 1.2;                // crítico si supera en 20% la referencia
const UV_ADVERTENCIA = 8;
const UV_CRITICO = 11;
const CICLOS_SIN_DATOS = 2;                // ciclos sin lotes antes de marcar la sede 'sin_datos'
const RETENCION_MS = 48 * HORA_MS;         // mediciones que se conservan para el gráfico
const RETENCION_SERIE_MS = SEMANAS_REFERENCIA * SEMANA_MS + DIA_MS;

// Puntos de medición: sede → variable → unidad (8 en total).
const PUNTOS = {
  oficina_rm: { electricidad: 'kWh', agua: 'L', hh_sin_incidentes: 'h' },
  planta: { electricidad: 'kWh', agua: 'L', produccion: 'tableros', hh_sin_incidentes: 'h', uv: 'índice' },
};
const VARIABLES_CONSUMO = ['electricidad', 'agua'];
const DIAS_SEMANA = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

const ruido = (p) => 1 + (Math.random() * 2 - 1) * p;
const redondear = (v, d) => Math.round(v * 10 ** d) / 10 ** d;
const diaLocal = (f) => `${f.getFullYear()}-${f.getMonth()}-${f.getDate()}`;
const mesLocal = (f) => `${f.getFullYear()}-${f.getMonth()}`;
const nf = (v, d) => v.toLocaleString('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });

// =====================================================================
// 1. GATEWAY (sensores de cada sede)
// =====================================================================

// Turnos: días de la semana (0 = domingo) y horario en que hay personal.
const TURNO = {
  oficina_rm: { dias: [1, 2, 3, 4, 5], desde: 8, hasta: 19 },
  planta: { dias: [1, 2, 3, 4, 5, 6], desde: 6, hasta: 22 },
};
const DOTACION = { oficina_rm: 25, planta: 80 };

// Consumo base por intervalo de 15 min: [en turno, fuera de turno].
const BASE = {
  electricidad: { oficina_rm: [22, 7], planta: [140, 60] },
  agua: { oficina_rm: [120, 10], planta: [900, 200] },
};

const enTurno = (sede, fecha) => {
  const t = TURNO[sede];
  const h = fecha.getHours();
  return t.dias.includes(fecha.getDay()) && h >= t.desde && h < t.hasta;
};

// Escenarios de demo activos (se pueden combinar).
const demo = { picoElectrico: false, picoAgua: false, uvAlto: false };

const hh = { oficina_rm: 18450, planta: 96320 };
const hhDia = {}; // día local en que se actualizó el contador por última vez

// HH sin incidentes: se actualiza una vez por día simulado, sumando las
// horas-hombre del día anterior si fue día de trabajo.
function actualizarHH(sede, fecha) {
  const dia = diaLocal(fecha);
  if (hhDia[sede] !== undefined && hhDia[sede] !== dia) {
    const t = TURNO[sede];
    const ayer = (fecha.getDay() + 6) % 7;
    if (t.dias.includes(ayer)) hh[sede] += DOTACION[sede] * (t.hasta - t.desde);
  }
  hhDia[sede] = dia;
}

function generar(sede, variable, fecha) {
  const turno = enTurno(sede, fecha) ? 0 : 1;
  switch (variable) {
    case 'electricidad': {
      let v = BASE.electricidad[sede][turno] * ruido(0.08);
      if (demo.picoElectrico && sede === 'planta') v *= 1.35;
      return redondear(v, 1);
    }
    case 'agua': {
      let v = BASE.agua[sede][turno] * ruido(0.15);
      if (demo.picoAgua && sede === 'oficina_rm') v *= 1.6; // fuga simulada
      return Math.round(v);
    }
    case 'produccion':
      return turno === 0 ? Math.round(45 * ruido(0.15)) : 0;
    case 'hh_sin_incidentes':
      return hh[sede];
    case 'uv': {
      if (demo.uvAlto) return 9; // escenario de demo: fuerza UV alto aunque sea de noche
      const h = fecha.getHours() + fecha.getMinutes() / 60;
      if (h < 7 || h > 19) return 0;
      return redondear(Math.min(7.6, 7.4 * Math.sin((Math.PI * (h - 7)) / 12) * ruido(0.05)), 1);
    }
  }
}

// Un lote por sede y por ciclo: { sede, ts, mediciones: [{ variable, valor, unidad }] }
function generarLote(sede, fecha) {
  actualizarHH(sede, fecha);
  return {
    sede,
    ts: fecha.toISOString(),
    mediciones: Object.entries(PUNTOS[sede]).map(([variable, unidad]) => ({
      variable, valor: generar(sede, variable, fecha), unidad,
    })),
  };
}

// =====================================================================
// 2. BACKEND (recepción de lotes, reglas, alertas)
// =====================================================================

let mediciones = [];
const serie = new Map();         // 'sede|variable|ms' → valor (consumos, ~4 semanas)
const estado = new Map();        // 'sede|variable' → { sede, variable, valor, unidad, estado, ts, ...extras }
const alertas = [];
const alertaAbierta = new Map(); // 'sede|variable' → alerta activa
const produccion = {};           // sede → acumulados del día y del mes
const uvMax = {};                // sede → máximo UV del día
const sedes = {
  oficina_rm: { conectada: true, buffer: [], ultimoLote: null, ultimoEntregado: null },
  planta: { conectada: true, buffer: [], ultimoLote: null, ultimoEntregado: null },
};
const oyentes = new Set();
let siguienteId = 1;
let temporizador = null;

// Consumo de la hora que termina en finMs (suma de 4 intervalos). null si falta alguno.
function consumoHora(sede, variable, finMs) {
  let total = 0;
  for (let i = 0; i < 4; i++) {
    const v = serie.get(`${sede}|${variable}|${finMs - i * PASO_MS}`);
    if (v === undefined) return null;
    total += v;
  }
  return total;
}

// Promedio de la misma hora y día de la semana en las 4 semanas previas.
function referenciaHora(sede, variable, finMs) {
  const previas = [];
  for (let k = 1; k <= SEMANAS_REFERENCIA; k++) {
    const c = consumoHora(sede, variable, finMs - k * SEMANA_MS);
    if (c !== null) previas.push(c);
  }
  return previas.length ? previas.reduce((a, b) => a + b, 0) / previas.length : null;
}

function evaluar({ sede, variable, valor, ts }) {
  if (VARIABLES_CONSUMO.includes(variable)) {
    // Electricidad y agua: crítico si el consumo de la hora supera en 20% el promedio
    // de esa misma hora y día de la semana de las 4 semanas previas.
    const ms = Date.parse(ts);
    const actual = consumoHora(sede, variable, ms);
    const referencia = referenciaHora(sede, variable, ms);
    if (actual === null || !referencia) return 'normal';
    return actual > referencia * UMBRAL_CONSUMO ? 'critico' : 'normal';
  }
  if (variable === 'uv') {
    if (valor >= UV_CRITICO) return 'critico';
    if (valor >= UV_ADVERTENCIA) return 'advertencia';
  }
  // Producción y HH: solo indicadores.
  return 'normal';
}

function mensajeAlerta({ sede, variable, valor, unidad, ts, estado: nivel }) {
  if (VARIABLES_CONSUMO.includes(variable)) {
    const ms = Date.parse(ts);
    const actual = consumoHora(sede, variable, ms);
    const ref = referenciaHora(sede, variable, ms);
    const exceso = Math.round((actual / ref - 1) * 100);
    const d = variable === 'agua' ? 0 : 1;
    return `Consumo de la última hora (${nf(actual, d)} ${unidad}) supera en ${exceso}% el promedio de los ${DIAS_SEMANA[new Date(ms).getDay()]} a esta hora en las 4 semanas previas (${nf(ref, d)} ${unidad}).`;
  }
  if (variable === 'uv') {
    return nivel === 'critico'
      ? `Índice UV ${nf(valor, 1)}: radiación extrema, evitar trabajos en exteriores.`
      : `Índice UV ${nf(valor, 1)}: radiación muy alta, usar protección solar en exteriores.`;
  }
  return `Valor fuera de rango: ${nf(valor, 1)}.`;
}

// Datos adicionales que el backend agrega a ciertas variables.
function extras({ sede, variable, valor }, fecha) {
  if (variable === 'produccion') {
    const p = (produccion[sede] ??= { dia: null, mes: null, hoy: 0, enMes: 0 });
    if (p.dia !== diaLocal(fecha)) Object.assign(p, { dia: diaLocal(fecha), hoy: 0 });
    if (p.mes !== mesLocal(fecha)) Object.assign(p, { mes: mesLocal(fecha), enMes: 0 });
    p.hoy += valor;
    p.enMes += valor;
    return { acumulado_dia: p.hoy, acumulado_mes: p.enMes };
  }
  if (variable === 'uv') {
    const m = (uvMax[sede] ??= { dia: null, max: 0 });
    if (m.dia !== diaLocal(fecha)) Object.assign(m, { dia: diaLocal(fecha), max: valor });
    else m.max = Math.max(m.max, valor);
    return { max_dia: m.max };
  }
  return {};
}

const copia = (o) => ({ ...o });

function emitir(evento) {
  for (const fn of oyentes) fn(evento);
}

function cerrarAlerta(clave) {
  const a = alertaAbierta.get(clave);
  a.activa = false;
  alertaAbierta.delete(clave);
  emitir({ tipo: 'alerta', data: copia(a) });
}

function actualizarAlerta(item) {
  const clave = `${item.sede}|${item.variable}`;
  const abierta = alertaAbierta.get(clave);
  if (item.estado === 'critico' || item.estado === 'advertencia') {
    if (abierta?.nivel === item.estado) return;
    if (abierta) cerrarAlerta(clave);
    const a = {
      id: String(siguienteId++), sede: item.sede, variable: item.variable,
      nivel: item.estado, mensaje: mensajeAlerta(item), ts: item.ts, activa: true,
    };
    alertas.push(a);
    alertaAbierta.set(clave, a);
    emitir({ tipo: 'alerta', data: copia(a) });
  } else if (abierta && item.estado === 'normal') {
    cerrarAlerta(clave);
  }
}

// Recibe un lote del gateway. Descarta lotes duplicados o atrasados: solo
// acepta uno si es más nuevo que el último lote recibido de esa sede.
function ingerirLote(lote) {
  const s = sedes[lote.sede];
  const ms = Date.parse(lote.ts);
  if (s.ultimoLote !== null && ms <= s.ultimoLote) return;
  s.ultimoLote = ms;
  const fecha = new Date(ms);
  for (const { variable, valor, unidad } of lote.mediciones) {
    const lectura = { sede: lote.sede, variable, valor, unidad, ts: lote.ts };
    mediciones.push(lectura);
    if (VARIABLES_CONSUMO.includes(variable)) serie.set(`${lote.sede}|${variable}|${ms}`, valor);
    const item = { ...lectura, estado: evaluar(lectura), ...extras(lectura, fecha) };
    estado.set(`${lote.sede}|${variable}`, item);
    actualizarAlerta(item);
  }
}

// Sin lotes durante 2 ciclos: toda la sede pasa a 'sin_datos', con la hora del último lote.
function revisarSinDatos(sede) {
  const s = sedes[sede];
  if (ahora - s.ultimoLote < CICLOS_SIN_DATOS * PASO_MS) return;
  for (const variable of Object.keys(PUNTOS[sede])) {
    const clave = `${sede}|${variable}`;
    estado.set(clave, { ...estado.get(clave), estado: 'sin_datos', ts: new Date(s.ultimoLote).toISOString() });
  }
}

function podar() {
  const limite = ahora - RETENCION_MS;
  mediciones = mediciones.filter((m) => Date.parse(m.ts) >= limite);
  if ((ahora / PASO_MS) % 96 !== 0) return; // la serie de consumos se poda una vez al día
  const limiteSerie = ahora - RETENCION_SERIE_MS;
  for (const clave of serie.keys()) {
    if (Number(clave.slice(clave.lastIndexOf('|') + 1)) < limiteSerie) serie.delete(clave);
  }
}

const emitirEstado = () => emitir({ tipo: 'estado', data: obtenerEstado() });

// =====================================================================
// Reloj simulado
// =====================================================================

let ahora;

function tick() {
  ahora += PASO_MS;
  const fecha = new Date(ahora);
  for (const [sede, s] of Object.entries(sedes)) {
    const lote = generarLote(sede, fecha);
    if (s.conectada) {
      ingerirLote(lote);
      s.ultimoEntregado = lote;
    } else {
      s.buffer.push(lote); // el gateway sigue midiendo pero no logra enviar
    }
    revisarSinDatos(sede);
  }
  podar();
  emitirEstado();
}

function reprogramar() {
  clearInterval(temporizador);
  temporizador = setInterval(tick, TICK_MS);
}

// Historial inicial: 4 semanas + 1 h (para tener referencia de consumo) o desde el
// inicio del mes si es antes (para el acumulado mensual de producción).
// Sin oyentes todavía, así que no emite nada.
{
  const ahoraReal = Math.floor(Date.now() / PASO_MS) * PASO_MS;
  const inicioMes = new Date(ahoraReal);
  inicioMes.setDate(1);
  inicioMes.setHours(0, 0, 0, 0);
  ahora = Math.min(ahoraReal - SEMANAS_REFERENCIA * SEMANA_MS - HORA_MS, inicioMes.getTime()) - PASO_MS;
  while (ahora < ahoraReal) tick();
}

// =====================================================================
// API pública (la usa data/mock.js)
// =====================================================================

export function obtenerEstado() {
  return [...estado.values()].map(copia);
}

export function obtenerAlertas({ activas } = {}) {
  return alertas.filter((a) => !activas || a.activa).map(copia);
}

export function obtenerMediciones({ sede, variable, desde } = {}) {
  const t0 = desde ? Date.parse(desde) : -Infinity;
  return mediciones
    .filter((m) => (!sede || m.sede === sede) && (!variable || m.variable === variable) && Date.parse(m.ts) >= t0)
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
    .map(copia);
}

export function suscribir(fn) {
  oyentes.add(fn);
  if (!temporizador) reprogramar();
  return () => oyentes.delete(fn);
}

// Aplica un cambio con un ciclo inmediato para que se vea sin esperar.
const aplicar = () => {
  tick();
  reprogramar();
};

// Escenarios del panel de demo.
export const escenarios = {
  normal() {
    for (const k of Object.keys(demo)) demo[k] = false;
    aplicar();
  },
  picoElectrico() {
    demo.picoElectrico = true;
    aplicar();
  },
  picoAgua() {
    demo.picoAgua = true;
    aplicar();
  },
  uvAlto() {
    demo.uvAlto = true;
    aplicar();
  },
  registrarIncidente(sede) {
    if (!(sede in hh)) return;
    hh[sede] = 0;
    aplicar();
  },
  desconectar(sede) {
    if (sedes[sede]) sedes[sede].conectada = false;
  },
  // Entrega los lotes acumulados en orden. Simula además que el gateway reenvía su
  // último lote ya entregado: ingerirLote() lo descarta, así no hay duplicados.
  reconectar() {
    for (const s of Object.values(sedes)) {
      if (s.conectada) continue;
      for (const lote of [s.ultimoEntregado, ...s.buffer]) ingerirLote(lote);
      s.ultimoEntregado = s.buffer.at(-1) ?? s.ultimoEntregado;
      Object.assign(s, { conectada: true, buffer: [] });
    }
    emitirEstado();
  },
  resumen() {
    return {
      activos: Object.keys(demo).filter((k) => demo[k]),
      desconectadas: Object.keys(sedes).filter((s) => !sedes[s].conectada),
    };
  },
};
