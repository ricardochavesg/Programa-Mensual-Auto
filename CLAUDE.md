# CLAUDE.md — Guía para agentes

App de escritorio (Windows, empaquetada como `.exe` con PyInstaller) que arma el
**programa mensual de la reunión Vida y Ministerio Cristianos**: descarga la guía
de actividades de cada semana, asigna personas a cada parte y logística, permite
editar en un navegador y exporta una imagen PNG lista para imprimir en hoja carta.

El usuario escribe en español y todo el código, comentarios, mensajes y UI están
en español. Mantén ese idioma y el estilo de los archivos (cabecera con docstring
del módulo, separadores `# ─────`, nombres en español).

## Comandos

```bash
pip install -r requirements.txt
python main.py                 # abre la ventana de control + editor web (http://127.0.0.1:5000/editar)
python -m pytest tests -q      # pruebas (sin internet ni Chrome; ~2 s)
python build.py                # genera dist/Programa_Reuniones.exe (en Windows)
python audit.py                # valida reglas sobre el último programa_mes.json
python guia.py 2026-11         # prueba la descarga/parseo de la guía de un mes
python setup_db.py --exportar respaldo.xlsx | --importar archivo.xlsx | --historial 2026-11
```

Corre `python -m pytest tests -q` antes de cada commit.

Funcionalidades acordadas y aún no hechas: `PENDIENTES.md`.

## Flujo

```
main.py ──> ventana.py (tkinter: botones "Abrir Editor Web" / "Cerrar programa" + log)
              └─ arranca Flask (app.py) con werkzeug.make_server en un hilo
app.py /editar?mes=YYYY-MM
  └─ assignator.generar_programa(mes)
       ├─ db.listar_personas()                      (SQLite)
       ├─ guia.obtener_semanas_mes(anio, mes)       input_html/ → cache_guias/ → wol.jw.org → jw.org
       │    └─ parser.construir_semana(...)         partes: tesoros / maestros / vida_cristiana
       ├─ db.historial(antes del mes)               reparto y rotación respecto al mes anterior
       └─ Assignator.asignar_mes()  → programa (dict) + avisos
app.py /guardar (botón "Generar Imagen Final")
  ├─ renderer.renderizar(programa)                  templates/programa.html → Chrome/Edge headless → PNG
  └─ db.guardar_historial(assignator.filas_historial(programa))   (reemplaza por semana: idempotente)
```

## Módulos

| Archivo | Rol |
|---|---|
| `main.py` | Entrada. Prepara carpetas, `config.json`, `programa.db` (migra `Personal_nuevo.xlsx` si existe) y abre la ventana. |
| `ventana.py` | Ventana tkinter en la barra de tareas. Redirige `print` al log de la ventana (el `.exe` es `--windowed`, sin consola). El servidor vive mientras la ventana esté abierta (no hay heartbeat/auto-apagado). |
| `app.py` | Flask: `/editar`, `/catalogo`, `/estadisticas?desde=&hasta=`, `/guardar`, `/imagen`, `/api/programa/*`, `/api/personal/*`, `/api/disponibilidad?anio=&mes=`, `/api/config`, `/api/asamblea`, `/api/limpieza`. Construye la tabla editable (`field_id = "{semana}|{seccion}|{clave}|{campo}"`). |
| `assignator.py` | Motor de asignación (ver reglas abajo) y `filas_historial()`. |
| `guia.py` | Calcula las semanas del mes, descarga/cachea la guía (wol.jw.org y, si no está, el cuadernillo bimestral de jw.org) y la disponibilidad por mes. |
| `parser.py` | Parseo del HTML de JW.org (autómata h2 = sección / h3 numerado = parte). También lee `input_html/`. |
| `db.py` | SQLite (`programa.db`): tablas `personas` e `historial`; `estadisticas()` (partes por persona y tipo según `TIPOS_ESTADISTICA`; "no aplica" ≠ 0); normalización de roles; importar/exportar Excel; respaldos. |
| `renderer.py` | Normaliza el programa a filas y genera `Programa_Mes.png` con Chrome/Edge headless (`_capturar`) + recorte PIL. |
| `config.py` | `config.json` (día de reunión, día FDS, `mostrar_limpieza`, `limpieza`, `semanas_asamblea`) y `PALETA_BANNER`. |
| `limpieza.py` | Rotación de limpieza por fecha (`calcular(lunes)`) y `normalizar()` (acepta el formato antiguo: solo el grupo). |
| `audit.py` | Auditoría por consola de reglas de negocio. |
| `paths.py` | `internal_path` (dentro del .exe: código, templates) vs `external_path` (junto al .exe: datos). |
| `templates/` | `editar.html` (editor, Tailwind por CDN + JS vanilla), `catalogo.html`, `estadisticas.html` (tabla ordenable de partes por persona), `base.html`, `programa.html` (plantilla de impresión, CSS propio). |
| `tests/` | `conftest.py` aísla rutas en `tmp_path` y simula la red; `test_sistema.py` cubre todo el sistema. |

## Datos (todos externos, junto al .exe; en `.gitignore`)

- `programa.db` — personal + historial. **Nunca** va dentro del .exe (PyInstaller `--onefile` borra su carpeta temporal al cerrar). `build.py` copia el de desarrollo a `dist/` si existe y no sobrescribe uno que ya esté en `dist/`.
- `fotos/` — `Foto_Path` o `Nombre.(png|jpg|jpeg|webp)`, búsqueda sin distinguir mayúsculas.
- `cache_guias/` — HTML de cada semana descargada (`es_2026-W45.html`).
- `input_html/` — HTML manuales: tienen prioridad sobre la descarga.
- `config.json`, `borrador_programa.json`, `programa_mes.json`, `Programa_Mes.png`, `temp.html`, `backups/`.

Datos reales de la congregación (nombres, fotos) son privados: no los subas al repo.

## Reglas del motor (`assignator.py`)

- **Entre semana (ES) y fin de semana (FDS) son pools separados**, con contadores de carga separados. En FDS se puede repetir a quien tiene parte ES. El Conductor de La Atalaya no recibe logística de FDS.
- **Puntaje** (menor = mejor): asignaciones del mes en esa reunión → reservar a quien cubre roles escasos (`_escasez_otros_roles`) → no repetir el mismo rol del mes anterior → menos asignaciones el mes anterior → más tiempo sin participar → azar.
- **Orden por escasez**: dentro de cada semana se asignan primero los roles con menos candidatos (Presidente, Diamantes…).
- **Descanso**: quien tuvo una parte (no logística) la semana anterior no repite la siguiente. Cámara/Zoom/Acomodador (`ROLES_SIN_DESCANSO`) no cuentan. Se inicializa con la última semana del historial (cruza meses).
- **Must-fill**: niveles de relajación (evitar pareja repetida → descanso → libre en la reunión → repetir persona con aviso). Ausencias (`DD/MM`) e Inactivos **nunca** se relajan.
- **Parejas (Maestros)**: Trigo y Ayudante prefieren mujeres; una vez al mes se intenta matrimonio o pareja de hombres (`nota: "excepcion_mensual"`); no repetir compañero en el mes. `Discurso_H` solo hombres.
- **Limpieza** (`limpieza.py`): cada semana le toca a un grupo (orden de `config.limpieza.orden`, por defecto Norte → Central → Sur) en las dos reuniones: *leve* entre semana y *profunda* el fin de semana. Los encargados del grupo se turnan por vuelta (1.º leve / 2.º profunda, luego al revés). Se calcula por fecha desde `config.limpieza.inicio`, así sigue sola entre meses (no usa el historial). Formato: `asignaciones["limpieza"] = {"es"|"fds": {"grupo", "encargado", "especial"}}`; `especial` (texto libre, ej. limpieza anual) reemplaza grupo y encargado. Dos filas opcionales (`mostrar_limpieza`): "Limpieza leve" tras Vida Cristiana y "Limpieza profunda" al final, sin cabecera de sección. En el editor: botones "Limpieza especial" y "Grupos de limpieza" (`POST /api/limpieza` guarda y recalcula el programa abierto conservando las especiales). Al cambiar el grupo de una celda, el editor pone el encargado de ese grupo según la vuelta de esa semana (`limpieza.encargados_por_grupo`, en `data-por-grupo`) y, si es la leve, el fin de semana toma el mismo grupo.
- **Asamblea**: `semana["asamblea"]` (botón en la cabecera de cada semana; se recuerda en `config.semanas_asamblea` vía `POST /api/asamblea`). Esa semana no se asigna a nadie, no entra al historial y pierde su turno de limpieza. En la imagen y el editor la columna se tapa con un letrero vertical "ASAMBLEA" posicionado por JS (`.asamblea-overlay`).
- Los avisos se agrupan y se muestran en el banner rojo del editor.

Roles oficiales: `db.ROLES_OFICIALES`. `db.normalizar_rol()` acepta variantes (`"Cámara"`, `"Diamante 1"`, `"Presidente"` → `Presidente_ES`). Si agregas un rol, actualízalo ahí y en `assignator.ROLES_POR_REUNION`.

## Guía de actividades (`guia.py`)

- Una semana pertenece al mes en que cae su reunión de entre semana (`config.dia_reunion`).
- wol: `https://wol.jw.org/{idioma}/wol/meetings/{r}/{lp}/{año ISO}/{semana ISO}`; busca bloques `[class*=pub-mwb]`, luego `<article>`, luego enlaces `/wol/d/`, luego toda la página.
- jw.org: `.../guia-actividades-reunion-testigos-jehova/{enero-febrero}-{año}-mwb/` y el enlace de la semana se encuentra comparando su texto/URL con `rango_texto(lunes)`.
- Errores tipados: `SinConexion` y `GuiaNoDisponible` (ambos `RuntimeError`).
- **No se pudo probar contra las páginas reales** desde el entorno de desarrollo en la nube (wol.jw.org y jw.org están bloqueados por el proxy). Si el parseo falla con la página real, pide al usuario el HTML guardado (Ctrl+S) y ajusta `_extraer_guia` / `_enlace_semana_jw` + agrega un test con ese HTML.

## Imagen final (`templates/programa.html` + `renderer.py`)

- Ancho 1440 CSS px (1400 de programa + márgenes), escala 2× → PNG de 2880 px de ancho.
- La altura se pasa con margen de sobra y `_recortar_blanco` elimina el sobrante: si cambias tamaños de letra/filas, revisa que no se corte (antes pasó).
- Letra ~1.5× para imprimir en carta. Sin emojis en Tesoros/Maestros/Vida Cristiana (solo número).
- Color del encabezado: `programa["banner_color"]` (al azar de `PALETA_BANNER` al generar; editable en el editor). También tiñe la fila de fechas y la celda "Asignación".

## Entorno y trampas conocidas

- Objetivo: **Windows** (`Segoe UI`, `.exe`). La imagen necesita Chrome o Edge instalado: `renderer._capturar` lanza el navegador headless directamente (de html2image solo se usan los buscadores de ejecutables), con perfil y salida en una carpeta temporal, prueba `--headless=new` y `--headless`, y si falla el error muestra lo que respondió el navegador. Nunca dejes que una captura fallida pase como éxito (antes quedaba la imagen anterior).
- El editor usa Tailwind desde `cdn.tailwindcss.com` (requiere internet para verse con estilos).
- En la nube no hay acceso a jw.org/wol ni al CDN de Tailwind. Para capturas con Playwright se puede servir `@tailwindcss/browser` (npm) interceptando la ruta del CDN, y Chromium está en `/opt/pw-browsers/chromium`. tkinter solo está disponible para `python3.12` del sistema (`xvfb-run` para probar la ventana).
- `parser.DIA_REUNION` y `guia.WOL_*` se leen de `config.json` **al importar**. El día del fin de semana (`dia_fds`: Sábado/Domingo) no: `parser.calcular_dia_fds` lo lee en cada llamada porque se cambia desde el editor (selector "Fin de semana"). Su fecha (`parser.fecha_reunion_texto`) se muestra en la fila de sección FIN DE SEMANA, en el editor y en la imagen.
- En el `.exe` `sys.stdout` es `None` hasta que `ventana.py` lo redirige; no uses `sys.stdout.buffer` fuera de scripts CLI.
- **Carpeta bloqueada en Windows**: si el .exe está en Documentos/Escritorio/OneDrive, la Protección contra ransomware (Acceso controlado a carpetas) puede bloquear cada .exe nuevo: escribir da `[Errno 2]` y SQLite `unable to open database file` (leer sí funciona). `paths.verificar_escritura()` lo detecta al arrancar y la ventana lo explica; la caché de guías es opcional (si no se puede guardar, la guía descargada se usa igual). Solución: mover la carpeta (p. ej. `C:\ProgramaReuniones`) o permitir el .exe. Solución definitiva pendiente (datos en `%LOCALAPPDATA%` + instalador): ver `PENDIENTES.md`.
- El servidor Flask es multihilo: cada acceso a SQLite abre su propia conexión (`db.conectar()`).
- El usuario trabaja sobre `main` y genera el `.exe` en su PC con `git pull` + `python build.py`.
