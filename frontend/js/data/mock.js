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

// Solo existe en el proveedor simulado: controla los escenarios del panel de demo.
// api.js no lo exporta, por eso el panel no aparece en modo 'api'.
export const escenarios = sim.escenarios;
