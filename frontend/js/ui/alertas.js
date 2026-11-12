// Panel de alertas activas, más recientes primero.
import { SEDES, VARIABLES } from '../perfiles.js';
import { hora, insignia, escapar } from './formato.js';

export function pintarAlertas(lista, contador, alertas) {
  const orden = [...alertas].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  contador.textContent = orden.length;
  lista.innerHTML = orden.length
    ? orden
        .map(
          (a) => `
        <li class="alerta" data-estado="${escapar(a.nivel)}">
          <div class="alerta-cabecera">
            ${insignia(a.nivel)}
            <time datetime="${escapar(a.ts)}">${hora(a.ts)}</time>
          </div>
          <strong>${escapar(SEDES[a.sede]?.nombre ?? a.sede)} · ${escapar(VARIABLES[a.variable]?.nombre ?? a.variable)}</strong>
          <p>${escapar(a.mensaje)}</p>
        </li>`,
        )
        .join('')
    : '<li class="vacio">Sin alertas activas</li>';
}
