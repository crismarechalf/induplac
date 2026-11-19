// Sesión del usuario: token JWT + perfil (vista y permisos que entrega el servidor al iniciar sesión).
// Se guarda en sessionStorage: se pierde al cerrar la pestaña. Sin almacenamiento, queda en memoria.

const CLAVE = 'induplac.sesion';
let enMemoria = null;

export function guardarSesion(sesion) {
  enMemoria = sesion;
  try {
    sessionStorage.setItem(CLAVE, JSON.stringify(sesion));
  } catch {
    /* queda en memoria mientras la página esté abierta */
  }
}

export function leerSesion() {
  try {
    return JSON.parse(sessionStorage.getItem(CLAVE)) ?? enMemoria;
  } catch {
    return enMemoria;
  }
}

export function cerrarSesion() {
  enMemoria = null;
  try {
    sessionStorage.removeItem(CLAVE);
  } catch {
    /* nada que borrar */
  }
}

// Token vencido o inválido (401 o cierre 4401 del WebSocket): de vuelta al login.
export function sesionExpirada() {
  cerrarSesion();
  location.replace('index.html?expirada=1');
}

export const tienePermiso = (permiso) => Boolean(leerSesion()?.usuario.permisos.includes(permiso));
