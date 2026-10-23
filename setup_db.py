"""
setup_db.py
Utilidades de la base de datos local (programa.db).

Uso:
    python setup_db.py                          → crea programa.db (y migra Personal_nuevo.xlsx si existe)
    python setup_db.py --importar archivo.xlsx  → importa / actualiza personas desde un Excel
    python setup_db.py --exportar archivo.xlsx  → exporta el catálogo a Excel (respaldo legible)
    python setup_db.py --historial 2026-11      → muestra las asignaciones guardadas de un mes
"""

import sys
from collections import Counter
from pathlib import Path

import db


def main(args: list[str]) -> None:
    db.inicializar()

    if len(args) >= 2 and args[0] == "--importar":
        n = db.importar_excel(Path(args[1]))
        print(f"[OK] {n} persona(s) importadas/actualizadas desde {args[1]}")
    elif len(args) >= 2 and args[0] == "--exportar":
        n = db.exportar_excel(Path(args[1]))
        print(f"[OK] {n} persona(s) exportadas a {args[1]}")
    elif len(args) >= 2 and args[0] == "--historial":
        filas = db.historial(mes=args[1])
        if not filas:
            print(f"Sin historial para {args[1]}.")
            return
        for f in filas:
            print(f"  {f['fecha']}  {f['reunion']:<3}  {f['rol']:<15} {f['nombre']}")
        print("\n  Asignaciones por persona:")
        for nombre, n in Counter(f["nombre"] for f in filas).most_common():
            print(f"  {nombre:<28} {n}")
    else:
        print(f"[OK] Base de datos lista: {db.DB_FILE}")
        print(f"     {len(db.listar_personas())} persona(s) registradas.")


if __name__ == "__main__":
    main(sys.argv[1:])
