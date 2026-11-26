// Carga manual por contingencia (admin, jefatura, prevención): cuando una sede no pudo enviar
// datos, se descarga la plantilla, se llena con las lecturas anotadas y se sube en dos pasos:
// validar (no guarda nada) y confirmar. El servidor decide qué puede cargar cada rol.
import { SEDES } from '../perfiles.js';
import { escapar, numero } from './formato.js';
import { descargar } from './exportar.js';

export function montarCargaManual({ boton, proveedor, sedes }) {
  const dialogo = document.createElement('dialog');
  dialogo.className = 'dialogo dialogo-ancho';
  dialogo.innerHTML = `
    <div class="formulario-incidente">
      <h2>Carga manual (contingencia)</h2>
      <p class="aviso-form">Para cuando una sede no pudo enviar datos (gateway o medidor caído, corte de Internet).
        Anota las lecturas en la plantilla y súbela cuando el sistema vuelva: el historial queda completo.
        Las lecturas atrasadas no abren alertas ni envían correos.</p>

      <h3>1. Descargar plantilla</h3>
      <div class="fila-carga">
        <label>Sede <select name="sede">${sedes.map((s) => `<option value="${s}">${SEDES[s].nombre}</option>`).join('')}</select></label>
        <button type="button" class="btn-salir" data-accion="plantilla">Descargar plantilla</button>
      </div>

      <h3>2. Subir archivo</h3>
      <label class="subir">Archivo CSV (máx. 1 MB y 5.000 filas)
        <input type="file" name="archivo" accept=".csv,text/csv">
      </label>
      <div class="carga-resumen" aria-live="polite"></div>

      <p class="login-error" role="alert"></p>
      <div class="acciones-form">
        <button type="button" class="btn-salir" data-accion="cerrar">Cerrar</button>
        <button type="button" class="btn-principal" data-accion="confirmar" disabled>Confirmar carga</button>
      </div>
    </div>`;
  document.body.append(dialogo);

  const $ = (sel) => dialogo.querySelector(sel);
  const error = $('[role="alert"]');
  const resumen = $('.carga-resumen');
  const botonConfirmar = $('[data-accion="confirmar"]');
  let idCarga = null;

  const reiniciar = () => {
    idCarga = null;
    botonConfirmar.disabled = true;
    resumen.innerHTML = '';
    error.textContent = '';
  };

  function pintarResumen(r) {
    const cifras = `
      <ul class="carga-cifras">
        <li><strong>${numero(r.filas_validas)}</strong> válidas (se guardarán)</li>
        <li><strong>${numero(r.filas_con_error)}</strong> con error</li>
        <li><strong>${numero(r.filas_duplicadas)}</strong> duplicadas (ya existen)</li>
      </ul>
      ${r.desde ? `<p class="ayuda">Período del archivo: ${escapar(r.desde)} a ${escapar(r.hasta)} (hora de Chile) · ${r.sedes.map((s) => SEDES[s]?.nombre ?? s).join(', ')}</p>` : ''}`;
    const tabla = r.errores.length
      ? `<table class="carga-errores">
           <thead><tr><th>Fila</th><th>Motivo</th></tr></thead>
           <tbody>${r.errores.map((e) => `<tr><td>${e.fila}</td><td>${escapar(e.motivo)}</td></tr>`).join('')}</tbody>
         </table>
         ${r.filas_con_error > r.errores.length ? `<p class="ayuda">Se muestran las primeras ${r.errores.length} filas con error.</p>` : ''}`
      : '';
    resumen.innerHTML = cifras + tabla;
  }

  dialogo.addEventListener('click', async (e) => {
    const accion = e.target.closest('[data-accion]')?.dataset.accion;
    if (accion === 'cerrar') dialogo.close();
    if (accion === 'plantilla') {
      error.textContent = '';
      try {
        descargar(await proveedor.plantillaCarga($('[name="sede"]').value));
      } catch (err) {
        error.textContent = `No se pudo descargar la plantilla: ${err.message}`;
      }
    }
    if (accion === 'confirmar' && idCarga) {
      botonConfirmar.disabled = true;
      error.textContent = '';
      try {
        const r = await proveedor.confirmarCarga(idCarga);
        idCarga = null;
        resumen.insertAdjacentHTML('beforeend',
          `<p class="carga-resultado">Carga lista: ${numero(r.guardadas)} lecturas guardadas y ${numero(r.descartadas)} descartadas.</p>`);
        $('[name="archivo"]').value = '';
      } catch (err) {
        error.textContent = `No se pudo confirmar: ${err.message}`;
      }
    }
  });

  $('[name="archivo"]').addEventListener('change', async (e) => {
    const archivo = e.target.files[0];
    reiniciar();
    if (!archivo) return;
    resumen.textContent = 'Revisando el archivo…';
    try {
      const r = await proveedor.validarCarga(archivo);
      pintarResumen(r);
      idCarga = r.id_carga;
      botonConfirmar.disabled = r.filas_validas === 0;
    } catch (err) {
      resumen.innerHTML = '';
      error.textContent = `No se pudo revisar el archivo: ${err.message}`;
    }
  });

  boton.hidden = false;
  boton.addEventListener('click', () => {
    reiniciar();
    $('[name="archivo"]').value = '';
    dialogo.showModal();
  });
}
