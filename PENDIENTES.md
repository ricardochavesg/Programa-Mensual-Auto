# Funcionalidades pendientes

## 1. Datos en `%LOCALAPPDATA%` + instalador (para compartir el programa)

**Estado:** pendiente (aprobado como idea, no implementado).

### Problema

Hoy los datos viven junto al `.exe` (`paths.external_path`). Si la carpeta está en
Documentos, Escritorio u OneDrive, la **Protección contra ransomware** de Windows
Defender ("Acceso controlado a carpetas") bloquea la escritura de cada `.exe` nuevo
(cada build cuenta como un programa distinto):

- escribir archivos da `[Errno 2] No such file or directory` aunque la carpeta exista;
- SQLite da `unable to open database file` (leer sí funciona, por eso el catálogo se ve).

Mitigación actual (commit `aade7f5`): `paths.verificar_escritura()` detecta el bloqueo al
arrancar y la ventana explica cómo solucionarlo; la caché de guías es opcional.

`C:\Program Files` **no** es solución: un programa normal tampoco puede escribir ahí.

### Solución propuesta

Separar programa y datos, como hacen las aplicaciones de Windows:

| Qué | Dónde |
|---|---|
| `.exe` (solo lectura) | Cualquier carpeta; con instalador, `C:\Program Files\Programa Reuniones\` |
| Datos: `programa.db`, `fotos/`, `cache_guias/`, `input_html/`, `backups/`, `config.json`, `Programa_Mes.png`, JSON de borrador/programa | `%LOCALAPPDATA%\ProgramaReuniones\` |

`%LOCALAPPDATA%` (AppData\Local) no está protegido por el Acceso controlado a carpetas,
es por usuario de Windows y no se sincroniza con OneDrive.

### Tareas

1. **`paths.external_path`**
   - En modo `.exe` (`sys.frozen`), devolver `%LOCALAPPDATA%\ProgramaReuniones\`.
   - En desarrollo (`python main.py`), seguir usando la carpeta del proyecto.
   - Permitir anularlo con una variable de entorno, por ejemplo `PROGRAMA_REUNIONES_DATOS`, para pruebas y uso portátil.
2. **Migración automática al primer arranque.**
   - Si `%LOCALAPPDATA%\ProgramaReuniones\programa.db` no existe pero hay datos junto al `.exe`, copiar `programa.db`, `Personal_nuevo.xlsx`, `fotos/`, `input_html/`, `cache_guias/`, `backups/` y `config.json`.
   - Copiar, no mover. Avisarlo en el log de la ventana.
3. **Botón "Abrir carpeta de datos"** en `ventana.py`, que llame a `os.startfile(external_path())`.
4. **`build.py`**
   - Dejar de copiar `programa.db` / Excel a `dist/`: los datos ya no van junto al `.exe`.
   - Opcional: un modo `--portable` que mantenga el comportamiento actual.
5. **Instalador (opcional)** con [Inno Setup](https://jrsoftware.org/isinfo.php), que es gratis.
   - Que `build.py` genere `Instalar_Programa_Reuniones.exe` si encuentra `ISCC.exe`.
   - El instalador pone el programa en Program Files y crea accesos directos en el Escritorio y el menú Inicio, más un desinstalador.
   - El desinstalador **no** borra los datos de AppData.
6. **Pruebas**
   - `external_path` en modo frozen (simulando `sys.frozen` y `LOCALAPPDATA`).
   - La migración copia los datos y no sobrescribe una base ya existente en AppData.
7. **Documentación:** actualizar CLAUDE.md (sección *Datos* y *Trampas*) y el README.

### Fuera de alcance

- **Firma de código.** El aviso de SmartScreen ("Windows protegió su PC") en un `.exe` sin firmar se pasa con *Más información → Ejecutar de todas formas*. Quitarlo requiere un certificado de pago.
