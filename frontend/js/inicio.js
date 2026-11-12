// Pantalla de entrada: selección de perfil (demo, sin contraseña).
import { PERFILES, guardarPerfil } from './perfiles.js';

const contenedor = document.getElementById('perfiles');
contenedor.innerHTML = Object.entries(PERFILES)
  .map(
    ([id, p]) => `
    <button class="perfil-btn" data-perfil="${id}">
      <strong>${p.nombre}</strong>
      <span>${p.descripcion}</span>
    </button>`,
  )
  .join('');

contenedor.addEventListener('click', (e) => {
  const id = e.target.closest('[data-perfil]')?.dataset.perfil;
  if (!id) return;
  // Si sessionStorage no está disponible, el perfil viaja en la URL.
  location.href = guardarPerfil(id) ? 'dashboard.html' : `dashboard.html?perfil=${id}`;
});
