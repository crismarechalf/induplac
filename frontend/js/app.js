// Orquestador del dashboard: conecta el proveedor de datos con los componentes de UI.
// No contiene reglas de negocio: los estados y alertas llegan calculados del proveedor.
import { DATA_SOURCE } from './config.js';
import { proveedor } from './data/index.js';
import { PERFILES, leerPerfil, borrarPerfil, puedeVer } from './perfiles.js';
import { montarSedes, pintarEstado } from './ui/tarjetas.js';
import { pintarAlertas } from './ui/alertas.js';
import { montarGrafico } from './ui/grafico.js';
import { montarDemo } from './ui/demo.js';

const $ = (sel) => document.querySelector(sel);

const TEXTO_CONEXION = {
  simulado: 'Datos simulados',
  conectado: 'En línea',
  reconectando: 'Reconectando…',
  error: 'Sin conexión con el servidor',
};

function pintarConexion(estado) {
  const el = $('#conexion');
  el.dataset.conexion = estado;
  el.querySelector('.conexion-texto').textContent = TEXTO_CONEXION[estado];
}

const perfil = PERFILES[leerPerfil()];
if (!perfil) location.replace('index.html');
else iniciar();

async function iniciar() {
  $('#perfil-nombre').textContent = perfil.nombre;
  $('#salir').addEventListener('click', () => {
    borrarPerfil();
    location.href = 'index.html';
  });

  // Filtro de visibilidad por perfil (qué se muestra, no cómo se evalúa).
  const visible = (x) => puedeVer(perfil, x.sede, x.variable);

  montarSedes($('#sedes'), perfil);
  const grafico = montarGrafico($('#historico'), perfil, proveedor);
  const alertas = new Map();
  const repintarAlertas = () => pintarAlertas($('#lista-alertas'), $('#total-alertas'), alertas.values());

  // Carga completa: al inicio y cada vez que el WebSocket se reconecta.
  async function sincronizar() {
    try {
      const [estado, activas] = await Promise.all([proveedor.getEstado(), proveedor.getAlertas({ activas: true })]);
      pintarEstado(estado.filter(visible));
      alertas.clear();
      activas.filter(visible).forEach((a) => alertas.set(a.id, a));
      repintarAlertas();
      grafico.actualizar(estado);
    } catch (err) {
      console.error('No se pudo sincronizar', err);
      pintarConexion('error');
    }
  }

  // Eventos en tiempo real. `data` puede venir como objeto o como lista.
  proveedor.suscribir(
    (evento) => {
      const datos = [].concat(evento.data);
      if (evento.tipo === 'estado') {
        pintarEstado(datos.filter(visible));
        grafico.actualizar(datos);
      } else if (evento.tipo === 'alerta') {
        for (const a of datos.filter(visible)) a.activa ? alertas.set(a.id, a) : alertas.delete(a.id);
        repintarAlertas();
      }
    },
    (estadoConexion) => {
      pintarConexion(estadoConexion);
      if (estadoConexion === 'conectado') sincronizar();
    },
  );

  await sincronizar();

  // El panel de demo existe solo con el simulador.
  if (DATA_SOURCE === 'mock' && proveedor.escenarios) montarDemo(proveedor.escenarios);
}
