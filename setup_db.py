"""
setup_db.py
Genera el archivo Personal.xlsx con la estructura base de datos del personal.
"""

import pandas as pd
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "Personal.xlsx"

SAMPLE_DATA = [
    # Matrimonios (ID 1)
    {
        "Nombre": "Carlos Martínez",
        "Genero": "H",
        "Roles": "Camara, Zoom, Diamante 1, Diamante 2, Diamante 3, Oveja 1",
        "Matrimonio_ID": 1,
        "Foto_Path": "carlos_martinez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    {
        "Nombre": "Laura Martínez",
        "Genero": "M",
        "Roles": "Zoom, Ayudante, Oveja 2",
        "Matrimonio_ID": 1,
        "Foto_Path": "laura_martinez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    # Matrimonios (ID 2)
    {
        "Nombre": "Pedro Sánchez",
        "Genero": "H",
        "Roles": "Trigo, Diamante 1, Diamante 3, Discurso_H, Oveja 1, Conductor",
        "Matrimonio_ID": 2,
        "Foto_Path": "pedro_sanchez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    {
        "Nombre": "Ana Sánchez",
        "Genero": "M",
        "Roles": "Ayudante, Oveja 2, Lector",
        "Matrimonio_ID": 2,
        "Foto_Path": "ana_sanchez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    # Solteros/Sin pareja
    {
        "Nombre": "Miguel Torres",
        "Genero": "H",
        "Roles": "Camara, Trigo, Diamante 2, Diamante 3, Discurso_H, Conductor, Lector",
        "Matrimonio_ID": None,
        "Foto_Path": "miguel_torres.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    {
        "Nombre": "Sofía Ramírez",
        "Genero": "M",
        "Roles": "Zoom, Ayudante, Oveja 1, Oveja 2",
        "Matrimonio_ID": None,
        "Foto_Path": "sofia_ramirez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    {
        "Nombre": "Andrés López",
        "Genero": "H",
        "Roles": "Camara, Zoom, Trigo, Diamante 1, Diamante 2, Diamante 3, Discurso_H",
        "Matrimonio_ID": None,
        "Foto_Path": "andres_lopez.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
    {
        "Nombre": "Valentina Cruz",
        "Genero": "M",
        "Roles": "Ayudante, Oveja 1, Lector",
        "Matrimonio_ID": None,
        "Foto_Path": "valentina_cruz.jpg",
        "Carga_Acumulada": 0,
        "Ausencias": "",
    },
]

COLUMN_ORDER = [
    "Nombre",
    "Genero",
    "Roles",
    "Matrimonio_ID",
    "Foto_Path",
    "Carga_Acumulada",
    "Ausencias",
]


def create_excel():
    df = pd.DataFrame(SAMPLE_DATA, columns=COLUMN_ORDER)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Personal")

        ws = writer.sheets["Personal"]

        # Ajustar ancho de columnas
        col_widths = {
            "A": 22,  # Nombre
            "B": 10,  # Genero
            "C": 55,  # Roles
            "D": 15,  # Matrimonio_ID
            "E": 28,  # Foto_Path
            "F": 18,  # Carga_Acumulada
            "G": 30,  # Ausencias
        }
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

    print(f"[OK] Archivo generado: {OUTPUT_FILE}")
    print(f"     {len(df)} personas registradas.")
    print(f"\nColumnas: {', '.join(COLUMN_ORDER)}")


if __name__ == "__main__":
    create_excel()
