"""
audit.py
Script de Auditoría de Calidad del Programa Mensual.

Lee programa_mes.json y Personal_nuevo.xlsx y valida que el motor de asignación
no violó ninguna regla de negocio.

Uso:
    python audit.py
"""

from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

# Forzar UTF-8 en stdout para que los emojis y caracteres especiales
# se muestren correctamente en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROGRAMA_JSON = Path(__file__).parent / "programa_mes.json"
PERSONAL_FILE = Path(__file__).parent / "Personal_nuevo.xlsx"

# Roles exentos de la regla de descanso y de duplicidad cross-session
ROLES_SIN_DESCANSO: frozenset = frozenset({"Camara", "Zoom", "Acomodador"})


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def cargar_personal() -> dict[str, dict]:
    """Devuelve {nombre: {genero, roles}} leyendo Personal_nuevo.xlsx."""
    df = pd.read_excel(PERSONAL_FILE, sheet_name="Personal")
    personal: dict[str, dict] = {}
    for _, row in df.iterrows():
        nombre = str(row["Nombre"]).strip()
        genero = str(row.get("Genero") or "H").strip().upper()
        raw_roles = row.get("Roles")
        roles_str = "" if pd.isna(raw_roles) else str(raw_roles).strip()
        roles = {
            r.strip()
            for r in roles_str.split(",")
            if r.strip() and r.strip().lower() != "nan"
        }
        personal[nombre] = {"genero": genero, "roles": roles}
    return personal


def cargar_programa() -> dict:
    return json.loads(PROGRAMA_JSON.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Extractor de asignaciones por semana
# ─────────────────────────────────────────────────────────────────────────────

def extraer_semana(asignaciones: dict) -> dict:
    """
    Retorna:
      entre_semana  : list[(nombre, rol_tipo)]  — tesoros+maestros+vc+logística_ES
      fin_de_semana : list[(nombre, rol_tipo)]  — logística_FDS
      discurso_h    : list[nombre]              — para R5a
      pareja_trigos : list[(nombre, nota)]      — para R5b
    """
    entre: list[tuple] = []
    fds: list[tuple] = []
    discurso_h: list[str] = []
    pareja_trigos: list[tuple] = []

    # Tesoros
    for t in asignaciones.get("tesoros", []):
        entre.append((t.get("asignado"), t.get("rol", "Tesoro")))

    # Maestros
    for m in asignaciones.get("maestros", []):
        tipo = m.get("tipo", "Individual")
        titulo = m.get("titulo", "")
        if tipo == "Pareja":
            trigo = m.get("trigo")
            ayudante = m.get("ayudante")
            nota = m.get("nota", "")
            entre.append((trigo, "Pareja-trigo"))
            entre.append((ayudante, "Pareja-ayudante"))
            pareja_trigos.append((trigo, nota))
        elif tipo == "Discurso_H":
            nombre = m.get("asignado")
            entre.append((nombre, "Discurso_H"))
            discurso_h.append(nombre)
        else:
            entre.append((m.get("asignado"), "Individual"))

    # Vida Cristiana
    for vc in asignaciones.get("vida_cristiana", []):
        entre.append((vc.get("asignado"), vc.get("rol", "VC")))

    # Logística entre semana
    for nombre in asignaciones.get("entre_semana", {}).get("camara", []):
        entre.append((nombre, "Camara"))
    for nombre in asignaciones.get("entre_semana", {}).get("zoom", []):
        entre.append((nombre, "Zoom"))
    for nombre in asignaciones.get("entre_semana", {}).get("acomodadores", []):
        entre.append((nombre, "Acomodador"))
    for nombre in asignaciones.get("entre_semana", {}).get("presidente", []):
        entre.append((nombre, "Presidente"))

    # Logística fin de semana
    for nombre in asignaciones.get("fin_de_semana", {}).get("camara", []):
        fds.append((nombre, "Camara"))
    for nombre in asignaciones.get("fin_de_semana", {}).get("zoom", []):
        fds.append((nombre, "Zoom"))
    for nombre in asignaciones.get("fin_de_semana", {}).get("acomodadores", []):
        fds.append((nombre, "Acomodador"))
    for nombre in asignaciones.get("fin_de_semana", {}).get("presidente", []):
        fds.append((nombre, "Presidente"))

    return {
        "entre_semana": entre,
        "fin_de_semana": fds,
        "discurso_h": discurso_h,
        "pareja_trigos": pareja_trigos,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Motor de auditoría
# ─────────────────────────────────────────────────────────────────────────────

class Auditoria:
    def __init__(self, programa: dict, personal: dict[str, dict]):
        self.programa = programa
        self.personal = personal
        self.errores: list[dict] = []
        self.oks: list[dict] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Ejecución principal
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        semanas = self.programa.get("semanas", [])

        # Estado para la regla de descanso:
        # guardamos las personas del entre_semana anterior (igual que el motor).
        personas_es_anterior: set[str] = set()

        for idx, semana in enumerate(semanas):
            rango = semana.get("rango_fechas", f"Semana {idx + 1}")
            asignaciones = semana.get("asignaciones", {})
            ex = extraer_semana(asignaciones)

            es = ex["entre_semana"]    # list[(nombre, rol)]
            fd = ex["fin_de_semana"]   # list[(nombre, rol)]

            # R1 — Celdas vacías
            self._r1_vacios(rango, es + fd)

            # R2 — No-Duplicidad semanal
            self._r2_duplicados(rango, es, fd)

            # R3 — Regla de descanso (desde semana 2 en adelante)
            if idx > 0:
                self._r3_descanso(rango, es + fd, personas_es_anterior)

            # R4 — Conductor Atalaya no en fin de semana
            self._r4_conductor_atalaya(rango, fd)

            # R5a — Discurso_H solo hombres
            self._r5a_discurso_h(rango, ex["discurso_h"])

            # R5b — Trigo de Pareja debe ser Mujer (salvo excepcion_mensual)
            self._r5b_pareja_genero(rango, ex["pareja_trigos"])

            # Actualizar estado para siguiente iteración
            # (el motor solo guarda _asignados_semana = entre_semana)
            personas_es_anterior = {n for n, _ in es if n}

    # ─────────────────────────────────────────────────────────────────────────
    # R1 — Celdas vacías
    # ─────────────────────────────────────────────────────────────────────────

    def _r1_vacios(self, rango: str, asignaciones: list[tuple]) -> None:
        vacios = [
            (nombre, rol)
            for nombre, rol in asignaciones
            if nombre is None or str(nombre).strip() in ("", "None", "nan")
        ]
        if vacios:
            for nombre, rol in vacios:
                self._error(rango, str(nombre), "R1-Celdas Vacías",
                            f"Asignación vacía en rol='{rol}'")
        else:
            self._ok(rango, "R1-Celdas Vacías", "Todas las asignaciones tienen persona")

    # ─────────────────────────────────────────────────────────────────────────
    # R2 — No-Duplicidad semanal
    # ─────────────────────────────────────────────────────────────────────────

    def _r2_duplicados(self, rango: str, es: list[tuple], fd: list[tuple]) -> None:
        errores: list[tuple[str, str]] = []

        # Duplicados dentro del pool entre-semana
        conteo: dict[str, list[str]] = defaultdict(list)
        for nombre, rol in es:
            if nombre:
                conteo[nombre].append(rol)
        for nombre, roles in conteo.items():
            if len(roles) > 1:
                errores.append((nombre, f"aparece {len(roles)}× en entre-semana: {roles}"))

        # Duplicados dentro del pool fin-de-semana
        conteo_fd: dict[str, list[str]] = defaultdict(list)
        for nombre, rol in fd:
            if nombre:
                conteo_fd[nombre].append(rol)
        for nombre, roles in conteo_fd.items():
            if len(roles) > 1:
                errores.append((nombre, f"aparece {len(roles)}× en fin-de-semana: {roles}"))

        # Cross-session: misma persona en ambos pools con rol NO exento en fin-de-semana
        nombres_es = {n for n, _ in es if n}
        for nombre, rol_fd in fd:
            if nombre and nombre in nombres_es and rol_fd not in ROLES_SIN_DESCANSO:
                roles_es = [r for n, r in es if n == nombre]
                errores.append((nombre,
                    f"tiene rol(es) entre-semana {roles_es} "
                    f"Y fin-de-semana '{rol_fd}' (no exento)"))

        if errores:
            for nombre, detalle in errores:
                self._error(rango, nombre, "R2-No-Duplicidad", detalle)
        else:
            self._ok(rango, "R2-No-Duplicidad", "Sin duplicados en la semana")

    # ─────────────────────────────────────────────────────────────────────────
    # R3 — Regla de descanso
    # ─────────────────────────────────────────────────────────────────────────

    def _r3_descanso(self, rango: str, asignaciones: list[tuple],
                     personas_anterior: set[str]) -> None:
        """
        Nadie de la semana N puede estar en la semana N+1,
        EXCEPTO si el rol actual es Camara, Zoom o Acomodador.
        """
        errores: list[tuple[str, str]] = []
        for nombre, rol in asignaciones:
            if not nombre or nombre not in personas_anterior:
                continue
            if rol in ROLES_SIN_DESCANSO:
                continue   # Exento
            errores.append((nombre, rol))

        if errores:
            for nombre, rol in errores:
                self._error(rango, nombre, "R3-Regla Descanso",
                            f"Asignado la semana anterior y de nuevo como '{rol}'")
        else:
            self._ok(rango, "R3-Regla Descanso", "Todos descansaron correctamente")

    # ─────────────────────────────────────────────────────────────────────────
    # R4 — Conductor Atalaya no en fin de semana
    # ─────────────────────────────────────────────────────────────────────────

    def _r4_conductor_atalaya(self, rango: str, fd: list[tuple]) -> None:
        errores: list[tuple[str, str]] = []
        for nombre, rol in fd:
            if not nombre:
                continue
            info = self.personal.get(nombre, {})
            if "Conductor_Atalaya" in info.get("roles", set()):
                errores.append((nombre, rol))

        if errores:
            for nombre, rol in errores:
                self._error(rango, nombre, "R4-Conductor Atalaya",
                            f"Tiene rol Conductor_Atalaya pero está en fin-de-semana como '{rol}'")
        else:
            self._ok(rango, "R4-Conductor Atalaya",
                     "Ningún Conductor_Atalaya en fin-de-semana")

    # ─────────────────────────────────────────────────────────────────────────
    # R5a — Discurso_H solo hombres
    # ─────────────────────────────────────────────────────────────────────────

    def _r5a_discurso_h(self, rango: str, nombres: list[str]) -> None:
        if not nombres:
            return
        errores: list[str] = []
        for nombre in nombres:
            if not nombre:
                continue
            info = self.personal.get(nombre)
            if info is None:
                self._error(rango, nombre, "R5a-Discurso_H Género",
                            f"'{nombre}' no se encontró en Personal.xlsx")
                continue
            if info["genero"] != "H":
                errores.append(nombre)

        if errores:
            for nombre in errores:
                self._error(rango, nombre, "R5a-Discurso_H Género",
                            f"Género={self.personal.get(nombre,{}).get('genero','?')} "
                            f"pero asignado a Discurso_H (solo hombres)")
        else:
            self._ok(rango, "R5a-Discurso_H Género",
                     "Todos los Discurso_H son hombres")

    # ─────────────────────────────────────────────────────────────────────────
    # R5b — Trigo de Pareja → Mujer (salvo excepcion_mensual)
    # ─────────────────────────────────────────────────────────────────────────

    def _r5b_pareja_genero(self, rango: str, pareja_trigos: list[tuple]) -> None:
        if not pareja_trigos:
            return
        errores: list[tuple[str, str]] = []
        for nombre, nota in pareja_trigos:
            if not nombre:
                continue
            if nota == "excepcion_mensual":
                continue
            info = self.personal.get(nombre)
            if info is None:
                self._error(rango, nombre, "R5b-Pareja Género",
                            f"'{nombre}' no se encontró en Personal.xlsx")
                continue
            if info["genero"] != "M":
                errores.append((nombre, info["genero"]))

        if errores:
            for nombre, genero in errores:
                self._error(rango, nombre, "R5b-Pareja Género",
                            f"Género={genero} en rol Trigo de Pareja (sin excepcion_mensual)")
        else:
            self._ok(rango, "R5b-Pareja Género",
                     "Todos los Trigos de Pareja son Mujeres (o excepción válida)")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de registro
    # ─────────────────────────────────────────────────────────────────────────

    def _error(self, semana: str, persona: str, regla: str, detalle: str) -> None:
        self.errores.append({
            "semana": semana, "persona": persona,
            "regla": regla, "detalle": detalle,
        })

    def _ok(self, semana: str, regla: str, detalle: str) -> None:
        self.oks.append({"semana": semana, "regla": regla, "detalle": detalle})


# ─────────────────────────────────────────────────────────────────────────────
# Reporte visual
# ─────────────────────────────────────────────────────────────────────────────

ANCHO = 72


def imprimir_reporte(auditoria: Auditoria) -> int:
    errores = auditoria.errores
    oks = auditoria.oks

    print("\n" + "═" * ANCHO)
    print("  AUDITORÍA DEL PROGRAMA MENSUAL")
    print("═" * ANCHO)

    semanas_programa = auditoria.programa.get("semanas", [])
    generado = auditoria.programa.get("generado", "—")
    print(f"  Generado : {generado}")
    print(f"  Semanas  : {len(semanas_programa)}")
    print(f"  Personal : {len(auditoria.personal)} personas")
    print("─" * ANCHO)

    if errores:
        # Agrupar errores por semana
        por_semana: dict[str, list[dict]] = defaultdict(list)
        for e in errores:
            por_semana[e["semana"]].append(e)

        print(f"\n  {'ERRORES DETECTADOS':^68}")
        for semana, lista in por_semana.items():
            print(f"\n  📅  {semana}")
            for e in lista:
                print(f"      ❌  [{e['regla']}]")
                print(f"           Persona : {e['persona']}")
                print(f"           Detalle : {e['detalle']}")
    else:
        print("\n  ✅  ¡Sin errores! El programa cumple todas las reglas de negocio.")

    # Resumen de checks OK agrupados por regla
    if oks:
        reglas_ok: dict[str, int] = defaultdict(int)
        for c in oks:
            reglas_ok[c["regla"]] += 1
        print(f"\n  {'─' * 68}")
        print("  VERIFICACIONES SUPERADAS:")
        for regla, count in sorted(reglas_ok.items()):
            print(f"  ✅  {regla:<42} {count} semana(s)")

    # Resultado final
    total_errores = len(errores)
    total_ok = len(oks)
    print(f"\n  {'═' * 68}")
    if total_errores == 0:
        estado = "✅  APROBADO"
    else:
        estado = f"❌  REPROBADO — {total_errores} error(es) encontrado(s)"
    print(f"  RESULTADO : {estado}")
    print(f"  Checks OK : {total_ok}   |   Errores : {total_errores}")
    print("═" * ANCHO + "\n")

    return total_errores


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("[1/2] Cargando datos...")

    if not PROGRAMA_JSON.exists():
        print(f"❌  No se encontró '{PROGRAMA_JSON}'. Genera el programa primero (python main.py).")
        sys.exit(1)
    if not PERSONAL_FILE.exists():
        print(f"❌  No se encontró '{PERSONAL_FILE}'.")
        sys.exit(1)

    programa = cargar_programa()
    personal = cargar_personal()
    n_semanas = len(programa.get("semanas", []))
    print(f"      {n_semanas} semana(s) cargada(s) | {len(personal)} persona(s) en personal.")

    print("[2/2] Ejecutando auditoría...")
    auditoria = Auditoria(programa, personal)
    auditoria.run()

    total_errores = imprimir_reporte(auditoria)
    sys.exit(1 if total_errores > 0 else 0)


if __name__ == "__main__":
    main()
