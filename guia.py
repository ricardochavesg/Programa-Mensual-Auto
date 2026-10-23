"""
guia.py
Obtiene automáticamente la Guía de actividades (Vida y Ministerio Cristianos)
de cada semana del mes desde wol.jw.org — ya no hace falta descargar el HTML
a mano.

Orden de búsqueda por semana:
  1. input_html/   → archivo descargado manualmente (tiene prioridad, sirve
                     para corregir una semana concreta).
  2. cache_guias/  → copia de una descarga anterior (funciona sin internet).
  3. wol.jw.org    → descarga y guarda en cache_guias/.

Configurable en config.json:
  "wol_idioma": "es", "wol_r": "r4", "wol_lp": "lp-s"
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import parser as weekly_parser
from paths import external_path

CACHE_DIR = external_path("cache_guias")
WOL_BASE  = "https://wol.jw.org"

try:
    _cfg = json.loads(external_path("config.json").read_text(encoding="utf-8"))
except Exception:
    _cfg = {}
WOL_IDIOMA: str = _cfg.get("wol_idioma", "es")
WOL_R: str      = _cfg.get("wol_r", "r4")
WOL_LP: str     = _cfg.get("wol_lp", "lp-s")

_MESES_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
_TIMEOUT = 20


class SinConexion(RuntimeError):
    """No hay internet o wol.jw.org no responde."""


class GuiaNoDisponible(RuntimeError):
    """wol.jw.org respondió, pero esa semana aún no está publicada."""


# ─────────────────────────────────────────────────────────────────────────────
# Fechas
# ─────────────────────────────────────────────────────────────────────────────

def _lunes_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


def lunes_del_mes(anio: int, mes: int) -> list[date]:
    """
    Lunes de las semanas cuya reunión de entre semana cae dentro del mes.
    (Ej.: si la reunión es el miércoles, la semana del 30-mar al 5-abr
    pertenece a abril solo si su miércoles es en abril.)
    """
    primero = date(anio, mes, 1)
    lunes = primero - timedelta(days=primero.weekday() + 7)
    resultado = []
    while lunes <= date(anio, mes, 28) + timedelta(days=7):
        reunion = weekly_parser.calcular_dia_reunion(lunes)
        if reunion.year == anio and reunion.month == mes:
            resultado.append(lunes)
        lunes += timedelta(days=7)
    return resultado


def rango_texto(lunes: date) -> str:
    """'27 de octubre a 2 de noviembre de 2026' (mismo formato que JW.org)."""
    domingo = lunes + timedelta(days=6)
    if lunes.month == domingo.month:
        return f"{lunes.day} a {domingo.day} de {_MESES_ES[domingo.month]} de {domingo.year}"
    if lunes.year == domingo.year:
        return (f"{lunes.day} de {_MESES_ES[lunes.month]} a "
                f"{domingo.day} de {_MESES_ES[domingo.month]} de {domingo.year}")
    return (f"{lunes.day} de {_MESES_ES[lunes.month]} de {lunes.year} a "
            f"{domingo.day} de {_MESES_ES[domingo.month]} de {domingo.year}")


# ─────────────────────────────────────────────────────────────────────────────
# Descarga
# ─────────────────────────────────────────────────────────────────────────────

def url_semana(lunes: date) -> str:
    anio, semana, _ = lunes.isocalendar()
    return f"{WOL_BASE}/{WOL_IDIOMA}/wol/meetings/{WOL_R}/{WOL_LP}/{anio}/{semana}"


def _descargar(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Programa-Mensual-Auto)",
        "Accept-Language": WOL_IDIOMA,
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _secciones_completas(secciones: dict) -> bool:
    return bool(secciones.get("tesoros")) and bool(secciones.get("maestros"))


def _extraer_guia(html: str, url_base: str) -> tuple[dict, str]:
    """
    Busca dentro de la página de reuniones el bloque de la guía de actividades.
    Devuelve (secciones, html_util). Si la página solo trae un enlace al
    artículo, lo sigue y extrae del artículo.
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. Bloques propios de la guía (clase 'pub-mwb…') o artículos de la página
    candidatos = soup.select('[class*="pub-mwb"]') + soup.find_all("article")
    for cont in candidatos:
        secciones = weekly_parser._extraer_secciones_articulo(cont)
        if _secciones_completas(secciones):
            return secciones, str(cont)

    # 2. Enlace al documento de la guía
    enlaces = []
    for bloque in soup.select('[class*="pub-mwb"]') or [soup]:
        enlaces += [a["href"] for a in bloque.find_all("a", href=True) if "/wol/d/" in a["href"]]
    for href in enlaces[:3]:
        try:
            doc = _descargar(urljoin(url_base, href))
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        secciones = weekly_parser._extraer_secciones_articulo(BeautifulSoup(doc, "lxml"))
        if _secciones_completas(secciones):
            return secciones, doc

    # 3. Último recurso: toda la página
    return weekly_parser._extraer_secciones_articulo(soup), html


def _ruta_cache(lunes: date):
    anio, semana, _ = lunes.isocalendar()
    return CACHE_DIR / f"{WOL_IDIOMA}_{anio}-W{semana:02d}.html"


def obtener_semana(lunes: date, usar_cache: bool = True) -> dict:
    """
    Devuelve el dict de semana (formato de parser.construir_semana) para el
    lunes indicado, usando la caché o descargando de wol.jw.org.
    Lanza SinConexion o GuiaNoDisponible (ambas RuntimeError) si no se pudo.
    """
    cache = _ruta_cache(lunes)
    nombre = f"wol {lunes.isocalendar()[0]}-W{lunes.isocalendar()[1]:02d}"

    if usar_cache and cache.exists():
        secciones = weekly_parser._extraer_secciones_articulo(
            BeautifulSoup(cache.read_text(encoding="utf-8"), "lxml")
        )
        if _secciones_completas(secciones):
            return weekly_parser.construir_semana(nombre, rango_texto(lunes), lunes, secciones)

    url = url_semana(lunes)
    try:
        html = _descargar(url)
    except urllib.error.HTTPError as exc:
        raise GuiaNoDisponible(f"{url} respondió {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SinConexion(f"No se pudo descargar {url}: {exc}") from exc

    secciones, html_util = _extraer_guia(html, url)
    if not _secciones_completas(secciones):
        raise GuiaNoDisponible(f"La página {url} no contiene la guía de actividades esperada.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(f"<html><body><article>{html_util}</article></body></html>"
                     if not html_util.lstrip().lower().startswith(("<html", "<!doctype"))
                     else html_util, encoding="utf-8")
    return weekly_parser.construir_semana(nombre, rango_texto(lunes), lunes, secciones)


# ─────────────────────────────────────────────────────────────────────────────
# Disponibilidad (para el selector de mes)
# ─────────────────────────────────────────────────────────────────────────────

_disponibles: set[tuple[int, int]] = set()   # meses ya confirmados en esta sesión


def disponibilidad_mes(anio: int, mes: int) -> str:
    """
    'disponible'    → la guía de la última semana del mes está en caché o en wol.
    'no_disponible' → wol aún no la publicó.
    'sin_conexion'  → no se pudo consultar (sin internet).
    La descarga queda en caché, así que generar ese mes luego es inmediato.
    """
    if (anio, mes) in _disponibles:
        return "disponible"
    semanas = lunes_del_mes(anio, mes)
    if not semanas:
        return "no_disponible"
    try:
        obtener_semana(semanas[-1])
    except GuiaNoDisponible:
        return "no_disponible"
    except SinConexion:
        return "sin_conexion"
    _disponibles.add((anio, mes))
    return "disponible"


def disponibilidad_anio(anio: int) -> dict[int, str]:
    """Disponibilidad de los 12 meses del año (consultas en paralelo)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=6) as pool:
        estados = pool.map(lambda m: disponibilidad_mes(anio, m), range(1, 13))
    return dict(zip(range(1, 13), estados))


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def obtener_semanas_mes(anio: int, mes: int) -> tuple[list[dict], list[str]]:
    """
    Devuelve (semanas, avisos) para todas las semanas del mes.
    Una semana que no se pudo obtener se incluye sin partes (solo logística)
    y se reporta en avisos.
    """
    locales: dict[date, dict] = {}
    for semana in weekly_parser.parsear_todos(silencioso=True):
        if semana.get("fecha_inicio"):
            locales[_lunes_de(semana["fecha_inicio"])] = semana

    semanas: list[dict] = []
    avisos: list[str] = []
    for lunes in lunes_del_mes(anio, mes):
        if lunes in locales:
            print(f"     {rango_texto(lunes)}: usando input_html/{locales[lunes]['archivo']}")
            semanas.append(locales[lunes])
            continue
        try:
            semana = obtener_semana(lunes)
            print(f"     {rango_texto(lunes)}: guía obtenida ({url_semana(lunes)})")
        except RuntimeError as exc:
            print(f"  [WARN] {exc}")
            avisos.append(
                f"No se pudo obtener la guía de la semana {rango_texto(lunes)}. "
                "Descarga el HTML manualmente en la carpeta input_html/ y vuelve a generar."
            )
            semana = weekly_parser.construir_semana(
                "sin guía", rango_texto(lunes), lunes,
                {"tesoros": [], "maestros": [], "vida_cristiana": []},
            )
        semanas.append(semana)
    return semanas, avisos


if __name__ == "__main__":
    import sys

    hoy = date.today()
    a, m = (int(x) for x in sys.argv[1].split("-")) if len(sys.argv) > 1 else (hoy.year, hoy.month)
    semanas, avisos = obtener_semanas_mes(a, m)
    for s in semanas:
        print(f"\n{s['rango_fechas']}  ({s['fecha_exacta']})")
        for sec, partes in s["partes"].items():
            for p in partes:
                print(f"  {sec:<15} {p.get('tipo', ''):<11} {p['titulo'][:60]}")
    for a in avisos:
        print("[!]", a)
