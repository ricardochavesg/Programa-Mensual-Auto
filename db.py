"""
db.py
Base de datos local (SQLite) del sistema.

Reemplaza a Personal_nuevo.xlsx. Un único archivo `programa.db` junto al .exe
guarda:

  · personas   → catálogo del personal (roles, género, matrimonio, ausencias…)
  · historial  → cada asignación confirmada, por semana / mes / reunión.
                 El motor lo usa para repartir la carga y evitar repetir
                 a las mismas personas que el mes anterior.

En el primer arranque, si la base está vacía y existe Personal_nuevo.xlsx,
se importa automáticamente (el Excel queda intacto como respaldo).
"""

from __future__ import annotations

import shutil
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from paths import external_path

DB_FILE    = external_path("programa.db")
EXCEL_FILE = external_path("Personal_nuevo.xlsx")

ES  = "ES"    # reunión entre semana
FDS = "FDS"   # reunión fin de semana

# Lista maestra de roles internos
ROLES_OFICIALES = [
    "Camara", "Zoom", "Acomodador", "Presidente_ES", "Presidente_FDS",
    "Diamante_1", "Diamante_2", "Diamante_3",
    "Trigo", "Ayudante", "Discurso_H",
    "Oveja", "Libro", "Lector_Libro",
    "Conductor_Atalaya",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT    NOT NULL UNIQUE,
    genero          TEXT    NOT NULL DEFAULT 'H',
    roles           TEXT    NOT NULL DEFAULT '',
    matrimonio_id   INTEGER,
    foto_path       TEXT    NOT NULL DEFAULT '',
    ausencias       TEXT    NOT NULL DEFAULT '',
    activo          INTEGER NOT NULL DEFAULT 1,
    carga_inicial   INTEGER NOT NULL DEFAULT 0   -- Carga_Acumulada importada del Excel
);

CREATE TABLE IF NOT EXISTS historial (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    semana   TEXT NOT NULL,   -- lunes de la semana (ISO)
    fecha    TEXT NOT NULL,   -- fecha de la reunión (ISO)
    mes      TEXT NOT NULL,   -- 'YYYY-MM' del programa al que pertenece
    reunion  TEXT NOT NULL,   -- 'ES' | 'FDS'
    seccion  TEXT NOT NULL,
    rol      TEXT NOT NULL,
    nombre   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_historial_semana ON historial(semana);
CREATE INDEX IF NOT EXISTS ix_historial_mes    ON historial(mes);
CREATE INDEX IF NOT EXISTS ix_historial_nombre ON historial(nombre);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Conexión
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inicializar() -> None:
    """Crea las tablas y migra desde Excel si la base está vacía."""
    with conectar() as con:
        con.executescript(_SCHEMA)
        vacia = con.execute("SELECT COUNT(*) FROM personas").fetchone()[0] == 0
    if vacia and EXCEL_FILE.exists():
        n = importar_excel(EXCEL_FILE)
        print(f"[INFO] Migración: {n} persona(s) importadas de {EXCEL_FILE.name} → {DB_FILE.name}")


def respaldar() -> Optional[Path]:
    """Copia programa.db a backups/ con marca de tiempo."""
    if not DB_FILE.exists():
        return None
    backups = DB_FILE.parent / "backups"
    backups.mkdir(exist_ok=True)
    destino = backups / f"programa_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(DB_FILE, destino)
    return destino


# ─────────────────────────────────────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────────────────────────────────────

def _clave_rol(texto: str) -> str:
    """'Cámara ' → 'camara', 'Diamante 1' → 'diamante_1'."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "_".join(sin_acentos.strip().lower().replace("-", " ").replace("_", " ").split())


_ROLES_CANONICOS: dict[str, str] = {_clave_rol(r): r for r in ROLES_OFICIALES}
# Alias históricos
_ROLES_CANONICOS.update({
    "presidente":   "Presidente_ES",
    "acomodadores": "Acomodador",
    "lector":       "Lector_Libro",
    "conductor":    "Conductor_Atalaya",
})


def normalizar_rol(rol: str) -> str:
    """Devuelve la forma canónica de un rol (tolerante a mayúsculas, espacios y acentos)."""
    return _ROLES_CANONICOS.get(_clave_rol(rol), rol.strip())


def _parsear_roles(texto: str) -> list[str]:
    roles: list[str] = []
    for r in (texto or "").split(","):
        r = r.strip()
        if r and r.lower() != "nan":
            canon = normalizar_rol(r)
            if canon not in roles:
                roles.append(canon)
    return roles


def _limpiar_ausencias(texto: str) -> str:
    return ", ".join(f.strip() for f in (texto or "").split(",") if f.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Personas
# ─────────────────────────────────────────────────────────────────────────────

def _fila_a_dict(row: sqlite3.Row) -> dict:
    return {
        "nombre":        row["nombre"],
        "genero":        (row["genero"] or "H").upper(),
        "roles":         _parsear_roles(row["roles"]),
        "matrimonio_id": row["matrimonio_id"],
        "foto_path":     row["foto_path"] or "",
        "ausencias":     row["ausencias"] or "",
        "activo":        bool(row["activo"]),
    }


def listar_personas() -> list[dict]:
    with conectar() as con:
        rows = con.execute("SELECT * FROM personas ORDER BY nombre COLLATE NOCASE").fetchall()
    return [_fila_a_dict(r) for r in rows]


def existe_persona(nombre: str) -> bool:
    with conectar() as con:
        return con.execute("SELECT 1 FROM personas WHERE nombre = ?", (nombre,)).fetchone() is not None


def crear_persona(
    nombre: str,
    genero: str = "H",
    roles: Optional[list[str]] = None,
    foto_path: str = "",
    ausencias: str = "",
    activo: bool = True,
    matrimonio_id: Optional[int] = None,
    carga_inicial: int = 0,
) -> None:
    with conectar() as con:
        con.execute(
            "INSERT INTO personas (nombre, genero, roles, matrimonio_id, foto_path,"
            " ausencias, activo, carga_inicial) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                nombre.strip(), (genero or "H").upper(),
                ", ".join(_parsear_roles(", ".join(roles or []))),
                matrimonio_id, foto_path, _limpiar_ausencias(ausencias),
                1 if activo else 0, carga_inicial,
            ),
        )


def actualizar_persona(nombre: str, genero: str, roles: list[str], ausencias: str) -> bool:
    with conectar() as con:
        cur = con.execute(
            "UPDATE personas SET genero = ?, roles = ?, ausencias = ? WHERE nombre = ?",
            ((genero or "H").upper(), ", ".join(_parsear_roles(", ".join(roles))),
             _limpiar_ausencias(ausencias), nombre),
        )
        return cur.rowcount > 0


def asignar_matrimonio(nombre_a: str, conyuge: str) -> None:
    """
    Vincula o desvincula a nombre_a con conyuge.

      · conyuge vacío   → desvincula a A (y a quien compartía su ID).
      · B ya tiene ID   → A adopta ese mismo ID.
      · Ninguno tiene ID → nuevo ID único para ambos.
    """
    with conectar() as con:
        fila_a = con.execute("SELECT matrimonio_id FROM personas WHERE nombre = ?",
                             (nombre_a,)).fetchone()
        if fila_a is None:
            return

        if not conyuge:
            if fila_a["matrimonio_id"] is not None:
                con.execute("UPDATE personas SET matrimonio_id = NULL WHERE matrimonio_id = ?",
                            (fila_a["matrimonio_id"],))
            return

        fila_b = con.execute("SELECT matrimonio_id FROM personas WHERE nombre = ?",
                             (conyuge,)).fetchone()
        if fila_b is None:
            return

        if fila_b["matrimonio_id"] is not None:
            con.execute("UPDATE personas SET matrimonio_id = ? WHERE nombre = ?",
                        (fila_b["matrimonio_id"], nombre_a))
        else:
            nuevo = (con.execute("SELECT MAX(matrimonio_id) FROM personas").fetchone()[0] or 0) + 1
            con.execute("UPDATE personas SET matrimonio_id = ? WHERE nombre IN (?, ?)",
                        (nuevo, nombre_a, conyuge))


def alternar_activo(nombre: str) -> Optional[bool]:
    """Invierte el estado Activo. Devuelve el nuevo estado o None si no existe."""
    with conectar() as con:
        fila = con.execute("SELECT activo FROM personas WHERE nombre = ?", (nombre,)).fetchone()
        if fila is None:
            return None
        nuevo = 0 if fila["activo"] else 1
        con.execute("UPDATE personas SET activo = ? WHERE nombre = ?", (nuevo, nombre))
        return bool(nuevo)


# ─────────────────────────────────────────────────────────────────────────────
# Importar / exportar Excel
# ─────────────────────────────────────────────────────────────────────────────

def importar_excel(ruta: Path) -> int:
    """Importa (o actualiza) personas desde un Excel con el formato antiguo."""
    import pandas as pd

    df = pd.read_excel(ruta, sheet_name="Personal")

    def _txt(row, col) -> str:
        v = row.get(col)
        return "" if v is None or pd.isna(v) else str(v).strip()

    n = 0
    with conectar() as con:
        for _, row in df.iterrows():
            nombre = _txt(row, "Nombre")
            if not nombre:
                continue
            mat = row.get("Matrimonio_ID")
            carga = row.get("Carga_Acumulada")
            activo = _txt(row, "Activo").lower() not in ("no", "false", "0")
            con.execute(
                "INSERT INTO personas (nombre, genero, roles, matrimonio_id, foto_path,"
                " ausencias, activo, carga_inicial) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(nombre) DO UPDATE SET genero=excluded.genero,"
                " roles=excluded.roles, matrimonio_id=excluded.matrimonio_id,"
                " foto_path=excluded.foto_path, ausencias=excluded.ausencias,"
                " activo=excluded.activo",
                (
                    nombre,
                    (_txt(row, "Genero") or "H").upper(),
                    ", ".join(_parsear_roles(_txt(row, "Roles"))),
                    None if mat is None or pd.isna(mat) else int(mat),
                    _txt(row, "Foto_Path"),
                    _limpiar_ausencias(_txt(row, "Ausencias")),
                    1 if activo else 0,
                    0 if carga is None or pd.isna(carga) else int(carga),
                ),
            )
            n += 1
    return n


def exportar_excel(ruta: Path) -> int:
    """Exporta el catálogo de personas a Excel (útil como respaldo legible)."""
    import pandas as pd

    personas = listar_personas()
    df = pd.DataFrame([{
        "Nombre":        p["nombre"],
        "Genero":        p["genero"],
        "Roles":         ", ".join(p["roles"]),
        "Matrimonio_ID": p["matrimonio_id"],
        "Foto_Path":     p["foto_path"],
        "Ausencias":     p["ausencias"],
        "Activo":        "Sí" if p["activo"] else "No",
    } for p in personas])
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Personal")
    return len(df)


# ─────────────────────────────────────────────────────────────────────────────
# Historial
# ─────────────────────────────────────────────────────────────────────────────

def mes_de(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def mes_anterior(mes: str) -> str:
    anio, m = (int(x) for x in mes.split("-"))
    return f"{anio - 1:04d}-12" if m == 1 else f"{anio:04d}-{m - 1:02d}"


def lunes_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


def guardar_historial(filas: list[dict]) -> int:
    """
    Reemplaza el historial de las semanas incluidas en `filas`.
    Cada fila: {semana, fecha, mes, reunion, seccion, rol, nombre}.
    Al reemplazar por semana, volver a generar el mismo mes no duplica registros.
    """
    semanas = sorted({f["semana"] for f in filas})
    with conectar() as con:
        con.executemany("DELETE FROM historial WHERE semana = ?", [(s,) for s in semanas])
        con.executemany(
            "INSERT INTO historial (semana, fecha, mes, reunion, seccion, rol, nombre)"
            " VALUES (:semana, :fecha, :mes, :reunion, :seccion, :rol, :nombre)",
            filas,
        )
    return len(filas)


def historial(
    mes: Optional[str] = None,
    semana: Optional[str] = None,
    antes_de: Optional[str] = None,
    excluir_semanas: tuple[str, ...] = (),
) -> list[dict]:
    """Consulta flexible del historial (todas las condiciones se combinan con AND)."""
    sql, args = "SELECT * FROM historial WHERE 1=1", []
    if mes:
        sql += " AND mes = ?"
        args.append(mes)
    if semana:
        sql += " AND semana = ?"
        args.append(semana)
    if antes_de:
        sql += " AND semana < ?"
        args.append(antes_de)
    if excluir_semanas:
        sql += f" AND semana NOT IN ({','.join('?' * len(excluir_semanas))})"
        args.extend(excluir_semanas)
    with conectar() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY fecha", args).fetchall()]


def carga_reciente(meses: int = 3) -> dict[str, int]:
    """Asignaciones por persona en los últimos `meses` meses (para mostrar en la UI)."""
    desde = (date.today() - timedelta(days=31 * meses)).isoformat()
    with conectar() as con:
        rows = con.execute(
            "SELECT nombre, COUNT(*) AS n FROM historial WHERE fecha >= ? GROUP BY nombre",
            (desde,),
        ).fetchall()
    return {r["nombre"]: r["n"] for r in rows}
