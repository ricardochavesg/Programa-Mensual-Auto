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
    # Rotación de limpieza (ver limpieza.py): la semana de `inicio` le toca al
    # primer grupo con su primer encargado entre semana.
    "limpieza": {
        "orden":      ["Norte", "Central", "Sur"],
        "encargados": {"Norte": [], "Central": [], "Sur": []},
        "inicio":     "2026-11-02",
    },
    # Lunes (YYYY-MM-DD) de las semanas de asamblea: esa semana no hay reunión
    # en el Salón y no se asigna a nadie.
    "semanas_asamblea": [],
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


def _combinar(datos: dict) -> dict:
    resultado = {**PREDETERMINADO, **datos}
    limpieza = datos.get("limpieza")
    resultado["limpieza"] = {**PREDETERMINADO["limpieza"],
                             **(limpieza if isinstance(limpieza, dict) else {})}
    return resultado


def leer() -> dict:
    try:
        datos = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        datos = {}
    return _combinar(datos)


def guardar(**cambios) -> dict:
    """Actualiza solo las claves indicadas y conserva el resto del archivo."""
    try:
        datos = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        datos = {}
    datos.update(cambios)
    CONFIG_FILE.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return _combinar(datos)
