"""
limpieza.py
Rotación de la limpieza del Salón.

Cada semana le toca a un grupo (Norte → Central → Sur) que limpia en las dos
reuniones: entre semana (Leve) y fin de semana (Profunda). Cada grupo tiene sus
encargados, que se turnan: en una vuelta el primero hace la leve y el segundo
la profunda; en la siguiente vuelta, al revés.

La rotación se calcula por fecha a partir de la semana de inicio guardada en
config.json ("limpieza"), así sigue sola de un mes a otro. Una semana de
asamblea consume su turno (al grupo que le tocaba se lo salta).

Formato de la limpieza de una semana (asignaciones["limpieza"]):
    {"es":  {"grupo": "Norte", "encargado": "Norlan",    "especial": ""},
     "fds": {"grupo": "Norte", "encargado": "R. Chaves", "especial": ""}}
`especial` es texto libre (ej. "LIMPIEZA ANUAL – TODOS LOS GRUPOS") que
reemplaza al grupo y al encargado de esa reunión.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import config

REUNIONES = ("es", "fds")
CAMPOS    = ("grupo", "encargado", "especial")

TEXTO_ESPECIAL = "LIMPIEZA ANUAL – TODOS LOS GRUPOS"


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _orden_y_turno(lunes: date, cfg: dict) -> tuple[list[str], int]:
    """Orden de los grupos y número de semanas desde el inicio (negativo antes: también rota)."""
    orden = [g for g in cfg.get("orden", []) if g] or list(config.PREDETERMINADO["limpieza"]["orden"])
    try:
        inicio = _lunes(date.fromisoformat(cfg.get("inicio", "")))
    except ValueError:
        inicio = _lunes(date.fromisoformat(config.PREDETERMINADO["limpieza"]["inicio"]))
    return orden, (_lunes(lunes) - inicio).days // 7


def encargados_por_grupo(lunes: Optional[date], cfg: Optional[dict] = None) -> dict:
    """
    Qué encargado le toca a CADA grupo en la vuelta de esa semana:
    {"es": {grupo: nombre}, "fds": {grupo: nombre}}. El editor lo usa para
    poner los encargados correctos cuando se cambia el grupo a mano.
    """
    cfg = cfg or config.leer()["limpieza"]
    resultado: dict = {"es": {}, "fds": {}}
    if lunes is None:
        return resultado
    orden, turno = _orden_y_turno(lunes, cfg)
    vuelta = turno // len(orden)
    for grupo in orden:
        encargados = [e for e in cfg.get("encargados", {}).get(grupo, []) if e]
        n = len(encargados)
        resultado["es"][grupo]  = encargados[vuelta % n] if n else ""
        resultado["fds"][grupo] = encargados[(vuelta + 1) % n] if n else ""
    return resultado


def calcular(lunes: Optional[date], cfg: Optional[dict] = None) -> dict:
    """Grupo y encargados que le tocan a la semana que empieza en `lunes`."""
    cfg = cfg or config.leer()["limpieza"]
    if lunes is None:
        return vacia()
    orden, turno = _orden_y_turno(lunes, cfg)
    grupo = orden[turno % len(orden)]
    por_grupo = encargados_por_grupo(lunes, cfg)
    return {r: {"grupo": grupo, "encargado": por_grupo[r][grupo], "especial": ""} for r in REUNIONES}


def vacia() -> dict:
    return {r: {"grupo": "", "encargado": "", "especial": ""} for r in REUNIONES}


def normalizar(valor) -> dict:
    """
    Acepta el formato actual o el antiguo (solo el nombre del grupo, de
    borradores guardados antes de este cambio) y devuelve el formato actual.
    """
    if isinstance(valor, str):
        return {r: {"grupo": valor, "encargado": "", "especial": ""} for r in REUNIONES}
    resultado = vacia()
    if isinstance(valor, dict):
        for r in REUNIONES:
            datos = valor.get(r) or {}
            for c in CAMPOS:
                resultado[r][c] = str(datos.get(c) or "").strip()
    return resultado
