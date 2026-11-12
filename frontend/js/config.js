// Configuración central del frontend Induplac.

// PUNTO DE CAMBIO EVA 3: cambiar a 'api' para leer del backend FastAPI real.
// 'mock' usa el simulador local (js/simulator.js) y habilita el panel de demo.
export const DATA_SOURCE = 'mock';

// URL base de la API. Vacía = mismo origen (FastAPI servirá este frontend como estáticos).
// Si la API vive en otro dominio, ej.: 'https://api.induplac.cl'
export const API_BASE_URL = '';

// WebSocket de eventos en tiempo real. Por defecto, mismo host que la página en /ws.
export const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;

// Duración de un ciclo del simulador: 3000 ms reales = 15 minutos simulados.
export const TICK_MS = 3000;
