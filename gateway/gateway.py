"""Gateway de sede Induplac (cliente IoT).

Corre en cada sede. En cada ciclo lee los medidores, arma un lote y lo envía a
la API REST. Si no hay conexión, el lote queda en una cola local (SQLite en
disco) y se reenvía en orden cuando vuelve el enlace: no se pierden lecturas.

En el MVP los medidores se emulan con el mismo modelo de consumo del simulador
del dashboard (turnos, dotación, ruido). Solo Python estándar: sin dependencias.

Uso (demo, reloj acelerado: 3 s reales = 15 min):
    python gateway.py --sede planta
    python gateway.py --sede oficina_rm
Operación real: --ciclo 900

Comandos en la consola mientras corre:
    e  pico eléctrico (+35%)      a  pico de agua (+60%, fuga)
    u  UV alto (índice 9)         x  UV extremo (índice 11)
    i  registrar incidente (HH a 0)
    n  operación normal           d  cortar enlace     r  reconectar
    s  estado de la cola          q  salir
"""
import argparse
import json
import math
import os
import random
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo("America/Santiago")
except Exception:  # Windows sin paquete tzdata: horario de verano de Chile (UTC-3)
    ZONA = timezone(timedelta(hours=-3))

PASO = timedelta(minutes=15)
SEMANAS_HISTORIAL = 4
TAMANO_ENVIO = 200  # lotes por solicitud al reenviar la cola

PUNTOS = {
    "oficina_rm": {"electricidad": "kWh", "agua": "L", "hh_sin_incidentes": "h"},
    "planta": {"electricidad": "kWh", "agua": "L", "produccion": "tableros", "hh_sin_incidentes": "h", "uv": "índice"},
}
TURNO = {"oficina_rm": ([0, 1, 2, 3, 4], 8, 19), "planta": ([0, 1, 2, 3, 4, 5], 6, 22)}  # lunes = 0
DOTACION = {"oficina_rm": 25, "planta": 80}
BASE = {  # consumo por intervalo de 15 min: (en turno, fuera de turno)
    "electricidad": {"oficina_rm": (22, 7), "planta": (140, 60)},
    "agua": {"oficina_rm": (120, 10), "planta": (900, 200)},
}
HH_INICIAL = {"oficina_rm": 18450, "planta": 96320}


def ruido(p):
    return 1 + (random.random() * 2 - 1) * p


class Medidores:
    """Emula los equipos de medición de una sede."""

    def __init__(self, sede, hh):
        self.sede = sede
        self.hh = hh
        self.dia_hh = None
        self.pico_electrico = self.pico_agua = False
        self.uv_forzado = None

    def en_turno(self, local):
        dias, desde, hasta = TURNO[self.sede]
        return local.weekday() in dias and desde <= local.hour < hasta

    def _actualizar_hh(self, local):
        # Se actualiza una vez al día, sumando las horas-hombre del día anterior si fue laboral.
        dia = local.date()
        if self.dia_hh is not None and dia != self.dia_hh:
            dias, desde, hasta = TURNO[self.sede]
            if (local.weekday() - 1) % 7 in dias:
                self.hh += DOTACION[self.sede] * (hasta - desde)
        self.dia_hh = dia

    def leer(self, ts_utc):
        local = ts_utc.astimezone(ZONA)
        self._actualizar_hh(local)
        turno = 0 if self.en_turno(local) else 1
        valores = {}
        for variable in PUNTOS[self.sede]:
            if variable == "electricidad":
                v = BASE["electricidad"][self.sede][turno] * ruido(0.08) * (1.35 if self.pico_electrico else 1)
                valores[variable] = round(v, 1)
            elif variable == "agua":
                v = BASE["agua"][self.sede][turno] * ruido(0.15) * (1.6 if self.pico_agua else 1)
                valores[variable] = round(v)
            elif variable == "produccion":
                valores[variable] = round(45 * ruido(0.15)) if turno == 0 else 0
            elif variable == "hh_sin_incidentes":
                valores[variable] = self.hh
            elif variable == "uv":
                if self.uv_forzado is not None:
                    valores[variable] = self.uv_forzado
                else:
                    h = local.hour + local.minute / 60
                    uv = 0 if h < 7 or h > 19 else min(7.6, 7.4 * math.sin(math.pi * (h - 7) / 12) * ruido(0.05))
                    valores[variable] = round(max(uv, 0), 1)
        return {
            "sede": self.sede,
            "ts": ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mediciones": [{"variable": k, "valor": v, "unidad": PUNTOS[self.sede][k]} for k, v in valores.items()],
        }


class Cola:
    """Cola persistente en disco: sobrevive a cortes de Internet y de energía."""

    def __init__(self, ruta):
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.lock = threading.Lock()
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS cola (ts TEXT PRIMARY KEY, lote TEXT, enviado INTEGER DEFAULT 0)")
            self.db.execute("CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT)")

    def guardar(self, lotes):
        with self.lock, self.db:
            self.db.executemany("INSERT OR IGNORE INTO cola (ts, lote) VALUES (?, ?)",
                                [(l["ts"], json.dumps(l)) for l in lotes])

    def pendientes(self, n):
        with self.lock:
            filas = self.db.execute("SELECT ts, lote FROM cola WHERE enviado = 0 ORDER BY ts LIMIT ?", (n,)).fetchall()
        return [ts for ts, _ in filas], [json.loads(l) for _, l in filas]

    def marcar(self, claves, valor=1):
        with self.lock, self.db:
            self.db.executemany("UPDATE cola SET enviado = ? WHERE ts = ?", [(valor, k) for k in claves])

    def total_pendientes(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM cola WHERE enviado = 0").fetchone()[0]

    def leer_estado(self, clave, defecto=None):
        with self.lock:
            fila = self.db.execute("SELECT valor FROM estado WHERE clave = ?", (clave,)).fetchone()
        return json.loads(fila[0]) if fila else defecto

    def guardar_estado(self, clave, valor):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO estado VALUES (?, ?)", (clave, json.dumps(valor)))


class ClienteAPI:
    """Cliente REST: obtiene el token JWT y envía los lotes por HTTP(S)."""

    def __init__(self, api, gateway_id, secreto):
        self.api = api.rstrip("/")
        self.gateway_id, self.secreto = gateway_id, secreto
        self.token = None

    def _post(self, ruta, cuerpo, token=None):
        req = urllib.request.Request(self.api + ruta, data=json.dumps(cuerpo).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def enviar(self, lotes, reintento=True):
        if not self.token:
            self.token = self._post("/api/auth/token", {"gateway_id": self.gateway_id, "secreto": self.secreto})["access_token"]
        try:
            return self._post("/api/lotes", lotes, self.token)
        except urllib.error.HTTPError as e:
            if e.code == 401 and reintento:  # token vencido: se pide otro y se reintenta una sola vez
                self.token = None
                return self.enviar(lotes, reintento=False)
            raise


class Gateway:
    def __init__(self, args):
        self.sede, self.ciclo = args.sede, args.ciclo
        self.cola = Cola(args.cola or f"cola_{args.sede}.db")
        self.cliente = ClienteAPI(args.api, args.id or f"gw-{args.sede.replace('_', '-')}", args.secreto)
        self.medidores = Medidores(args.sede, self.cola.leer_estado("hh", HH_INICIAL[args.sede]))
        self.enlace = True
        self.activo = True
        guardado = self.cola.leer_estado("reloj")
        ahora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        ahora -= timedelta(minutes=ahora.minute % 15)
        if guardado:
            self.reloj = datetime.fromisoformat(guardado)
        else:
            self.reloj = ahora
            if not args.sin_historico:
                self.cargar_historial(ahora)

    def log(self, texto):
        print(f"[{datetime.now():%H:%M:%S}] [{self.sede}] {texto}", flush=True)

    def cargar_historial(self, hasta):
        """Primera puesta en marcha: carga 4 semanas de lecturas para que la regla
        del +20% tenga contra qué comparar desde el primer día."""
        t = hasta - SEMANAS_HISTORIAL * timedelta(weeks=1) - timedelta(hours=1)
        lotes = []
        while t <= hasta:
            lotes.append(self.medidores.leer(t))
            t += PASO
        self.cola.guardar(lotes)
        self.cola.guardar_estado("reloj", hasta.isoformat())
        self.log(f"Historial generado: {len(lotes)} lotes ({SEMANAS_HISTORIAL} semanas) en cola")

    def vaciar_cola(self):
        if not self.enlace:
            return
        while True:
            claves, lotes = self.cola.pendientes(TAMANO_ENVIO)
            if not lotes:
                return
            try:
                r = self.cliente.enviar(lotes)
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")[:300]
                if e.code == 422:  # lote mal formado: no se reintenta para no bloquear la cola
                    self.cola.marcar(claves, 2)
                    self.log(f"Lote rechazado por validación (422): {detalle}")
                    continue
                self.log(f"API respondió {e.code}: {detalle}")
                return
            except (urllib.error.URLError, OSError) as e:
                self.log(f"Sin conexión con la API ({getattr(e, 'reason', e)}). En cola: {self.cola.total_pendientes()}")
                return
            self.cola.marcar(claves)
            if len(lotes) > 1 or r["descartados"]:
                self.log(f"Enviados {len(lotes)} lote(s): {r['aceptados']} aceptados, {r['descartados']} descartados")

    def ciclo_lectura(self):
        self.reloj += PASO
        lote = self.medidores.leer(self.reloj)
        self.cola.guardar([lote])
        self.cola.guardar_estado("reloj", self.reloj.isoformat())
        self.cola.guardar_estado("hh", self.medidores.hh)
        resumen = ", ".join(f"{m['variable']}={m['valor']}" for m in lote["mediciones"])
        self.log(f"{lote['ts']} {resumen}" + ("" if self.enlace else "  [ENLACE CORTADO]"))
        self.vaciar_cola()

    def comandos(self):
        m = self.medidores
        acciones = {
            "e": ("Pico eléctrico", lambda: setattr(m, "pico_electrico", True)),
            "a": ("Pico de agua (fuga)", lambda: setattr(m, "pico_agua", True)),
            "u": ("UV alto (9)", lambda: setattr(m, "uv_forzado", 9)),
            "x": ("UV extremo (11)", lambda: setattr(m, "uv_forzado", 11)),
            "i": ("Incidente registrado: HH sin incidentes = 0", lambda: setattr(m, "hh", 0)),
            "n": ("Operación normal", lambda: (setattr(m, "pico_electrico", False), setattr(m, "pico_agua", False),
                                               setattr(m, "uv_forzado", None))),
            "d": ("Enlace cortado: las lecturas quedan en la cola local", lambda: setattr(self, "enlace", False)),
            "r": ("Enlace restablecido: reenviando cola", lambda: setattr(self, "enlace", True)),
            "s": ("Estado", lambda: None),
        }
        for linea in sys.stdin:
            c = linea.strip().lower()[:1]
            if c == "q":
                self.activo = False
                return
            if c in acciones:
                nombre, accion = acciones[c]
                accion()
                self.log(f"{nombre} · enlace={'OK' if self.enlace else 'CORTADO'} · en cola={self.cola.total_pendientes()}")
                if c == "r":
                    self.vaciar_cola()

    def correr(self):
        self.log(f"Gateway iniciado → {self.cliente.api} · ciclo {self.ciclo}s = 15 min · reloj {self.reloj:%Y-%m-%d %H:%M}Z")
        self.vaciar_cola()
        threading.Thread(target=self.comandos, daemon=True).start()
        while self.activo:
            inicio = time.monotonic()
            self.ciclo_lectura()
            time.sleep(max(0, self.ciclo - (time.monotonic() - inicio)))


def main():
    # Consolas de Windows con codificación cp1252: no caerse por "→" o "·" en los mensajes.
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="Gateway de sede Induplac")
    p.add_argument("--sede", required=True, choices=list(PUNTOS))
    p.add_argument("--api", default=os.getenv("INDUPLAC_API", "http://localhost:8000"))
    p.add_argument("--id", help="id del gateway (por defecto gw-oficina-rm / gw-planta)")
    p.add_argument("--secreto", default=os.getenv("GATEWAY_SECRET"))
    p.add_argument("--ciclo", type=float, default=float(os.getenv("CICLO_SEG", 3)),
                   help="segundos reales por ciclo de 15 min (demo 3, real 900)")
    p.add_argument("--cola", help="archivo SQLite de la cola local")
    p.add_argument("--sin-historico", action="store_true", help="no generar las 4 semanas de historial")
    args = p.parse_args()
    if not args.secreto:
        args.secreto = {"oficina_rm": "secreto-rm", "planta": "secreto-planta"}[args.sede]
    try:
        Gateway(args).correr()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
