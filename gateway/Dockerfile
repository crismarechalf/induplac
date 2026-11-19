# Gateway de sede en contenedor (sin dependencias: solo Python estándar).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY gateway.py .
# Usuario sin privilegios. /datos guarda la cola SQLite y el reloj (volumen propio por sede).
RUN useradd --create-home gateway && mkdir /datos && chown gateway /datos
USER gateway
VOLUME /datos
CMD ["sh", "-c", "exec python gateway.py --sede \"$SEDE\" --api http://api:8000 --secreto \"$SECRETO\" --ciclo \"$CICLO_SEG\" --cola \"/datos/cola_$SEDE.db\" --sin-consola"]
