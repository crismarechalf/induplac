// Registro de incidentes (prevención de riesgos y admin) y tarjeta "Incidentes recientes".
import { SEDES } from '../perfiles.js';
import { escapar } from './formato.js';

const TIPOS = ['Accidente con tiempo perdido', 'Accidente sin tiempo perdido', 'Cuasi accidente'];

const fechaHora = (ts) =>
  new Date(ts).toLocaleString('es-CL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

// Valor para <input type="datetime-local"> con la hora local actual.
function ahoraLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

// Tarjeta con los últimos 5 incidentes (los entrega el servidor ya filtrados por rol).
export function montarIncidentes(seccion, proveedor) {
  const lista = seccion.querySelector('#lista-incidentes');
  let incidentes = [];
  seccion.hidden = false;

  const pintar = () => {
    lista.innerHTML = incidentes.length
      ? incidentes
          .map(
            (i) => `
        <li class="incidente">
          <div class="alerta-cabecera"><strong>${escapar(i.tipo)}</strong><time datetime="${escapar(i.ts)}">${fechaHora(i.ts)}</time></div>
          <span class="incidente-sede">${escapar(SEDES[i.sede]?.nombre ?? i.sede)} · registrado por ${escapar(i.registrado_por)}</span>
          <p>${escapar(i.descripcion)}</p>
        </li>`,
          )
          .join('')
      : '<li class="vacio">Sin incidentes registrados</li>';
  };

  return {
    async cargar() {
      try {
        incidentes = await proveedor.getIncidentes();
        pintar();
      } catch (err) {
        console.error('No se pudieron leer los incidentes', err);
      }
    },
    agregar(incidente) {
      incidentes = [incidente, ...incidentes.filter((i) => i.id !== incidente.id)].slice(0, 5);
      pintar();
    },
  };
}

// Formulario modal para registrar un incidente. Al guardar, el servidor reinicia las HH de la sede.
export function montarFormularioIncidente(boton, proveedor) {
  const dialogo = document.createElement('dialog');
  dialogo.className = 'dialogo';
  dialogo.innerHTML = `
    <form method="dialog" class="formulario-incidente">
      <h2>Registrar incidente</h2>
      <label>Sede
        <select name="sede" required>
          <option value="">Elegir…</option>
          ${Object.entries(SEDES).map(([id, s]) => `<option value="${id}">${s.nombre}</option>`).join('')}
        </select>
      </label>
      <label>Fecha y hora <input name="ts" type="datetime-local" required></label>
      <label>Tipo
        <select name="tipo" required>${TIPOS.map((t) => `<option>${t}</option>`).join('')}</select>
      </label>
      <label>Descripción
        <textarea name="descripcion" rows="4" minlength="10" maxlength="500" required
          placeholder="Qué pasó, dónde y a quién (10 a 500 caracteres)"></textarea>
        <span class="contador-texto">0 / 500</span>
      </label>
      <p class="aviso-form">Al registrarlo, las HH sin incidentes de la sede vuelven a 0 y se envía un aviso por correo.</p>
      <p class="login-error" role="alert"></p>
      <div class="acciones-form">
        <button type="button" value="cancelar" class="btn-salir">Cancelar</button>
        <button type="submit" class="btn-principal">Registrar</button>
      </div>
    </form>`;
  document.body.append(dialogo);

  const form = dialogo.querySelector('form');
  const error = form.querySelector('[role="alert"]');
  const contador = form.querySelector('.contador-texto');
  form.descripcion.addEventListener('input', () => (contador.textContent = `${form.descripcion.value.length} / 500`));
  form.querySelector('[value="cancelar"]').addEventListener('click', () => dialogo.close());

  boton.hidden = false;
  boton.addEventListener('click', () => {
    form.reset();
    form.ts.value = ahoraLocal();
    form.ts.max = ahoraLocal();
    contador.textContent = '0 / 500';
    error.textContent = '';
    dialogo.showModal();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const enviar = form.querySelector('[type="submit"]');
    enviar.disabled = true;
    try {
      await proveedor.registrarIncidente({
        sede: form.sede.value,
        ts: new Date(form.ts.value).toISOString(),
        tipo: form.tipo.value,
        descripcion: form.descripcion.value.trim(),
      });
      dialogo.close(); // la tarjeta se actualiza con el evento WebSocket "incidente"
    } catch (err) {
      error.textContent = `No se pudo registrar: ${err.message}`;
    } finally {
      enviar.disabled = false;
    }
  });
}
