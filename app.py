"""
app.py
Servidor Flask para edición interactiva del programa de reuniones.

Rutas:
  GET  /          → redirige a /editar
  GET  /catalogo  → cuadrícula de todo el personal
  GET  /editar    → genera propuesta y muestra tabla editable
  POST /guardar   → aplica cambios y genera Programa_Mes.png
  GET  /imagen    → sirve Programa_Mes.png generado
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request, send_file

import assignator as engine
import renderer
from paths import external_path, internal_path

FOTOS_DIR    = external_path("fotos")
BORRADOR_JSON = external_path("borrador_programa.json")
app = Flask(__name__, template_folder=str(internal_path("templates")))

# Estado de sesión (app local de usuario único)
_estado: dict = {"programa": None}

# ─────────────────────────────────────────────────────────────────────────────
# Heartbeat — auto-apagado cuando el navegador se cierra
# ─────────────────────────────────────────────────────────────────────────────

_ultima_actividad: float = time.time()
_TIMEOUT_SEGUNDOS: int = 7    # si pasan 7 s sin heartbeat → apagar
_INTERVALO_CHEQUEO: int = 5   # el hilo revisa cada 5 s


@app.route("/api/heartbeat")
def api_heartbeat():
    global _ultima_actividad
    _ultima_actividad = time.time()
    return "", 204


def _vigilante_heartbeat() -> None:
    """Hilo daemon que apaga el proceso si el navegador deja de latir."""
    while True:
        time.sleep(_INTERVALO_CHEQUEO)
        if time.time() - _ultima_actividad > _TIMEOUT_SEGUNDOS:
            print("Navegador cerrado. Apagando servidor...")
            os._exit(0)


_hilo_vigilante = threading.Thread(target=_vigilante_heartbeat, daemon=True)
_hilo_vigilante.start()

# Lista maestra de roles internos
ROLES_OFICIALES = [
    "Camara", "Zoom", "Acomodador", "Presidente_ES", "Presidente_FDS",
    "Diamante_1", "Diamante_2", "Diamante_3",
    "Trigo", "Ayudante", "Discurso_H",
    "Oveja", "Libro", "Lector_Libro",
    "Conductor_Atalaya",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de datos
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_personal_con_fotos() -> list[dict]:
    """Lee Personal_nuevo.xlsx y adjunta foto base64, iniciales y color."""
    df = pd.read_excel(engine.PERSONAL_FILE, sheet_name="Personal")
    result = []
    for _, row in df.iterrows():
        nombre    = str(row["Nombre"]).strip()
        foto_path = str(row.get("Foto_Path") or "").strip()
        roles_raw = row.get("Roles", "")
        roles_str = "" if pd.isna(roles_raw) else str(roles_raw).strip()
        roles     = [r.strip() for r in roles_str.split(",")
                     if r.strip() and r.strip() != "nan"]
        carga_raw = row.get("Carga_Acumulada")
        carga     = 0 if pd.isna(carga_raw) else int(carga_raw)
        genero_raw = row.get("Genero")
        genero    = "H" if pd.isna(genero_raw) else str(genero_raw).strip().upper()
        mat_raw   = row.get("Matrimonio_ID")
        mat_id    = None if pd.isna(mat_raw) else int(mat_raw)
        aus_raw   = row.get("Ausencias")
        aus_str   = "" if pd.isna(aus_raw) else str(aus_raw).strip()
        ausencias = ", ".join(f.strip() for f in aus_str.split(",") if f.strip())
        activo_raw = row.get("Activo")
        activo = str(activo_raw).strip().lower() not in ("no", "false", "0") if pd.notna(activo_raw) else True
        result.append({
            "nombre":        nombre,
            "foto":          renderer._foto_a_b64(foto_path),
            "iniciales":     renderer._iniciales(nombre),
            "color":         renderer._color_avatar(nombre),
            "roles":         roles,
            "carga":         carga,
            "genero":        genero,
            "matrimonio_id": mat_id,
            "ausencias":     ausencias,
            "activo":        activo,
        })
    return result


def _mk_slot(
    si: int,
    sec: str,
    key: str,
    campo: str,
    nombre: Optional[str],
    personal_map: dict,
    rol: str = "",
    extra: bool = False,
) -> dict:
    """Construye el dict de un slot editable."""
    p = personal_map.get(nombre) if nombre else None
    return {
        "field_id":         f"{si}|{sec}|{key}|{campo}",
        "nombre_actual":    nombre or "",
        "foto_actual":      p["foto"]      if p else None,
        "iniciales_actual": renderer._iniciales(nombre) if nombre else "—",
        "color_actual":     renderer._color_avatar(nombre) if nombre else "#cbd5e1",
        "vacio":            not nombre,
        "rol":              rol,
        "extra":            extra,   # True → slot añadido dinámicamente (mostrará botón ×)
    }


def _extra_slots(
    si: int, sec: str, key: str,
    parte: dict, personal_map: dict, rol: str,
) -> list:
    """Genera slots para los campos extra_0, extra_1, … de una parte (si los hay)."""
    slots = []
    n = 0
    while f"extra_{n}" in parte:
        v = parte[f"extra_{n}"] or None
        if v is not None:   # no mostrar slots de extras ya eliminados
            slots.append(_mk_slot(si, sec, key, f"extra_{n}", v, personal_map, rol, extra=True))
        n += 1
    return slots


def _construir_tabla_editable(programa: dict, personal: list[dict]) -> dict:
    """
    Devuelve la estructura de filas consumida por editar.html,
    paralela a renderer._normalizar pero con slots editables.
    """
    semanas      = programa.get("semanas", [])
    personal_map = {p["nombre"]: p for p in personal}

    headers = [
        {"rango": s["rango_fechas"], "fecha": s.get("fecha_exacta", "")}
        for s in semanas
    ]

    filas: list[dict] = []

    def add(seccion, icono, numero, etiqueta, celdas, es_limpieza=False):
        filas.append({
            "seccion":          seccion,
            "mostrar_cabecera": False,
            "icono":            icono,
            "numero":           numero,
            "etiqueta":         etiqueta,
            "celdas":           celdas,
            "es_limpieza":      es_limpieza,
        })

    LOGISTICA = [
        ("presidente",   "🎤", "Presidente", "Presidente", 1),
        ("camara",       "🎥", "Cámara/PC 💻", "Camara",   2),
        ("zoom",         "💻", "Zoom",        "Zoom",       1),
        ("acomodadores", "🪑", "Acomodadores","Acomodador", 2),
    ]

    # ── Entre semana ──────────────────────────────────────────────────────────
    for key, emo, lbl, rol, n in LOGISTICA:
        celdas = []
        for si, s in enumerate(semanas):
            lst = s["asignaciones"]["entre_semana"].get(key, [None] * n)
            celdas.append([
                _mk_slot(si, "entre_semana", key, str(i),
                         lst[i] if i < len(lst) else None,
                         personal_map, rol)
                for i in range(n)
            ])
        add("entre_semana", emo, 0, lbl, celdas)

    # ── Tesoros ───────────────────────────────────────────────────────────────
    for i in range(3):
        celdas = []
        for si, s in enumerate(semanas):
            partes = s["asignaciones"]["tesoros"]
            nombre = partes[i]["asignado"] if i < len(partes) else None
            celdas.append([_mk_slot(si, "tesoros", str(i), "asignado",
                                    nombre, personal_map, "Trigo")])
        add("tesoros", "💎", i + 1, f"Diamante {i + 1}", celdas)

    # ── Maestros ──────────────────────────────────────────────────────────────
    max_m   = max((len(s["asignaciones"]["maestros"]) for s in semanas), default=0)
    trigo_n = 4
    for i in range(max_m):
        celdas = []
        for si, s in enumerate(semanas):
            partes = s["asignaciones"]["maestros"]
            if i < len(partes):
                parte = partes[i]
                tipo  = parte.get("tipo", "Individual")
                if tipo == "Pareja":
                    base = [
                        _mk_slot(si, "maestros", str(i), "trigo",
                                 parte.get("trigo"),    personal_map, "Trigo"),
                        _mk_slot(si, "maestros", str(i), "ayudante",
                                 parte.get("ayudante"), personal_map, "Ayudante"),
                    ]
                    celdas.append(base + _extra_slots(si, "maestros", str(i), parte, personal_map, "Trigo"))
                else:
                    rol_m = "Discurso_H" if tipo == "Discurso_H" else "Trigo"
                    base  = [_mk_slot(si, "maestros", str(i), "asignado",
                                      parte.get("asignado"), personal_map, rol_m)]
                    celdas.append(base + _extra_slots(si, "maestros", str(i), parte, personal_map, rol_m))
            else:
                celdas.append([_mk_slot(si, "maestros", str(i), "asignado",
                                        None, personal_map, "Trigo")])
        add("maestros", "🌾", trigo_n, f"Trigo {trigo_n}", celdas)
        trigo_n += 1

    # ── Vida Cristiana ────────────────────────────────────────────────────────
    # Estructura uniforme: todas las partes usan campo 'asignado'.
    # tipo == 'Libro'  → Estudio Bíblico (última parte)
    # tipo == 'Oveja'  → partes previas
    max_vc  = max((len(s["asignaciones"]["vida_cristiana"]) for s in semanas), default=0)
    oveja_n = 1
    for i in range(max_vc):
        celdas   = []
        tipo_dom = None
        for si, s in enumerate(semanas):
            partes = s["asignaciones"]["vida_cristiana"]
            if i < len(partes):
                parte = partes[i]
                tipo  = parte.get("tipo", "Oveja")
                if tipo_dom is None:
                    tipo_dom = tipo
                rol_vc = parte.get("rol", "Oveja")
                base   = [_mk_slot(si, "vida_cristiana", str(i), "asignado",
                                   parte.get("asignado"), personal_map, rol_vc)]
                celdas.append(base + _extra_slots(si, "vida_cristiana", str(i), parte, personal_map, rol_vc))
            else:
                celdas.append([_mk_slot(si, "vida_cristiana", str(i), "asignado",
                                        None, personal_map, "Oveja")])

        tipo_dom = tipo_dom or "Oveja"
        if tipo_dom == "Libro":
            emo, num, lbl = "📖", oveja_n, f"{oveja_n}. Estudio del libro"
        else:
            emo, num, lbl = "🐑", oveja_n, f"Oveja {oveja_n}"
        oveja_n += 1
        add("vida_cristiana", emo, num, lbl, celdas)

    # ── Fin de semana ─────────────────────────────────────────────────────────
    for key, emo, lbl, rol, n in LOGISTICA:
        celdas = []
        for si, s in enumerate(semanas):
            lst = s["asignaciones"]["fin_de_semana"].get(key, [None] * n)
            celdas.append([
                _mk_slot(si, "fin_de_semana", key, str(i),
                         lst[i] if i < len(lst) else None,
                         personal_map, rol)
                for i in range(n)
            ])
        add("fin_de_semana", emo, 0, lbl, celdas)

    # ── Limpieza ──────────────────────────────────────────────────────────────
    add("limpieza", "🧹", 0, "Limpieza",
        [{"field_id": f"{si}|limpieza|limpieza|valor",
          "valor":    s["asignaciones"].get("limpieza", "Norte")}
         for si, s in enumerate(semanas)],
        es_limpieza=True)

    # Marcar primera fila de cada sección
    seen: set[str] = set()
    for fila in filas:
        if fila["seccion"] not in seen:
            fila["mostrar_cabecera"] = True
            seen.add(fila["seccion"])

    return {
        "headers":     headers,
        "filas":       filas,
        "seccion_cfg": renderer.SECCION_CFG,
    }


def _limpiar_nulos(programa: dict) -> dict:
    """
    Elimina de cada parte (maestros, tesoros, vida_cristiana) las claves
    de persona (trigo, asignado, ayudante, extra_N) cuyo valor sea None o vacío.
    Así el renderer no genera círculos vacíos para slots eliminados.
    """
    for semana in programa.get("semanas", []):
        asig = semana.get("asignaciones", {})
        for sec in ("tesoros", "maestros", "vida_cristiana"):
            for parte in asig.get(sec, []):
                if not isinstance(parte, dict):
                    continue
                claves_nulas = [
                    k for k, v in parte.items()
                    if (v is None or v == "")
                    and (k in ("trigo", "asignado", "ayudante") or k.startswith("extra_"))
                ]
                for k in claves_nulas:
                    del parte[k]
    return programa


def _aplicar_cambios(programa: dict, cambios: dict) -> dict:
    """
    Aplica el mapa {field_id: nombre_nuevo} sobre una copia profunda del programa.
    field_id formato: '{si}|{sec}|{key}|{campo}'
    """
    prog = copy.deepcopy(programa)
    for field_id, nombre_nuevo in cambios.items():
        partes = field_id.split("|")
        if len(partes) != 4:
            continue
        si_str, sec, key, campo = partes
        try:
            si = int(si_str)
        except ValueError:
            continue
        if si >= len(prog["semanas"]):
            continue

        asig = prog["semanas"][si]["asignaciones"]
        val  = nombre_nuevo if nombre_nuevo else None

        if sec in ("tesoros", "maestros", "vida_cristiana"):
            try:
                idx = int(key)
            except ValueError:
                continue
            if idx < len(asig[sec]):
                asig[sec][idx][campo] = val

        elif sec in ("entre_semana", "fin_de_semana"):
            try:
                idx = int(campo)
            except ValueError:
                continue
            lst = asig[sec].setdefault(key, [])
            while len(lst) <= idx:
                lst.append(None)
            lst[idx] = val

        elif sec == "limpieza":
            asig["limpieza"] = val or "Norte"

    return prog


# ─────────────────────────────────────────────────────────────────────────────
# Rutas Flask
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/editar")


@app.route("/catalogo")
def catalogo():
    personal = _cargar_personal_con_fotos()
    return render_template("catalogo.html", personal=personal,
                           roles_oficiales=ROLES_OFICIALES)


@app.route("/editar")
def editar():
    desde_borrador = False

    if BORRADOR_JSON.exists():
        try:
            programa = json.loads(BORRADOR_JSON.read_text(encoding="utf-8"))
            _estado["programa"] = programa
            desde_borrador = True
            print("\n[Web /editar] Borrador cargado desde borrador_programa.json")
        except Exception as exc:
            print(f"[WARN] No se pudo leer el borrador: {exc}. Generando desde cero.")
            BORRADOR_JSON.unlink(missing_ok=True)

    if not desde_borrador:
        print("\n[Web /editar] Generando propuesta con el assignator...")
        programa = engine.generar_programa(guardar_carga=False)
        _estado["programa"] = programa

    personal = _cargar_personal_con_fotos()
    tabla    = _construir_tabla_editable(programa, personal)
    personal_json = json.dumps(
        [{k: v for k, v in p.items()} for p in personal],
        ensure_ascii=False,
    )
    return render_template(
        "editar.html",
        tabla=tabla,
        personal_json=personal_json,
        desde_borrador=desde_borrador,
    )


@app.route("/guardar", methods=["POST"])
def guardar():
    data    = request.get_json(force=True)
    cambios = data.get("cambios", {})

    prog_base = _estado.get("programa")
    if not prog_base:
        return jsonify({"ok": False,
                        "error": "Sin programa en memoria. Abre /editar primero."}), 400

    programa_final   = _aplicar_cambios(prog_base, cambios)
    programa_final   = _limpiar_nulos(programa_final)
    _estado["programa"] = programa_final

    try:
        png = renderer.renderizar(programa_final, actualizar_carga=True)
        # Auto-guardar borrador para que la última versión generada quede disponible
        BORRADOR_JSON.write_text(
            json.dumps(programa_final, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return jsonify({"ok": True, "path": str(png)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/programa/guardar_borrador", methods=["POST"])
def api_guardar_borrador():
    """Aplica los cambios actuales al programa en memoria y lo guarda como borrador."""
    prog_base = _estado.get("programa")
    if not prog_base:
        return jsonify({"ok": False, "error": "Sin programa en memoria. Abre /editar primero."}), 400

    data    = request.get_json(force=True)
    cambios = data.get("cambios", {})
    programa_guardado = _aplicar_cambios(prog_base, cambios)
    programa_guardado = _limpiar_nulos(programa_guardado)
    _estado["programa"] = programa_guardado

    try:
        BORRADOR_JSON.write_text(
            json.dumps(programa_guardado, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/programa/descartar_borrador", methods=["POST"])
def api_descartar_borrador():
    """Elimina el borrador guardado para forzar una nueva asignación automática."""
    try:
        BORRADOR_JSON.unlink(missing_ok=True)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/imagen")
def imagen():
    png = renderer.OUTPUT_PNG
    if not png.exists():
        return "Imagen no generada aún", 404
    return send_file(str(png), mimetype="image/png")


# ─────────────────────────────────────────────────────────────────────────────
# API de gestión de personal
# ─────────────────────────────────────────────────────────────────────────────

def _asignar_matrimonio(df: pd.DataFrame, nombre_a: str, conyuge_nombre: str) -> None:
    """
    Vincula o desvincula a nombre_a con conyuge_nombre en la columna Matrimonio_ID.

    Casos:
      · conyuge_nombre vacío  → elimina el ID de A (desvincula).
      · B ya tiene ID         → asigna ese mismo ID a A.
      · Ninguno tiene ID      → genera nuevo ID único y lo asigna a ambos.

    Modifica el DataFrame en el lugar; no guarda a disco.
    """
    mask_a = df["Nombre"] == nombre_a

    if not conyuge_nombre:
        # Desvincular: limpiar también al otro cónyuge para no dejar IDs huérfanos
        id_actual_raw = df.loc[mask_a, "Matrimonio_ID"].iloc[0]
        if pd.notna(id_actual_raw):
            mask_mismo_id = df["Matrimonio_ID"] == int(id_actual_raw)
            df.loc[mask_mismo_id, "Matrimonio_ID"] = pd.NA
        else:
            df.loc[mask_a, "Matrimonio_ID"] = pd.NA
        return

    mask_b = df["Nombre"] == conyuge_nombre
    if not mask_b.any():
        return

    id_b_raw = df.loc[mask_b, "Matrimonio_ID"].iloc[0]
    if pd.notna(id_b_raw):
        # Caso 1: B ya tiene ID → A adopta ese mismo ID
        df.loc[mask_a, "Matrimonio_ID"] = int(id_b_raw)
    else:
        # Caso 2: ninguno tiene ID → generar uno nuevo para ambos
        ids_existentes = df["Matrimonio_ID"].dropna().astype(int).tolist()
        nuevo_id = max(ids_existentes, default=0) + 1
        df.loc[mask_a, "Matrimonio_ID"] = nuevo_id
        df.loc[mask_b, "Matrimonio_ID"] = nuevo_id


@app.route("/api/personal/actualizar", methods=["POST"])
def api_actualizar():
    """Actualiza Roles, Género y cónyuge de una persona existente."""
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        df   = pd.read_excel(engine.PERSONAL_FILE, sheet_name="Personal")
        mask = df["Nombre"] == nombre
        if not mask.any():
            return jsonify({"ok": False, "error": f"'{nombre}' no encontrado"}), 404

        roles_validos = [r for r in data.get("roles", []) if r in ROLES_OFICIALES]
        aus_raw  = data.get("ausencias", "")
        ausencias = ", ".join(f.strip() for f in aus_raw.split(",") if f.strip())

        df.loc[mask, "Genero"]    = data.get("genero", "H")
        df.loc[mask, "Roles"]     = ", ".join(roles_validos)
        if "Ausencias" not in df.columns:
            df["Ausencias"] = ""
        df["Ausencias"] = df["Ausencias"].fillna("").astype(str).replace("nan", "")
        df.loc[mask, "Ausencias"] = ausencias

        conyuge = data.get("conyuge", "").strip()
        _asignar_matrimonio(df, nombre, conyuge)

        with pd.ExcelWriter(engine.PERSONAL_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Personal")
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False,
                        "error": "Archivo en uso. Cierra Excel e intenta de nuevo."}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/personal/nuevo", methods=["POST"])
def api_nuevo():
    """Agrega una nueva persona a Personal.xlsx, guardando la foto si viene."""
    import base64 as _b64
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        df = pd.read_excel(engine.PERSONAL_FILE, sheet_name="Personal")
        if (df["Nombre"] == nombre).any():
            return jsonify({"ok": False, "error": f"'{nombre}' ya existe en el catálogo"}), 409

        # Guardar foto si viene como data URI base64
        foto_path = ""
        foto_b64  = data.get("foto_b64", "")
        if foto_b64:
            header, _, encoded = foto_b64.partition(",")
            ext = "jpg" if "jpeg" in header or "jpg" in header else \
                  "webp" if "webp" in header else "png"
            foto_nombre = f"{nombre}.{ext}"
            FOTOS_DIR.mkdir(parents=True, exist_ok=True)
            (FOTOS_DIR / foto_nombre).write_bytes(_b64.b64decode(encoded))
            foto_path = foto_nombre

        roles_validos = [r for r in data.get("roles", []) if r in ROLES_OFICIALES]
        aus_raw   = data.get("ausencias", "")
        ausencias = ", ".join(f.strip() for f in aus_raw.split(",") if f.strip())
        nueva = {
            "Nombre":          nombre,
            "Genero":          data.get("genero", "H"),
            "Roles":           ", ".join(roles_validos),
            "Matrimonio_ID":   pd.NA,
            "Foto_Path":       foto_path,
            "Carga_Acumulada": 0,
            "Ausencias":       ausencias,
        }
        if "Ausencias" not in df.columns:
            df["Ausencias"] = ""
        df["Ausencias"] = df["Ausencias"].fillna("").astype(str).replace("nan", "")
        df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)

        # Vincular cónyuge si se indicó (la persona ya debe existir en el df ampliado)
        conyuge = data.get("conyuge", "").strip()
        if conyuge:
            _asignar_matrimonio(df, nombre, conyuge)

        with pd.ExcelWriter(engine.PERSONAL_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Personal")
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False,
                        "error": "Archivo en uso. Cierra Excel e intenta de nuevo."}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/personal/toggle_activo", methods=["POST"])
def api_toggle_activo():
    """Cambia el estado Activo de una persona entre 'Sí' y 'No' en el Excel."""
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        df = pd.read_excel(engine.PERSONAL_FILE, sheet_name="Personal")
        mask = df["Nombre"] == nombre
        if not mask.any():
            return jsonify({"ok": False, "error": f"'{nombre}' no encontrado"}), 404

        if "Activo" not in df.columns:
            df["Activo"] = "Sí"

        actual = str(df.loc[mask, "Activo"].iloc[0]).strip().lower()
        nuevo  = "No" if actual not in ("no", "false", "0") else "Sí"
        df.loc[mask, "Activo"] = nuevo

        with pd.ExcelWriter(engine.PERSONAL_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Personal")
        return jsonify({"ok": True, "activo": nuevo == "Sí"})
    except PermissionError:
        return jsonify({"ok": False,
                        "error": "Archivo en uso. Cierra Excel e intenta de nuevo."}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada standalone
# ─────────────────────────────────────────────────────────────────────────────

def run(port: int = 5000, open_browser: bool = True) -> None:
    import threading
    import time
    import webbrowser

    if open_browser:
        def _abrir():
            time.sleep(1.2)
            webbrowser.open_new_tab(f"http://127.0.0.1:{port}/editar")
        threading.Thread(target=_abrir, daemon=True).start()

    print(f"\n  Servidor iniciado → http://127.0.0.1:{port}/editar\n")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run()
