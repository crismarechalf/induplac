"""Modelo de datos (SQLAlchemy). PostgreSQL en Docker; SQLite en las pruebas.

Todas las fechas se guardan en UTC sin zona (naive) para que PostgreSQL y SQLite
comparen igual. La API las entrega con sufijo "Z".
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


class Lote(Base):
    """Un envío del gateway: todas las mediciones de una sede en un ciclo."""
    __tablename__ = "lotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sede: Mapped[str] = mapped_column(String(20), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)            # hora de la lectura
    recibido: Mapped[datetime] = mapped_column(DateTime)      # hora de llegada al servidor
    gateway: Mapped[str] = mapped_column(String(40))


class Medicion(Base):
    __tablename__ = "mediciones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"))
    sede: Mapped[str] = mapped_column(String(20))
    variable: Mapped[str] = mapped_column(String(30))
    valor: Mapped[float] = mapped_column(Float)
    unidad: Mapped[str] = mapped_column(String(20))
    ts: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (Index("ix_medicion_serie", "sede", "variable", "ts"),)


class EstadoActual(Base):
    """Último valor evaluado de cada punto de medición (8 filas)."""
    __tablename__ = "estado_actual"
    sede: Mapped[str] = mapped_column(String(20), primary_key=True)
    variable: Mapped[str] = mapped_column(String(30), primary_key=True)
    valor: Mapped[float] = mapped_column(Float)
    unidad: Mapped[str] = mapped_column(String(20))
    estado: Mapped[str] = mapped_column(String(15))
    ts: Mapped[datetime] = mapped_column(DateTime)
    extras: Mapped[dict] = mapped_column(JSON, default=dict)


class Alerta(Base):
    __tablename__ = "alertas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sede: Mapped[str] = mapped_column(String(20))
    variable: Mapped[str] = mapped_column(String(30))
    nivel: Mapped[str] = mapped_column(String(15))
    mensaje: Mapped[str] = mapped_column(String(400))
    ts: Mapped[datetime] = mapped_column(DateTime)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    cerrada_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Usuario(Base):
    """Usuarios del dashboard. La clave se guarda como hash scrypt con sal propia."""
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(80))
    rol: Mapped[str] = mapped_column(String(20))
    sede: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hash: Mapped[str] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado: Mapped[datetime] = mapped_column(DateTime)


class Incidente(Base):
    """Incidente de seguridad registrado por prevención de riesgos."""
    __tablename__ = "incidentes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sede: Mapped[str] = mapped_column(String(20), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)          # cuándo ocurrió (hora real, UTC)
    tipo: Mapped[str] = mapped_column(String(40))
    descripcion: Mapped[str] = mapped_column(String(500))
    registrado_por: Mapped[str] = mapped_column(String(40))
    creado: Mapped[datetime] = mapped_column(DateTime)


class Auditoria(Base):
    """Quién hizo qué y cuándo (hora real): logins, consola e incidentes."""
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    usuario: Mapped[str] = mapped_column(String(40))
    accion: Mapped[str] = mapped_column(String(40))
    detalle: Mapped[dict] = mapped_column(JSON, default=dict)


class Config(Base):
    """Valores del sistema que deben sobrevivir a un reinicio (ej. inicio del reloj simulado)."""
    __tablename__ = "config"
    clave: Mapped[str] = mapped_column(String(40), primary_key=True)
    valor: Mapped[str] = mapped_column(String(200))


_conexion = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_conexion, pool_pre_ping=True)
SesionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def crear_tablas() -> None:
    Base.metadata.create_all(engine)


def obtener_sesion():
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()
