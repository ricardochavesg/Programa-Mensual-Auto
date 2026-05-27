"""
paths.py
Utilidad central de rutas para modo desarrollo (script) y modo .exe (PyInstaller).

Uso:
    from paths import internal_path, external_path

    internal_path("templates")        → dentro del .exe  (sys._MEIPASS)
    external_path("Personal_nuevo.xlsx") → junto al .exe (sys.executable)

Regla de diseño:
  · Archivos INTERNOS: lógica, templates.   Solo lectura, el usuario no los toca.
  · Archivos EXTERNOS: Excel, fotos, HTML de entrada, backups, JSON de salida.
                       El usuario los lee/modifica directamente.
"""

from __future__ import annotations

import sys
from pathlib import Path


def internal_path(relative: str = "") -> Path:
    """
    Devuelve la ruta a un recurso empaquetado DENTRO del .exe.
    En modo desarrollo apunta a la carpeta del script.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)          # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return base / relative if relative else base


def external_path(relative: str = "") -> Path:
    """
    Devuelve la ruta a un archivo EXTERNO al .exe (junto al ejecutable).
    En modo desarrollo apunta a la carpeta del script.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    return base / relative if relative else base
