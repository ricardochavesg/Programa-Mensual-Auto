"""
parser.py
Lee archivos HTML/HTM de programas semanales de JW.org y extrae la estructura
de asignaciones por semana como lista de diccionarios.

Dependencias: beautifulsoup4, pandas, lxml
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from paths import external_path

INPUT_DIR = external_path("input_html")
_CFG_PATH = external_path("config.json")

# Día de la reunión de entre semana (configurable en config.json)
try:
    _cfg = json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    DIA_REUNION: str = _cfg.get("dia_reunion", "Miércoles")
except Exception:
    DIA_REUNION = "Miércoles"

# Meses en español -> número
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Partes numeradas: "4. Empiece conversaciones", "8. Estudio bíblico..."
_PARTE_NUMERADA = re.compile(r"^\d+\.")


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades de fecha
# ─────────────────────────────────────────────────────────────────────────────

def extraer_fecha_inicio(texto_rango: str) -> date | None:
    """
    Parsea rangos de fecha en múltiples formatos:
      '6-12 de abril de 2026'           (guión, mismo mes)
      '6 a 12 de abril de 2026'         (JW.org: "a", mismo mes)
      '30 de marzo–5 de abril de 2026'  (guión, cruce de mes)
      '27 de abril a 3 de mayo de 2026' (JW.org: "a", cruce de mes)
      '28 de diciembre de 2026–3 de enero de 2027' (cruce de año)

    Devuelve la fecha del primer día del rango.
    """
    texto = texto_rango.strip().lower()
    sep   = r"[-–a]"          # acepta guión, em-dash y la letra "a"

    # ── Caso simple: "6-12 de abril de 2026" / "6 a 12 de abril de 2026" ──
    m = re.match(rf"(\d{{1,2}})\s*{sep}\s*\d{{1,2}}\s+de\s+(\w+)\s+de\s+(\d{{4}})", texto)
    if m:
        dia, mes_str, anio = int(m.group(1)), m.group(2), int(m.group(3))
        mes = MESES.get(mes_str)
        if mes:
            return date(anio, mes, dia)

    # ── Cruce de mes: "30 de marzo–5 de abril de 2026" ──
    m = re.match(
        rf"(\d{{1,2}})\s+de\s+(\w+)\s*{sep}\s*\d{{1,2}}\s+de\s+\w+\s+de\s+(\d{{4}})", texto
    )
    if m:
        dia, mes_str, anio = int(m.group(1)), m.group(2), int(m.group(3))
        mes = MESES.get(mes_str)
        if mes:
            return date(anio, mes, dia)

    # ── Cruce de año: "28 de diciembre de 2026–3 de enero de 2027" ──
    m = re.match(rf"(\d{{1,2}})\s+de\s+(\w+)\s+de\s+(\d{{4}})\s*{sep}", texto)
    if m:
        dia, mes_str, anio = int(m.group(1)), m.group(2), int(m.group(3))
        mes = MESES.get(mes_str)
        if mes:
            return date(anio, mes, dia)

    return None


# Días válidos para la reunión de entre semana
DIAS_SEMANA = {"Lunes": 0, "Martes": 1, "Miércoles": 2, "Jueves": 3, "Viernes": 4}


def calcular_dia_reunion(fecha_inicio: date, dia_semana: str = DIA_REUNION) -> date:
    """Dado el lunes de la semana, devuelve la fecha del día de reunión configurado."""
    objetivo = DIAS_SEMANA.get(dia_semana, 2)
    dias = (objetivo - fecha_inicio.weekday()) % 7
    return fecha_inicio + timedelta(days=dias)


def formatear_fecha_exacta(d: date, dia_semana: str = DIA_REUNION) -> str:
    """Devuelve la fecha con el patrón 'Día-DD-MM-AA', ej: 'Miércoles-15-04-26'."""
    return f"{dia_semana}-{d.strftime('%d-%m-%y')}"


# ─────────────────────────────────────────────────────────────────────────────
# Clasificación de partes — Sección MAESTROS
# ─────────────────────────────────────────────────────────────────────────────

PALABRAS_PAREJA = re.compile(
    r"conversaci[oó]n|empiece\s+conversaciones?|revisita|disc[ií]pulo|haga\s+disc"
    r"|escenificaci[oó]n|escenificado",
    re.IGNORECASE,
)
PALABRAS_INDIVIDUAL = re.compile(r"creencia|explique\s+sus\s+creencias?", re.IGNORECASE)
PALABRAS_DISCURSO   = re.compile(r"discurso", re.IGNORECASE)


def clasificar_parte_maestros(titulo: str) -> dict:
    """
    Clasifica una parte de Maestros en:
      'Pareja'     → 2 personas (Alumno + Ayudante)
      'Individual' → 1 persona
      'Discurso_H' → 1 persona, debe ser hombre
    """
    if PALABRAS_PAREJA.search(titulo):
        tipo = "Pareja"
    elif PALABRAS_INDIVIDUAL.search(titulo):
        tipo = "Individual"
    elif PALABRAS_DISCURSO.search(titulo):
        tipo = "Discurso_H"
    else:
        tipo = "Individual"
    return {"tipo": tipo, "titulo": titulo}


# ─────────────────────────────────────────────────────────────────────────────
# Clasificación — Estudio Bíblico
# ─────────────────────────────────────────────────────────────────────────────

LFB_PATTERN = re.compile(r"\blfb\b", re.IGNORECASE)


def clasificar_estudio_biblico(titulo: str) -> dict:
    if LFB_PATTERN.search(titulo):
        return {"tipo": "Estudio_LFB",    "titulo": titulo, "personas": 1}
    return     {"tipo": "Estudio_Normal", "titulo": titulo, "personas": 2}


# ─────────────────────────────────────────────────────────────────────────────
# Extractor principal de secciones del HTML de JW.org
# ─────────────────────────────────────────────────────────────────────────────

def _extraer_secciones_articulo(soup: BeautifulSoup) -> dict[str, list[str]]:
    """
    Recorre el <article> de la página de JW.org y extrae las partes numeradas
    de cada sección usando un autómata de estados sobre h2/h3.

    Estructura real de JW.org:
      <h2> TESOROS DE LA BIBLIA
        <h3> 1. Título parte 1
        <h3> 2. Título parte 2
        <h3> 3. Título parte 3
      <h2> SEAMOS MEJORES MAESTROS
        <h3> 4. Título...
        ...
      <h2> NUESTRA VIDA CRISTIANA
        <h3> Canción XX          ← no numerado, se ignora
        <h3> 7. Título...
        <h3> 8. Estudio bíblico...
        <h3> Palabras de conclusión... ← no numerado, se ignora

    Devuelve:
      {
        "tesoros":        ["1. Título...", "2. Título...", "3. Título..."],
        "maestros":       ["4. Título...", "5. Título...", ...],
        "vida_cristiana": ["7. Título...", "8. Estudio bíblico..."],
      }
    """
    article = soup.find("article")
    if not article:
        # Fallback: usar todo el documento
        article = soup

    MAPA_SECCIONES = {
        "tesoros":        ["tesoros"],
        "maestros":       ["seamos mejores", "maestros"],
        "vida_cristiana": ["vida cristiana", "nuestra vida"],
    }

    resultado: dict[str, list[str]] = {}
    seccion_actual: str | None = None

    for tag in article.find_all(["h2", "h3"]):
        texto = tag.get_text(" ", strip=True)

        if tag.name == "h2":
            texto_lower = texto.lower()
            seccion_actual = None
            for clave, palabras in MAPA_SECCIONES.items():
                if any(p in texto_lower for p in palabras):
                    seccion_actual = clave
                    resultado.setdefault(clave, [])
                    break

        elif tag.name == "h3" and seccion_actual:
            if _PARTE_NUMERADA.match(texto):
                resultado[seccion_actual].append(texto)

    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Parseo de secciones (reciben lista de títulos ya extraídos)
# ─────────────────────────────────────────────────────────────────────────────

def parsear_tesoros(items: list[str]) -> list[dict]:
    """Mapea los 3 primeros títulos a Diamante_1, Diamante_2 y Diamante_3."""
    etiquetas = ["Diamante_1", "Diamante_2", "Diamante_3"]
    return [
        {"rol": etiquetas[i], "titulo": titulo, "tipo": "Individual", "seccion": "Tesoros"}
        for i, titulo in enumerate(items[:3])
    ]


def parsear_maestros(items: list[str]) -> list[dict]:
    """Clasifica cada parte de Maestros según su contenido."""
    partes = []
    for titulo in items:
        c = clasificar_parte_maestros(titulo)
        c["seccion"] = "Maestros"
        partes.append(c)
    return partes


def parsear_vida_cristiana(items: list[str]) -> list[dict]:
    """
    Regla del Libro:
      · El ÚLTIMO h3 numerado de la sección → tipo 'Libro', rol 'Libro'.
      · Todos los anteriores               → tipo 'Oveja',  rol 'Oveja'.

    Esta regla es independiente del número de partes capturadas,
    lo que hace el parser 100 % dinámico ante cualquier estructura HTML.
    """
    if not items:
        return []

    partes = []
    for titulo in items[:-1]:          # todas excepto la última → Oveja
        partes.append({
            "rol":     "Oveja",
            "titulo":  titulo,
            "tipo":    "Oveja",
            "seccion": "Vida Cristiana",
        })

    partes.append({                    # última → Libro
        "rol":     "Libro",
        "titulo":  items[-1],
        "tipo":    "Libro",
        "seccion": "Vida Cristiana",
    })
    return partes


# ─────────────────────────────────────────────────────────────────────────────
# Extracción del rango de fechas
# ─────────────────────────────────────────────────────────────────────────────

def _extraer_rango_fechas(soup: BeautifulSoup, ruta: Path) -> str | None:
    """
    Estrategia (en orden de fiabilidad):
      1. El último <h3> del artículo contiene "(fecha completa con año)".
      2. Regex en todo el texto que combine DD-DD/a de mes de AAAA.
      3. El nombre del archivo como fallback.
    """
    # ── 1. Footer h3: "Vida y Ministerio Cristianos (6 a 12 de abril de 2026)" ──
    article = soup.find("article") or soup
    for h3 in reversed(article.find_all("h3")):
        texto = h3.get_text(" ", strip=True)
        m = re.search(
            r"\((\d{1,2}(?:\s+de\s+\w+)?\s*(?:[-–a])\s*\d{1,2}\s+de\s+\w+\s+de\s+\d{4})\)",
            texto, re.IGNORECASE,
        )
        if m:
            return m.group(1)

    # ── 2. Regex general en todo el documento ──
    patron = re.compile(
        r"\d{1,2}(?:\s+de\s+\w+)?\s*(?:[-–a])\s*\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",
        re.IGNORECASE,
    )
    for tag in soup.find_all(["h1", "h2", "h3", "title", "span", "p"]):
        m = patron.search(tag.get_text(" ", strip=True))
        if m:
            return m.group(0)

    # ── 3. Fallback: nombre del archivo ──
    nombre = ruta.stem  # e.g. "Vida y Ministerio Cristianos_ 6 a 12 de abril de 2026"
    m = patron.search(nombre)
    if m:
        return m.group(0)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Parser de un archivo HTML/HTM completo
# ─────────────────────────────────────────────────────────────────────────────

def parsear_archivo(ruta: Path) -> dict | None:
    """
    Procesa un archivo HTML/HTM de JW.org y devuelve:

    {
        "archivo":        str,
        "rango_fechas":  str,
        "fecha_inicio":  date | None,
        "fecha_reunion": date | None,
        "fecha_exacta":  str,
        "partes": {
            "tesoros":       [...],
            "maestros":      [...],
            "vida_cristiana":[...],
        }
    }
    """
    try:
        html = ruta.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = ruta.read_text(encoding="latin-1")

    soup = BeautifulSoup(html, "lxml")

    # ── Fechas ──
    rango = _extraer_rango_fechas(soup, ruta)
    if not rango:
        print(f"  [WARN] No se encontro rango de fechas en {ruta.name}")
        rango = "Desconocido"

    fecha_inicio  = extraer_fecha_inicio(rango) if rango != "Desconocido" else None
    fecha_reunion = calcular_dia_reunion(fecha_inicio) if fecha_inicio else None
    fecha_exacta  = formatear_fecha_exacta(fecha_reunion) if fecha_reunion else ""

    # ── Partes del programa ──
    secciones = _extraer_secciones_articulo(soup)

    tesoros       = parsear_tesoros(secciones.get("tesoros", []))
    maestros      = parsear_maestros(secciones.get("maestros", []))
    vida_cristiana= parsear_vida_cristiana(secciones.get("vida_cristiana", []))

    if not (tesoros or maestros or vida_cristiana):
        print(f"  [WARN] No se extrajeron partes de {ruta.name}. "
              "Verifica que sea un HTML valido de JW.org.")

    return {
        "archivo":       ruta.name,
        "rango_fechas":  rango,
        "fecha_inicio":  fecha_inicio,
        "fecha_reunion": fecha_reunion,
        "fecha_exacta":  fecha_exacta,
        "partes": {
            "tesoros":        tesoros,
            "maestros":       maestros,
            "vida_cristiana": vida_cristiana,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

def parsear_todos() -> list[dict]:
    """
    Lee todos los archivos .html y .htm de INPUT_DIR.
    Devuelve la lista de semanas estructuradas, ordenada por fecha.
    """
    # Aceptar tanto .html como .htm (JW.org usa .htm al guardar)
    archivos = sorted(
        list(INPUT_DIR.glob("*.html")) + list(INPUT_DIR.glob("*.htm")),
        key=lambda p: p.name,
    )

    if not archivos:
        print(f"[WARN] No se encontraron archivos HTML/HTM en: {INPUT_DIR}")
        print("       Descarga los programas de JW.org y guardalo(s) en esa carpeta.")
        return []

    print(f"[>>] {len(archivos)} archivo(s) encontrado(s) en {INPUT_DIR.name}/")
    resultados = []
    for ruta in archivos:
        print(f"     Procesando: {ruta.name}")
        datos = parsear_archivo(ruta)
        if datos:
            resultados.append(datos)
            _imprimir_resumen(datos)

    # Ordenar por fecha de reunión (semanas sin fecha al final)
    resultados.sort(key=lambda s: s["fecha_reunion"] or date.max)

    print(f"\n[OK] {len(resultados)} semana(s) procesada(s).")
    return resultados


def _imprimir_resumen(datos: dict) -> None:
    total = sum(len(v) for v in datos["partes"].values())
    print(f"       Rango    : {datos['rango_fechas']}")
    print(f"       Reunion  : {datos['fecha_exacta']}")
    print(f"       Partes   : {total} asignaciones detectadas")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Modo standalone: inspección rápida
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    semanas = parsear_todos()

    if semanas:
        filas = []
        for semana in semanas:
            for seccion, partes in semana["partes"].items():
                for parte in partes:
                    filas.append({
                        "Reunion": semana["fecha_exacta"],
                        "Seccion":   seccion,
                        "Rol":       parte.get("rol", "-"),
                        "Tipo":      parte.get("tipo", "-"),
                        "Titulo":    parte.get("titulo", "-")[:55],
                    })
        df = pd.DataFrame(filas)
        print(df.to_string(index=False))
