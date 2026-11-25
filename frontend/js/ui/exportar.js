// Exportación a CSV: descarga directa (histórico del gráfico) o diálogo con período (alertas,
// incidentes, auditoría). Mostrar u ocultar botones es solo interfaz: el servidor decide qué entrega.
import { SEDES } from '../perfiles.js';

const DIA_MS = 24 * 60 * 60 * 1000;

// Valor para <input type="datetime-local"> (hora local del navegador).
function aInput(fecha) {
  const d = new Date(fecha);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function descargar({ blob, nombre }) {
  const url = URL.createObjectURL(blob);
  const enlace = Object.assign(document.createElement('a'), { href: url, download: nombre });
  document.body.append(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Descarga y devuelve null, o el mensaje de error de la API en palabras (403, 422…).
export async function exportarCsv(proveedor, recurso, params) {
  try {
    descargar(await proveedor.exportar(recurso, params));
    return null;
  } catch (err) {
    return err.message;
  }
}

/**
 * Botón que abre un diálogo para elegir el período (y la sede, si corresponde) y descargar el CSV.
 * @param {object} o
 * @param {HTMLButtonElement} o.boton
 * @param {string} o.recurso      mediciones | alertas | incidentes | auditoria
 * @param {string} o.titulo
 * @param {string[]} [o.sedes]    sedes para elegir (vacío = sin selector)
 * @param {() => Date} o.ahora    fin del período por defecto (hora simulada o real)
 * @param {number} [o.dias=7]     largo del período por defecto
 * @param {string} [o.nota]       aclaración bajo el título
 */
export function montarExportador({ boton, proveedor, recurso, titulo, sedes = [], ahora, dias = 7, nota = '' }) {
  const dialogo = document.createElement('dialog');
  dialogo.className = 'dialogo';
  dialogo.innerHTML = `
    <form method="dialog" class="formulario-incidente">
      <h2>${titulo}</h2>
      ${nota ? `<p class="aviso-form">${nota}</p>` : ''}
      <label>Desde <input name="desde" type="datetime-local" required></label>
      <label>Hasta <input name="hasta" type="datetime-local" required></label>
      ${sedes.length > 1 ? `<label>Sede
        <select name="sede"><option value="">Todas</option>${sedes.map((s) => `<option value="${s}">${SEDES[s].nombre}</option>`).join('')}</select>
      </label>` : ''}
      <p class="login-error" role="alert"></p>
      <div class="acciones-form">
        <button type="button" value="cancelar" class="btn-salir">Cancelar</button>
        <button type="submit" class="btn-principal">Descargar CSV</button>
      </div>
    </form>`;
  document.body.append(dialogo);
  const form = dialogo.querySelector('form');
  const error = form.querySelector('[role="alert"]');
  form.querySelector('[value="cancelar"]').addEventListener('click', () => dialogo.close());

  boton.hidden = false;
  boton.addEventListener('click', () => {
    const fin = ahora();
    form.hasta.value = aInput(fin);
    form.desde.value = aInput(fin.getTime() - dias * DIA_MS);
    error.textContent = '';
    dialogo.showModal();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const enviar = form.querySelector('[type="submit"]');
    enviar.disabled = true;
    error.textContent = '';
    const mensaje = await exportarCsv(proveedor, recurso, {
      desde: new Date(form.desde.value).toISOString(),
      hasta: new Date(form.hasta.value).toISOString(),
      sede: form.sede?.value,
    });
    enviar.disabled = false;
    if (mensaje) error.textContent = `No se pudo exportar: ${mensaje}`;
    else dialogo.close();
  });
}
