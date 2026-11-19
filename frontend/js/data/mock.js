// Proveedor simulado (sin servidor): mismo contrato de lectura que api.js, con datos de simulator.js.
// Sirve para trabajar en la interfaz sin backend. No tiene consola ni incidentes: eso requiere la API.
// El login es local y no valida la contraseña (no hay servidor contra el cual hacerlo).
import * as sim from '../simulator.js';

const TODO = {
  oficina_rm: ['electricidad', 'agua', 'hh_sin_incidentes'],
  planta: ['electricidad', 'agua', 'produccion', 'hh_sin_incidentes', 'uv'],
};
const ROLES = {
  jefatura: { rol_nombre: 'Jefatura de operaciones', vista: TODO },
  prevencion: { rol_nombre: 'Prevención de riesgos', vista: { oficina_rm: ['hh_sin_incidentes'], planta: ['hh_sin_incidentes', 'uv'] } },
  personal_rm: { rol_nombre: 'Personal Oficina RM', vista: { oficina_rm: TODO.oficina_rm } },
  personal_planta: { rol_nombre: 'Personal Planta', vista: { planta: TODO.planta } },
};

export async function login(usuario) {
  const rol = ROLES[usuario];
  if (!rol) throw Object.assign(new Error('Modo simulado: usa jefatura, prevencion, personal_rm o personal_planta'), { status: 400 });
  return { token: 'simulado', usuario: { usuario, nombre: rol.rol_nombre, rol: usuario, ...rol, permisos: [] } };
}

export const yo = async () => null; // sin servidor: se usa el perfil guardado al iniciar sesión

export const getEstado = async () => sim.obtenerEstado();

export const getAlertas = async (filtro = {}) => sim.obtenerAlertas(filtro);

export const getMediciones = async (filtro = {}) => sim.obtenerMediciones(filtro);

export function suscribir(callback, onConexion = () => {}) {
  onConexion('simulado');
  return sim.suscribir(callback);
}
