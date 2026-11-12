// Panel de escenarios para la demostración en vivo (botón "Demo" o tecla D).
// Solo llama a los controles del simulador; app.js no lo monta en modo 'api'.
import { SEDES } from '../perfiles.js';

const ESCENARIOS = { picoElectrico: 'Pico eléctrico', picoAgua: 'Pico de agua', uvAlto: 'UV alto' };

export function montarDemo(escenarios) {
  const boton = document.createElement('button');
  boton.className = 'btn-demo';
  boton.textContent = 'Demo';
  boton.title = 'Escenarios de demostración (tecla D)';
  boton.setAttribute('aria-expanded', 'false');

  const panel = document.createElement('aside');
  panel.className = 'panel-demo';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Escenarios de demostración');
  panel.innerHTML = `
    <div class="demo-cabecera">
      <h2>Escenarios de demo</h2>
      <button class="btn-cerrar" data-accion="cerrar" aria-label="Cerrar panel">×</button>
    </div>
    <button data-accion="normal">Operación normal</button>
    <button data-accion="picoElectrico">Pico eléctrico en la Planta</button>
    <button data-accion="picoAgua">Pico de agua en la Oficina RM</button>
    <button data-accion="uvAlto">UV alto en la Planta</button>
    <label class="demo-sede">Sede
      <select id="demo-sede">${Object.entries(SEDES).map(([id, s]) => `<option value="${id}">${s.nombre}</option>`).join('')}</select>
    </label>
    <div class="demo-fila">
      <button data-accion="desconectar">Desconectar</button>
      <button data-accion="registrarIncidente">Registrar incidente</button>
    </div>
    <button data-accion="reconectar">Reconectar</button>
    <p class="demo-resumen" aria-live="polite"></p>`;
  document.body.append(boton, panel);

  const resumen = () => {
    const r = escenarios.resumen();
    const activos = r.activos.map((k) => ESCENARIOS[k]).join(', ') || 'Operación normal';
    const desc = r.desconectadas.map((s) => SEDES[s].nombre).join(', ') || 'ninguna';
    panel.querySelector('.demo-resumen').textContent = `Activo: ${activos} · Sin conexión: ${desc}`;
  };

  const alternar = (abrir = panel.hidden) => {
    panel.hidden = !abrir;
    boton.setAttribute('aria-expanded', String(abrir));
    if (abrir) resumen();
  };

  boton.addEventListener('click', () => alternar());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') return alternar(false);
    const escribiendo = e.target.closest?.('input, select, textarea');
    if (e.key.toLowerCase() === 'd' && !escribiendo && !e.ctrlKey && !e.metaKey && !e.altKey) alternar();
  });

  panel.addEventListener('click', (e) => {
    const accion = e.target.closest('[data-accion]')?.dataset.accion;
    if (!accion) return;
    if (accion === 'cerrar') return alternar(false);
    // desconectar y registrarIncidente usan la sede elegida; el resto la ignora.
    escenarios[accion](panel.querySelector('#demo-sede').value);
    resumen();
  });
}
