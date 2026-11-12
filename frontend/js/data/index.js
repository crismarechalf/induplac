// Punto único de acceso a los datos. La UI solo importa `proveedor` desde aquí
// y nunca sabe si los datos son simulados o reales.
//
// PUNTO DE CAMBIO EVA 3: no hay que tocar este archivo; basta con DATA_SOURCE en config.js.
// Ambos proveedores exponen el mismo contrato:
//   getEstado()                         → [{ sede, variable, valor, unidad, estado, ts }]
//   getAlertas({ activas })             → [{ id, sede, variable, nivel, mensaje, ts, activa }]
//   getMediciones({ sede, variable, desde }) → [{ sede, variable, valor, unidad, ts }]
//   suscribir(callback, onConexion?)    → función para cancelar; eventos { tipo: 'estado' | 'alerta', data }
import { DATA_SOURCE } from '../config.js';

// Import dinámico: en modo 'api' el simulador ni siquiera se carga.
export const proveedor = await import(DATA_SOURCE === 'api' ? './api.js' : './mock.js');
