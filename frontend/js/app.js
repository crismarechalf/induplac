// Orquestador del dashboard: conecta el proveedor de datos con los componentes de UI.
// No contiene reglas de negocio ni filtra datos: el servidor entrega solo lo que el rol puede ver.
import { proveedor } from './data/index.js';
import { cerrarSesion, guardarSesion, leerSesion, tienePermiso } from './sesion.js';
import { montarSedes, pintarEstado } from './ui/tarjetas.js';
import { pintarAlertas } from './ui/alertas.js';
import { montarGrafico } from './ui/grafico.js';
import { montarConsola } from './ui/consola.js';
import { montarFormularioIncidente, montarIncidentes } from './ui/incidentes.js';
import { hora } from './ui/formato.js';

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

// Reloj de simulación único (lo manda el servidor). Se sincroniza cada 30 s y avanza localmente
// con el factor entre medio, para que "Hora simulada" se vea fluida.
function montarReloj() {
  let base = null; // { simulada: ms, real: ms, factor }
  const sincronizar = async () => {
    try {
      const r = await proveedor.getReloj();
      base = { simulada: Date.parse(r.hora_simulada), real: Date.now(), factor: r.factor };
    } catch (err) {
      console.error('No se pudo leer el reloj', err);
    }
  };
  const actual = () => (base ? new Date(base.simulada + (Date.now() - base.real) * base.factor) : null);
  sincronizar();
  setInterval(sincronizar, 30000);
  setInterval(() => {
    const h = actual();
    if (h) $('#hora-simulada').textContent = hora(h);
  }, 1000);
  return actual;
}

if (!leerSesion()) location.replace('index.html');
else iniciar();

async function iniciar() {
  // Perfil vigente según el servidor (si el token venció, api.js lleva de vuelta al login).
  const actualizado = await proveedor.yo().catch(() => null);
  if (actualizado) guardarSesion({ ...leerSesion(), usuario: actualizado });
  const { usuario } = leerSesion();

  $('#usuario-nombre').textContent = usuario.nombre;
  $('#usuario-rol').textContent = usuario.rol_nombre;
  $('#salir').addEventListener('click', () => {
    cerrarSesion();
    location.replace('index.html');
  });

  // La vista (sedes y variables) la define el rol en el servidor.
  const perfil = { ver: usuario.vista };
  montarSedes($('#sedes'), perfil);
  const grafico = montarGrafico($('#historico'), perfil, proveedor);
  const alertas = new Map();
  const repintarAlertas = () => pintarAlertas($('#lista-alertas'), $('#total-alertas'), alertas.values());
  const ultimos = new Map(); // último estado de cada punto, para la consola

  const horaSimulada = proveedor.getReloj ? montarReloj() : () => null;
  if (!proveedor.getReloj) $('.hora-simulada').hidden = true;

  const incidentes = tienePermiso('incidentes_ver') && proveedor.getIncidentes
    ? montarIncidentes($('#incidentes'), proveedor) : null;
  if (tienePermiso('incidentes_registrar') && proveedor.registrarIncidente) {
    montarFormularioIncidente($('#btn-incidente'), proveedor);
  }
  const consola = tienePermiso('consola') && proveedor.consola
    ? montarConsola({
        boton: $('#btn-consola'),
        proveedor,
        valorActual: (sede, variable) => ultimos.get(`${sede}|${variable}`),
        horaSimulada,
      })
    : null;

  function aplicarEstado(items) {
    pintarEstado(items);
    for (const it of items) ultimos.set(`${it.sede}|${it.variable}`, it);
    consola?.actualizarValores();
  }

  // Carga completa: al inicio y cada vez que el WebSocket se reconecta.
  async function sincronizar() {
    try {
      const [estado, activas] = await Promise.all([proveedor.getEstado(), proveedor.getAlertas({ activas: true })]);
      aplicarEstado(estado);
      alertas.clear();
      activas.forEach((a) => alertas.set(a.id, a));
      repintarAlertas();
      grafico.actualizar(estado);
      incidentes?.cargar();
    } catch (err) {
      console.error('No se pudo sincronizar', err);
      pintarConexion('error');
    }
  }

  // Eventos en tiempo real, ya filtrados por rol en el servidor. `data` puede venir como objeto o lista.
  proveedor.suscribir(
    (evento) => {
      const datos = [].concat(evento.data);
      if (evento.tipo === 'estado') {
        aplicarEstado(datos);
        grafico.actualizar(datos);
      } else if (evento.tipo === 'alerta') {
        for (const a of datos) a.activa ? alertas.set(a.id, a) : alertas.delete(a.id);
        repintarAlertas();
      } else if (evento.tipo === 'incidente') {
        datos.forEach((i) => incidentes?.agregar(i));
      }
    },
    (estadoConexion) => {
      pintarConexion(estadoConexion);
      if (estadoConexion === 'conectado') sincronizar();
    },
  );

  await sincronizar();
}
