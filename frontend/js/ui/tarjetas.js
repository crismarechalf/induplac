// Columnas por sede y tarjetas por variable.
// Las tarjetas se crean una vez y luego solo se actualizan, para que la
// transición de color al cambiar de estado se vea suave.
import { SEDES, VARIABLES } from '../perfiles.js';
import { numero, hora, insignia } from './formato.js';

const idTarjeta = (sede, variable) => `tarjeta-${sede}-${variable}`;

function tarjeta(sede, variable) {
  const meta = VARIABLES[variable];
  return `
    <article class="tarjeta" id="${idTarjeta(sede, variable)}">
      <h3 class="tarjeta-nombre">${meta.nombre}</h3>
      <p class="tarjeta-detalle">${meta.detalle}</p>
      <p class="tarjeta-valor"><span class="num">—</span> <span class="unidad"></span></p>
      <p class="tarjeta-estado"><span class="insignia"></span></p>
      <p class="tarjeta-pie">Esperando datos…</p>
    </article>`;
}

export function montarSedes(contenedor, perfil) {
  const sedes = Object.keys(perfil.ver);
  contenedor.dataset.columnas = sedes.length;
  contenedor.innerHTML = sedes
    .map(
      (sede) => `
      <section class="sede" aria-labelledby="titulo-${sede}">
        <h2 class="sede-titulo" id="titulo-${sede}">${SEDES[sede].nombre}</h2>
        <div class="tarjetas">${perfil.ver[sede].map((v) => tarjeta(sede, v)).join('')}</div>
      </section>`,
    )
    .join('');
}

// Subtítulo: usa los campos opcionales que entrega el proveedor (no los calcula).
function detalle(it) {
  if (it.max_dia !== undefined) return `Máx. del día: ${numero(it.max_dia, 1)}`;
  if (it.acumulado_dia !== undefined) return `Hoy: ${numero(it.acumulado_dia)} · Mes: ${numero(it.acumulado_mes)}`;
  return VARIABLES[it.variable]?.detalle ?? '';
}

// Pinta los ítems de estado tal como llegan del proveedor.
export function pintarEstado(items) {
  for (const it of items) {
    const el = document.getElementById(idTarjeta(it.sede, it.variable));
    if (!el) continue;
    if (el.dataset.estado !== it.estado) {
      el.dataset.estado = it.estado;
      el.querySelector('.insignia').innerHTML = insignia(it.estado);
    }
    el.querySelector('.num').textContent = numero(it.valor, VARIABLES[it.variable]?.decimales);
    el.querySelector('.unidad').textContent = it.unidad;
    el.querySelector('.tarjeta-detalle').textContent = detalle(it);
    el.querySelector('.tarjeta-pie').textContent =
      `${it.estado === 'sin_datos' ? 'Última lectura' : 'Actualizado'} ${hora(it.ts)}`;
  }
}
