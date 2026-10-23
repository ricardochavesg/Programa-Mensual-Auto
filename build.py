"""
build.py
Script de compilación — genera Programa_Reuniones.exe con PyInstaller.

Uso:
    python build.py

Requisitos:
    pip install pyinstaller

Resultado:
    dist/Programa_Reuniones.exe   ← ejecutable portátil
    dist/programa.db              ← base de datos (copiada si existe en desarrollo)
    dist/Personal_nuevo.xlsx      ← solo si no hay programa.db: se migra en el primer arranque
    dist/input_html/              ← HTML manuales de JW.org (opcional: la guía se descarga sola)
    dist/cache_guias/             ← copias de las guías descargadas
    dist/fotos/                   ← carpeta para las fotos del personal
    dist/backups/                 ← carpeta para copias de seguridad automáticas
    dist/config.json              ← configuración del día de reunión
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DIST = HERE / "dist"
EXE_NAME = "Programa_Reuniones"


# ─────────────────────────────────────────────────────────────────────────────
# Verificaciones previas
# ─────────────────────────────────────────────────────────────────────────────

def _verificar_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[ERROR] PyInstaller no está instalado.")
        print("        Ejecuta:  pip install pyinstaller")
        sys.exit(1)


def _verificar_templates() -> None:
    templates = HERE / "templates"
    if not templates.exists() or not any(templates.iterdir()):
        print(f"[ERROR] Carpeta 'templates/' no encontrada o vacía en: {HERE}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Compilación
# ─────────────────────────────────────────────────────────────────────────────

def compilar() -> None:
    print("[1/3] Verificando requisitos...")
    _verificar_pyinstaller()
    _verificar_templates()

    print("[2/3] Compilando con PyInstaller...")

    # En Windows el separador de --add-data es punto y coma (;)
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",                          # Sin consola: la actividad se ve en la ventana de control
        f"--name={EXE_NAME}",
        f"--add-data=templates{sep}templates", # Empaquetar plantillas HTML dentro del .exe
        # Hidden imports comunes de Flask y dependencias
        "--hidden-import=flask",
        "--hidden-import=jinja2",
        "--hidden-import=openpyxl",
        "--hidden-import=pandas",
        "--hidden-import=html2image",
        "--hidden-import=PIL",
        "--hidden-import=bs4",
        "--hidden-import=lxml",
        "--hidden-import=lxml.etree",
        "--hidden-import=sqlite3",
        "--hidden-import=tkinter",
        # Suprimir advertencias de análisis de módulos innecesarios
        "--noconfirm",
        "--clean",
        "main.py",
    ]

    result = subprocess.run(cmd, cwd=str(HERE))
    if result.returncode != 0:
        print("\n[ERROR] La compilación falló. Revisa los mensajes anteriores.")
        sys.exit(result.returncode)


# ─────────────────────────────────────────────────────────────────────────────
# Preparación del directorio de distribución
# ─────────────────────────────────────────────────────────────────────────────

def preparar_dist() -> None:
    print("[3/3] Preparando directorio de distribución...")

    # Crear carpetas externas junto al .exe
    for carpeta in ("fotos", "input_html", "backups", "cache_guias"):
        (DIST / carpeta).mkdir(parents=True, exist_ok=True)
        print(f"      Carpeta creada: dist/{carpeta}/")

    # config.json con valor predeterminado
    import json
    cfg_dest = DIST / "config.json"
    if not cfg_dest.exists():
        cfg_dest.write_text(
            json.dumps({"dia_reunion": "Miércoles", "dia_fds": "Domingo"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("      Archivo creado: dist/config.json")

    # Datos del personal: programa.db si existe; si no, Personal_nuevo.xlsx
    # (que el .exe migra a programa.db en el primer arranque).
    # Nunca se sobrescribe una base que ya esté en dist/ (datos reales del usuario).
    db_src     = HERE / "programa.db"
    db_dst     = DIST / "programa.db"
    excel_src  = HERE / "Personal_nuevo.xlsx"
    excel_dst  = DIST / "Personal_nuevo.xlsx"
    if db_dst.exists():
        print("      Se conserva la base existente: dist/programa.db")
    elif db_src.exists():
        shutil.copy2(db_src, db_dst)
        print("      Archivo copiado: dist/programa.db (personal + historial)")
    elif excel_src.exists():
        if not excel_dst.exists():
            shutil.copy2(excel_src, excel_dst)
        print("      programa.db no encontrada: se usará dist/Personal_nuevo.xlsx "
              "(se migra al abrir el .exe)")
    else:
        print("      Sin programa.db ni Personal_nuevo.xlsx: el .exe creará personal de ejemplo")

    # Limpiar artefactos de PyInstaller del directorio raíz
    spec_file = HERE / f"{EXE_NAME}.spec"
    build_dir = HERE / "build"
    if spec_file.exists():
        spec_file.unlink()
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("      Limpiado: build/ y .spec")

    print(f"\n{'=' * 60}")
    print(f"  COMPILACION EXITOSA")
    print(f"{'=' * 60}")
    print(f"  Ejecutable : dist/{EXE_NAME}.exe")
    print(f"  Para distribuir, copia TODA la carpeta dist/ al destino.")
    print(f"  El usuario solo necesita la carpeta dist/ completa.")
    print(f"{'=' * 60}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    compilar()
    preparar_dist()
