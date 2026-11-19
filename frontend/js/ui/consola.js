// Consola de operación y pruebas (solo admin): panel lateral para ajustar cada variable de cada sede.
// Cada cambio se aplica al soltar el deslizador o al hacer click (un PUT por cambio, sin botón "Aplicar").
// Los controles que existen en cada sede los decide el servidor (la Oficina RM no tiene producción ni UV).
import { SEDES, VARIABLES } from '../perfiles.js';
import { escapar, hora, insignia, numero } from './formato.js';

const AYUDA_CONSUMO = 'Alerta crítica si la última hora supera +20% del promedio de 4 semanas';

const CONTROLES = {
  electricidad_pct: { variable: 'electricidad', etiqueta: 'Variación del consumo', min: -50, max: 100, paso: 5,
    base: 0, atajos: [0, 25, 50], ayuda: AYUDA_CONSUMO },
  agua_pct: { variable: 'agua', etiqueta: 'Variación del consumo', min: -50, max: 100, paso: 5,
    base: 0, atajos: [0, 25, 50], ayuda: AYUDA_CONSUMO },
  produccion_pct: { variable: 'produccion', etiqueta: 'Ritmo de la línea', min: 0, max: 150, paso: 10, base: 100,
    ayuda: 'Advertencia si la línea está detenida en turno durante 2 lecturas' },
  uv_forzado: { variable: 'uv', ayuda: 'Escala OMS: ≥ 8 advertencia, ≥ 11 crítico' },
  enlace_cortado: { ayuda: 'Cortado: la sede sigue midiendo y guarda en su cola; el dashboard la marca Sin datos a los 2 ciclos' },
};

const pct = (v, base) => (base === 0 && v > 0 ? `+${v}%` : `${v}%`);

export function montarConsola({ boton, proveedor, valorActual, horaSimulada }) {
  const panel = document.createElement('aside');
  panel.className = 'consola';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Consola de operación y pruebas');
  panel.innerHTML = `
    <div class="consola-cabecera">
      <div>
        <h2>Consola de operación y pruebas</h2>
        <p class="consola-reloj"></p>
      </div>
      <button class="btn-cerrar" aria-label="Cerrar consola">×</button>
    </div>
    <div class="pestanas" role="tablist">
      ${Object.entries(SEDES).map(([id, s], i) => `<button role="tab" data-sede="${id}" aria-selected="${i === 0}">${s.nombre}</button>`).join('')}
    </div>
    <div class="consola-controles" role="tabpanel"></div>
    <button class="btn-restablecer">Restablecer todo</button>
    <p class="consola-estado" role="status"></p>
    <h3>Registro de acciones</h3>
    <ol class="consola-registro"></ol>`;
  document.body.append(panel);

  const contenedor = panel.querySelector('.consola-controles');
  const textoEstado = panel.querySelector('.consola-estado');
  let datos = null; // respuesta de GET /api/simulacion
  let sede = 'oficina_rm';

  // ---------- render ----------
  function textoActual(variable) {
    const actual = valorActual(sede, variable);
    if (!actual) return 'Sin lecturas aún';
    return `Actual: <strong>${numero(actual.valor, VARIABLES[variable].decimales)} ${escapar(actual.unidad)}</strong> ${insignia(actual.estado)}`;
  }

  const filaValor = (variable) => `<span class="consola-actual" data-variable="${variable}">${textoActual(variable)}</span>`;

  const etiquetaAuto = (enBase) => (enBase ? '<span class="automatico">Automático</span>' : '<span class="intervenido">Intervenido</span>');

  function control(campo, valor) {
    const c = CONTROLES[campo];
    const titulo = c.variable ? VARIABLES[c.variable].nombre : 'Enlace de la sede';
    let cuerpo;
    if (campo === 'uv_forzado') {
      const forzado = valor !== null;
      cuerpo = `
        <button class="interruptor" role="switch" aria-checked="${forzado}" data-campo="uv_modo">${forzado ? 'Forzado' : 'Automático'}</button>
        <div class="deslizador" ${forzado ? '' : 'hidden'}>
          <input type="range" min="0" max="14" step="0.5" value="${forzado ? valor : 9}" data-campo="uv_forzado" list="marcas-uv" aria-label="Índice UV forzado">
          <output>${numero(forzado ? valor : 9, 1)}</output>
        </div>
        <datalist id="marcas-uv"><option value="8" label="8"></option><option value="11" label="11"></option></datalist>
        <div class="marcas"><span style="left:${(8 / 14) * 100}%">8 · advertencia</span><span style="left:${(11 / 14) * 100}%">11 · crítico</span></div>`;
    } else if (campo === 'enlace_cortado') {
      cuerpo = `<button class="interruptor ${valor ? 'cortado' : ''}" role="switch" aria-checked="${!valor}" data-campo="enlace_cortado">${valor ? 'Cortado' : 'Conectado'}</button>`;
    } else {
      cuerpo = `
        <div class="deslizador">
          <input type="range" min="${c.min}" max="${c.max}" step="${c.paso}" value="${valor}" data-campo="${campo}" aria-label="${c.etiqueta} de ${titulo}">
          <output>${pct(valor, c.base)}</output>
        </div>
        <div class="atajos">
          ${(c.atajos ?? []).map((a) => `<button data-campo="${campo}" data-valor="${a}">${pct(a, c.base)}</button>`).join('')}
          ${campo === 'produccion_pct' ? `<button data-campo="${campo}" data-valor="0" class="parada">Parada de línea</button><button data-campo="${campo}" data-valor="100">100%</button>` : ''}
        </div>`;
    }
    const enBase = campo === 'uv_forzado' ? valor === null : valor === (c.base ?? false);
    return `
      <section class="control">
        <div class="control-cabecera"><h4>${titulo}${c.etiqueta ? ` · <span>${c.etiqueta}</span>` : ''}</h4>${etiquetaAuto(enBase)}</div>
        ${c.variable ? filaValor(c.variable) : ''}
        ${cuerpo}
        <p class="ayuda">${c.ayuda}</p>
      </section>`;
  }

  function textoAccion(a) {
    if (a.accion === 'restablecer') return 'Restableció todo';
    const { sede: s, ...cambios } = a.detalle;
    const partes = Object.entries(cambios).map(([campo, v]) => {
      if (campo === 'uv_forzado') return v === null ? 'UV automático' : `UV forzado ${numero(v, 1)}`;
      if (campo === 'enlace_cortado') return v ? 'enlace cortado' : 'enlace conectado';
      const c = CONTROLES[campo];
      return `${VARIABLES[c.variable].nombre.toLowerCase()} ${pct(v, c.base)}`;
    });
    return `${SEDES[s]?.nombre ?? s}: ${partes.join(', ')}`;
  }

  function pintar() {
    if (!datos) return;
    panel.querySelectorAll('[role="tab"]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.sede === sede)));
    const estado = datos.sedes[sede];
    contenedor.innerHTML = datos.controles[sede].map((campo) => control(campo, estado[campo])).join('');
    panel.querySelector('.consola-registro').innerHTML = datos.registro.length
      ? datos.registro
          .map((a) => `<li><time>${new Date(a.ts).toLocaleTimeString('es-CL', { hour12: false })}</time> <strong>${escapar(a.usuario)}</strong> ${escapar(textoAccion(a))}</li>`)
          .join('')
      : '<li class="vacio">Sin acciones todavía</li>';
    pintarReloj();
  }

  function pintarReloj() {
    const h = horaSimulada();
    panel.querySelector('.consola-reloj').textContent = `Hora simulada ${h ? hora(h) : '--:--'} · 1 ciclo = 15 min`;
  }

  // ---------- acciones ----------
  async function ejecutar(promesa, texto) {
    textoEstado.textContent = 'Aplicando…';
    try {
      datos = await promesa;
      textoEstado.textContent = texto;
      pintar();
    } catch (err) {
      textoEstado.textContent = `No se pudo aplicar: ${err.message}`;
      pintar(); // vuelve a mostrar el último estado confirmado por el servidor
    }
  }

  const cambiar = (cambios) => ejecutar(proveedor.consola.cambiar(sede, cambios), 'Cambio aplicado');

  contenedor.addEventListener('input', (e) => {
    // Mientras se arrastra solo se actualiza el número; el PUT va al soltar (evento change).
    const campo = e.target.dataset.campo;
    if (!campo || e.target.type !== 'range') return;
    const v = Number(e.target.value);
    e.target.nextElementSibling.textContent = campo === 'uv_forzado' ? numero(v, 1) : pct(v, CONTROLES[campo].base);
  });
  contenedor.addEventListener('change', (e) => {
    const campo = e.target.dataset.campo;
    if (campo && e.target.type === 'range') cambiar({ [campo]: Number(e.target.value) });
  });
  contenedor.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-campo]');
    if (!b) return;
    const campo = b.dataset.campo;
    if (b.dataset.valor !== undefined) return cambiar({ [campo]: Number(b.dataset.valor) });
    if (campo === 'enlace_cortado') return cambiar({ enlace_cortado: b.getAttribute('aria-checked') === 'true' });
    if (campo === 'uv_modo') {
      const forzar = b.getAttribute('aria-checked') !== 'true';
      return cambiar({ uv_forzado: forzar ? Number(contenedor.querySelector('[data-campo="uv_forzado"]').value) : null });
    }
  });
  panel.querySelector('.pestanas').addEventListener('click', (e) => {
    const tab = e.target.closest('[role="tab"]');
    if (!tab) return;
    sede = tab.dataset.sede;
    pintar();
  });
  panel.querySelector('.btn-restablecer').addEventListener('click', () =>
    ejecutar(proveedor.consola.restablecer(), 'Todo en Automático'));

  const alternar = async (abrir = panel.hidden) => {
    panel.hidden = !abrir;
    boton.setAttribute('aria-expanded', String(abrir));
    document.body.classList.toggle('consola-abierta', abrir);
    if (abrir) await ejecutar(proveedor.consola.obtener(), '');
  };
  panel.querySelector('.btn-cerrar').addEventListener('click', () => alternar(false));
  document.addEventListener('keydown', (e) => e.key === 'Escape' && !panel.hidden && alternar(false));
  boton.hidden = false;
  boton.addEventListener('click', () => alternar());

  return {
    // Llamar cuando llegan lecturas nuevas: solo cambia el texto "Actual" (los controles no se
    // reconstruyen, para no perder un click o un deslizador en uso).
    actualizarValores() {
      if (panel.hidden) return;
      panel.querySelectorAll('.consola-actual').forEach((el) => (el.innerHTML = textoActual(el.dataset.variable)));
      pintarReloj();
    },
  };
}
