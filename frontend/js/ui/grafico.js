// Gráfico histórico (últimas 24 h) con selector de sede y variable.
// Usa Chart.js global, cargado desde el CDN en dashboard.html.
import { SEDES, VARIABLES } from '../perfiles.js';
import { hora } from './formato.js';

const DIA_MS = 24 * 60 * 60 * 1000;

export function montarGrafico(seccion, perfil, proveedor) {
  const selSede = seccion.querySelector('#hist-sede');
  const selVariable = seccion.querySelector('#hist-variable');
  const lienzo = seccion.querySelector('canvas');

  const opciones = (claves, catalogo) =>
    claves.map((c) => `<option value="${c}">${catalogo[c].nombre}</option>`).join('');
  selSede.innerHTML = opciones(Object.keys(perfil.ver), SEDES);
  const llenarVariables = () => (selVariable.innerHTML = opciones(perfil.ver[selSede.value], VARIABLES));
  llenarVariables();

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  Chart.defaults.color = '#A9B8CE';
  const grafico = new Chart(lienzo, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        data: [], borderColor: '#17A9C9', backgroundColor: 'rgba(23,169,201,.15)',
        fill: true, borderWidth: 2, pointRadius: 0, tension: 0.25,
      }],
    },
    options: {
      locale: 'es-CL',
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,.06)' }, ticks: { maxTicksLimit: 12, autoSkip: true, maxRotation: 0 } },
        y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,.08)' } },
      },
    },
  });

  let ultimoTs = null; // ts más reciente conocido: define la ventana de 24 h
  let cargando = false;

  async function recargar() {
    if (!ultimoTs || cargando) return;
    cargando = true;
    try {
      const desde = new Date(Date.parse(ultimoTs) - DIA_MS).toISOString();
      const serie = await proveedor.getMediciones({ sede: selSede.value, variable: selVariable.value, desde });
      const unidad = serie[0]?.unidad ?? '';
      grafico.data.labels = serie.map((m) => hora(m.ts));
      grafico.data.datasets[0].data = serie.map((m) => m.valor);
      grafico.data.datasets[0].label = `${VARIABLES[selVariable.value].nombre} (${unidad})`;
      grafico.options.scales.y.title = { display: true, text: unidad };
      grafico.update();
    } catch (err) {
      console.error('No se pudo cargar el historial', err);
    } finally {
      cargando = false;
    }
  }

  selSede.addEventListener('change', () => {
    llenarVariables();
    recargar();
  });
  selVariable.addEventListener('change', recargar);

  return {
    // Recibe ítems de estado; recarga solo si incluyen la serie seleccionada.
    actualizar(items) {
      for (const it of items) if (!ultimoTs || Date.parse(it.ts) > Date.parse(ultimoTs)) ultimoTs = it.ts;
      if (items.some((it) => it.sede === selSede.value && it.variable === selVariable.value)) recargar();
    },
  };
}
