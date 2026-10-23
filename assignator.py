"""
assignator.py
Motor de asignación mensual para el programa de reuniones.

Consume:
  - guia.obtener_semanas_mes()  →  semanas del mes (descarga automática)
  - db (SQLite)                 →  personal + historial de meses anteriores

Devuelve un dict JSON-serializable con el programa completo del mes
y lo persiste en programa_mes.json.

Reglas principales
──────────────────
· Entre semana (ES) y fin de semana (FDS) son pools SEPARADOS, con su propio
  contador de carga. La carga del fin de semana (logística, liviana) no quita
  turnos entre semana, y en FDS se permite repetir a quien ya tiene parte ES.
· Reparto equitativo: primero quien tiene menos asignaciones en el mes; en
  empate, quien no tuvo ese mismo rol el mes anterior, luego quien tuvo menos
  asignaciones el mes anterior y por último quien lleva más tiempo sin
  participar (todo leído del historial en la base de datos).
· Dentro de una semana se asignan primero los roles con MENOS candidatos
  (ej. Presidente) para que no se queden sin gente y aparezcan huecos o
  repeticiones.
· Llenado garantizado (must-fill): si no hay nadie libre se relajan las reglas
  en orden; las ausencias y el estado Inactivo nunca se relajan.
"""

from __future__ import annotations

import json
import random
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import db
import guia
import parser as weekly_parser
from paths import external_path

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_JSON     = external_path("programa_mes.json")
GRUPOS_LIMPIEZA = ["Norte", "Sur", "Central"]

ES, FDS = db.ES, db.FDS

# Roles exentos de la regla de descanso semanal (logística de alta rotación)
ROLES_SIN_DESCANSO: frozenset = frozenset({"Camara", "Zoom", "Acomodador"})

# (clave, rol ES, rol FDS, cantidad)
LOGISTICA = [
    ("presidente",   "Presidente_ES", "Presidente_FDS", 1),
    ("camara",       "Camara",        "Camara",         2),
    ("zoom",         "Zoom",          "Zoom",           1),
    ("acomodadores", "Acomodador",    "Acomodador",     2),
]


# ─────────────────────────────────────────────────────────────────────────────
# Modelo de datos
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Persona:
    nombre:        str
    genero:        str            # "H" | "M"
    roles:         set            # set[str]
    matrimonio_id: Optional[int]
    foto_path:     str
    ausencias:     set            # set[str] de fechas "DD/MM" bloqueadas
    activo:        bool           # False → excluido de toda asignación (bloqueador absoluto)
    # Carga por reunión durante el mes que se genera
    mes:           Counter = field(default_factory=Counter)   # {ES: n, FDS: n}
    # Historial del mes anterior (leído de la base de datos)
    prev:          Counter = field(default_factory=Counter)   # {ES: n, FDS: n}
    prev_roles:    set     = field(default_factory=set)       # {(reunion, rol)}
    ultima:        dict    = field(default_factory=dict)      # {reunion: date}


def _cargar_personal() -> list[Persona]:
    personas = db.listar_personas()
    if not personas:
        raise RuntimeError("No hay personal registrado. Agrega personas en el Catálogo.")
    return [
        Persona(
            nombre        = p["nombre"],
            genero        = p["genero"],
            roles         = set(p["roles"]),
            matrimonio_id = p["matrimonio_id"],
            foto_path     = p["foto_path"],
            ausencias     = {f.strip() for f in p["ausencias"].split(",") if f.strip()},
            activo        = p["activo"],
        )
        for p in personas
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Motor de asignación
# ─────────────────────────────────────────────────────────────────────────────

class Assignator:
    """
    Procesa una lista de semanas y asigna personal a cada parte.
    `historial_previo` son filas de db.historial() anteriores al mes generado.
    """

    def __init__(
        self,
        personal: list[Persona],
        semanas: list[dict],
        historial_previo: Optional[list[dict]] = None,
        mes_anterior: Optional[str] = None,
    ):
        self.personal = personal
        self._por_nombre = {p.nombre: p for p in personal}
        self.semanas  = sorted(semanas, key=lambda s: s["fecha_reunion"] or date.min)

        # ── Estado de semana (reiniciado cada semana) ──
        self._usados: dict[str, set[str]]    = {ES: set(), FDS: set()}
        self._anterior: dict[str, set[str]]  = {ES: set(), FDS: set()}
        self._fecha: dict[str, Optional[date]] = {ES: None, FDS: None}

        # ── Estado de mes ──
        self._excepcion_hombre_pendiente = True
        self._historial_parejas: dict[str, set[str]] = defaultdict(set)
        self._parejas_restantes_mes = sum(
            1 for s in self.semanas for p in s["partes"].get("maestros", [])
            if p.get("tipo") == "Pareja"
        )
        self._limpieza_idx = 0

        self._aplicar_historial(historial_previo or [], mes_anterior)

    # =========================================================================
    # Historial
    # =========================================================================

    def _aplicar_historial(self, filas: list[dict], mes_anterior: Optional[str]) -> None:
        """
        · Mes anterior → contadores `prev` / `prev_roles` (evitar repetir).
        · Última semana registrada justo antes del mes → regla de descanso.
        · Fecha de última participación → desempate por antigüedad.
        """
        primera = self.semanas[0]["fecha_inicio"] if self.semanas else None
        semana_previa = (
            (db.lunes_de(primera) - timedelta(days=7)).isoformat()
            if primera else None
        )
        if mes_anterior is None and primera:
            mes_anterior = db.mes_anterior(db.mes_de(weekly_parser.calcular_dia_reunion(primera)))

        for f in filas:
            p = self._por_nombre.get(f["nombre"])
            if p is None:
                continue
            reunion, fecha = f["reunion"], date.fromisoformat(f["fecha"])
            if f["mes"] == mes_anterior:
                p.prev[reunion] += 1
                p.prev_roles.add((reunion, f["rol"]))
            if f["semana"] == semana_previa:
                self._anterior[reunion].add(p.nombre)
            if fecha > p.ultima.get(reunion, date.min):
                p.ultima[reunion] = fecha

    # =========================================================================
    # Entrada principal
    # =========================================================================

    def asignar_mes(self) -> dict:
        """Procesa todas las semanas y devuelve el programa mensual completo."""
        semanas_resultado = []

        for semana in self.semanas:
            asignaciones = self._asignar_semana(semana)
            semanas_resultado.append({
                "rango_fechas":  semana["rango_fechas"],
                "fecha_inicio":  (semana["fecha_inicio"].isoformat()
                                  if semana.get("fecha_inicio") else None),
                "fecha_reunion": (semana["fecha_reunion"].isoformat()
                                  if semana["fecha_reunion"] else None),
                "fecha_exacta":  semana.get("fecha_exacta", ""),
                "asignaciones":  asignaciones,
            })
            # Lo de esta semana pasa a ser "la semana anterior" (regla de descanso)
            self._anterior = {ES: set(self._usados[ES]), FDS: set(self._usados[FDS])}
            self._usados   = {ES: set(), FDS: set()}

        resumen = self._generar_resumen_carga()
        self._imprimir_resumen_carga(resumen)

        return {
            "generado": datetime.now().isoformat(timespec="seconds"),
            "semanas":  semanas_resultado,
            "resumen_carga": resumen,
        }

    # =========================================================================
    # Despacho por semana
    # =========================================================================

    def _asignar_semana(self, semana: dict) -> dict:
        fecha_es = semana.get("fecha_reunion")
        inicio   = semana.get("fecha_inicio")
        self._fecha = {
            ES:  fecha_es,
            FDS: weekly_parser.calcular_dia_fds(db.lunes_de(inicio)) if inicio else fecha_es,
        }
        partes = semana["partes"]

        resultado: dict = {
            "tesoros": [
                {"rol": p.get("rol", ""), "titulo": p.get("titulo", ""), "asignado": None}
                for p in partes.get("tesoros", [])
            ],
            "maestros":       [None] * len(partes.get("maestros", [])),
            "vida_cristiana": [
                {"rol": p.get("rol", "Oveja"), "titulo": p.get("titulo", ""),
                 "tipo": p.get("tipo", p.get("rol", "Oveja")), "asignado": None}
                for p in partes.get("vida_cristiana", [])
            ],
            "entre_semana":  {k: [None] * n for k, _, _, n in LOGISTICA},
            "fin_de_semana": {k: [None] * n for k, _, _, n in LOGISTICA},
            "limpieza":      self._siguiente_grupo_limpieza(),
        }

        # Cada tarea = (rol que determina la escasez, reunión, función que asigna)
        tareas: list[tuple[str, str, Callable[[], None]]] = []

        def _simple(destino: dict, rol: str, reunion: str, **kw):
            def run():
                p = self._elegir(rol, reunion, **kw)
                destino["asignado"] = p.nombre if p else None
            return run

        for parte in resultado["tesoros"]:
            tareas.append((parte["rol"], ES, _simple(parte, parte["rol"], ES)))

        for i, parte in enumerate(partes.get("maestros", [])):
            tipo, titulo = parte.get("tipo", "Individual"), parte.get("titulo", "")
            if tipo == "Pareja":
                def run(i=i, titulo=titulo):
                    resultado["maestros"][i] = self._asignar_pareja_trigo(titulo)
                tareas.append(("Trigo", ES, run))
            else:
                destino = {"titulo": titulo, "tipo": tipo, "asignado": None}
                resultado["maestros"][i] = destino
                if tipo == "Discurso_H":
                    tareas.append(("Discurso_H", ES,
                                   _simple(destino, "Discurso_H", ES, solo_genero="H")))
                else:
                    tareas.append(("Trigo", ES, _simple(destino, "Trigo", ES)))

        for parte in resultado["vida_cristiana"]:
            tareas.append((parte["rol"], ES, _simple(parte, parte["rol"], ES)))

        for clave, rol_es, rol_fds, n in LOGISTICA:
            for reunion, rol, sec in ((ES, rol_es, "entre_semana"), (FDS, rol_fds, "fin_de_semana")):
                for idx in range(n):
                    def run(sec=sec, clave=clave, idx=idx, rol=rol, reunion=reunion):
                        p = self._elegir(rol, reunion)
                        resultado[sec][clave][idx] = p.nombre if p else None
                    tareas.append((rol, reunion, run))

        # Roles escasos primero (orden estable para empates)
        tareas.sort(key=lambda t: len(self._pool(t[0], t[1])))
        for _, _, run in tareas:
            run()

        return resultado

    # =========================================================================
    # LIMPIEZA (rotación Norte → Sur → Central)
    # =========================================================================

    def _siguiente_grupo_limpieza(self) -> str:
        grupo = GRUPOS_LIMPIEZA[self._limpieza_idx % len(GRUPOS_LIMPIEZA)]
        self._limpieza_idx += 1
        return grupo

    # =========================================================================
    # MOTOR DE TRIGOS
    # =========================================================================

    def _asignar_pareja_trigo(self, titulo: str) -> dict:
        """
        Asigna Trigo + Ayudante con las siguientes reglas (en orden):

        1. Excepción mensual: intenta matrimonio o pareja de hombres (una vez/mes).
        2. Asignación normal: prioriza mujeres en ambos slots.
        3. Historial de parejas: evita repetir compañero dentro del mes.
        """
        base = {"titulo": titulo, "tipo": "Pareja", "trigo": None, "ayudante": None}

        # ── Regla 1: excepción mensual ──
        self._parejas_restantes_mes = max(0, self._parejas_restantes_mes - 1)
        es_ultima_pareja = self._parejas_restantes_mes == 0
        if self._excepcion_hombre_pendiente and (es_ultima_pareja or random.random() < 0.25):
            excepcion = self._intentar_excepcion_hombre()
            if excepcion:
                self._excepcion_hombre_pendiente = False
                return {**base, **excepcion, "nota": "excepcion_mensual"}

        # ── Regla 2 + 3: asignación normal con prioridad femenina ──
        trigo = self._elegir("Trigo", ES, preferir_genero="M")
        if not trigo:
            return base

        ayudante = self._elegir(
            "Ayudante", ES, preferir_genero="M",
            evitar=self._historial_parejas[trigo.nombre],
        )
        if ayudante:
            self._historial_parejas[trigo.nombre].add(ayudante.nombre)

        return {
            **base,
            "trigo":    trigo.nombre,
            "ayudante": ayudante.nombre if ayudante else None,
        }

    def _intentar_excepcion_hombre(self) -> Optional[dict]:
        """
        Intenta construir la pareja especial mensual:
          1ª opción: matrimonio disponible (H con Trigo + su esposa M con Ayudante)
          2ª opción: pareja de dos hombres (H Trigo + H Ayudante)

        Devuelve dict parcial {"trigo": ..., "ayudante": ...} o None.
        """
        def libre(p: Persona) -> bool:
            return (p.activo and not self._esta_ausente(p, ES)
                    and p.nombre not in self._usados[ES]
                    and p.nombre not in self._anterior[ES])

        disponibles = [p for p in self.personal if libre(p)]

        # ─ Buscar matrimonio ─
        por_id: dict[int, list[Persona]] = defaultdict(list)
        for p in disponibles:
            if p.matrimonio_id is not None:
                por_id[p.matrimonio_id].append(p)

        matrimonios: list[tuple[Persona, Persona]] = []
        for miembros in por_id.values():
            hombre = next((p for p in miembros if p.genero == "H" and "Trigo" in p.roles), None)
            mujer  = next((p for p in miembros if p.genero == "M" and "Ayudante" in p.roles), None)
            if hombre and mujer:
                matrimonios.append((hombre, mujer))

        if matrimonios:
            hombre, mujer = min(
                matrimonios,
                key=lambda t: (self._puntaje(t[0], "Trigo", ES), self._puntaje(t[1], "Ayudante", ES)),
            )
        else:
            # ─ Buscar pareja de hombres ─
            hombres_trigo = sorted(
                (p for p in disponibles if p.genero == "H" and "Trigo" in p.roles),
                key=lambda p: self._puntaje(p, "Trigo", ES),
            )
            hombre = mujer = None
            for trigo_h in hombres_trigo:
                ayudantes_h = [p for p in disponibles
                               if p.genero == "H" and "Ayudante" in p.roles
                               and p.nombre != trigo_h.nombre]
                if ayudantes_h:
                    hombre = trigo_h
                    mujer  = min(ayudantes_h, key=lambda p: self._puntaje(p, "Ayudante", ES))
                    break
            if hombre is None:
                return None  # no fue posible la excepción

        self._confirmar(hombre, "Trigo", ES)
        self._confirmar(mujer, "Ayudante", ES)
        self._historial_parejas[hombre.nombre].add(mujer.nombre)
        return {"trigo": hombre.nombre, "ayudante": mujer.nombre}

    # =========================================================================
    # Selección genérica
    # =========================================================================

    def _esta_ausente(self, persona: Persona, reunion: str) -> bool:
        """True si la persona marcó como ausencia la fecha de esa reunión (o su semana)."""
        if not persona.ausencias:
            return False
        fechas = {self._fecha[reunion]} | ({self._fecha[ES]} if reunion == FDS else set())
        return any(f and f"{f.day:02d}/{f.month:02d}" in persona.ausencias for f in fechas)

    def _pool(self, rol: str, reunion: str, solo_genero: Optional[str] = None) -> list[Persona]:
        """Candidatos posibles: rol + activo + no ausente (bloqueadores permanentes)."""
        rol = db.normalizar_rol(rol)
        return [
            p for p in self.personal
            if rol in p.roles
            and p.activo
            and (solo_genero is None or p.genero == solo_genero)
            and not self._esta_ausente(p, reunion)
            # El conductor de La Atalaya ya tiene parte el fin de semana
            and not (reunion == FDS and "Conductor_Atalaya" in p.roles)
        ]

    def _puntaje(self, p: Persona, rol: str, reunion: str) -> tuple:
        """Menor = mejor candidato."""
        return (
            p.mes[reunion],                          # menos asignaciones este mes
            (reunion, rol) in p.prev_roles,          # no repetir el rol del mes anterior
            p.prev[reunion],                         # menos asignaciones el mes anterior
            p.ultima.get(reunion, date.min),         # más tiempo sin participar
            random.random(),                         # desempate aleatorio
        )

    def _elegir(
        self,
        rol: str,
        reunion: str = ES,
        solo_genero: Optional[str] = None,
        preferir_genero: Optional[str] = None,
        evitar: frozenset | set = frozenset(),
    ) -> Optional[Persona]:
        """
        Elige una persona con el rol dado aplicando niveles de relajación para
        garantizar llenado total (must-fill):

          Nivel 1: libre en esta reunión + descansó la semana pasada + no en `evitar`.
          Nivel 2: libre en esta reunión + descansó.
          Nivel 3: libre en esta reunión (ignora descanso).
          Nivel 4: cualquiera con el rol (repite persona en la reunión, con aviso).

        Si hay `preferir_genero`, los niveles 1-3 se intentan primero solo con
        ese género. Ausencias e Inactivos NUNCA se relajan.
        """
        rol  = db.normalizar_rol(rol)
        pool = self._pool(rol, reunion, solo_genero)
        etiqueta = "entre semana" if reunion == ES else "fin de semana"

        if not pool:
            warnings.warn(
                f"[{etiqueta}] Sin candidatos para rol='{rol}'"
                + (f", género='{solo_genero}'" if solo_genero else "")
                + ". Revisa los roles en el Catálogo.",
                stacklevel=2,
            )
            return None

        usados   = self._usados[reunion]
        anterior = self._anterior[reunion]
        exento   = rol in ROLES_SIN_DESCANSO

        niveles: list[Callable[[Persona], bool]] = [
            lambda p: p.nombre not in usados and (exento or p.nombre not in anterior)
                      and p.nombre not in evitar,
            lambda p: p.nombre not in usados and (exento or p.nombre not in anterior),
            lambda p: p.nombre not in usados,
        ]
        filtros_genero = ([lambda p: p.genero == preferir_genero] if preferir_genero else []) \
                         + [lambda p: True]

        for por_genero in filtros_genero:
            for nivel in niveles:
                candidatos = [p for p in pool if por_genero(p) and nivel(p)]
                if candidatos:
                    elegido = min(candidatos, key=lambda p: self._puntaje(p, rol, reunion))
                    self._confirmar(elegido, rol, reunion)
                    return elegido

        # Nivel 4: must-fill — repetir persona en la misma reunión
        elegido = min(pool, key=lambda p: (self._puntaje(p, rol, reunion)))
        warnings.warn(
            f"[{etiqueta} {self._fecha[reunion]}] Rol='{rol}': no hay suficientes personas "
            f"libres; '{elegido.nombre}' queda con más de una parte.",
            stacklevel=2,
        )
        self._confirmar(elegido, rol, reunion)
        return elegido

    def _confirmar(self, persona: Persona, rol: str, reunion: str) -> None:
        """Suma carga del mes y marca como asignado en la reunión en curso."""
        persona.mes[reunion] += 1
        self._usados[reunion].add(persona.nombre)
        if self._fecha[reunion]:
            persona.ultima[reunion] = self._fecha[reunion]

    # =========================================================================
    # Resumen de carga
    # =========================================================================

    def _generar_resumen_carga(self) -> dict:
        return {
            p.nombre: {
                "entre_semana":  p.mes[ES],
                "fin_de_semana": p.mes[FDS],
                "mes_anterior":  p.prev[ES] + p.prev[FDS],
            }
            for p in sorted(self.personal, key=lambda p: (-p.mes[ES], -p.mes[FDS], p.nombre))
        }

    def _imprimir_resumen_carga(self, resumen: dict) -> None:
        ancho = 60
        print(f"\n{'=' * ancho}")
        print("  RESUMEN DE CARGA DEL MES")
        print("=" * ancho)
        print(f"  {'Nombre':<26} {'Entre sem.':>10} {'Fin sem.':>9} {'Mes ant.':>9}")
        print("-" * ancho)
        for nombre, d in resumen.items():
            print(f"  {nombre:<26} {d['entre_semana']:>10} {d['fin_de_semana']:>9} "
                  f"{d['mes_anterior']:>9}")
        print("=" * ancho)


# ─────────────────────────────────────────────────────────────────────────────
# Historial: programa → filas de la base de datos
# ─────────────────────────────────────────────────────────────────────────────

def filas_historial(programa: dict) -> list[dict]:
    """Convierte un programa (ya editado) en filas para db.guardar_historial()."""
    mes = programa.get("mes")
    filas: list[dict] = []
    for semana in programa.get("semanas", []):
        if not semana.get("fecha_reunion"):
            continue
        f_es  = date.fromisoformat(semana["fecha_reunion"])
        lunes = (date.fromisoformat(semana["fecha_inicio"]) if semana.get("fecha_inicio")
                 else db.lunes_de(f_es))
        f_fds = weekly_parser.calcular_dia_fds(lunes)
        base  = {"semana": lunes.isoformat(), "mes": mes or db.mes_de(f_es)}
        asig  = semana["asignaciones"]

        def add(reunion, fecha, seccion, rol, nombre):
            if nombre:
                filas.append({**base, "fecha": fecha.isoformat(), "reunion": reunion,
                              "seccion": seccion, "rol": rol, "nombre": nombre})

        for parte in asig.get("tesoros", []):
            add(ES, f_es, "tesoros", parte.get("rol", "Diamante"), parte.get("asignado"))
        for parte in asig.get("maestros", []):
            tipo = parte.get("tipo", "Individual")
            if tipo == "Pareja":
                add(ES, f_es, "maestros", "Trigo", parte.get("trigo"))
                add(ES, f_es, "maestros", "Ayudante", parte.get("ayudante"))
            else:
                add(ES, f_es, "maestros", "Discurso_H" if tipo == "Discurso_H" else "Trigo",
                    parte.get("asignado"))
            n = 0
            while f"extra_{n}" in parte:
                add(ES, f_es, "maestros", "Ayudante", parte[f"extra_{n}"])
                n += 1
        for parte in asig.get("vida_cristiana", []):
            add(ES, f_es, "vida_cristiana", parte.get("rol", "Oveja"), parte.get("asignado"))
            n = 0
            while f"extra_{n}" in parte:
                add(ES, f_es, "vida_cristiana", "Lector_Libro", parte[f"extra_{n}"])
                n += 1
        for clave, rol_es, rol_fds, _ in LOGISTICA:
            for nombre in asig.get("entre_semana", {}).get(clave, []):
                add(ES, f_es, "entre_semana", rol_es, nombre)
            for nombre in asig.get("fin_de_semana", {}).get(clave, []):
                add(FDS, f_fds, "fin_de_semana", rol_fds, nombre)
    return filas


# ─────────────────────────────────────────────────────────────────────────────
# Serialización JSON
# ─────────────────────────────────────────────────────────────────────────────

class _DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def mes_por_defecto(hoy: Optional[date] = None) -> str:
    """El mes siguiente (el programa se prepara normalmente con antelación)."""
    hoy = hoy or date.today()
    return f"{hoy.year + 1}-01" if hoy.month == 12 else f"{hoy.year}-{hoy.month + 1:02d}"


def generar_programa(mes: Optional[str] = None) -> dict:
    """
    Función principal del módulo.
    Orquesta la carga de datos, la obtención de la guía y la asignación.

    Args:
        mes: 'YYYY-MM'. Por defecto, el mes siguiente.

    Returns:
        dict con el programa mensual completo (JSON-serializable). Incluye
        'avisos' con los problemas detectados (semanas sin guía, roles sin
        candidatos, personas repetidas…).
    """
    mes = mes or mes_por_defecto()
    anio, m = (int(x) for x in mes.split("-"))

    print("[1/3] Cargando personal desde la base de datos...")
    personal = _cargar_personal()
    print(f"      {len(personal)} personas cargadas.")

    print(f"[2/3] Obteniendo la guía de actividades de {mes}...")
    semanas, avisos = guia.obtener_semanas_mes(anio, m)
    if not semanas:
        return {"mes": mes, "semanas": [], "avisos": avisos or ["No hay semanas para procesar."]}

    lunes_mes = tuple(db.lunes_de(s["fecha_inicio"]).isoformat()
                      for s in semanas if s.get("fecha_inicio"))
    previo = db.historial(antes_de=min(lunes_mes), excluir_semanas=lunes_mes) if lunes_mes else []

    print(f"[3/3] Asignando personal a {len(semanas)} semana(s)...")
    motor = Assignator(personal, semanas, previo, mes_anterior=db.mes_anterior(mes))

    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        programa = motor.asignar_mes()

    # Agrupar avisos repetidos (ej. el mismo rol sin candidatos cada semana)
    conteo = Counter(str(w.message) for w in capturados)
    programa["mes"] = mes
    programa["avisos"] = avisos + [f"{msg} (×{n})" if n > 1 else msg for msg, n in conteo.items()]
    if programa["avisos"]:
        print(f"\n  [!] {len(programa['avisos'])} advertencia(s) durante la asignacion:")
        for aviso in programa["avisos"]:
            print(f"     {aviso}")

    OUTPUT_JSON.write_text(
        json.dumps(programa, ensure_ascii=False, indent=2, cls=_DateEncoder),
        encoding="utf-8",
    )
    print(f"\n[OK] Programa guardado en: {OUTPUT_JSON}")
    return programa


if __name__ == "__main__":
    import sys

    db.inicializar()
    generar_programa(sys.argv[1] if len(sys.argv) > 1 else None)
