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
from typing import Optional


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


MENSAJE_SIN_ESCRITURA = (
    "Windows no deja que el programa guarde archivos en su carpeta:\n"
    "{carpeta}\n\n"
    "Sin esto no se pueden guardar cambios del personal, el historial ni las guías.\n\n"
    "Causa más común: la protección contra ransomware de Windows Defender\n"
    "(\"Acceso controlado a carpetas\") bloquea los .exe nuevos en Documentos,\n"
    "Escritorio y OneDrive. Cada vez que generas un .exe nuevo cuenta como otro programa.\n\n"
    "Soluciones (una de las dos):\n"
    "  1. Mueve la carpeta del programa a una ruta fuera de Documentos/OneDrive,\n"
    "     por ejemplo C:\\ProgramaReuniones\\\n"
    "  2. Seguridad de Windows → Protección antivirus y contra amenazas →\n"
    "     Protección contra ransomware → \"Permitir una aplicación a través del\n"
    "     Acceso controlado a carpetas\" → agrega este .exe."
)


def verificar_escritura() -> Optional[str]:
    """
    Comprueba que se pueda escribir junto al .exe (y en cache_guias/).
    Devuelve None si todo está bien, o el mensaje de error para el usuario.
    """
    for carpeta in (external_path(), external_path("cache_guias")):
        prueba = carpeta / ".prueba_escritura"
        try:
            prueba.write_text("ok", encoding="utf-8")
            prueba.unlink()
        except OSError:
            return MENSAJE_SIN_ESCRITURA.format(carpeta=external_path())
    return None
