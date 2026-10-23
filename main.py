"""
main.py
Punto de entrada principal del sistema.

Muestra la ventana de control (barra de tareas), inicia el servidor Flask
y abre automáticamente el navegador en http://127.0.0.1:5000/editar.
El programa sigue activo hasta pulsar "Cerrar programa" en la ventana.

Uso:
  python main.py          (desarrollo)
  Programa_Reuniones.exe  (producción)
"""

import sys
from pathlib import Path

# Asegurar que el directorio del script esté en sys.path
sys.path.insert(0, str(Path(__file__).parent))

from paths import external_path


# ─────────────────────────────────────────────────────────────────────────────
# Inicialización del entorno de datos (primera ejecución o .exe nuevo)
# ─────────────────────────────────────────────────────────────────────────────

def _crear_directorios() -> None:
    """Crea las carpetas externas necesarias si no existen."""
    for carpeta in ("fotos", "input_html", "backups", "cache_guias"):
        ruta = external_path(carpeta)
        ruta.mkdir(parents=True, exist_ok=True)


def _crear_config_ejemplo() -> None:
    """Crea config.json con valores predeterminados si no existe."""
    import config
    if not config.CONFIG_FILE.exists():
        config.guardar(**config.PREDETERMINADO)
        print(f"[INFO] config.json creado en: {config.CONFIG_FILE}")


def _crear_personal_ejemplo() -> None:
    """
    Si la base de datos está vacía (y no había Excel que migrar), crea un
    personal mínimo de ejemplo para que el sistema arranque sin errores.
    """
    import db

    if db.listar_personas():
        return

    print("[INFO] Base de datos vacía. Creando personal de ejemplo...")
    todos = [r for r in db.ROLES_OFICIALES if r != "Conductor_Atalaya"]
    db.crear_persona("Ejemplo H1", "H", todos, matrimonio_id=1)
    db.crear_persona("Ejemplo M1", "M", ["Trigo", "Ayudante"], matrimonio_id=1)
    db.crear_persona("Ejemplo H2", "H", todos)
    db.crear_persona("Ejemplo M2", "M", ["Trigo", "Ayudante"])
    print("[INFO] IMPORTANTE: agrega el personal real desde el Catálogo")
    print("       antes de generar el programa.")


def _inicializar_entorno() -> None:
    """Punto único de arranque del entorno de datos."""
    import db

    _crear_directorios()
    _crear_config_ejemplo()
    db.inicializar()          # crea programa.db y migra Personal_nuevo.xlsx si existe
    _crear_personal_ejemplo()


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import ventana

    def preparar():
        print("=" * 50)
        print("  SISTEMA DE ASIGNACION DE ROLES")
        print("=" * 50)
        _inicializar_entorno()
        from app import app
        return app

    ventana.ejecutar(puerto=5000, preparar=preparar)


if __name__ == "__main__":
    main()
