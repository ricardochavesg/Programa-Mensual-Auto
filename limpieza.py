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


def calcular(lunes: Optional[date], cfg: Optional[dict] = None) -> dict:
    """Grupo y encargados que le tocan a la semana que empieza en `lunes`."""
    cfg = cfg or config.leer()["limpieza"]
    orden = [g for g in cfg.get("orden", []) if g] or list(config.PREDETERMINADO["limpieza"]["orden"])
    if lunes is None:
        return vacia()
    try:
        inicio = _lunes(date.fromisoformat(cfg.get("inicio", "")))
    except ValueError:
        inicio = _lunes(date.fromisoformat(config.PREDETERMINADO["limpieza"]["inicio"]))

    turno  = (_lunes(lunes) - inicio).days // 7      # negativo antes del inicio: también rota
    grupo  = orden[turno % len(orden)]
    vuelta = turno // len(orden)
    encargados = [e for e in cfg.get("encargados", {}).get(grupo, []) if e]
    n = len(encargados)
    return {
        "es":  {"grupo": grupo, "encargado": encargados[vuelta % n] if n else "", "especial": ""},
        "fds": {"grupo": grupo, "encargado": encargados[(vuelta + 1) % n] if n else "", "especial": ""},
    }


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
