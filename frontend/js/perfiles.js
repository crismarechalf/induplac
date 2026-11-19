// Catálogo de presentación: nombres visibles de sedes y variables.
// Qué ve cada usuario lo decide el servidor según su rol (vista del perfil al iniciar sesión).

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
