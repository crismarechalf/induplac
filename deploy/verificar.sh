#!/bin/bash
# Revisión rápida de Induplac en la EC2. Correr después de cada "Start Lab":
#   sudo /opt/induplac/deploy/verificar.sh
# Muestra ✓ o ✗ con el motivo. Código de salida = cantidad de revisiones fallidas.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fallas=0
ok() { echo "✓ $1"; }
mal() { echo "✗ $1 — $2"; fallas=$((fallas + 1)); }
leer_env() { grep "^$1=" .env 2>/dev/null | head -n 1 | cut -d= -f2- | tr -d "'\""; }
DOMINIO=$(leer_env DOMINIO)

# 1. Contenedores arriba
esperados="db api gateway-planta gateway-rm caddy"
corriendo=$(docker compose ps --status running --services 2>/dev/null | tr '\n' ' ')
faltan=""
for s in $esperados; do [[ " $corriendo " == *" $s "* ]] || faltan+="$s "; done
if [[ -z "$faltan" ]]; then ok "Contenedores arriba ($esperados)"; else mal "Contenedores" "detenidos: $faltan(ver: docker compose logs <servicio>)"; fi

# 2. API y base de datos
salud=$(curl -fsS --max-time 10 http://localhost:8000/api/salud 2>/dev/null || true)
if [[ "$salud" == *'"api":"ok"'* && "$salud" == *'"base_datos":"ok"'* ]]; then
  ok "API y base de datos responden (/api/salud)"
else
  mal "API / base de datos" "/api/salud no responde bien (ver: docker compose logs api db)"
fi

# 3. DuckDNS apunta a la IP pública actual
token=$(curl -fsS --max-time 5 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
ip=$(curl -fsS --max-time 5 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)
resuelta=$(dig +short "$DOMINIO" @1.1.1.1 2>/dev/null | tail -n 1)
if [[ -n "$ip" && "$resuelta" == "$ip" ]]; then
  ok "DuckDNS: $DOMINIO → $ip"
else
  mal "DuckDNS" "$DOMINIO resuelve '${resuelta:-nada}' y la IP pública es '${ip:-desconocida}' (correr: sudo /opt/duckdns/actualizar.sh y esperar 1-2 min)"
fi

# 4. HTTPS con certificado válido (curl valida el certificado por defecto)
if curl -fsS --max-time 15 -o /dev/null "https://$DOMINIO/api/salud" 2>/tmp/induplac-https.err; then
  ok "HTTPS con certificado válido: https://$DOMINIO"
else
  mal "HTTPS" "$(head -c 200 /tmp/induplac-https.err) (ver: docker compose logs caddy; plan B en deploy/README.md)"
fi

# 5. Las 2 sedes enviaron un lote hace menos de 30 s
edades=$(printf '%s' "$salud" | python3 -c '
import json, sys
from datetime import datetime, timezone
try:
    sedes = json.load(sys.stdin)["sedes"]
except Exception:
    sys.exit()
ahora = datetime.now(timezone.utc)
for sede, d in sedes.items():
    t = d.get("ultimo_lote_recibido")
    edad = int((ahora - datetime.fromisoformat(t.replace("Z", "+00:00"))).total_seconds()) if t else -1
    print(sede, edad)
' 2>/dev/null)
viejas=""
for sede in oficina_rm planta; do
  edad=$(awk -v s="$sede" '$1 == s {print $2}' <<< "$edades")
  if [[ -z "$edad" || "$edad" -lt 0 ]]; then viejas+="$sede (nunca) "
  elif (( edad > 30 )); then viejas+="$sede (hace ${edad} s) "; fi
done
if [[ -z "$viejas" ]]; then ok "Las 2 sedes enviaron un lote hace menos de 30 s"; else mal "Lotes recientes" "sin lotes: $viejas(¿panel Demo con una sede desconectada? ver: docker compose logs gateway-planta gateway-rm)"; fi

# 6. API de simulación (panel Demo)
if curl -fsS --max-time 10 http://localhost:8000/api/simulacion > /dev/null 2>&1; then
  ok "API de simulación responde (/api/simulacion)"
else
  mal "API de simulación" "/api/simulacion no responde"
fi

echo
if (( fallas == 0 )); then echo "Todo OK. Dashboard: https://$DOMINIO"; else echo "$fallas revisión(es) con problemas."; fi
exit "$fallas"
