"""
app.py
Servidor Flask para edición interactiva del programa de reuniones.

Rutas:
  GET  /          → redirige a /editar
  GET  /catalogo  → cuadrícula de todo el personal
  GET  /editar    → genera propuesta y muestra tabla editable (?mes=YYYY-MM)
  POST /guardar   → aplica cambios, genera Programa_Mes.png y guarda el historial
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

from flask import Flask, jsonify, redirect, render_template, request, send_file

import assignator as engine
import db
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
ROLES_OFICIALES = db.ROLES_OFICIALES


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de datos
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_personal_con_fotos() -> list[dict]:
    """Lee el personal de la base de datos y adjunta foto base64, iniciales y color."""
    carga = db.carga_reciente()
    result = []
    for p in db.listar_personas():
        nombre = p["nombre"]
        result.append({
            "nombre":        nombre,
            "foto":          renderer._foto_a_b64(p["foto_path"] or nombre),
            "iniciales":     renderer._iniciales(nombre),
            "color":         renderer._color_avatar(nombre),
            "roles":         p["roles"],
            "carga":         carga.get(nombre, 0),   # asignaciones en los últimos 3 meses
            "genero":        p["genero"],
            "matrimonio_id": p["matrimonio_id"],
            "ausencias":     p["ausencias"],
            "activo":        p["activo"],
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
            nombre = partes[i].get("asignado") if i < len(partes) else None
            celdas.append([_mk_slot(si, "tesoros", str(i), "asignado",
                                    nombre, personal_map, f"Diamante_{i + 1}")])
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
    mes_pedido = request.args.get("mes", "").strip() or None
    desde_borrador = False
    programa = None

    if BORRADOR_JSON.exists():
        try:
            borrador = json.loads(BORRADOR_JSON.read_text(encoding="utf-8"))
            if mes_pedido is None or borrador.get("mes") == mes_pedido:
                programa = borrador
                desde_borrador = True
                print("\n[Web /editar] Borrador cargado desde borrador_programa.json")
        except Exception as exc:
            print(f"[WARN] No se pudo leer el borrador: {exc}. Generando desde cero.")
            BORRADOR_JSON.unlink(missing_ok=True)

    if not desde_borrador:
        print("\n[Web /editar] Generando propuesta con el assignator...")
        try:
            programa = engine.generar_programa(mes_pedido)
        except Exception as exc:
            programa = {"mes": mes_pedido or engine.mes_por_defecto(), "semanas": [],
                        "avisos": [f"Error al generar el programa: {exc}"]}

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
        mes=programa.get("mes") or engine.mes_por_defecto(),
        avisos=programa.get("avisos", []),
        historial_guardado=bool(programa.get("historial_guardado")),
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
        png = renderer.renderizar(programa_final)
        # Registrar las asignaciones finales en el historial (reemplaza las de
        # esas mismas semanas si el mes se vuelve a generar)
        db.respaldar()
        n = db.guardar_historial(engine.filas_historial(programa_final))
        programa_final["historial_guardado"] = True
        print(f"[OK] {n} asignación(es) guardadas en el historial ({db.DB_FILE.name})")
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

@app.route("/api/personal/actualizar", methods=["POST"])
def api_actualizar():
    """Actualiza Roles, Género, Ausencias y cónyuge de una persona existente."""
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        roles_validos = [r for r in data.get("roles", []) if r in ROLES_OFICIALES]
        if not db.actualizar_persona(nombre, data.get("genero", "H"), roles_validos,
                                     data.get("ausencias", "")):
            return jsonify({"ok": False, "error": f"'{nombre}' no encontrado"}), 404

        db.asignar_matrimonio(nombre, data.get("conyuge", "").strip())
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/personal/nuevo", methods=["POST"])
def api_nuevo():
    """Agrega una nueva persona a la base de datos, guardando la foto si viene."""
    import base64 as _b64
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        if db.existe_persona(nombre):
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
        db.crear_persona(
            nombre,
            genero    = data.get("genero", "H"),
            roles     = roles_validos,
            foto_path = foto_path,
            ausencias = data.get("ausencias", ""),
        )

        # Vincular cónyuge si se indicó
        conyuge = data.get("conyuge", "").strip()
        if conyuge:
            db.asignar_matrimonio(nombre, conyuge)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/personal/toggle_activo", methods=["POST"])
def api_toggle_activo():
    """Cambia el estado Activo de una persona."""
    try:
        data   = request.get_json(force=True)
        nombre = data.get("nombre", "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre requerido"}), 400

        nuevo = db.alternar_activo(nombre)
        if nuevo is None:
            return jsonify({"ok": False, "error": f"'{nombre}' no encontrado"}), 404
        return jsonify({"ok": True, "activo": nuevo})
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
