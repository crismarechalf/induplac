// Pantalla de inicio de sesión: usuario y contraseña → token JWT con el rol.
import { proveedor } from './data/index.js';
import { guardarSesion, leerSesion } from './sesion.js';

const formulario = document.getElementById('login');
const error = document.getElementById('login-error');

if (leerSesion()) location.replace('dashboard.html');
if (new URLSearchParams(location.search).has('expirada')) error.textContent = 'Tu sesión venció. Vuelve a ingresar.';

formulario.addEventListener('submit', async (e) => {
  e.preventDefault();
  const usuario = formulario.usuario.value.trim();
  const clave = formulario.clave.value;
  if (!usuario || !clave) {
    error.textContent = 'Ingresa usuario y contraseña.';
    return;
  }
  const boton = formulario.querySelector('button');
  boton.disabled = true;
  error.textContent = '';
  try {
    guardarSesion(await proveedor.login(usuario, clave));
    location.replace('dashboard.html');
  } catch (err) {
    // 401: credenciales incorrectas · 429: bloqueo por intentos fallidos (el mensaje dice cuánto esperar).
    error.textContent = err.status === 401 ? 'Usuario o contraseña incorrectos.' : err.message;
    formulario.clave.value = '';
    formulario.clave.focus();
  } finally {
    boton.disabled = false;
  }
});
