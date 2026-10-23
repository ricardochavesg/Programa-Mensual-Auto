"""
config.py
Lectura y escritura de config.json (preferencias que el programa recuerda).
"""

from __future__ import annotations

import json

from paths import external_path

CONFIG_FILE = external_path("config.json")

PREDETERMINADO = {
    "dia_reunion":      "Miércoles",
    "dia_fds":          "Domingo",
    "mostrar_limpieza": True,
}

# Colores oscuros (texto blanco legible) para el encabezado de la imagen.
# Al generar un mes se elige uno al azar; se puede cambiar en el editor.
PALETA_BANNER = [
    "#1e3a5f",  # azul marino
    "#075985",  # azul océano
    "#3730a3",  # índigo
    "#581c87",  # morado
    "#701a75",  # ciruela
    "#7f1d1d",  # vino
    "#78350f",  # café
    "#14532d",  # verde bosque
    "#134e4a",  # verde azulado
    "#1f2937",  # grafito
]


def leer() -> dict:
    try:
        datos = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        datos = {}
    return {**PREDETERMINADO, **datos}


def guardar(**cambios) -> dict:
    """Actualiza solo las claves indicadas y conserva el resto del archivo."""
    try:
        datos = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        datos = {}
    datos.update(cambios)
    CONFIG_FILE.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**PREDETERMINADO, **datos}
