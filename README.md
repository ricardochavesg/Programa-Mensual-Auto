# 📅 Weekly Schedule Manager

A web app I built to automate a 4-hour manual task down to 15 minutes.
Handles staff scheduling, conflict detection, workload balancing,
and exports a print-ready image — all from a clean visual interface.

---

## ✨ Features

- **Visual Editor** — reassign tasks with a single click; built-in search on every selector
- **Duplicate Detection** — flags conflicts in real time with a red highlight if someone is double-booked
- **Workload Balancing** — selectors auto-prioritize members with the lowest accumulated workload
- **Draft Saving** — save progress locally without generating the final output
- **Image Export** — renders the final schedule as a 1400px PNG ready for distribution
- **Session Heartbeat** — keeps the server session alive while the tab is open
- **Automatic Guide Download** — pick a month and the weekly meeting guide is fetched
  from wol.jw.org (cached in `cache_guias/`; files in `input_html/` still take priority)
- **Monthly History (SQLite)** — every final schedule is saved per week/month in
  `programa.db`, so the next month avoids repeating the same people and roles
- **Split Workloads** — midweek and weekend meetings have separate load counters;
  weekend logistics may repeat people who already have a midweek part

---

## 🛠️ Built With

| Technology | Role |
| :--- | :--- |
| **Tailwind CSS** | Responsive layout, modals, animations |
| **Vanilla JavaScript** | DOM logic, validation, Base64 image preview, Fetch API |
| **Jinja2** | Dynamic data injection and conditional rendering |

---

## 🧩 Modules

**1. Staff Catalog** (`catalogo.html`)
Manage your personnel database — filter by role/category, edit profiles,
upload avatars, and set temporary absences.

**2. Schedule Editor** (`editar.html`)
Cross-reference participants with a weekly calendar via an interactive matrix.
Supports multi-person slots and custom logistics roles.

**3. Output Template** (`programa.html`)
High-fidelity render layer optimized for backend image capture (`PIL-crop`).
Clean white background, gradient headers, circular avatars.

---

## 🚀 Getting Started

1. Download the latest compiled `.exe` from Releases (or build with `build.py`)
2. Run the `.exe` — it starts a local server and opens the UI in your browser
3. Go to **Catalog** and add your staff directly from the form
4. Open **Editor**, build the weekly schedule, and export your PNG

> All data (staff info, history, photos) is managed automatically in `programa.db`
> and `/fotos`. An existing `Personal_nuevo.xlsx` is imported on first launch.
> `python setup_db.py --exportar respaldo.xlsx` exports the staff catalog to Excel.
