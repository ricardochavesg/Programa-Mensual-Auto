"""
assignator.py
Motor de asignación mensual para el programa de reuniones.

Consume:
  - parser.parsear_todos()  →  lista de semanas del mes
  - Personal.xlsx           →  base de datos del personal

Devuelve un dict JSON-serializable con el programa completo del mes
y lo persiste en programa_mes.json.
"""

from __future__ import annotations

import json
import random
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

import parser as weekly_parser
from paths import external_path

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

PERSONAL_FILE = external_path("Personal_nuevo.xlsx")
OUTPUT_JSON   = external_path("programa_mes.json")
GRUPOS_LIMPIEZA = ["Norte", "Sur", "Central"]

# Roles exentos de la regla de descanso semanal (logística de alta rotación)
ROLES_SIN_DESCANSO: frozenset = frozenset({"Camara", "Zoom", "Acomodador"})

# Mapa de normalización de roles (variaciones → forma canónica)
_ROLES_CANONICOS: dict[str, str] = {
    r.lower(): r for r in [
        "Camara", "Zoom", "Acomodador", "Presidente_ES", "Presidente_FDS",
        "Diamante_1", "Diamante_2", "Diamante_3",
        "Trigo", "Ayudante", "Discurso_H",
        "Oveja", "Libro", "Lector_Libro",
    ]
}


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
    carga:         int            # mutable durante el procesamiento
    carga_inicial: int            # snapshot al inicio (para el resumen final)
    ausencias:     set            # set[str] de fechas "DD/MM" bloqueadas
    activo:        bool           # False → excluido de toda asignación (bloqueador absoluto)


def _cargar_personal() -> list[Persona]:
    if not PERSONAL_FILE.exists():
        raise FileNotFoundError(
            f"No se encontró '{PERSONAL_FILE}'. Ejecuta setup_db.py primero."
        )
    df = pd.read_excel(PERSONAL_FILE, sheet_name="Personal")
    resultado: list[Persona] = []

    for _, row in df.iterrows():
        raw_roles = row.get("Roles")
        roles_str = "" if pd.isna(raw_roles) else str(raw_roles).strip()
        roles = set()
        for r in roles_str.split(","):
            r = r.strip()
            if r and r.lower() != "nan":
                # Normalizar a forma canónica (sin importar mayúsculas/espacios)
                roles.add(_ROLES_CANONICOS.get(r.lower(), r))

        raw_id = row.get("Matrimonio_ID")
        mat_id = None if pd.isna(raw_id) else int(raw_id)

        raw_carga = row.get("Carga_Acumulada")
        carga = 0 if pd.isna(raw_carga) else int(raw_carga)

        raw_aus = row.get("Ausencias")
        aus_str = "" if pd.isna(raw_aus) else str(raw_aus).strip()
        ausencias: set[str] = set()
        for fecha_str in aus_str.split(","):
            fecha_str = fecha_str.strip()
            if fecha_str:
                ausencias.add(fecha_str)

        raw_activo = row.get("Activo")
        activo = str(raw_activo).strip().lower() not in ("no", "false", "0") if pd.notna(raw_activo) else True

        resultado.append(Persona(
            nombre        = str(row["Nombre"]).strip(),
            genero        = str(row.get("Genero") or "H").strip().upper(),
            roles         = roles,
            matrimonio_id = mat_id,
            foto_path     = str(row.get("Foto_Path") or "").strip(),
            carga         = carga,
            carga_inicial = carga,
            ausencias     = ausencias,
            activo        = activo,
        ))
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Motor de asignación
# ─────────────────────────────────────────────────────────────────────────────

class Assignator:
    """
    Procesa una lista de semanas (output de parser.parsear_todos) y asigna
    personal a cada parte respetando:
      · Menor Carga_Acumulada primero
      · Sin duplicar persona en la misma semana
      · Reglas de Trigo (prioridad femenina, excepción mensual, historial de parejas)
    """

    def __init__(self, personal: list[Persona], semanas: list[dict]):
        self.personal = personal
        self.semanas  = sorted(
            semanas, key=lambda s: s["fecha_reunion"] or date.min
        )
        # ── Estado de semana (reiniciado cada semana) ──
        self._asignados_semana: set[str] = set()
        # Personas asignadas la semana anterior (regla de descanso)
        self._asignados_semana_anterior: set[str] = set()
        # Pool independiente de fin de semana (no comparte con entre semana)
        self._asignados_fds: set[str] = set()
        # Fecha de la reunión en curso (para filtro de ausencias)
        self._fecha_reunion_actual: Optional[date] = None

        # ── Estado de mes (reiniciado al cambiar de mes) ──
        self._excepcion_hombre_pendiente = True
        self._historial_parejas: dict[str, set[str]] = defaultdict(set)
        self._mes_actual: Optional[int] = None
        # Cuántas partes Pareja quedan en el mes (decrementado en cada asignación)
        self._parejas_restantes_mes: int = 0

        # ── Estado global ──
        self._limpieza_idx = 0

    # =========================================================================
    # Entrada principal
    # =========================================================================

    def asignar_mes(self) -> dict:
        """Procesa todas las semanas y devuelve el programa mensual completo."""
        semanas_resultado = []

        for semana in self.semanas:
            # Guardar semana anterior ANTES de reiniciar (regla de descanso)
            self._asignados_semana_anterior = set(self._asignados_semana)
            self._asignados_semana = set()
            self._asignados_fds    = set()
            self._verificar_cambio_mes(semana)
            asignaciones = self._asignar_semana(semana)
            semanas_resultado.append({
                "rango_fechas":  semana["rango_fechas"],
                "fecha_reunion": (
                    semana["fecha_reunion"].isoformat()
                    if semana["fecha_reunion"] else None
                ),
                "fecha_exacta":  semana.get("fecha_exacta", ""),
                "asignaciones":  asignaciones,
            })

        resumen = self._generar_resumen_carga()
        self._imprimir_resumen_carga(resumen)

        return {
            "generado": datetime.now().isoformat(timespec="seconds"),
            "semanas":  semanas_resultado,
            "resumen_carga": resumen,
        }

    # =========================================================================
    # Control de estado mensual
    # =========================================================================

    def _verificar_cambio_mes(self, semana: dict) -> None:
        """Reinicia flags mensuales cuando detecta un cambio de mes."""
        if semana["fecha_reunion"] is None:
            return
        mes = semana["fecha_reunion"].month
        if mes != self._mes_actual:
            self._mes_actual = mes
            self._excepcion_hombre_pendiente = True
            self._historial_parejas = defaultdict(set)
            # Contar cuántas partes Pareja hay en este mes
            self._parejas_restantes_mes = sum(
                1
                for s in self.semanas
                if s["fecha_reunion"] and s["fecha_reunion"].month == mes
                for p in s["partes"].get("maestros", [])
                if p.get("tipo") == "Pareja"
            )

    # =========================================================================
    # Despacho por semana
    # =========================================================================

    def _asignar_semana(self, semana: dict) -> dict:
        self._fecha_reunion_actual = semana.get("fecha_reunion")
        partes = semana["partes"]
        return {
            "tesoros":        self._asignar_tesoros(partes.get("tesoros", [])),
            "maestros":       self._asignar_maestros(partes.get("maestros", [])),
            "vida_cristiana": self._asignar_vida_cristiana(partes.get("vida_cristiana", [])),
            # Logística extra: mismo pool de asignados → no duplicidad entre reuniones
            "entre_semana":   self._asignar_logistica("entre semana"),
            "fin_de_semana":  self._asignar_logistica("fin de semana"),
            "limpieza":       self._siguiente_grupo_limpieza(),
        }

    # =========================================================================
    # Sección TESOROS
    # =========================================================================

    def _asignar_tesoros(self, partes: list[dict]) -> list[dict]:
        resultado = []
        for parte in partes:
            rol    = parte.get("rol", "")
            titulo = parte.get("titulo", "")
            p      = self._elegir(rol)
            resultado.append({
                "rol":      rol,
                "titulo":   titulo,
                "asignado": p.nombre if p else None,
            })
        return resultado

    # =========================================================================
    # Sección MAESTROS
    # =========================================================================

    def _asignar_maestros(self, partes: list[dict]) -> list[dict]:
        resultado = []
        for parte in partes:
            tipo   = parte.get("tipo", "Individual")
            titulo = parte.get("titulo", "")

            if tipo == "Pareja":
                resultado.append(self._asignar_pareja_trigo(titulo))

            elif tipo == "Discurso_H":
                p = self._elegir("Discurso_H", solo_genero="H")
                resultado.append({
                    "titulo":   titulo,
                    "tipo":     "Discurso_H",
                    "asignado": p.nombre if p else None,
                })

            else:  # Individual (ej. Creencias)
                p = self._elegir("Trigo")
                resultado.append({
                    "titulo":   titulo,
                    "tipo":     "Individual",
                    "asignado": p.nombre if p else None,
                })
        return resultado

    # =========================================================================
    # Sección VIDA CRISTIANA
    # =========================================================================

    def _asignar_vida_cristiana(self, partes: list[dict]) -> list[dict]:
        """
        Itera dinámicamente sobre todas las partes de Vida Cristiana.
        Cada parte tiene un rol ('Oveja' o 'Libro') y se asigna una persona
        con ese rol mediante _elegir(), respetando descanso y aleatoriedad.
        Estructura de salida uniforme: siempre incluye 'asignado'.
        """
        resultado = []
        for parte in partes:
            rol    = parte.get("rol", "Oveja")
            titulo = parte.get("titulo", "")
            p      = self._elegir(rol)
            resultado.append({
                "rol":      rol,
                "titulo":   titulo,
                "tipo":     parte.get("tipo", rol),
                "asignado": p.nombre if p else None,
            })
        return resultado

    # =========================================================================
    # LOGÍSTICA EXTRA (Cámara, Zoom, Acomodadores, Presidente)
    # =========================================================================

    def _asignar_logistica(self, etiqueta: str) -> dict:
        """
        Asigna los roles logísticos de una reunión.
        · Entre semana: usa _elegir() (pool compartido con tesoros/maestros/vc).
        · Fin de semana: usa _elegir_fds() (pool completamente independiente,
          con relajación progresiva para garantizar llenado total).
        """
        es_fds = etiqueta == "fin de semana"

        def _n(rol: str, cantidad: int) -> list:
            asignados = []
            for _ in range(cantidad):
                p = (self._elegir_fds(rol, contexto=etiqueta)
                     if es_fds else
                     self._elegir(rol, contexto=etiqueta))
                asignados.append(p.nombre if p else None)
            return asignados

        return {
            "camara":       _n("Camara", 2),
            "zoom":         _n("Zoom", 1),
            "acomodadores": _n("Acomodador", 2),
            "presidente":   _n("Presidente_FDS" if es_fds else "Presidente_ES", 1),
        }

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
        trigo = self._elegir_con_preferencia("Trigo", preferir_genero="M")
        if not trigo:
            return base

        ayudante = self._elegir_ayudante(trigo)
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
        disponibles = {
            p.nombre: p for p in self.personal
            if p.activo
            and p.nombre not in self._asignados_semana
            and not self._esta_ausente(p)
        }

        # ─ Buscar matrimonio ─
        por_id: dict[int, list[Persona]] = defaultdict(list)
        for p in disponibles.values():
            if p.matrimonio_id is not None:
                por_id[p.matrimonio_id].append(p)

        matrimonios_validos: list[tuple[Persona, Persona]] = []
        for miembros in por_id.values():
            hombre = next(
                (p for p in miembros if p.genero == "H" and "Trigo" in p.roles), None
            )
            mujer = next(
                (p for p in miembros if p.genero == "M" and "Ayudante" in p.roles), None
            )
            if hombre and mujer:
                matrimonios_validos.append((hombre, mujer))

        if matrimonios_validos:
            # Mezclar primero para aleatorizar empates, luego ordenar por carga combinada
            random.shuffle(matrimonios_validos)
            matrimonios_validos.sort(key=lambda t: t[0].carga + t[1].carga)
            hombre, mujer = matrimonios_validos[0]
            self._confirmar(hombre)
            self._confirmar(mujer)
            self._historial_parejas[hombre.nombre].add(mujer.nombre)
            return {"trigo": hombre.nombre, "ayudante": mujer.nombre}

        # ─ Buscar pareja de hombres ─
        hombres_trigo = [p for p in disponibles.values() if p.genero == "H" and "Trigo" in p.roles]
        random.shuffle(hombres_trigo)
        hombres_trigo.sort(key=lambda p: p.carga)

        for trigo_h in hombres_trigo:
            ayudantes_h = [
                p for p in disponibles.values()
                if p.genero == "H"
                and "Ayudante" in p.roles
                and p.nombre != trigo_h.nombre
            ]
            if ayudantes_h:
                random.shuffle(ayudantes_h)
                ayudantes_h.sort(key=lambda p: p.carga)
                ayudante_h = ayudantes_h[0]
                self._confirmar(trigo_h)
                self._confirmar(ayudante_h)
                self._historial_parejas[trigo_h.nombre].add(ayudante_h.nombre)
                return {"trigo": trigo_h.nombre, "ayudante": ayudante_h.nombre}

        return None  # no fue posible la excepción

    def _elegir_ayudante(self, trigo: Persona) -> Optional[Persona]:
        """
        Elige el mejor Ayudante para el Trigo dado:
          · Excluye a quienes ya fueron compañeros de este Trigo este mes.
          · Si no hay frescos, relaja la restricción y avisa.
          · Prioriza mujeres; desempata por menor carga.
        """
        ya_trabajaron = self._historial_parejas.get(trigo.nombre, set())
        excluidos     = self._asignados_semana | {trigo.nombre}

        todos = [
            p for p in self.personal
            if "Ayudante" in p.roles and p.nombre not in excluidos
        ]
        frescos = [p for p in todos if p.nombre not in ya_trabajaron]

        pool = frescos
        if not pool:
            if todos:
                warnings.warn(
                    f"[WARN] Todos los Ayudantes ya trabajaron con '{trigo.nombre}' "
                    "este mes. Relajando restricción de historial.",
                    stacklevel=3,
                )
            else:
                warnings.warn(
                    f"[WARN] Sin Ayudantes disponibles para '{trigo.nombre}'.",
                    stacklevel=3,
                )
                return None
            pool = todos

        mujeres = sorted([p for p in pool if p.genero == "M"], key=lambda p: (p.carga, p.nombre))
        hombres = sorted([p for p in pool if p.genero == "H"], key=lambda p: (p.carga, p.nombre))
        elegido = (mujeres + hombres)[0]
        self._confirmar(elegido)
        return elegido

    # =========================================================================
    # Selección genérica
    # =========================================================================

    def _esta_ausente(self, persona: Persona) -> bool:
        """Devuelve True si la persona tiene marcada la semana actual como ausencia."""
        if not persona.ausencias or self._fecha_reunion_actual is None:
            return False
        fecha = self._fecha_reunion_actual
        return f"{fecha.day:02d}/{fecha.month:02d}" in persona.ausencias

    def _elegir(
        self,
        rol: str,
        solo_genero: Optional[str] = None,
        contexto: str = "",
    ) -> Optional[Persona]:
        """
        Elige una persona con el rol dado aplicando 3 niveles de relajación
        para garantizar llenado total (must-fill):

          Nivel 1: rol + no en semana + descanso (ROLES_SIN_DESCANSO exentos).
          Nivel 2: rol + no en semana            (ignora regla de descanso).
          Nivel 3: rol únicamente                (ignora unicidad semanal).

        La regla de Ausencias NUNCA se relaja — es un bloqueo absoluto.
        Menor Carga_Acumulada primero; empate → random.shuffle.
        """
        rol_canon = _ROLES_CANONICOS.get(rol.strip().lower(), rol.strip())

        # Pool base: rol + género + activo + NO ausente (bloqueadores permanentes)
        con_rol = [
            p for p in self.personal
            if rol_canon in p.roles
            and p.activo
            and (solo_genero is None or p.genero == solo_genero)
            and not self._esta_ausente(p)
        ]

        if not con_rol:
            ctx = f" [{contexto}]" if contexto else ""
            warnings.warn(
                f"[WARN]{ctx} Sin candidatos para rol='{rol_canon}'"
                + (f", género='{solo_genero}'" if solo_genero else ""),
                stacklevel=2,
            )
            return None

        def _mejor(pool: list) -> Persona:
            min_carga = min(p.carga for p in pool)
            empatados = [p for p in pool if p.carga == min_carga]
            random.shuffle(empatados)
            return empatados[0]

        # ── Nivel 1: no en semana + descanso ─────────────────────────────────
        sin_semana = [p for p in con_rol if p.nombre not in self._asignados_semana]
        if sin_semana:
            if rol_canon in ROLES_SIN_DESCANSO:
                candidatos = sin_semana
            else:
                descansados = [p for p in sin_semana
                               if p.nombre not in self._asignados_semana_anterior]
                candidatos  = descansados if descansados else None

            if candidatos:
                elegido = _mejor(candidatos)
                self._confirmar(elegido)
                return elegido

        # ── Nivel 2: no en semana (relaja descanso) ───────────────────────────
        if sin_semana:
            elegido = _mejor(sin_semana)
            self._confirmar(elegido)
            return elegido

        # ── Nivel 3: must-fill — ignora unicidad semanal ─────────────────────
        elegido = _mejor(con_rol)
        self._confirmar(elegido)
        return elegido

    def _elegir_con_preferencia(self, rol: str, preferir_genero: str) -> Optional[Persona]:
        """
        Como _elegir pero prioriza el género indicado (niveles 1 y 2).
        Si no encuentra nadie del género preferido, delega en _elegir (any gender,
        3 niveles de must-fill incluidos).
        """
        rol_canon = _ROLES_CANONICOS.get(rol.strip().lower(), rol.strip())

        con_pref = [
            p for p in self.personal
            if rol_canon in p.roles
            and p.genero == preferir_genero
            and not self._esta_ausente(p)
        ]

        if con_pref:
            def _mejor_pref(pool: list) -> Persona:
                min_carga = min(p.carga for p in pool)
                empatados = [p for p in pool if p.carga == min_carga]
                random.shuffle(empatados)
                return empatados[0]

            sin_semana = [p for p in con_pref if p.nombre not in self._asignados_semana]
            if sin_semana:
                if rol_canon in ROLES_SIN_DESCANSO:
                    candidatos = sin_semana
                else:
                    descansados = [p for p in sin_semana
                                   if p.nombre not in self._asignados_semana_anterior]
                    candidatos  = descansados if descansados else sin_semana
                elegido = _mejor_pref(candidatos)
                self._confirmar(elegido)
                return elegido

        # Fallback: cualquier género con must-fill completo
        return self._elegir(rol_canon)

    def _confirmar(self, persona: Persona) -> None:
        """Incrementa carga y marca como asignado para la semana en curso."""
        persona.carga += 1
        self._asignados_semana.add(persona.nombre)

    def _confirmar_fds(self, persona: Persona) -> None:
        """Incrementa carga y marca como asignado en el pool de fin de semana."""
        persona.carga += 1
        self._asignados_fds.add(persona.nombre)

    def _elegir_fds(
        self,
        rol: str,
        contexto: str = "",
    ) -> Optional[Persona]:
        """
        Elige una persona para el fin de semana con relajación progresiva
        para garantizar llenado total (must-fill).

        Roles EXENTOS (Camara, Zoom, Acomodador) — 2 niveles:
          Nivel 1: no en _asignados_fds
          Nivel 2: cualquier persona con el rol (must-fill)

        Roles NO EXENTOS (Presidente y demás) — 4 niveles:
          Nivel 1: no en _asignados_fds + no en _asignados_semana + descanso
          Nivel 2: no en _asignados_fds + no en _asignados_semana (relaja descanso)
          Nivel 3: no en _asignados_fds (relaja restricción entre-semana)
          Nivel 4: cualquier persona con el rol (must-fill)

        Bloqueadores permanentes (nunca relajables): ausencias, Conductor_Atalaya.
        """
        rol_canon = _ROLES_CANONICOS.get(rol.strip().lower(), rol.strip())

        # Pool base: rol + activo + NO ausente + NO Conductor_Atalaya (bloqueadores permanentes)
        todos = [
            p for p in self.personal
            if rol_canon in p.roles
            and p.activo
            and not self._esta_ausente(p)
            and "Conductor_Atalaya" not in p.roles
        ]
        if not todos:
            ctx = f" [{contexto}]" if contexto else ""
            warnings.warn(
                f"[WARN]{ctx} Sin personas con rol='{rol_canon}'",
                stacklevel=2,
            )
            return None

        def _mejor(pool: list) -> Persona:
            min_carga = min(p.carga for p in pool)
            empatados = [p for p in pool if p.carga == min_carga]
            random.shuffle(empatados)
            self._confirmar_fds(empatados[0])
            return empatados[0]

        # ── ROLES EXENTOS (Camara, Zoom, Acomodador) ─────────────────────────
        if rol_canon in ROLES_SIN_DESCANSO:
            sin_fds = [p for p in todos if p.nombre not in self._asignados_fds]
            return _mejor(sin_fds) if sin_fds else _mejor(todos)

        # ── ROLES NO EXENTOS (Presidente, etc.) ──────────────────────────────
        # Nivel 1: no en fds + no en entre-semana + descansados
        sin_ambos = [
            p for p in todos
            if p.nombre not in self._asignados_fds
            and p.nombre not in self._asignados_semana
        ]
        if sin_ambos:
            descansados = [p for p in sin_ambos
                           if p.nombre not in self._asignados_semana_anterior]
            if descansados:
                return _mejor(descansados)

        # Nivel 2: no en fds + no en entre-semana (relaja descanso)
        if sin_ambos:
            return _mejor(sin_ambos)

        # Nivel 3: no en fds (relaja restricción entre-semana)
        sin_fds = [p for p in todos if p.nombre not in self._asignados_fds]
        if sin_fds:
            warnings.warn(
                f"[WARN] [{contexto}] Rol='{rol_canon}': se relaja no-duplicidad "
                "entre-semana/fin-de-semana por falta de candidatos.",
                stacklevel=2,
            )
            return _mejor(sin_fds)

        # Nivel 4: must-fill — cualquiera con el rol
        warnings.warn(
            f"[WARN] [{contexto}] Rol='{rol_canon}': must-fill, "
            "ignorando todas las restricciones.",
            stacklevel=2,
        )
        return _mejor(todos)

    # =========================================================================
    # Resumen de carga
    # =========================================================================

    def _generar_resumen_carga(self) -> dict:
        return {
            p.nombre: {
                "inicio": p.carga_inicial,
                "fin":    p.carga,
                "delta":  p.carga - p.carga_inicial,
            }
            for p in sorted(self.personal, key=lambda p: -(p.carga - p.carga_inicial))
        }

    def _imprimir_resumen_carga(self, resumen: dict) -> None:
        ancho = 54
        sep_doble  = "=" * ancho
        sep_simple = "-" * ancho
        print(f"\n{sep_doble}")
        print("  RESUMEN DE CARGA ACUMULADA")
        print(sep_doble)
        print(f"  {'Nombre':<24} {'Inicio':>6}  {'Fin':>5}  {'Delta':>6}")
        print(sep_simple)
        for nombre, d in resumen.items():
            delta_str = f"+{d['delta']}" if d["delta"] >= 0 else str(d["delta"])
            print(f"  {nombre:<24} {d['inicio']:>6}  {d['fin']:>5}  {delta_str:>6}")
        print(sep_doble)


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia de carga
# ─────────────────────────────────────────────────────────────────────────────

def guardar_carga_actualizada(personal: list[Persona]) -> None:
    """
    Escribe los valores actualizados de Carga_Acumulada de vuelta al Excel,
    para que el próximo mes parta desde los valores correctos.
    """
    df = pd.read_excel(PERSONAL_FILE, sheet_name="Personal")
    carga_map = {p.nombre: p.carga for p in personal}
    df["Carga_Acumulada"] = df["Nombre"].map(carga_map).fillna(df["Carga_Acumulada"])

    with pd.ExcelWriter(PERSONAL_FILE, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Personal")
    print(f"[OK] Carga actualizada guardada en {PERSONAL_FILE}")


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

def generar_programa(guardar_carga: bool = True) -> dict:
    """
    Función principal del módulo.
    Orquesta la carga de datos, la asignación y la exportación.

    Args:
        guardar_carga: Si True, persiste los nuevos valores de Carga_Acumulada
                       en Personal.xlsx al finalizar.

    Returns:
        dict con el programa mensual completo (JSON-serializable).
    """
    print("[1/3] Cargando personal desde Excel...")
    personal = _cargar_personal()
    print(f"      {len(personal)} personas cargadas.")

    print("[2/3] Parseando archivos HTML...")
    semanas = weekly_parser.parsear_todos()
    if not semanas:
        print("[WARN] No hay semanas para procesar. Verifica input_html/")
        return {}

    print(f"[3/3] Asignando personal a {len(semanas)} semana(s)...")
    motor = Assignator(personal, semanas)

    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        programa = motor.asignar_mes()

    if capturados:
        print(f"\n  [!] {len(capturados)} advertencia(s) durante la asignacion:")
        for w in capturados:
            print(f"     {w.message}")

    # Guardar JSON de salida
    OUTPUT_JSON.write_text(
        json.dumps(programa, ensure_ascii=False, indent=2, cls=_DateEncoder),
        encoding="utf-8",
    )
    print(f"\n[OK] Programa guardado en: {OUTPUT_JSON}")

    if guardar_carga:
        guardar_carga_actualizada(personal)

    _imprimir_roles_disponibles(personal)

    return programa


def _imprimir_roles_disponibles(personal: list[Persona]) -> None:
    """
    Imprime en consola todos los roles actualmente asignados en Personal.xlsx,
    para que el usuario pueda verificar que los nombres coinciden exactamente.
    """
    todos_los_roles: set[str] = set()
    for p in personal:
        todos_los_roles.update(p.roles)

    roles_ordenados = sorted(todos_los_roles)
    ancho = 54
    print(f"\n{'=' * ancho}")
    print("  ROLES DISPONIBLES EN Personal.xlsx")
    print(f"  (Usa estos nombres exactos en la columna 'Roles')")
    print(f"{'=' * ancho}")
    for rol in roles_ordenados:
        personas_con_rol = [p.nombre for p in personal if rol in p.roles]
        print(f"  {rol:<22} ({len(personas_con_rol)} persona(s))")
    print(f"{'=' * ancho}")


if __name__ == "__main__":
    programa = generar_programa()
