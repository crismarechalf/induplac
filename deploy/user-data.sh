#!/bin/bash
# Induplac · despliegue completo en una EC2 (Ubuntu Server 24.04) desde "User data".
#
# 1. Completa las 8 variables de abajo EN LA CONSOLA DE AWS (nunca en el repositorio).
# 2. Pega el script completo en: Launch instance → Advanced details → User data.
# Log: /var/log/induplac-deploy.log. Se puede volver a correr: no regenera secretos.
#
# ======================= COMPLETAR (obligatorias, salvo ALERTA_DESTINO) =======================
DUCKDNS_SUBDOMINIO="CAMBIAR"     # solo la parte antes de .duckdns.org
DUCKDNS_TOKEN="CAMBIAR"
SMTP_USER="CAMBIAR@gmail.com"
SMTP_PASS="CAMBIAR"              # contraseña de aplicación de Google (16 caracteres)
ALERTA_DESTINO=""                # opcional, varios separados por coma; vacío = se avisa a SMTP_USER
ADMIN_USUARIO="admin"            # usuario administrador del dashboard (consola de operación)
ADMIN_CLAVE="CAMBIAR"            # su contraseña
USUARIOS_CLAVE="CAMBIAR"         # contraseña de jefatura, prevencion, personal_rm y personal_planta
# ===============================================================================================

set -euo pipefail
LOG=/var/log/induplac-deploy.log
exec > >(tee -a "$LOG") 2>&1
echo "===== $(date -Is) Inicio del despliegue de Induplac ====="

REPO="https://github.com/crismarechalf/induplac"
DIR=/opt/induplac
DOMINIO="${DUCKDNS_SUBDOMINIO}.duckdns.org"

falla() { echo "ERROR: $*"; exit 1; }

# ---------------------------------------------------------------- 0. validar variables
for nombre in DUCKDNS_SUBDOMINIO DUCKDNS_TOKEN SMTP_USER SMTP_PASS ADMIN_USUARIO ADMIN_CLAVE USUARIOS_CLAVE; do
  valor="${!nombre}"
  [[ -n "$valor" && "$valor" != *CAMBIAR* ]] || falla "Falta completar $nombre al inicio del script"
  # Comillas simples o saltos de línea romperían el .env.
  [[ "$valor" != *"'"* && "$valor" != *$'\n'* ]] || falla "$nombre no puede tener comillas simples ni saltos de línea"
done
[[ "$ALERTA_DESTINO" != *CAMBIAR* && "$ALERTA_DESTINO" != *"'"* ]] || falla "Revisa ALERTA_DESTINO (o déjalo vacío)"
SMTP_PASS="${SMTP_PASS// /}"   # Google muestra la clave en bloques de 4: se quitan los espacios

# ---------------------------------------------------------------- 1. Docker, compose y git
echo "--- Instalando Docker, Docker Compose y git"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 git curl dnsutils openssl ca-certificates
systemctl enable --now docker

# ---------------------------------------------------------------- 2. DuckDNS
# En el Learner Lab la IP pública cambia cada vez que se detiene y vuelve a iniciar el lab:
# el script se corre ahora, en cada arranque y cada 5 minutos.
echo "--- Configurando DuckDNS para $DOMINIO"
install -d -m 700 /opt/duckdns
cat > /opt/duckdns/actualizar.sh <<EOF
#!/bin/bash
respuesta=\$(curl -fsS --max-time 20 "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMINIO}&token=${DUCKDNS_TOKEN}&ip=" || echo "ERROR de red")
echo "\$(date -Is) \$respuesta" >> /var/log/duckdns.log
EOF
chmod 700 /opt/duckdns/actualizar.sh
cat > /etc/cron.d/duckdns <<'EOF'
@reboot root sleep 20 && /opt/duckdns/actualizar.sh
*/5 * * * * root /opt/duckdns/actualizar.sh
EOF
/opt/duckdns/actualizar.sh
echo "DuckDNS respondió: $(tail -n 1 /var/log/duckdns.log)"

# ---------------------------------------------------------------- 3. esperar el DNS
# Let's Encrypt falla si el nombre todavía no apunta a esta instancia.
imds() {  # metadata service con IMDSv2
  local token
  token=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
  curl -fsS -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$1"
}
IP_PUBLICA=$(imds public-ipv4 || true)
echo "--- IP pública: ${IP_PUBLICA:-desconocida}. Esperando que $DOMINIO apunte a ella (máx. 10 min)"
for _ in $(seq 1 60); do
  resuelta=$(dig +short "$DOMINIO" @1.1.1.1 | tail -n 1 || true)
  [[ -n "$IP_PUBLICA" && "$resuelta" == "$IP_PUBLICA" ]] && { echo "DNS OK: $DOMINIO → $resuelta"; break; }
  sleep 10
done
[[ "${resuelta:-}" == "$IP_PUBLICA" ]] || echo "AVISO: el DNS aún no apunta a esta IP (resuelve '${resuelta:-nada}'). Caddy reintentará el certificado solo."

# ---------------------------------------------------------------- 4. código
echo "--- Código en $DIR (rama main)"
if [[ -d "$DIR/.git" ]]; then
  git -C "$DIR" pull --ff-only
else
  git clone --branch main "$REPO" "$DIR"
fi
cd "$DIR"

# ---------------------------------------------------------------- 5. .env (solo si no existe)
poner_var() {  # reemplaza o agrega CLAVE='valor' en .env sin interpretar caracteres especiales
  local clave="$1" valor="$2"
  { grep -v "^${clave}=" .env || true; printf "%s='%s'\n" "$clave" "$valor"; } > .env.nuevo
  chmod 600 .env.nuevo && mv .env.nuevo .env
}
if [[ -f .env ]]; then
  echo "--- .env ya existe: se conservan los secretos"
else
  echo "--- Generando .env con secretos nuevos"
  umask 077
  {
    echo "DB_PASSWORD='$(openssl rand -hex 24)'"
    echo "JWT_SECRET='$(openssl rand -hex 32)'"
    echo "GATEWAY_OFICINA_RM_SECRET='$(openssl rand -hex 24)'"
    echo "GATEWAY_PLANTA_SECRET='$(openssl rand -hex 24)'"
    echo "CICLO_SEG='3'"
    echo "ZONA_HORARIA='America/Santiago'"
    echo "RETENCION_DIAS='60'"
    echo "COMPOSE_PROFILES='gateways,https'"
    echo "DOMINIO='$DOMINIO'"
    echo "URL_PUBLICA='https://$DOMINIO'"
    echo "ADMIN_USUARIO='$ADMIN_USUARIO'"
    echo "ADMIN_CLAVE='$ADMIN_CLAVE'"
    echo "USUARIOS_CLAVE='$USUARIOS_CLAVE'"
    echo "SMTP_HOST='smtp.gmail.com'"
    echo "SMTP_PORT='587'"
    echo "SMTP_USER='$SMTP_USER'"
    echo "SMTP_PASS='$SMTP_PASS'"
    echo "ALERTA_DESTINO='$ALERTA_DESTINO'"
    echo "ALERTA_ENFRIAMIENTO_MIN='10'"
  } > .env
  chmod 600 .env
fi
install -m 600 .env /root/induplac.env.bak
echo "Respaldo de .env en /root/induplac.env.bak"

# ---------------------------------------------------------------- 6. levantar
echo "--- docker compose up -d --build (la primera vez tarda unos minutos)"
docker compose up -d --build

echo "--- Esperando a la API"
for _ in $(seq 1 60); do
  curl -fsS http://localhost:8000/api/salud > /dev/null 2>&1 && { echo "API OK"; break; }
  sleep 5
done

# ---------------------------------------------------------------- 7. prueba de correo
# AWS a veces bloquea el 587: si falla, se prueba el 465 y se deja en .env el que funcionó.
echo "--- Correo de prueba a ${ALERTA_DESTINO:-$SMTP_USER}"
if docker compose exec -T api python -m app.notificador --prueba; then
  echo "Correo OK por el puerto configurado"
elif docker compose exec -T -e SMTP_PORT=465 api python -m app.notificador --prueba; then
  echo "El 587 falló y el 465 funcionó: se deja SMTP_PORT=465"
  poner_var SMTP_PORT 465
  install -m 600 .env /root/induplac.env.bak
  docker compose up -d api
else
  echo "AVISO: no se pudo enviar el correo de prueba (ver el error arriba). El sistema funciona igual, sin avisos por correo."
fi

# ---------------------------------------------------------------- 8. verificación
echo "--- Verificación (los gateways cargan 4 semanas de historial: ~1 min)"
sleep 60
bash "$DIR/deploy/verificar.sh" || true
echo "===== $(date -Is) Fin del despliegue. Dashboard: https://$DOMINIO ====="
