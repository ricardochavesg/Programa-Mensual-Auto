"""
ventana.py
Ventana de control del programa (aparece en la barra de tareas).

  · "Abrir Editor Web"  → abre http://127.0.0.1:<puerto>/editar en el navegador.
  · "Cerrar programa"   → detiene el servidor y sale.

El servidor vive mientras la ventana esté abierta: cerrar el navegador ya no
apaga el programa (antes se cerraba solo, a veces a mitad de un análisis).
La ventana muestra además la actividad (lo que antes salía en la consola),
útil en el .exe, que no tiene consola.
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
import webbrowser
from typing import Callable

import tkinter as tk
from tkinter import messagebox, scrolledtext

TITULO = "Programa Reuniones"


class _SalidaVentana:
    """Reemplazo de sys.stdout: manda el texto a la ventana (y a la consola si existe)."""

    def __init__(self, cola: queue.Queue, original):
        self._cola = cola
        self._original = original

    def write(self, texto: str) -> int:
        self._cola.put(texto)
        if self._original is not None:
            try:
                self._original.write(texto)
            except Exception:
                pass
        return len(texto)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass


def ejecutar(puerto: int, preparar: Callable[[], object]) -> None:
    """
    Muestra la ventana de control y arranca el servidor en segundo plano.
    `preparar()` inicializa el entorno y devuelve la app WSGI (Flask).
    """
    from werkzeug.serving import make_server

    url = f"http://127.0.0.1:{puerto}/editar"

    root = tk.Tk()
    root.title(TITULO)
    root.geometry("560x380")
    root.minsize(420, 260)

    # ── Cabecera y botones ────────────────────────────────────────────────────
    marco = tk.Frame(root, padx=16, pady=12)
    marco.pack(fill="x")
    tk.Label(marco, text=TITULO.upper(), font=("Segoe UI", 14, "bold")).pack(anchor="w")
    estado = tk.Label(marco, text="Iniciando...", fg="#64748b", font=("Segoe UI", 9))
    estado.pack(anchor="w", pady=(0, 10))

    botones = tk.Frame(marco)
    botones.pack(fill="x")

    def abrir_editor() -> None:
        webbrowser.open_new_tab(url)

    servidor = {"srv": None}

    def cerrar() -> None:
        if not messagebox.askokcancel(TITULO, "¿Cerrar el programa?\n"
                                      "El editor web dejará de funcionar."):
            return
        if servidor["srv"] is not None:
            threading.Thread(target=servidor["srv"].shutdown, daemon=True).start()
        root.destroy()

    btn_abrir = tk.Button(botones, text="Abrir Editor Web", command=abrir_editor,
                          bg="#2563eb", fg="white", activebackground="#1d4ed8",
                          activeforeground="white", font=("Segoe UI", 11, "bold"),
                          relief="flat", padx=16, pady=8, state="disabled")
    btn_abrir.pack(side="left", expand=True, fill="x", padx=(0, 6))
    tk.Button(botones, text="Cerrar programa", command=cerrar,
              bg="#e2e8f0", activebackground="#cbd5e1", font=("Segoe UI", 11),
              relief="flat", padx=16, pady=8).pack(side="left", expand=True, fill="x", padx=(6, 0))
    root.protocol("WM_DELETE_WINDOW", cerrar)

    # ── Registro de actividad ─────────────────────────────────────────────────
    tk.Label(root, text="Actividad", anchor="w", padx=16,
             font=("Segoe UI", 9, "bold")).pack(fill="x")
    log = scrolledtext.ScrolledText(root, height=12, font=("Consolas", 9),
                                    state="disabled", wrap="word")
    log.pack(fill="both", expand=True, padx=16, pady=(2, 16))

    cola: queue.Queue = queue.Queue()
    sys.stdout = _SalidaVentana(cola, sys.stdout)

    def volcar_log() -> None:
        partes = []
        while not cola.empty():
            partes.append(cola.get_nowait())
        if partes:
            log.configure(state="normal")
            log.insert("end", "".join(partes))
            # Limitar a ~2000 líneas para no crecer sin fin
            if int(log.index("end-1c").split(".")[0]) > 2000:
                log.delete("1.0", "500.0")
            log.see("end")
            log.configure(state="disabled")
        root.after(200, volcar_log)

    volcar_log()

    # ── Servidor ──────────────────────────────────────────────────────────────
    try:
        app = preparar()
        try:
            servidor["srv"] = make_server("127.0.0.1", puerto, app, threaded=True)
        except OSError:
            # Puerto ocupado: lo más probable es que el programa ya esté abierto
            messagebox.showinfo(TITULO, "El programa ya está abierto.\nSe abrirá el editor web.")
            abrir_editor()
            root.destroy()
            return
    except Exception:
        # Error al preparar datos (permisos, disco lleno, base dañada…)
        print(traceback.format_exc())
        estado.configure(text="Error al iniciar. Revisa la actividad.", fg="#dc2626")
        messagebox.showerror(TITULO, "No se pudo iniciar el programa.\n"
                                     "Revisa el detalle en la ventana.")
        root.mainloop()
        return

    threading.Thread(target=servidor["srv"].serve_forever, daemon=True).start()
    print(f"Servidor iniciado → {url}")
    estado.configure(text=f"Activo en {url}", fg="#15803d")
    btn_abrir.configure(state="normal")
    root.after(800, abrir_editor)

    root.mainloop()
