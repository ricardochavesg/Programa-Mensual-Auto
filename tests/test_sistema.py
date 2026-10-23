"""
Pruebas del sistema completo (sin internet ni Chrome).

    python -m pytest tests -q
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

import pandas as pd
import pytest
from jinja2 import Environment, FileSystemLoader

import app as app_mod
import assignator
import config
import db
import guia
import renderer
from conftest import PAGINA_WOL, RAIZ, http_404, sembrar_personal


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def nombres_reunion(asig: dict, reunion: str) -> list[str]:
    """Todos los nombres asignados en una reunión ('ES' o 'FDS') de una semana."""
    if reunion == "FDS":
        return [n for lst in asig["fin_de_semana"].values() for n in lst]
    nombres = [n for lst in asig["entre_semana"].values() for n in lst]
    for sec in ("tesoros", "maestros", "vida_cristiana"):
        for parte in asig[sec]:
            nombres += [parte.get(k) for k in ("asignado", "trigo", "ayudante") if k in parte]
    return nombres


def generar_y_guardar(mes: str) -> dict:
    prog = assignator.generar_programa(mes)
    db.guardar_historial(assignator.filas_historial(prog))
    return prog


# ─────────────────────────────────────────────────────────────────────────────
# Base de datos
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("Cámara", "Camara"), ("camara ", "Camara"), ("Diamante 1", "Diamante_1"),
    ("diamante-2", "Diamante_2"), ("PRESIDENTE", "Presidente_ES"), ("presidente fds", "Presidente_FDS"),
    ("Acomodadores", "Acomodador"), ("lector libro", "Lector_Libro"), ("RolNuevo", "RolNuevo"),
])
def test_normalizar_rol(entrada, esperado):
    assert db.normalizar_rol(entrada) == esperado


def test_crud_personas(entorno):
    db.crear_persona("Ana", "m", ["Trigo", "ayudante", "Trigo"], ausencias=" 04/11 ,, 11/11")
    db.crear_persona("Luis", "H", ["Camara"])
    ana = next(p for p in db.listar_personas() if p["nombre"] == "Ana")
    assert ana["genero"] == "M" and ana["roles"] == ["Trigo", "Ayudante"]
    assert ana["ausencias"] == "04/11, 11/11" and ana["activo"]

    assert db.actualizar_persona("Luis", "H", ["Zoom"], "")
    assert not db.actualizar_persona("Nadie", "H", [], "")

    db.asignar_matrimonio("Luis", "Ana")
    ids = {p["nombre"]: p["matrimonio_id"] for p in db.listar_personas()}
    assert ids["Luis"] == ids["Ana"] is not None
    db.asignar_matrimonio("Luis", "")
    assert all(p["matrimonio_id"] is None for p in db.listar_personas())

    assert db.alternar_activo("Ana") is False
    assert db.alternar_activo("Ana") is True
    assert db.alternar_activo("Nadie") is None


def test_migracion_desde_excel(entorno):
    pd.DataFrame([
        {"Nombre": "Juan", "Genero": "H", "Roles": "Presidente, Diamante 1, Cámara",
         "Matrimonio_ID": 1, "Foto_Path": "juan.jpg", "Carga_Acumulada": 5,
         "Ausencias": float("nan"), "Activo": "Sí"},
        {"Nombre": "Ana", "Genero": "M", "Roles": "Trigo", "Matrimonio_ID": 1,
         "Foto_Path": float("nan"), "Carga_Acumulada": float("nan"), "Ausencias": "04/11",
         "Activo": "No"},
    ]).to_excel(db.EXCEL_FILE, index=False, sheet_name="Personal")
    db.inicializar()
    personas = {p["nombre"]: p for p in db.listar_personas()}
    assert personas["Juan"]["roles"] == ["Presidente_ES", "Diamante_1", "Camara"]
    assert personas["Juan"]["foto_path"] == "juan.jpg"
    assert personas["Ana"]["activo"] is False and personas["Ana"]["ausencias"] == "04/11"
    # Segunda inicialización: no duplica
    db.inicializar()
    assert len(db.listar_personas()) == 2

    salida = entorno["dir"] / "export.xlsx"
    assert db.exportar_excel(salida) == 2
    assert set(pd.read_excel(salida)["Nombre"]) == {"Juan", "Ana"}


def test_historial_idempotente(entorno):
    sembrar_personal()
    prog = generar_y_guardar("2026-11")
    n = len(db.historial(mes="2026-11"))
    assert n > 0
    db.guardar_historial(assignator.filas_historial(prog))
    assert len(db.historial(mes="2026-11")) == n
    assert db.mes_anterior("2027-01") == "2026-12"


# ─────────────────────────────────────────────────────────────────────────────
# Guía de actividades
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("anio", [2026, 2027])
def test_lunes_del_mes_cubre_todas_las_reuniones(anio):
    for mes in range(1, 13):
        lunes = guia.lunes_del_mes(anio, mes)
        assert 4 <= len(lunes) <= 5
        assert all(l.weekday() == 0 for l in lunes)
        assert all(guia.weekly_parser.calcular_dia_reunion(l).month == mes for l in lunes)
        assert all(b - a == timedelta(days=7) for a, b in zip(lunes, lunes[1:]))


def test_rango_texto():
    assert guia.rango_texto(date(2027, 1, 4)) == "4 a 10 de enero de 2027"
    assert guia.rango_texto(date(2026, 11, 30)) == "30 de noviembre a 6 de diciembre de 2026"
    assert guia.rango_texto(date(2026, 12, 28)) == "28 de diciembre de 2026 a 3 de enero de 2027"


def test_extraer_guia_ignora_la_atalaya():
    secciones, _ = guia._extraer_guia(PAGINA_WOL, "https://wol.jw.org/x")
    assert len(secciones["tesoros"]) == 3
    assert len(secciones["maestros"]) == 3
    assert secciones["vida_cristiana"] == ["7. Necesidades de la congregación",
                                           "8. Estudio bíblico de la congregación"]


def test_obtener_semana_usa_cache(entorno):
    lunes = date(2026, 11, 2)
    semana = guia.obtener_semana(lunes)
    assert semana["fecha_reunion"] == date(2026, 11, 4)
    assert [p["tipo"] for p in semana["partes"]["maestros"]] == ["Pareja", "Pareja", "Discurso_H"]
    assert semana["partes"]["vida_cristiana"][-1]["rol"] == "Libro"
    n = len(entorno["pedidas"])
    guia.obtener_semana(lunes)
    assert len(entorno["pedidas"]) == n          # segunda vez: desde caché


def test_respaldo_desde_jw_org(entorno, monkeypatch):
    lunes = date(2027, 3, 1)                     # wol simulado no la tiene
    indice = ('<a href="/es/biblioteca/guia-actividades-reunion-testigos-jehova/marzo-abril-2027-mwb/'
              'Vida-y-Ministerio-Cristianos-1-a-7-de-marzo-de-2027/">1-7 de marzo</a>')
    original = guia._descargar

    def descargar(url):
        if url.endswith("marzo-abril-2027-mwb/"):
            return indice
        if "1-a-7-de-marzo" in url:
            return PAGINA_WOL.replace("todayItem pub-mwb", "x")
        return original(url)

    monkeypatch.setattr(guia, "_descargar", descargar)
    semana = guia.obtener_semana(lunes)
    assert "jw.org" in guia.fuente_semana[lunes]
    assert len(semana["partes"]["tesoros"]) == 3


def test_disponibilidad(entorno, monkeypatch):
    assert guia.disponibilidad_mes(2026, 12) == "disponible"
    assert guia.disponibilidad_mes(2027, 6) == "no_disponible"

    import urllib.error
    monkeypatch.setattr(guia, "_consultas", {})

    def sin_red(url):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(guia, "_descargar", sin_red)
    assert guia.disponibilidad_mes(2027, 7) == "sin_conexion"
    assert guia.disponibilidad_mes(2026, 12) == "disponible"   # ya en caché


def test_input_html_tiene_prioridad(entorno):
    entorno["dir"].joinpath("input_html").mkdir()
    html = PAGINA_WOL.replace("<h1>X</h1>", "").replace(
        "</body>", "<article><h3>Vida y Ministerio (2 a 8 de noviembre de 2026)</h3></article></body>")
    (entorno["dir"] / "input_html" / "semana.html").write_text(html, encoding="utf-8")
    semanas, avisos = guia.obtener_semanas_mes(2026, 11)
    assert semanas[0]["archivo"] == "semana.html" and not avisos


# ─────────────────────────────────────────────────────────────────────────────
# Motor de asignación
# ─────────────────────────────────────────────────────────────────────────────

def test_doce_meses_sin_huecos_ni_duplicados(entorno):
    sembrar_personal()
    db.actualizar_persona("Hermana 05", "M", ["Trigo", "Ayudante"], "04/11, 11/11")
    db.alternar_activo("Hermano 10")
    personas = {p["nombre"]: p for p in db.listar_personas()}

    meses = [f"2026-{m:02d}" for m in range(3, 13)] + ["2027-01", "2027-02"]
    anterior_es: set[str] = set()
    for mes in meses:
        prog = generar_y_guardar(mes)
        assert prog["avisos"] == [], (mes, prog["avisos"])
        for semana in prog["semanas"]:
            asig = semana["asignaciones"]
            es, fds = nombres_reunion(asig, "ES"), nombres_reunion(asig, "FDS")
            assert None not in es + fds, (mes, semana["fecha_exacta"])
            assert len(es) == len(set(es)), (mes, Counter(es).most_common(2))
            assert len(fds) == len(set(fds)), (mes, Counter(fds).most_common(2))
            assert "Hermano 10" not in es + fds                     # inactivo
            if semana["fecha_reunion"] in ("2026-11-04", "2026-11-11"):
                assert "Hermana 05" not in es + fds                 # ausente
            assert not any("Conductor_Atalaya" in personas[n]["roles"] for n in fds)
            for parte in asig["maestros"]:
                if parte["tipo"] == "Discurso_H":
                    assert personas[parte["asignado"]]["genero"] == "H"
            # Descanso: partes que no son logística no se repiten en semanas seguidas
            logistica = {n for k in ("camara", "zoom", "acomodadores")
                         for n in asig["entre_semana"][k]}
            assert not (set(es) - logistica) & anterior_es, (mes, semana["fecha_exacta"])
            anterior_es = set(es) - logistica


def test_reparto_equitativo_y_rotacion_mensual(entorno):
    sembrar_personal()
    generar_y_guardar("2026-10")
    prog = generar_y_guardar("2026-11")
    carga = Counter(f["nombre"] for f in db.historial(mes="2026-11") if f["reunion"] == "ES")
    hermanas = [carga.get(f"Hermana {i:02d}", 0) for i in range(1, 17)]
    assert max(hermanas) - min(hermanas) <= 1
    # Pocas repeticiones del mismo rol "de discurso" respecto al mes anterior
    def roles(mes):
        return {(f["nombre"], f["rol"]) for f in db.historial(mes=mes)
                if f["reunion"] == "ES" and f["rol"] not in ("Camara", "Zoom", "Acomodador")}
    repetidos = roles("2026-10") & roles("2026-11")
    assert len(repetidos) <= len(roles("2026-11")) * 0.25
    assert prog["banner_color"] in config.PALETA_BANNER


def test_personal_insuficiente_llena_y_avisa(entorno):
    db.crear_persona("Solo", "H", list(db.ROLES_OFICIALES))
    prog = assignator.generar_programa("2026-11")
    for semana in prog["semanas"]:
        assert "Solo" in nombres_reunion(semana["asignaciones"], "ES")
    assert any("más de una parte" in a for a in prog["avisos"])
    # Avisos agrupados: el mismo aviso no aparece repetido
    assert len(prog["avisos"]) == len(set(prog["avisos"]))


def test_semana_sin_guia_asigna_logistica(entorno):
    sembrar_personal()
    prog = assignator.generar_programa("2027-03")     # no publicada en la red simulada
    assert prog["semanas"] and all("No se pudo obtener" in a for a in prog["avisos"])
    asig = prog["semanas"][0]["asignaciones"]
    assert asig["tesoros"] == [] and None not in asig["entre_semana"]["presidente"]


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación web
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(entorno, monkeypatch):
    sembrar_personal()
    monkeypatch.setattr(renderer, "renderizar", lambda prog: renderer.OUTPUT_PNG)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_editor_y_guardado(cliente, entorno):
    r = cliente.get("/editar?mes=2026-11")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="input-mes" value="2026-11"' in html and "Noviembre" not in html.split("<script")[0]

    r = cliente.post("/guardar", json={"cambios": {"0|entre_semana|zoom|0": "Hermana 01"},
                                       "banner_color": "#123456"})
    assert r.get_json()["ok"]
    borrador = json.loads(app_mod.BORRADOR_JSON.read_text(encoding="utf-8"))
    assert borrador["banner_color"] == "#123456"
    assert borrador["semanas"][0]["asignaciones"]["entre_semana"]["zoom"] == ["Hermana 01"]
    assert any(f["nombre"] == "Hermana 01" and f["rol"] == "Zoom"
               for f in db.historial(mes="2026-11"))

    # Mismo mes → borrador; otro mes → programa nuevo
    assert "borrador guardado" in cliente.get("/editar").get_data(as_text=True)
    assert "borrador guardado" not in cliente.get("/editar?mes=2026-12").get_data(as_text=True)


def test_selectores_del_editor_filtran_por_rol_real(cliente):
    cliente.get("/editar?mes=2026-11")
    personal = app_mod._cargar_personal_con_fotos()
    tabla = app_mod._construir_tabla_editable(app_mod._estado["programa"], personal)
    roles_oficiales = set(db.ROLES_OFICIALES)
    for fila in tabla["filas"]:
        if fila["es_limpieza"]:
            continue
        for celda in fila["celdas"]:
            for slot in celda:
                assert slot["rol"] in roles_oficiales, (fila["seccion"], fila["etiqueta"], slot["rol"])


def test_borrador_y_descartar(cliente):
    cliente.get("/editar?mes=2026-11")
    assert cliente.post("/api/programa/guardar_borrador",
                        json={"cambios": {}, "banner_color": "#000000"}).get_json()["ok"]
    assert app_mod.BORRADOR_JSON.exists()
    assert cliente.post("/api/programa/descartar_borrador").get_json()["ok"]
    assert not app_mod.BORRADOR_JSON.exists()


def test_api_personal(cliente):
    r = cliente.post("/api/personal/nuevo", json={"nombre": "Nuevo", "genero": "H",
                                                  "roles": ["Camara", "RolFalso"]})
    assert r.get_json()["ok"]
    assert cliente.post("/api/personal/nuevo", json={"nombre": "Nuevo"}).status_code == 409
    assert cliente.post("/api/personal/nuevo", json={"nombre": " "}).status_code == 400
    nuevo = next(p for p in db.listar_personas() if p["nombre"] == "Nuevo")
    assert nuevo["roles"] == ["Camara"]
    assert cliente.post("/api/personal/actualizar",
                        json={"nombre": "Nadie", "roles": []}).status_code == 404
    assert cliente.post("/api/personal/toggle_activo",
                        json={"nombre": "Nuevo"}).get_json()["activo"] is False
    assert cliente.get("/catalogo").status_code == 200


def test_api_config_y_disponibilidad(cliente):
    assert config.leer()["mostrar_limpieza"] is True
    cliente.post("/api/config", json={"mostrar_limpieza": False})
    assert config.leer()["mostrar_limpieza"] is False
    assert config.leer()["dia_reunion"] == "Miércoles"
    r = cliente.get("/api/disponibilidad?anio=2026&mes=12").get_json()
    assert r["estado"] == "disponible"
    assert cliente.get("/api/disponibilidad?anio=x").status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Imagen final
# ─────────────────────────────────────────────────────────────────────────────

def test_plantilla_de_impresion(entorno):
    sembrar_personal()
    prog = assignator.generar_programa("2026-11")
    prog["banner_color"] = "#abcdef"
    env = Environment(loader=FileSystemLoader(str(RAIZ / "templates")))

    ctx = renderer._normalizar(prog, {}, mostrar_limpieza=True)
    html = env.get_template("programa.html").render(**ctx)
    assert "#abcdef" in html and "NOVIEMBRE 2026" in html and "Norte" in html
    for fila in ctx["filas"]:
        if fila["seccion"] in ("tesoros", "maestros", "vida_cristiana"):
            assert fila["icono"] == "" and fila["numero"] > 0
    assert not any(c.get("vacio") for f in ctx["filas"] if not f["es_limpieza"]
                   for celda in f["celdas"] for c in celda)

    ctx = renderer._normalizar(prog, {}, mostrar_limpieza=False)
    assert not any(f["es_limpieza"] for f in ctx["filas"])
