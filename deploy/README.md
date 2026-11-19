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
   | `DEMO_USUARIO` / `DEMO_CLAVE` | Usuario y contraseña del panel **Demo** del dashboard (obligatorios). Sin comillas simples |

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

- Dashboard: `https://<subdominio>.duckdns.org` → elige un perfil. Debe decir **En línea**.
- Swagger: `https://<subdominio>.duckdns.org/docs`
- Salud: `https://<subdominio>.duckdns.org/api/salud`
- Llega un correo **"[Induplac] Prueba de aviso"**.

Revisión completa: **EC2 → la instancia → Connect → EC2 Instance Connect → Connect**, y luego:

```bash
sudo /opt/induplac/deploy/verificar.sh
```

Muestra ✓ o ✗ para: contenedores, API y base de datos, DuckDNS, HTTPS, lotes recientes de las 2 sedes y API de simulación.

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

Por HTTP el usuario y la contraseña del panel Demo viajan sin cifrar: úsalo solo como emergencia.

## El día de la presentación

1. **Start Lab unos 15 minutos antes.** En el Learner Lab la IP pública cambia cada vez que el lab se detiene y vuelve a iniciar: DuckDNS se actualiza solo al arrancar la instancia y cada 5 minutos.
2. Si la instancia quedó detenida: **EC2 → Instance state → Start instance**.
3. Conéctate con EC2 Instance Connect y corre `sudo /opt/induplac/deploy/verificar.sh`. Todo debe salir con ✓.
4. Abre el dashboard, presiona **D** (o el botón **Demo**) e ingresa el usuario y la contraseña de demo.
5. **Restablecer todo** deja la simulación en el estado base con un clic.

### Panel Demo

| Botón | Efecto |
|---|---|
| Restablecer todo | Operación normal + reconectar todas las sedes |
| Operación normal | Apaga los picos y el UV alto (no reconecta) |
| Pico eléctrico en la Planta | +35%: crítico en 3–4 ciclos (~10 s) y correo |
| Pico de agua en la Oficina RM | +60% (fuga): crítico y correo |
| UV alto en la Planta | Índice 9: advertencia |
| Desconectar (sede elegida) | Esa sede deja de enviar: "Sin datos" en ~6 s y correo |
| Registrar incidente (sede elegida) | HH sin incidentes de esa sede vuelve a 0 |
| Reconectar | Las sedes envían la cola acumulada, en orden y sin duplicados |

Correos: como máximo 1 por sede y variable cada 10 minutos (`ALERTA_ENFRIAMIENTO_MIN`).

## Actualizar el código

Desde EC2 Instance Connect:

```bash
cd /opt/induplac && sudo git pull && sudo docker compose up -d --build
```

Congelamiento: después del merge del despliegue no hay cambios de código salvo correcciones de errores, hasta la presentación del 25-11.
