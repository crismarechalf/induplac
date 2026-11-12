// Catálogo de presentación (nombres visibles) y perfiles de acceso de la demo.
// Sin autenticación real: el perfil elegido solo filtra qué se muestra.

export const SEDES = {
  oficina_rm: { nombre: 'Oficina RM' },
  planta: { nombre: 'Planta Valparaíso' },
};

export const VARIABLES = {
  electricidad: { nombre: 'Electricidad', detalle: 'Consumo últimos 15 min', decimales: 1 },
  agua: { nombre: 'Agua', detalle: 'Consumo últimos 15 min', decimales: 0 },
  produccion: { nombre: 'Producción', detalle: 'Tableros últimos 15 min', decimales: 0 },
  hh_sin_incidentes: { nombre: 'HH sin incidentes', detalle: 'Acumuladas · actualización diaria', decimales: 0 },
  uv: { nombre: 'Índice UV', detalle: 'Radiación exterior', decimales: 1 },
};

const TODO_RM = ['electricidad', 'agua', 'hh_sin_incidentes'];
const TODO_PLANTA = ['electricidad', 'agua', 'produccion', 'hh_sin_incidentes', 'uv'];

// ver: sede → variables visibles para el perfil.
export const PERFILES = {
  jefatura: {
    nombre: 'Jefatura de operaciones',
    descripcion: 'Ambas sedes, todos los indicadores.',
    ver: { oficina_rm: TODO_RM, planta: TODO_PLANTA },
  },
  prevencion: {
    nombre: 'Prevención de riesgos',
    descripcion: 'HH sin incidentes de ambas sedes e índice UV de la planta.',
    ver: { oficina_rm: ['hh_sin_incidentes'], planta: ['hh_sin_incidentes', 'uv'] },
  },
  personal_rm: {
    nombre: 'Personal Oficina RM',
    descripcion: 'Indicadores de la Oficina RM.',
    ver: { oficina_rm: TODO_RM },
  },
  personal_planta: {
    nombre: 'Personal Planta',
    descripcion: 'Indicadores de la Planta Valparaíso.',
    ver: { planta: TODO_PLANTA },
  },
};

export const puedeVer = (perfil, sede, variable) => Boolean(perfil.ver[sede]?.includes(variable));

// Perfil en sessionStorage; si el navegador lo bloquea, se pasa por la URL.
const CLAVE = 'induplac.perfil';

export function guardarPerfil(id) {
  try {
    sessionStorage.setItem(CLAVE, id);
    return true;
  } catch {
    return false;
  }
}

export function leerPerfil() {
  const deUrl = new URLSearchParams(location.search).get('perfil');
  if (deUrl) return deUrl;
  try {
    return sessionStorage.getItem(CLAVE);
  } catch {
    return null;
  }
}

export function borrarPerfil() {
  try {
    sessionStorage.removeItem(CLAVE);
  } catch {
    /* sin almacenamiento: nada que borrar */
  }
}
