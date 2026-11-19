// Panel de escenarios para la demostración en vivo (botón "Demo" o tecla D).
// Funciona igual con el simulador (mock) y con la API: solo llama a `escenarios`.
// Con la API, primero pide usuario y contraseña en un formulario propio (una vez por sesión).
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
    <form class="demo-acceso" hidden>
      <label>Usuario <input name="usuario" autocomplete="username" required></label>
      <label>Contraseña <input name="clave" type="password" autocomplete="current-password" required></label>
      <button type="submit">Entrar</button>
      <p class="demo-error" role="alert"></p>
    </form>
    <div class="demo-acciones">
      <button data-accion="restablecer">Restablecer todo</button>
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
      <p class="demo-resumen" aria-live="polite"></p>
    </div>`;
  document.body.append(boton, panel);

  const acceso = panel.querySelector('.demo-acceso');
  const acciones = panel.querySelector('.demo-acciones');
  const textoResumen = panel.querySelector('.demo-resumen');

  // Muestra el formulario si hacen falta credenciales; si no, los botones.
  const mostrarAcceso = (error = '') => {
    const pedir = Boolean(escenarios.requiereCredenciales && !escenarios.tieneCredenciales());
    acceso.hidden = !pedir;
    acciones.hidden = pedir;
    acceso.querySelector('.demo-error').textContent = error;
    if (pedir && !panel.hidden) acceso.querySelector('input').focus();
  };

  const resumen = () => {
    const r = escenarios.resumen();
    const activos = r.activos.map((k) => ESCENARIOS[k]).join(', ') || 'Operación normal';
    const desc = r.desconectadas.map((s) => SEDES[s].nombre).join(', ') || 'ninguna';
    textoResumen.textContent = `Activo: ${activos} · Sin conexión: ${desc}`;
  };

  const alternar = async (abrir = panel.hidden) => {
    panel.hidden = !abrir;
    boton.setAttribute('aria-expanded', String(abrir));
    if (!abrir) return;
    mostrarAcceso();
    resumen();
    try {
      await escenarios.actualizar?.(); // con la API: estado real del servidor
      resumen();
    } catch {
      textoResumen.textContent = 'No se pudo leer el estado de la simulación.';
    }
  };

  boton.addEventListener('click', () => alternar());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') return alternar(false);
    const escribiendo = e.target.closest?.('input, select, textarea');
    if (e.key.toLowerCase() === 'd' && !escribiendo && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault(); // si no, la "d" se escribe en el campo Usuario que recibe el foco
      alternar();
    }
  });

  acceso.addEventListener('submit', (e) => {
    e.preventDefault();
    escenarios.guardarCredenciales(acceso.usuario.value, acceso.clave.value);
    acceso.reset();
    mostrarAcceso();
  });

  acciones.addEventListener('click', async (e) => {
    const accion = e.target.closest('[data-accion]')?.dataset.accion;
    if (!accion) return;
    try {
      // desconectar y registrarIncidente usan la sede elegida; el resto la ignora.
      await escenarios[accion](panel.querySelector('#demo-sede').value);
      resumen();
    } catch (err) {
      if (err.name === 'CredencialesInvalidas') mostrarAcceso(err.message);
      else textoResumen.textContent = `No se pudo aplicar: ${err.message}`;
    }
  });

  panel.querySelector('[data-accion="cerrar"]').addEventListener('click', () => alternar(false));
}
