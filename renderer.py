"""
renderer.py
Genera Programa_Mes.png a partir del dict de salida del assignator.

Flujo:
  1. Carga fotos como base64 desde /fotos (fallback: iniciales)
  2. Normaliza el programa en filas de tabla
  3. Renderiza templates/programa.html con Jinja2 → temp.html
  4. Captura PNG con html2image (Chrome headless, 1240 px)
  5. Recorta espacio blanco inferior con PIL
  6. Actualiza Carga_Acumulada en Personal.xlsx (solo asignados)
"""

from __future__ import annotations

import base64
import math
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from html2image import Html2Image
from jinja2 import Environment, FileSystemLoader
from PIL import Image

from paths import external_path, internal_path

# Externos: junto al .exe, el usuario interactúa con ellos
FOTOS_DIR     = external_path("fotos")
PERSONAL_FILE = external_path("Personal_nuevo.xlsx")
TEMP_HTML     = external_path("temp.html")
OUTPUT_PNG    = external_path("Programa_Mes.png")

# Interno: empaquetado dentro del .exe
TEMPLATES_DIR = internal_path("templates")

# ─────────────────────────────────────────────────────────────────────────────
# Config visual: colores por sección
# ─────────────────────────────────────────────────────────────────────────────

SECCION_CFG = {
    "entre_semana": {
        "label":     "ENTRE SEMANA",
        "hdr_bg":    "#334155",
        "row_bg":    "#f8fafc",
        "row_color": "#334155",
        "badge":     "#475569",
    },
    "tesoros": {
        "label":     "TESOROS DE LA BIBLIA",
        "hdr_bg":    "#0f766e",
        "row_bg":    "#f0fdfa",
        "row_color": "#0f766e",
        "badge":     "#0f766e",
    },
    "maestros": {
        "label":     "SEAMOS MEJORES MAESTROS",
        "hdr_bg":    "#b45309",
        "row_bg":    "#fffbeb",
        "row_color": "#92400e",
        "badge":     "#b45309",
    },
    "vida_cristiana": {
        "label":     "NUESTRA VIDA CRISTIANA",
        "hdr_bg":    "#991b1b",
        "row_bg":    "#fff1f2",
        "row_color": "#991b1b",
        "badge":     "#991b1b",
    },
    "fin_de_semana": {
        "label":     "FIN DE SEMANA",
        "hdr_bg":    "#334155",
        "row_bg":    "#f8fafc",
        "row_color": "#334155",
        "badge":     "#475569",
    },
    "limpieza": {
        "label":     "LIMPIEZA",
        "hdr_bg":    "#15803d",
        "row_bg":    "#f0fdf4",
        "row_color": "#15803d",
        "badge":     "#15803d",
    },
}

LOGISTICA_META = {
    "presidente":   ("🎤", "Presidente"),
    "camara":       ("🎥", "Cámara/PC 💻"),
    "zoom":         ("💻", "Zoom"),
    "acomodadores": ("🪑", "Acomodadores"),
}

# Colores para avatares sin foto
AVATAR_PALETTE = [
    "#4f46e5", "#0891b2", "#059669", "#d97706",
    "#dc2626", "#7c3aed", "#db2777", "#0284c7",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _iniciales(nombre: str) -> str:
    partes = nombre.split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    return nombre[:2].upper()


def _color_avatar(nombre: str) -> str:
    idx = sum(ord(c) for c in nombre) % len(AVATAR_PALETTE)
    return AVATAR_PALETTE[idx]


_MIME_MAP = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "gif":  "image/gif",
    "webp": "image/webp",
}
_EXTENSIONES_FALLBACK = [".png", ".jpg", ".jpeg", ".webp"]


def _buscar_archivo_foto(fotos_dir: Path, nombre_archivo: str) -> Optional[Path]:
    """
    Busca nombre_archivo en fotos_dir de forma case-insensitive.

    · Si nombre_archivo tiene extensión  → busca ese nombre (cualquier capitalización).
    · Si NO tiene extensión              → prueba .png / .jpg / .jpeg / .webp en ese orden.

    Usa FOTOS_DIR (resuelto desde paths.py) para evitar problemas de CWD y .exe.
    """
    # Construir índice case-insensitive del directorio una sola vez
    try:
        indice: dict[str, Path] = {
            f.name.lower(): f for f in FOTOS_DIR.iterdir() if f.is_file()
        }
    except (FileNotFoundError, PermissionError):
        return None

    stem = Path(nombre_archivo).stem   # "Pedro"
    ext  = Path(nombre_archivo).suffix # ".jpg"  o  ""

    if ext:
        # Tiene extensión: buscar case-insensitive
        clave = f"{stem}{ext}".lower()
        return indice.get(clave)
    else:
        # Sin extensión: probar todas las extensiones conocidas
        for e in _EXTENSIONES_FALLBACK:
            clave = f"{stem}{e}".lower()
            if clave in indice:
                return indice[clave]
        return None


def _foto_a_b64(nombre_archivo: str) -> Optional[str]:
    """
    Busca nombre_archivo en FOTOS_DIR, lo convierte a data URI base64.
    Imprime diagnóstico en consola para cada intento.
    Devuelve None si no se encuentra o falla la lectura (→ avatar con iniciales).
    """
    ruta_buscada = FOTOS_DIR / nombre_archivo
    print(f"      Buscando foto: {ruta_buscada.resolve()}")

    found = _buscar_archivo_foto(FOTOS_DIR, nombre_archivo)

    if found is None:
        print(f"      Foto NO encontrada, usando iniciales.")
        return None

    try:
        ext  = found.suffix.lower().lstrip(".")
        mime = _MIME_MAP.get(ext, f"image/{ext}")
        with open(found, "rb") as fh:
            raw = fh.read()
        data = base64.b64encode(raw).decode("ascii").replace("\n", "")
        print(f"      Foto encontrada y convertida. ({len(data):,} chars, {mime})")
        return f"data:{mime};base64,{data}"
    except Exception as exc:
        print(f"      ERROR al convertir {found.name}: {exc}")
        return None


def _build_foto_map() -> dict[str, Optional[str]]:
    """
    Devuelve {nombre_persona: data_uri_o_None}.

    Estrategia de búsqueda por persona:
      1. Si Foto_Path tiene valor  → buscar ese nombre de archivo (case-insensitive,
                                     con o sin extensión).
      2. Si Foto_Path está vacío   → intentar Nombre + extensiones conocidas.
    """
    if not PERSONAL_FILE.exists():
        print(f"[WARN] Personal.xlsx no encontrado en: {PERSONAL_FILE.resolve()}")
        return {}

    archivos_en_disco = list(FOTOS_DIR.glob("*.*")) if FOTOS_DIR.exists() else []
    print(f"         Carpeta fotos : {FOTOS_DIR}")
    print(f"         Fotos en disco: {len(archivos_en_disco)} archivo(s)")

    df = pd.read_excel(PERSONAL_FILE, sheet_name="Personal")
    foto_map: dict[str, Optional[str]] = {}

    for _, row in df.iterrows():
        nombre   = str(row["Nombre"]).strip()
        raw_foto = row.get("Foto_Path")
        foto_rel = "" if pd.isna(raw_foto) else str(raw_foto).strip()

        # Elegir candidato a buscar: Foto_Path si existe, sino el Nombre de la persona
        candidato = foto_rel if foto_rel else nombre
        foto_map[nombre] = _foto_a_b64(candidato)

    encontradas = sum(1 for v in foto_map.values() if v)
    print(f"         Resultado     : {encontradas}/{len(foto_map)} fotos cargadas.")
    return foto_map


def _extraer_personas_parte(parte: dict) -> list:
    """
    Extrae todos los nombres de persona de una parte en orden canónico:
      trigo → asignado → ayudante → extra_0 → extra_1 → …

    Omite cualquier campo cuyo valor sea None, null o string vacío,
    evitando círculos vacíos en la imagen final.
    Garantiza devolver al menos [None] si no hay nadie asignado.
    """
    personas: list[str] = []
    for campo in ("trigo", "asignado", "ayudante"):
        if campo in parte:
            v = parte[campo]
            if v:  # ignorar None y string vacío
                personas.append(v)
    n = 0
    while f"extra_{n}" in parte:
        v = parte[f"extra_{n}"]
        if v:  # ignorar None y string vacío
            personas.append(v)
        n += 1
    return personas if personas else [None]


def _persona_celda(nombre: Optional[str], foto_map: dict) -> dict:
    """
    Construye el dict de una persona para la plantilla.
    Si nombre es None → celda vacía (guion).
    """
    if not nombre:
        return {"nombre": "—", "foto": None, "iniciales": "—", "color": "#cbd5e1", "vacio": True}
    return {
        "nombre":    nombre,
        "foto":      foto_map.get(nombre),
        "iniciales": _iniciales(nombre),
        "color":     _color_avatar(nombre),
        "vacio":     False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Normalización del programa → tabla de filas
# ─────────────────────────────────────────────────────────────────────────────

def _normalizar(programa: dict, foto_map: dict) -> dict:
    """
    Convierte el dict del programa en la estructura plana que consume
    el template Jinja2:

        {
          "titulo": str,
          "generado": str,
          "headers": [{"rango": str, "fecha": str}, ...],
          "filas": [
              {
                "seccion":        str,
                "mostrar_cabecera": bool,
                "icono":           str,   # emoji
                "numero":          int,   # badge numérico (0 = sin badge)
                "etiqueta":        str,
                "celdas":          list,  # one per week; each = list[persona_dict]
                "es_limpieza":     bool,
              }, ...
          ],
          "seccion_cfg": SECCION_CFG,
        }
    """
    semanas = programa.get("semanas", [])

    headers = [
        {"rango": s["rango_fechas"], "fecha": s.get("fecha_exacta", "")}
        for s in semanas
    ]

    filas: list[dict] = []

    def _fila(seccion, icono, numero, etiqueta, celdas, es_limpieza=False):
        filas.append({
            "seccion":         seccion,
            "mostrar_cabecera": False,   # se rellena al final
            "icono":           icono,
            "numero":          numero,
            "etiqueta":        etiqueta,
            "celdas":          celdas,
            "es_limpieza":     es_limpieza,
        })

    def _celdas_logistica(key: str, n: int, es_fin: bool) -> list:
        celdas = []
        reunion = "fin_de_semana" if es_fin else "entre_semana"
        for s in semanas:
            nombres = s["asignaciones"][reunion].get(key, [None] * n)
            celdas.append([_persona_celda(nm, foto_map) for nm in nombres])
        return celdas

    # ── Entre semana ──────────────────────────────────────────────────────────
    for key, (emo, lbl) in LOGISTICA_META.items():
        n = 2 if key in ("camara", "acomodadores") else 1
        _fila("entre_semana", emo, 0, lbl, _celdas_logistica(key, n, False))

    # ── Tesoros ───────────────────────────────────────────────────────────────
    for i in range(3):
        celdas = []
        for s in semanas:
            partes = s["asignaciones"]["tesoros"]
            if i < len(partes):
                celdas.append([_persona_celda(partes[i]["asignado"], foto_map)])
            else:
                celdas.append([_persona_celda(None, foto_map)])
        lbl_tesoros = ["Tesoros", "Perlas", "Lectura"][i]
        _fila("tesoros", "💎", i + 1, lbl_tesoros, celdas)

    # ── Maestros ─────────────────────────────────────────────────────────────
    max_maestros = max((len(s["asignaciones"]["maestros"]) for s in semanas), default=0)
    trigo_num = 4
    for i in range(max_maestros):
        celdas = []
        for s in semanas:
            partes = s["asignaciones"]["maestros"]
            if i < len(partes):
                parte  = partes[i]
                nombres = _extraer_personas_parte(parte)
                celdas.append([_persona_celda(n, foto_map) for n in nombres])
            else:
                celdas.append([_persona_celda(None, foto_map)])

        _fila("maestros", "🌾", trigo_num, "", celdas)
        trigo_num += 1

    # ── Vida Cristiana ───────────────────────────────────────────────────────
    # Estructura uniforme: cada parte tiene siempre un campo 'asignado'.
    # tipo == 'Libro'  → última parte (Estudio Bíblico, rol Libro)
    # tipo == 'Oveja'  → partes anteriores
    max_vc    = max((len(s["asignaciones"]["vida_cristiana"]) for s in semanas), default=0)
    oveja_num = 1
    for i in range(max_vc):
        celdas   = []
        tipo_dom = None
        for s in semanas:
            partes = s["asignaciones"]["vida_cristiana"]
            if i < len(partes):
                parte   = partes[i]
                tipo    = parte.get("tipo", "Oveja")
                if tipo_dom is None:
                    tipo_dom = tipo
                nombres = _extraer_personas_parte(parte)
                celdas.append([_persona_celda(n, foto_map) for n in nombres])
            else:
                celdas.append([_persona_celda(None, foto_map)])

        tipo_dom = tipo_dom or "Oveja"
        if tipo_dom == "Libro":
            icono, num, etiqueta = "🐑", oveja_num, f"{oveja_num}. "
        else:
            icono, num, etiqueta = "🐑", oveja_num, ""
        oveja_num += 1

        _fila("vida_cristiana", icono, num, etiqueta, celdas)

    # ── Fin de semana ─────────────────────────────────────────────────────────
    for key, (emo, lbl) in LOGISTICA_META.items():
        n = 2 if key in ("camara", "acomodadores") else 1
        _fila("fin_de_semana", emo, 0, lbl, _celdas_logistica(key, n, True))

    # ── Limpieza ──────────────────────────────────────────────────────────────
    limpiezas = [s["asignaciones"].get("limpieza", "—") for s in semanas]
    _fila("limpieza", "🧹", 0, "Limpieza", limpiezas, es_limpieza=True)

    # ── Marcar cabeceras de sección ───────────────────────────────────────────
    seccion_vista: set[str] = set()
    for fila in filas:
        if fila["seccion"] not in seccion_vista:
            fila["mostrar_cabecera"] = True
            seccion_vista.add(fila["seccion"])

    # ── Título del mes ────────────────────────────────────────────────────────
    titulo = "PROGRAMA DE REUNIONES"
    if semanas:
        try:
            from datetime import date as _date
            fecha_str = semanas[0].get("fecha_reunion", "")
            if fecha_str:
                d = _date.fromisoformat(fecha_str)
                MESES_ES = [
                    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
                ]
                titulo = f"PROGRAMA DE REUNIONES — {MESES_ES[d.month].upper()} {d.year}"
        except Exception:
            pass

    return {
        "titulo":      titulo,
        "generado":    datetime.now().strftime("%d/%m/%Y %H:%M"),
        "headers":     headers,
        "filas":       filas,
        "seccion_cfg": SECCION_CFG,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Actualizar Excel
# ─────────────────────────────────────────────────────────────────────────────

def _actualizar_carga_excel(resumen_carga: dict) -> None:
    """
    Escribe los valores `fin` de resumen_carga de vuelta en Carga_Acumulada.
    Solo toca a las personas con delta > 0.
    """
    if not PERSONAL_FILE.exists():
        print("[WARN] Personal.xlsx no encontrado. No se actualiza carga.")
        return

    # Auto-backup antes de sobrescribir
    backups_dir = PERSONAL_FILE.parent / "backups"
    backups_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"Personal_backup_{ts}.xlsx"
    shutil.copy2(PERSONAL_FILE, backup_path)
    print(f"[OK] Backup guardado en: backups/{backup_path.name}")

    df = pd.read_excel(PERSONAL_FILE, sheet_name="Personal")
    actualizados = 0
    for nombre, datos in resumen_carga.items():
        if datos.get("delta", 0) > 0:
            mask = df["Nombre"] == nombre
            if mask.any():
                df.loc[mask, "Carga_Acumulada"] = datos["fin"]
                actualizados += 1

    try:
        with pd.ExcelWriter(PERSONAL_FILE, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Personal")
        print(f"[OK] Carga_Acumulada actualizada para {actualizados} persona(s) en {PERSONAL_FILE.name}")
    except PermissionError:
        print(
            f"[WARN] No se pudo guardar '{PERSONAL_FILE.name}' porque esta abierto en otra aplicacion.\n"
            "       Cierra Excel y vuelve a ejecutar: python renderer.py --solo-carga"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Recorte de espacio blanco
# ─────────────────────────────────────────────────────────────────────────────

def _recortar_blanco(png_path: Path, padding: int = 40) -> None:
    """
    Elimina espacio vacío en la parte inferior de la imagen.
    Busca la última fila con al menos un píxel que no sea blanco/casi-blanco.
    Umbral conservador: suma RGB < 765 (cualquier pixel no puramente blanco).
    """
    img = Image.open(png_path).convert("RGB")
    pixels = list(img.getdata())
    w, h   = img.size

    last_row = h - 1
    for y in range(h - 1, -1, -1):
        row = pixels[y * w : (y + 1) * w]
        # Un pixel "no blanco" tiene al menos un canal < 250
        if any(min(p) < 250 for p in row):
            last_row = y
            break

    new_h = min(last_row + padding, h)
    # quality=95: sin pérdida visible; PNG es lossless así que el parámetro
    # equivale a compress_level bajo — máxima fidelidad, mínima compresión.
    img.crop((0, 0, w, new_h)).save(png_path, optimize=False, compress_level=1)


# ─────────────────────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────────────────────

def renderizar(programa: dict, actualizar_carga: bool = True) -> Path:
    """
    Genera Programa_Mes.png a partir del dict del assignator.

    Args:
        programa:        Dict devuelto por assignator.generar_programa().
        actualizar_carga: Si True (por defecto), actualiza Personal.xlsx al final.

    Returns:
        Path del PNG generado.
    """
    # 1. Fotos
    print("[Renderer 1/4] Cargando fotos...")
    foto_map = _build_foto_map()
    fotos_ok  = sum(1 for v in foto_map.values() if v)
    print(f"              {fotos_ok}/{len(foto_map)} fotos encontradas.")

    # 2. Normalizar datos
    print("[Renderer 2/4] Normalizando datos para el template...")
    ctx = _normalizar(programa, foto_map)
    n_semanas = len(ctx["headers"])
    n_filas   = len(ctx["filas"])
    print(f"              {n_semanas} semana(s), {n_filas} fila(s) de tabla.")

    # 3. Renderizar HTML
    print("[Renderer 3/4] Renderizando HTML...")
    TEMPLATES_DIR.mkdir(exist_ok=True)
    env  = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    tmpl = env.get_template("programa.html")
    html = tmpl.render(**ctx)
    TEMP_HTML.write_text(html, encoding="utf-8")
    print(f"              HTML guardado en: {TEMP_HTML.resolve()}")
    print(f"              (Abrelo en Chrome para verificar imagenes antes del PNG)")

    # 4. Capturar PNG
    print("[Renderer 4/4] Capturando PNG con Chrome headless (2x Retina)...")
    # Altura estimada con avatares de 85 px: header + filas*(95) + cabeceras de sección
    n_secciones = len({f["seccion"] for f in ctx["filas"]})
    alto_est    = 120 + n_filas * 95 + n_secciones * 36 + 60
    alto_seguro = max(alto_est, 1600)

    hti = Html2Image(
        output_path=str(OUTPUT_PNG.parent),
        custom_flags=[
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",   # resolución 2× (efecto Retina)
        ],
    )
    # Pequeña pausa para que Chrome decodifique los data URIs antes del screenshot
    time.sleep(1)
    hti.screenshot(
        html_file=str(TEMP_HTML),
        save_as=OUTPUT_PNG.name,
        size=(1400, alto_seguro),   # CSS pixels; con scale-factor=2 → 2800×(alto×2) px reales
    )

    if OUTPUT_PNG.exists():
        _recortar_blanco(OUTPUT_PNG)
        print(f"[OK] Imagen generada: {OUTPUT_PNG}")
    else:
        print("[WARN] No se encontro el PNG de salida. Revisa si Chrome esta disponible.")

    # 5. Actualizar Excel
    if actualizar_carga and OUTPUT_PNG.exists():
        _actualizar_carga_excel(programa.get("resumen_carga", {}))

    return OUTPUT_PNG


# ─────────────────────────────────────────────────────────────────────────────
# Uso standalone: python renderer.py [--solo-carga]
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    if "--solo-carga" in sys.argv:
        # Modo rápido: solo actualizar Excel desde el JSON existente
        if not OUTPUT_JSON.exists():
            print(f"[ERROR] No se encontro {OUTPUT_JSON}. Ejecuta main.py primero.")
            sys.exit(1)
        prog = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        _actualizar_carga_excel(prog.get("resumen_carga", {}))
    else:
        if not OUTPUT_JSON.exists():
            print(f"[ERROR] No se encontro {OUTPUT_JSON}. Ejecuta main.py primero.")
            sys.exit(1)
        prog = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        renderizar(prog)
