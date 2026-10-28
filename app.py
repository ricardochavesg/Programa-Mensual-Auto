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
import re
from datetime import date
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, redirect, render_template, request, send_file

import assignator as engine
import config
import db
import guia
import limpieza
import parser as weekly_parser
import renderer
from paths import external_path, internal_path

FOTOS_DIR    = external_path("fotos")
BORRADOR_JSON = external_path("borrador_programa.json")
app = Flask(__name__, template_folder=str(internal_path("templates")))

# Estado de sesión (app local de usuario único)
_estado: dict = {"programa": None}

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
        {"rango": s["rango_fechas"], "fecha": s.get("fecha_exacta", ""),
         "asamblea": bool(s.get("asamblea")),
         "field_asamblea": f"{si}|semana|asamblea|valor",
         "visita": bool(s.get("visita")),
         "field_visita": f"{si}|semana|visita|valor",
         "fecha_fds": weekly_parser.fecha_reunion_texto(s, "fds"),
         "lunes": _lunes_semana(s)}
        for si, s in enumerate(semanas)
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

    # (clave, emoji, etiqueta, rol entre semana, rol fin de semana, cantidad)
    LOGISTICA = [
        ("presidente",   "🎤", "Presidente",   "Presidente_ES", "Presidente_FDS", 1),
        ("camara",       "🎥", "Cámara/PC 💻", "Camara",        "Camara",         2),
        ("zoom",         "💻", "Zoom",         "Zoom",          "Zoom",           1),
        ("acomodadores", "🪑", "Acomodadores", "Acomodador",    "Acomodador",     2),
    ]

    # ── Entre semana ──────────────────────────────────────────────────────────
    for key, emo, lbl, rol_es, _, n in LOGISTICA:
        celdas = []
        for si, s in enumerate(semanas):
            lst = s["asignaciones"]["entre_semana"].get(key, [None] * n)
            celdas.append([
                _mk_slot(si, "entre_semana", key, str(i),
                         lst[i] if i < len(lst) else None,
                         personal_map, rol_es)
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

    # ── Limpieza (leve: entre semana; profunda: fin de semana) ───────────────
    def add_limpieza(reunion: str, etiqueta: str) -> None:
        celdas = []
        for si, s in enumerate(semanas):
            datos = limpieza.normalizar(s["asignaciones"].get("limpieza"))[reunion]
            lunes = _lunes_semana(s)
            por_grupo = limpieza.encargados_por_grupo(date.fromisoformat(lunes) if lunes else None)
            celdas.append({**datos, "field_base": f"{si}|limpieza|{reunion}",
                           "fecha": weekly_parser.fecha_reunion_texto(s, reunion),
                           "por_grupo": por_grupo[reunion]})
        add("limpieza", "🧹", 0, etiqueta, celdas, es_limpieza=True)

    add_limpieza("es", "Limpieza leve")

    # ── Fin de semana ─────────────────────────────────────────────────────────
    for key, emo, lbl, _, rol_fds, n in LOGISTICA:
        celdas = []
        for si, s in enumerate(semanas):
            lst = s["asignaciones"]["fin_de_semana"].get(key, [None] * n)
            celdas.append([
                _mk_slot(si, "fin_de_semana", key, str(i),
                         lst[i] if i < len(lst) else None,
                         personal_map, rol_fds)
                for i in range(n)
            ])
        add("fin_de_semana", emo, 0, lbl, celdas)

    add_limpieza("fds", "Limpieza profunda")

    # Marcar primera fila de cada sección (las filas de limpieza no llevan)
    seen: set[str] = {"limpieza"}
    for fila in filas:
        if fila["seccion"] not in seen:
            fila["mostrar_cabecera"] = True
            seen.add(fila["seccion"])

    return {
        "headers":     headers,
        "filas":       filas,
        "seccion_cfg": renderer.SECCION_CFG,
    }


def _lunes_semana(semana: dict) -> str:
    fecha = semana.get("fecha_inicio") or semana.get("fecha_reunion")
    return db.lunes_de(date.fromisoformat(fecha)).isoformat() if fecha else ""


def _migrar_limpieza(programa: dict) -> dict:
    """
    Borradores guardados antes de la limpieza leve/profunda solo tenían el
    nombre del grupo: se recalcula la rotación actual (grupo + encargados).
    """
    for semana in programa.get("semanas", []):
        asig = semana.get("asignaciones", {})
        if not isinstance(asig.get("limpieza"), dict):
            lunes = _lunes_semana(semana)
            asig["limpieza"] = limpieza.calcular(date.fromisoformat(lunes) if lunes else None)
    return programa


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

        if sec == "semana" and key == "asamblea":
            prog["semanas"][si]["asamblea"] = bool(val)
            continue
        if sec == "semana" and key == "visita":
            if bool(val) != bool(prog["semanas"][si].get("visita")):
                weekly_parser.aplicar_visita(prog["semanas"][si], bool(val))
            continue

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
            if key in limpieza.REUNIONES and campo in limpieza.CAMPOS:
                datos = limpieza.normalizar(asig.get("limpieza"))
                datos[key][campo] = (val or "").strip()
                asig["limpieza"] = datos

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


@app.route("/estadisticas")
def estadisticas():
    meses = db.meses_con_historial()
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    formato = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
    if (desde and not formato.fullmatch(desde)) or (hasta and not formato.fullmatch(hasta)):
        desde = hasta = ""
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
    datos = db.estadisticas(desde or None, hasta or None)
    presets = [(etq, meses[-n] if len(meses) >= n else (meses[0] if meses else ""))
               for etq, n in (("Último mes", 1), ("Últimos 3 meses", 3), ("Últimos 6 meses", 6))]
    presets.append(("Todo", meses[0] if meses else ""))
    return render_template("estadisticas.html", d=datos, presets=presets,
                           ultimo_mes=meses[-1] if meses else "")


@app.route("/editar")
def editar():
    mes_pedido = request.args.get("mes", "").strip() or None
    desde_borrador = False
    programa = None

    if BORRADOR_JSON.exists():
        try:
            borrador = json.loads(BORRADOR_JSON.read_text(encoding="utf-8"))
            if mes_pedido is None or borrador.get("mes") == mes_pedido:
                programa = _migrar_limpieza(borrador)
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
        banner_color=programa.get("banner_color") or config.PALETA_BANNER[0],
        paleta_banner=config.PALETA_BANNER,
        mostrar_limpieza=config.leer()["mostrar_limpieza"],
        cfg_limpieza=config.leer()["limpieza"],
        dia_fds=config.leer()["dia_fds"],
        dia_reunion=config.leer()["dia_reunion"],
        dias_reunion=list(weekly_parser.DIAS_SEMANA),
        texto_especial=limpieza.TEXTO_ESPECIAL,
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
    if data.get("banner_color"):
        programa_final["banner_color"] = data["banner_color"]
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
    if data.get("banner_color"):
        programa_guardado["banner_color"] = data["banner_color"]
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


@app.route("/api/disponibilidad")
def api_disponibilidad():
    """Si la guía de un mes está publicada en wol.jw.org (o ya en caché)."""
    try:
        anio, mes = int(request.args.get("anio", "")), int(request.args.get("mes", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "Año o mes inválido"}), 400
    return jsonify({"ok": True, "anio": anio, "mes": mes,
                    "estado": guia.disponibilidad_mes(anio, mes)})


@app.route("/api/config", methods=["POST"])
def api_config():
    """Guarda preferencias que el programa recuerda (ej. mostrar la fila de limpieza)."""
    data = request.get_json(force=True)
    cambios = {}
    if "mostrar_limpieza" in data:
        cambios["mostrar_limpieza"] = bool(data["mostrar_limpieza"])
    if data.get("dia_fds") in ("Sábado", "Domingo"):
        cambios["dia_fds"] = data["dia_fds"]
    if data.get("dia_reunion") in weekly_parser.DIAS_SEMANA:
        cambios["dia_reunion"] = data["dia_reunion"]
    nueva = config.guardar(**cambios)

    # Otro día de reunión: recalcular las fechas del programa abierto
    programa = _estado.get("programa")
    if "dia_reunion" in cambios and programa:
        for semana in programa.get("semanas", []):
            weekly_parser.aplicar_visita(semana, bool(semana.get("visita")))
        try:
            BORRADOR_JSON.write_text(json.dumps(programa, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "config": nueva})


def _marcar_semana(clave: str):
    """Agrega o quita el lunes de una semana de la lista `clave` de config.json."""
    data  = request.get_json(force=True)
    lunes = str(data.get("semana", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lunes):
        return jsonify({"ok": False, "error": "Semana inválida"}), 400
    semanas = [s for s in config.leer()[clave] if s != lunes]
    if data.get("activa"):
        semanas.append(lunes)
    config.guardar(**{clave: sorted(semanas)})
    return jsonify({"ok": True})


@app.route("/api/asamblea", methods=["POST"])
def api_asamblea():
    """
    Marca o desmarca una semana de asamblea. Se recuerda en config.json para
    que, al volver a generar el mes, esa semana no reciba asignaciones.
    """
    return _marcar_semana("semanas_asamblea")


@app.route("/api/visita", methods=["POST"])
def api_visita():
    """Marca o desmarca la semana de la visita del superintendente (reunión el martes)."""
    return _marcar_semana("semanas_visita")


@app.route("/api/limpieza", methods=["POST"])
def api_limpieza():
    """
    Guarda los grupos de limpieza (orden, encargados, semana de inicio) y
    recalcula la rotación del programa abierto, conservando las limpiezas
    especiales. Los demás cambios se guardan antes con el borrador.
    """
    data = request.get_json(force=True)
    orden = [str(g).strip() for g in data.get("orden", []) if str(g).strip()]
    if not orden:
        return jsonify({"ok": False, "error": "Indica al menos un grupo"}), 400
    inicio = str(data.get("inicio", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", inicio):
        return jsonify({"ok": False, "error": "Fecha de inicio inválida"}), 400
    encargados = {g: [str(n).strip() for n in data.get("encargados", {}).get(g, []) if str(n).strip()]
                  for g in orden}
    cfg = config.guardar(limpieza={"orden": orden, "encargados": encargados, "inicio": inicio})

    programa = _estado.get("programa")
    if programa:
        for semana in programa.get("semanas", []):
            lunes = _lunes_semana(semana)
            nueva = limpieza.calcular(date.fromisoformat(lunes) if lunes else None, cfg["limpieza"])
            anterior = limpieza.normalizar(semana["asignaciones"].get("limpieza"))
            for r in limpieza.REUNIONES:
                nueva[r]["especial"] = anterior[r]["especial"]
            semana["asignaciones"]["limpieza"] = nueva
        try:
            BORRADOR_JSON.write_text(json.dumps(programa, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "config": cfg["limpieza"]})


@app.route("/imagen")
def imagen():
    png = renderer.OUTPUT_PNG
    if not png.exists():
        return "Imagen no generada aún", 404
    resp = send_file(str(png), mimetype="image/png", max_age=0, etag=False)
    resp.headers["Cache-Control"] = "no-store"   # nunca mostrar/descargar una imagen anterior
    return resp


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
            # Nombre de archivo seguro: sin separadores de carpeta ni caracteres inválidos
            seguro = "".join(c for c in nombre if c not in '\\/:*?"<>|').strip(" .") or "foto"
            foto_nombre = f"{seguro}.{ext}"
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
