# Manual de uso — Programa de Reuniones

Guía paso a paso para preparar el programa mensual de la reunión **Vida y
Ministerio Cristianos** (entre semana y fin de semana) e imprimirlo.

---

## 1. Instalación

### Opción A: el `.exe` (recomendado)

1. Copia `Programa_Reuniones.exe` a una carpeta propia, por ejemplo
   `C:\ProgramaReuniones\`.
   > **Evita Documentos, Escritorio y OneDrive.** La protección contra
   > ransomware de Windows puede impedir que el programa guarde datos ahí
   > (el programa te avisa al abrir si pasa).
2. Ábrelo con doble clic. Si Windows muestra "Windows protegió su PC", pulsa
   **Más información → Ejecutar de todas formas**.
3. Necesitas **Google Chrome o Microsoft Edge** instalado: se usa para crear
   la imagen final.

### Opción B: desde el código

```bash
pip install -r requirements.txt
python main.py
```

Para generar el `.exe` (en Windows): `git pull` y luego `python build.py`
→ queda en `dist/Programa_Reuniones.exe`.

---

## 2. La ventana del programa

Al abrirlo aparece una ventana pequeña en la barra de tareas:

- **Abrir Editor Web**: abre el editor en tu navegador
  (`http://127.0.0.1:5000/editar`).
- **Cerrar programa**: detiene todo. Mientras la ventana esté abierta el
  editor funciona.
- **Actividad**: registro de lo que hace el programa. Si algo falla, el
  motivo aparece aquí.

---

## 3. Personal (Catálogo)

Menú **👥 Catálogo**. Aquí está toda la congregación.

- **Agregar persona**: nombre, género, foto (opcional), roles y cónyuge.
- **Roles**: definen qué partes puede recibir cada persona (Presidente,
  Diamantes, Trigo, Ayudante, Discurso, Vida Cristiana, Estudio del libro,
  Cámara, Zoom, Acomodador, Presidente de fin de semana…).
- **Ausencias**: fechas en formato `DD/MM` separadas por coma
  (ej. `08/04, 15/04`). Esos días nunca se le asigna nada.
- **Activo / Inactivo**: un inactivo no recibe ninguna asignación.
- **Fotos**: también puedes ponerlas en la carpeta `fotos/` con el nombre de
  la persona (`Juan Pérez.jpg`).

---

## 4. Preparar un mes

Menú **✏️ Editar**.

1. Pulsa **📅 (mes)**, elige el mes y **Generar programa**.
   - Punto verde: la guía de ese mes ya está publicada.
   - La guía se descarga sola de wol.jw.org (o jw.org) y se guarda en
     `cache_guias/`. Si no hay internet o no está publicada, puedes guardar
     la página (Ctrl+S) en `input_html/`.
2. El programa asigna a todos automáticamente:
   - reparte la carga (primero quien tiene menos partes),
   - no repite el mismo rol del mes anterior,
   - quien tuvo parte una semana descansa la siguiente,
   - respeta ausencias e inactivos,
   - entre semana y fin de semana se reparten por separado.
3. Si aparece el **banner rojo de avisos**, revisa lo que indica (roles sin
   candidatos, personas repetidas, semanas sin guía).

### Cambiar una asignación

- Haz clic en una foto → busca y elige a otra persona. La lista muestra solo
  a quienes tienen ese rol, ordenados por menor carga.
- Si alguien queda repetido en la misma reunión, se marca en **rojo**.
- En Maestros y Vida Cristiana: **+** agrega una persona, **×** la quita.

### Botones principales

| Botón | Qué hace |
|---|---|
| 💾 Guardar Borrador | Guarda tus cambios sin generar la imagen. Al volver a abrir el editor se carga el borrador. |
| 🗑️ Empezar de nuevo | Descarta el borrador y genera el mes otra vez desde cero. |
| 🖼️ Generar Imagen Final | Crea `Programa_Mes.png`, lo muestra y guarda las asignaciones en el historial. |

> El historial es lo que permite que el mes siguiente no repita a las
> mismas personas. Genera siempre la imagen final del mes definitivo.

---

## 5. Opciones de la imagen

En la barra **Opciones de la imagen**:

- **🎨 Color del encabezado**: elige un color o uno personalizado.
- **📅 Entre semana**: día regular de la reunión (lunes a viernes).
- **Fin de semana**: Sábado o Domingo. Su fecha aparece en la fila
  **FIN DE SEMANA** de cada semana.
- **🧹 Incluir filas de limpieza**: muestra u oculta la limpieza.

Si cambias el día de entre semana con un mes ya generado, usa
**Empezar de nuevo** para que cada semana quede en el mes correcto.

---

## 6. Semanas especiales

En el encabezado de cada semana hay dos botones:

### Asamblea

- Toda la semana se apaga: nadie recibe asignaciones y en la imagen la
  columna se tapa con un letrero vertical **ASAMBLEA**.
- No cuenta para el historial.
- El grupo de limpieza que tocaba pierde su turno (la semana siguiente sigue
  con el grupo siguiente).

### Visita (del superintendente)

- La reunión de entre semana pasa al **martes** (la fecha se recalcula).
- La columna se pinta de **naranja pastel** y la fecha lleva la etiqueta
  **VISITA**.
- Las ausencias se revisan con la fecha del martes.

Ambas se recuerdan: si generas el mes otra vez, la semana sigue marcada.

---

## 7. Limpieza

Dos filas en el programa:

- **Limpieza leve** (entre semana), después de Nuestra Vida Cristiana.
- **Limpieza profunda** (fin de semana), al final.

Cada semana le toca a un grupo (Norte → Central → Sur) en las dos reuniones.
Cada grupo tiene dos encargados que se turnan: en una vuelta el 1.º hace la
leve y el 2.º la profunda; en la siguiente, al revés. La rotación continúa
sola de un mes a otro.

### Configurar los grupos (una sola vez)

**👥 Grupos de limpieza**:

1. Escribe el nombre de cada grupo y sus dos encargados (se sugieren los
   nombres del Catálogo). Puedes agregar o quitar grupos.
2. **Semana de inicio**: una semana en la que le toque al primer grupo con su
   primer encargado entre semana.
3. **Guardar y aplicar**: se recalcula el mes abierto.

### Cambiar a mano

- Cambia el grupo de una celda y se ponen solos los encargados de ese grupo.
  Si cambias la leve, la profunda de esa semana toma el mismo grupo.
- El encargado también se puede escribir a mano.

### Limpieza especial (anual, mensual…)

**✨ Limpieza especial** → elige la fecha (cualquier reunión del mes) y el
texto (por defecto "LIMPIEZA ANUAL – TODOS LOS GRUPOS"). Reemplaza al grupo y
encargado de esa reunión. Para quitarla, pulsa la **×** de la celda.

---

## 8. Estadísticas

Menú **📊 Estadísticas**: cuántas partes tuvo cada persona y de qué tipo.

- Periodo: último mes, 3 meses, 6 meses, todo o un rango propio.
- Filtros por hombres/mujeres y búsqueda por nombre; columnas ordenables.
- **—** significa que ese tipo no le aplica (ej. Discurso para una hermana);
  un **0** en ámbar significa que le aplica pero no ha tenido ninguna.

Solo cuenta lo guardado con **Generar Imagen Final**.

---

## 9. Datos y respaldos

Todo se guarda junto al `.exe`:

| Archivo / carpeta | Contenido |
|---|---|
| `programa.db` | Personal e historial. **Es lo más importante: respáldalo.** |
| `backups/` | Copia automática de `programa.db` cada vez que generas la imagen. |
| `fotos/` | Fotos del personal. |
| `config.json` | Preferencias (días de reunión, grupos de limpieza, asambleas, visitas…). |
| `cache_guias/` | Guías descargadas. |
| `input_html/` | Guías guardadas a mano (tienen prioridad). |
| `borrador_programa.json` | Borrador del mes en edición. |
| `Programa_Mes.png` | La última imagen generada. |

Para pasar el programa a otra PC copia la carpeta completa.

Exportar / importar el personal en Excel (desde el código):

```bash
python setup_db.py --exportar respaldo.xlsx
python setup_db.py --importar archivo.xlsx
python setup_db.py --historial 2026-11      # ver el historial de un mes
```

---

## 10. Problemas comunes

| Problema | Solución |
|---|---|
| Al abrir dice que no tiene permiso para guardar | La carpeta está en Documentos/Escritorio/OneDrive. Muévela a `C:\ProgramaReuniones\` o permite el `.exe` en *Seguridad de Windows → Protección contra ransomware*. |
| "El navegador no generó la imagen" | Verifica que Chrome o Edge estén instalados. El aviso incluye lo que respondió el navegador; mándalo a quien mantiene el programa. |
| El editor se ve sin estilos | El editor necesita internet para cargar sus estilos (Tailwind). |
| No descarga la guía | Sin internet o aún no publicada. Guarda la página de la semana (Ctrl+S) en `input_html/`. |
| La limpieza sale sin encargados | Configúralos en **👥 Grupos de limpieza**. |
