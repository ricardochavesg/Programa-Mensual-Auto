# 📅 Gestor y Generador Interactivo de Programas

¡Bienvenido! Esta es una aplicación web moderna y dinámica diseñada para optimizar la **gestión de personal y la asignación interactiva de tareas semanales**. El sistema resuelve problemas complejos de logística interna, permitiendo organizar participantes, detectar conflictos de horarios en tiempo real, balancear cargas de trabajo y exportar el resultado final en imágenes de alta calidad listas para distribución.

La interfaz está construida con una arquitectura limpia basada en **HTML5, Vanilla JavaScript, Jinja2** y estilizada de forma fluida utilizando **Tailwind CSS**.

---

## ✨ Características Principales

* **🧩 Editor Visual Inteligente:** Cambia las asignaciones de tareas con un solo clic sobre la foto del participante. Incluye un buscador integrado por cada selector para agilizar la localización de candidatos.
* **⚠️ Alerta de Duplicados en Tiempo Real:** El sistema valida la consistencia del programa. Si un participante es asignado dos veces en la misma semana, la interfaz resalta visualmente el avatar con un borde rojo y añade una advertencia de duplicado.
* **⚖️ Algoritmo de Sugerencia por Carga:** Al desplegar los selectores, el sistema prioriza automáticamente a los miembros activos y muestra su carga de trabajo acumulada, garantizando una distribución equitativa de las tareas.
* **💾 Gestión de Borradores:** Permite salvar el progreso del estado actual del programa de forma local/servidor sin necesidad de renderizar el archivo definitivo, permitiendo retomar el flujo o descartarlo por completo.
* **📸 Motor de Exportación a Imagen:** Transforma la estructura de datos del programa en una imagen final (`Programa_Mes.png`) optimizada con dimensiones fijas (`1400px`) y estilos CSS puros listos para ser procesados o capturados.
* **🔄 Navegación Fluida & Heartbeat:** Barra superior anclada para transiciones limpias entre módulos y un sistema de *heartbeat* integrado para mantener el estado de la sesión del servidor activo mientras la pestaña esté abierta.

---

## 🛠️ Tecnologías Empleadas

| Tecnología | Uso en el Proyecto |
| :--- | :--- |
| **Tailwind CSS** | Maquetación responsiva, utilidades de diseño modernas, control de estados `hover`, animaciones y capas de modales. |
| **Vanilla JavaScript** | Gestión asíncrona del DOM, validación de reglas de negocio, previsualización de imágenes mediante Base64 y comunicación con el backend vía `Fetch API` (`/api/*`). |
| **Jinja2 Templates** | Inyección dinámica de datos desde el backend, renderizado condicional de componentes estructurales y control de flujos. |

---

## 🧩 Módulos del Sistema

El ecosistema de la interfaz gráfica está modularizado en tres componentes clave:

### 1. Catálogo de Personal (`catalogo.html`)
Panel administrativo centralizado para gestionar la base de datos de los participantes.
* **Filtros Dinámicos:** Segmentación instantánea de la cuadrícula mediante tags o categorías como "Todos", "Hermanos" (H) o "Hermanas" (M).
* **Tarjetas de Información:** Tarjetas visuales que muestran avatares/iniciales, roles habilitados, periodos de ausencia activos y métricas de carga de trabajo.
* **Modal de Edición Avanzada:** Formulario interactivo para registrar nombres, género, vinculación conyugal, subida de imágenes de perfil (Formatos: `JPG`, `PNG`, `WEBP`) y desactivación temporal por ausencias.

### 2. Editor del Programa (`editar.html`)
La mesa de trabajo principal donde se realiza el cruce entre los participantes y el calendario.
* **Matriz Interactiva:** Renderizado en formato de tabla cruzada con semanas en los ejes de las columnas y roles/tareas en las filas.
* **Slots Dinámicos Multi-Persona:** Secciones flexibles que admiten la adición de múltiples personas a una sola asignación mediante controles interactivos de agregar (`+`) o remover (`x`).
* **Asignaciones Especiales:** Selectores customizados para roles logísticos específicos (ej: zonas de "Limpieza" parametrizadas por Norte, Sur y Central).

### 3. Plantilla de Generación (`programa.html`)
El motor de renderizado encargado de dar el formato visual estricto para el output final.
* **Diseño de Alta Fidelidad:** Implementación de CSS estructurado específicamente para ser procesado por herramientas de captura (como `PIL-crop` en backend), asegurando un fondo blanco sólido sin artefactos visuales.
* **Estética Limpia:** Cabeceras con degradados modernos, badges numéricos, avatares circulares minimalistas e insignias verdes para destacar los grupos de logística especial.

---

## 🚀 Instalación, Configuración y Uso

El sistema está diseñado para ser completamente autónomo y fácil de desplegar, automatizando el almacenamiento de datos en segundo plano a través de su interfaz gráfica.

### 1. Clonación e Instalación Local
Descarga el .exe compilado mas reciente o compilalo con el build.py

2. Preparación de Archivos

    Input HTML: Agrega los archivos HTML de las semanas correspondientes en la carpeta de entrada del sistema para que la aplicación pueda procesar y cargar el calendario de asignaciones.

3. Ejecución del Sistema

    Localiza el archivo binario ejecutable en el directorio raíz del proyecto.

    ejecuta el .exe para levantar el servidor local y abrir automáticamente la interfaz de usuario en tu navegador web.

4. Gestión Automática de Personal (Desde la App)

    Cero manipulación manual: Una vez dentro del programa, ve directamente al módulo de Catálogo y agrega a tu personal desde el formulario interactivo. ¡No hace falta editar bases de datos ni arrastrar imágenes de forma externa!

    Base de datos integrada: Todos los participantes que registres, junto con sus nombres, roles y configuraciones se guardarán automáticamente en un archivo .xlsx.

    Almacenamiento de fotos: Las imágenes de perfil cargadas desde el formulario se estructuran solas dentro de la carpeta local /fotos.

        ⚠️ Nota sobre archivos locales: El archivo .xlsx y la carpeta /fotos actúan estrictamente como el respaldo local y persistencia de datos del sistema. No es necesario manipularlos manualmente en ningún momento; la aplicación lee y escribe en ellos de forma transparente a través del ejecutable.
