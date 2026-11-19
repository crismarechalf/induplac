# Despliegue de Induplac en AWS Academy (Learner Lab)

Todo corre en **una sola instancia EC2**: API, PostgreSQL, los 2 gateways y HTTPS (Caddy + DuckDNS).
Nada queda corriendo en un notebook. **Nada de la instancia es irremplazable**: si se pierde, se crea una nueva con el mismo User data y queda igual (los datos de la demo se regeneran solos).

## Antes de empezar (una sola vez)

1. **DuckDNS**: entra a <https://www.duckdns.org> con tu cuenta de Google, crea un subdominio (ej. `induplac-demo`) y copia el **token** que aparece arriba.
2. **Gmail**: en la cuenta que enviará los avisos, activa la verificación en 2 pasos y crea una **contraseña de aplicación** en <https://myaccount.google.com/apppasswords>. Son 16 letras.
3. Abre [`user-data.sh`](user-data.sh), copia **todo** su contenido a un bloc de notas y completa las variables del inicio:

   | Variable | Qué poner |
   |---|---|
   | `DUCKDNS_SUBDOMINIO` | Solo la parte antes de `.duckdns.org` |
   | `DUCKDNS_TOKEN` | El token de DuckDNS |
   | `SMTP_USER` | El Gmail que envía los avisos |
   | `SMTP_PASS` | La contraseña de aplicación (con o sin espacios) |
   | `ALERTA_DESTINO` | Opcional. Correos que reciben los avisos, separados por coma. Vacío = `SMTP_USER` |
   | `ADMIN_USUARIO` / `ADMIN_CLAVE` | Usuario y contraseña del administrador (consola de operación y auditoría). Sin comillas simples |
   | `USUARIOS_CLAVE` | Contraseña inicial de `jefatura`, `prevencion`, `personal_rm` y `personal_planta` |

   Estos valores **nunca** se suben al repositorio: solo se pegan en la consola de AWS.

## Crear la instancia

1. **Start Lab** y espera a que el punto quede verde. Abre **AWS**.
2. **EC2 → Launch instance**:
   - **Name**: `induplac`
   - **AMI**: Ubuntu Server 24.04 LTS
   - **Instance type**: `t3.small`
   - **Key pair**: `vockey`
   - **Storage**: 20 GiB gp3
3. **Network settings → Edit → Security group** (crear uno nuevo):

   | Puerto | Origen | Para qué |
   |---|---|---|
   | 22 (SSH) | My IP | EC2 Instance Connect |
   | 80 (HTTP) | 0.0.0.0/0 | Let's Encrypt y redirección a HTTPS |
   | 443 (HTTPS) | 0.0.0.0/0 | Dashboard |

   **No** abras el 8000: es el plan B (ver abajo).
4. **Advanced details → User data**: pega el script ya completado.
5. **Launch instance**. El despliegue tarda entre 5 y 10 minutos.

## Verificar

- Dashboard: `https://<subdominio>.duckdns.org` → inicia sesión con uno de los usuarios. Debe decir **En línea**.
- Swagger: `https://<subdominio>.duckdns.org/docs`
- Salud: `https://<subdominio>.duckdns.org/api/salud`
- Llega un correo **"[Induplac] Prueba de aviso"**.

Revisión completa: **EC2 → la instancia → Connect → EC2 Instance Connect → Connect**, y luego:

```bash
sudo /opt/induplac/deploy/verificar.sh
```

Muestra ✓ o ✗ para: contenedores, API y base de datos, DuckDNS, HTTPS, lotes recientes de las 2 sedes, login del administrador y consola de operación.

## Usuarios

Se crean solos en el primer arranque. Cambiar una clave: `cd /opt/induplac && sudo docker compose exec api python -m app.usuarios cambiar-clave <usuario>`.

| Usuario | Clave | Ve | Puede |
|---|---|---|---|
| `admin` (o `ADMIN_USUARIO`) | `ADMIN_CLAVE` | Todo | Consola de operación y pruebas, auditoría, registrar incidentes |
| `jefatura` | `USUARIOS_CLAVE` | Ambas sedes, todas las variables, incidentes | Solo ver |
| `prevencion` | `USUARIOS_CLAVE` | HH sin incidentes de ambas sedes, UV de la Planta, incidentes | Registrar incidentes |
| `personal_rm` | `USUARIOS_CLAVE` | Solo la Oficina RM | Solo ver |
| `personal_planta` | `USUARIOS_CLAVE` | Solo la Planta Valparaíso | Solo ver |

5 intentos fallidos de un usuario en 5 minutos lo bloquean durante 5 minutos.

## Si algo falla

Desde EC2 Instance Connect:

```bash
sudo tail -n 100 /var/log/induplac-deploy.log   # log del despliegue (incluye la prueba de correo)
sudo tail -n 5 /var/log/duckdns.log             # actualizaciones de DuckDNS ("OK" = bien)
cd /opt/induplac && sudo docker compose ps       # estado de los contenedores
sudo docker compose logs --tail 50 api           # también: caddy, gateway-planta, gateway-rm, db
```

- **El script se detuvo al inicio** ("Falta completar …"): quedó un `CAMBIAR` en las variables. Termina la instancia y créala de nuevo con el User data corregido.
- **Correos**: si el 587 está bloqueado, el script prueba el 465 y deja el que funcionó. Para probar a mano: `cd /opt/induplac && sudo docker compose exec api python -m app.notificador --prueba`.

### Plan B: HTTPS no funciona (Let's Encrypt)

El certificado se guarda en el volumen `caddy_data` y sobrevive a cada parada del lab. Si aun así HTTPS falla el día de la presentación:

1. **EC2 → Security groups →** el de la instancia **→ Edit inbound rules → Add rule**: Custom TCP **8000**, origen 0.0.0.0/0.
2. Entra por `http://<subdominio>.duckdns.org:8000` (sin la "s").
3. Al terminar, borra esa regla.

Por HTTP las contraseñas viajan sin cifrar: úsalo solo como emergencia.

## El día de la presentación

1. **Start Lab unos 15 minutos antes.** En el Learner Lab la IP pública cambia cada vez que el lab se detiene y vuelve a iniciar: DuckDNS se actualiza solo al arrancar la instancia y cada 5 minutos.
2. Si la instancia quedó detenida: **EC2 → Instance state → Start instance**.
3. Conéctate con EC2 Instance Connect y corre `sudo /opt/induplac/deploy/verificar.sh`. Todo debe salir con ✓.
4. Inicia sesión como `admin` y abre **Consola** (botón del header). **Restablecer todo** deja la simulación en el estado base con un clic.

### Consola de operación (solo admin)

Panel lateral con una pestaña por sede. Cada cambio se aplica al soltar el deslizador o al hacer click; queda en el **Registro de acciones** y en la auditoría.

| Control | Sedes | Efecto |
|---|---|---|
| Electricidad / Agua · Variación del consumo (−50% a +100%) | ambas | Crítico si la última hora supera +20% del promedio de 4 semanas **y** el exceso supera el piso (10% del consumo típico en turno). De noche el consumo es bajo: para mostrar la alerta, hazlo en horario de turno |
| Producción · Ritmo de la línea (0% a 150%) y **Parada de línea** | Planta | Advertencia "Línea detenida" si produce 0 en 2 lecturas seguidas dentro del turno (L–S 6–22 h) |
| Índice UV · Automático / Forzado (0 a 14) | Planta | ≥ 8 advertencia, ≥ 11 crítico |
| Enlace de la sede · Conectado / Cortado | ambas | La sede sigue midiendo y encola; "Sin datos" a los 2 ciclos y correo. Al reconectar llega la cola en orden y sin duplicados |

### Registrar incidente (prevención y admin)

Botón **Registrar incidente** del header: sede, fecha y hora, tipo y descripción. Reinicia a 0 las HH sin incidentes de esa sede, envía un correo "[Induplac] INCIDENTE · …" y aparece en **Incidentes recientes**.

Correos: como máximo 1 por sede y variable cada 10 minutos (`ALERTA_ENFRIAMIENTO_MIN`).

## Actualizar el código

Desde EC2 Instance Connect:

```bash
cd /opt/induplac && sudo git pull && sudo docker compose up -d --build
```

**Desde la versión con panel Demo a la versión con login** (EC2 ya creada):

1. Agrega las variables nuevas al `.env` existente:

   ```bash
   cd /opt/induplac && sudo nano .env
   ```

   Al final, agrega (sin espacios alrededor del `=`):

   ```
   ADMIN_USUARIO='admin'
   ADMIN_CLAVE='una-clave-para-el-admin'
   USUARIOS_CLAVE='una-clave-para-los-demas'
   ```

   Guarda con Ctrl+O, Enter y Ctrl+X. Si no las agregas, la API usa `DEMO_USUARIO` / `DEMO_CLAVE` del `.env` anterior (admin = `DEMO_USUARIO`, el resto de los usuarios con `DEMO_CLAVE`).
2. Actualiza y reconstruye: `sudo git pull && sudo docker compose up -d --build`.
3. Las tablas nuevas (usuarios, incidentes, auditoría, config) se crean solas y los datos existentes se conservan. El reloj simulado único arranca después de la última lectura guardada.
4. Corre `sudo /opt/induplac/deploy/verificar.sh`.

Congelamiento: después del merge del despliegue no hay cambios de código salvo correcciones de errores, hasta la presentación del 25-11.
