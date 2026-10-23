"""
Entorno aislado para las pruebas: todos los archivos externos (base de datos,
config, caché de guías, borrador…) van a una carpeta temporal y la descarga
de wol.jw.org / jw.org se reemplaza por páginas simuladas (sin internet).
"""

from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import app as app_mod      # noqa: E402
import assignator          # noqa: E402
import config              # noqa: E402
import db                  # noqa: E402
import guia                # noqa: E402
import parser as weekly_parser  # noqa: E402
import renderer            # noqa: E402

# Página de wol con el bloque de la guía (estructura h2/h3 de JW.org)
PAGINA_WOL = """<html><body>
<div class="todayItem pub-mwb"><h1>X</h1>
<h2>TESOROS DE LA BIBLIA</h2><h3>1. Tesoro</h3><h3>2. Busquemos perlas escondidas</h3>
<h3>3. Lectura de la Biblia</h3>
<h2>SEAMOS MEJORES MAESTROS</h2><h3>4. Empiece conversaciones</h3><h3>5. Haga revisitas</h3>
<h3>6. Discurso</h3>
<h2>NUESTRA VIDA CRISTIANA</h2><h3>Canción 1</h3><h3>7. Necesidades de la congregación</h3>
<h3>8. Estudio bíblico de la congregación</h3><h3>Palabras de conclusión</h3>
</div>
<div class="todayItem pub-w"><article><h2>LA ATALAYA</h2><h3>1. Otra cosa</h3></article></div>
</body></html>"""


def http_404(url):
    return urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Rutas externas en tmp_path + red simulada (wol publica hasta 2027-W08)."""
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "programa.db")
    monkeypatch.setattr(db, "EXCEL_FILE", tmp_path / "Personal_nuevo.xlsx")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(guia, "CACHE_DIR", tmp_path / "cache_guias")
    monkeypatch.setattr(weekly_parser, "INPUT_DIR", tmp_path / "input_html")
    monkeypatch.setattr(assignator, "OUTPUT_JSON", tmp_path / "programa_mes.json")
    monkeypatch.setattr(app_mod, "BORRADOR_JSON", tmp_path / "borrador_programa.json")
    monkeypatch.setattr(app_mod, "FOTOS_DIR", tmp_path / "fotos")
    monkeypatch.setattr(renderer, "FOTOS_DIR", tmp_path / "fotos")
    monkeypatch.setattr(renderer, "OUTPUT_PNG", tmp_path / "Programa_Mes.png")
    monkeypatch.setattr(renderer, "TEMP_HTML", tmp_path / "temp.html")
    monkeypatch.setattr(guia, "_consultas", {})
    monkeypatch.setattr(guia, "_indices_jw", {})

    pedidas: list[str] = []

    def descargar(url: str) -> str:
        pedidas.append(url)
        if "wol.jw.org" in url:
            anio, semana = (int(x) for x in url.rstrip("/").split("/")[-2:])
            if (anio, semana) <= (2027, 8):
                return PAGINA_WOL
        raise http_404(url)

    monkeypatch.setattr(guia, "_descargar", descargar)
    db.inicializar()
    return {"dir": tmp_path, "pedidas": pedidas}


def sembrar_personal(n_ancianos: int = 12, n_hermanos: int = 10, n_hermanas: int = 16) -> None:
    """Congregación de ejemplo con suficientes personas para cada rol."""
    logistica = ["Camara", "Zoom", "Acomodador"]
    ancianos = ["Presidente_ES", "Presidente_FDS", "Diamante_1", "Diamante_2", "Diamante_3",
                "Oveja", "Libro", "Discurso_H", "Trigo", "Ayudante"]
    for i in range(n_ancianos):
        roles = ancianos + logistica + (["Conductor_Atalaya"] if i == 0 else [])
        db.crear_persona(f"Anciano {i + 1:02d}", "H", roles, matrimonio_id=i + 1 if i < 3 else None)
    for i in range(n_hermanos):
        db.crear_persona(f"Hermano {i + 1:02d}", "H",
                         logistica + ["Trigo", "Ayudante", "Discurso_H", "Diamante_3"])
    for i in range(n_hermanas):
        db.crear_persona(f"Hermana {i + 1:02d}", "M", ["Trigo", "Ayudante"],
                         matrimonio_id=i + 1 if i < 3 else None)
