"""
build.py
Script de compilación — genera Programa_Reuniones.exe con PyInstaller.

Uso:
    python build.py

Requisitos:
    pip install pyinstaller

Resultado:
    dist/Programa_Reuniones.exe   ← ejecutable portátil
    dist/Personal_nuevo.xlsx      ← plantilla vacía lista para el usuario
    dist/input_html/              ← carpeta para los HTML de JW.org
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
        "--windowed",                          # Sin ventana de consola negra
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
        "--hidden-import=pkg_resources.py2_compat",
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
    for carpeta in ("fotos", "input_html", "backups"):
        (DIST / carpeta).mkdir(parents=True, exist_ok=True)
        print(f"      Carpeta creada: dist/{carpeta}/")

    # config.json con valor predeterminado
    import json
    cfg_dest = DIST / "config.json"
    if not cfg_dest.exists():
        cfg_dest.write_text(
            json.dumps({"dia_reunion": "Miércoles"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("      Archivo creado: dist/config.json")

    # Copiar Personal_nuevo.xlsx si existe (como plantilla de referencia)
    personal_src = HERE / "Personal_nuevo.xlsx"
    personal_dst = DIST / "Personal_nuevo.xlsx"
    if personal_src.exists() and not personal_dst.exists():
        shutil.copy2(personal_src, personal_dst)
        print("      Archivo copiado: dist/Personal_nuevo.xlsx")

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
