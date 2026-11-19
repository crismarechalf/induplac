// Proveedor simulado: mismo contrato que api.js, pero los datos vienen de simulator.js.
// Las funciones son async para comportarse igual que fetch.
import * as sim from '../simulator.js';

export const getEstado = async () => sim.obtenerEstado();

export const getAlertas = async (filtro = {}) => sim.obtenerAlertas(filtro);

export const getMediciones = async (filtro = {}) => sim.obtenerMediciones(filtro);

export function suscribir(callback, onConexion = () => {}) {
  onConexion('simulado');
  return sim.suscribir(callback);
}

// Escenarios del panel de demo (simulador local).
// api.js exporta uno equivalente que controla los gateways a través de la API.
export const escenarios = sim.escenarios;
