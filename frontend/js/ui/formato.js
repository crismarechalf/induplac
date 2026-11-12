// Utilidades de presentación: formato es-CL e insignias de estado.
// Solo traducen el campo `estado` recibido a color + ícono + texto; no calculan nada.

export const numero = (valor, decimales = 0) =>
  Number(valor).toLocaleString('es-CL', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });

export const hora = (ts) =>
  new Date(ts).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', hour12: false });

export const escapar = (texto) =>
  String(texto).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const svg = (trazos) =>
  `<svg class="icono" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${trazos}</svg>`;

export const ESTADOS = {
  normal: { etiqueta: 'Normal', icono: svg('<circle cx="8" cy="8" r="6.5"/><path d="M5 8.3l2 2 4-4.3"/>') },
  advertencia: { etiqueta: 'Advertencia', icono: svg('<path d="M8 1.8l6.6 11.8H1.4z"/><path d="M8 6.3v3.2M8 11.6v.1"/>') },
  critico: { etiqueta: 'Crítico', icono: svg('<circle cx="8" cy="8" r="6.5"/><path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8"/>') },
  sin_datos: { etiqueta: 'Sin datos', icono: svg('<circle cx="8" cy="8" r="6.5" stroke-dasharray="2.4 2.2"/><path d="M5.3 8h5.4"/>') },
};

// Insignia accesible: color + ícono + texto (nunca solo color).
export function insignia(estado) {
  const e = ESTADOS[estado] ?? { etiqueta: escapar(estado), icono: '' };
  return `<span class="estado" data-estado="${escapar(estado)}">${e.icono}<span>${e.etiqueta}</span></span>`;
}
