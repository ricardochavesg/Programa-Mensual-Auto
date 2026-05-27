"""
main.py
Punto de entrada principal del sistema.

Inicia el servidor Flask y abre automáticamente el navegador en
http://127.0.0.1:5000/editar para la edición interactiva del programa.

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
    for carpeta in ("fotos", "input_html", "backups"):
        ruta = external_path(carpeta)
        ruta.mkdir(parents=True, exist_ok=True)


def _crear_personal_ejemplo() -> None:
    """
    Si Personal_nuevo.xlsx no existe, crea uno mínimo de ejemplo para que
    el sistema arranque sin errores. El usuario debe reemplazarlo con datos reales.
    """
    personal_path = external_path("Personal_nuevo.xlsx")
    if personal_path.exists():
        return

    print("[INFO] Personal_nuevo.xlsx no encontrado. Creando archivo de ejemplo...")

    import pandas as pd

    personas_ejemplo = [
        {
            "Nombre": "Ejemplo H1",
            "Genero": "H",
            "Roles": (
                "Camara, Zoom, Acomodador, Presidente_ES, Presidente_FDS, "
                "Diamante_1, Diamante_2, Diamante_3, "
                "Trigo, Ayudante, Discurso_H, Oveja, Libro, Lector_Libro"
            ),
            "Matrimonio_ID": 1,
            "Foto_Path": "",
            "Carga_Acumulada": 0,
            "Activo": "Sí",
        },
        {
            "Nombre": "Ejemplo M1",
            "Genero": "M",
            "Roles": "Trigo, Ayudante",
            "Matrimonio_ID": 1,
            "Foto_Path": "",
            "Carga_Acumulada": 0,
            "Activo": "Sí",
        },
        {
            "Nombre": "Ejemplo H2",
            "Genero": "H",
            "Roles": (
                "Camara, Zoom, Acomodador, Presidente_ES, Presidente_FDS, "
                "Diamante_1, Diamante_2, Diamante_3, "
                "Trigo, Ayudante, Discurso_H, Oveja, Libro, Lector_Libro"
            ),
            "Matrimonio_ID": pd.NA,
            "Foto_Path": "",
            "Carga_Acumulada": 0,
            "Activo": "Sí",
        },
        {
            "Nombre": "Ejemplo M2",
            "Genero": "M",
            "Roles": "Trigo, Ayudante",
            "Matrimonio_ID": pd.NA,
            "Foto_Path": "",
            "Carga_Acumulada": 0,
            "Activo": "Sí",
        },
    ]

    df = pd.DataFrame(personas_ejemplo)
    with pd.ExcelWriter(personal_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Personal")

    print(f"[INFO] Archivo de ejemplo creado en: {personal_path}")
    print("[INFO] IMPORTANTE: Reemplaza Personal_nuevo.xlsx con los datos reales")
    print("       de la congregación antes de generar el programa.")


def _crear_config_ejemplo() -> None:
    """Crea config.json con valores predeterminados si no existe."""
    import json
    cfg_path = external_path("config.json")
    if not cfg_path.exists():
        cfg_path.write_text(
            json.dumps({"dia_reunion": "Miércoles"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[INFO] config.json creado en: {cfg_path}")


def _migrar_presidente() -> None:
    """
    Migración de datos: convierte el rol antiguo 'Presidente' a 'Presidente_ES'
    en Personal_nuevo.xlsx para que nadie pierda sus datos al actualizar.
    """
    personal_path = external_path("Personal_nuevo.xlsx")
    if not personal_path.exists():
        return

    import pandas as pd

    df = pd.read_excel(personal_path, sheet_name="Personal")
    cambios = 0
    for idx, row in df.iterrows():
        roles_str = "" if pd.isna(row.get("Roles")) else str(row["Roles"]).strip()
        roles = [r.strip() for r in roles_str.split(",") if r.strip()]
        if "Presidente" in roles:
            roles = ["Presidente_ES" if r == "Presidente" else r for r in roles]
            df.at[idx, "Roles"] = ", ".join(roles)
            cambios += 1

    if cambios:
        with pd.ExcelWriter(personal_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Personal")
        print(f"[INFO] Migración: {cambios} persona(s) actualizadas de 'Presidente' → 'Presidente_ES'")


def _migrar_activo() -> None:
    """Añade la columna 'Activo' con valor 'Sí' para todos si no existe."""
    personal_path = external_path("Personal_nuevo.xlsx")
    if not personal_path.exists():
        return

    import pandas as pd

    df = pd.read_excel(personal_path, sheet_name="Personal")
    if "Activo" not in df.columns:
        df["Activo"] = "Sí"
        with pd.ExcelWriter(personal_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Personal")
        print("[INFO] Migración: columna 'Activo' añadida con valor 'Sí' para todos.")


def _inicializar_entorno() -> None:
    """Punto único de arranque del entorno de datos."""
    _crear_directorios()
    _crear_config_ejemplo()
    _crear_personal_ejemplo()
    _migrar_presidente()
    _migrar_activo()


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _inicializar_entorno()

    from app import run

    print("=" * 60)
    print("  SISTEMA DE ASIGNACION DE ROLES")
    print("=" * 60)
    print("  Abriendo interfaz web en http://127.0.0.1:5000/editar")
    print("  Presiona Ctrl+C para detener el servidor.")
    print("=" * 60)
    run(port=5000, open_browser=True)


if __name__ == "__main__":
    main()
