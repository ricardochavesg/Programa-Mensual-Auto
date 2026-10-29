# 📅 Weekly Schedule Manager

A desktop web app I built to automate a 4-hour manual task down to 15 minutes.
It downloads the weekly meeting guide, assigns people to every part and
logistics role, lets you fine-tune everything in a visual editor, and exports
a print-ready image — all from a clean interface.

> 📖 **User guide (Spanish):** [MANUAL.md](MANUAL.md)

---

## ✨ Features

### Scheduling engine
- **Automatic Guide Download** — pick a month and each week's meeting guide is fetched
  from wol.jw.org, falling back to the bimonthly workbook on jw.org (cached in
  `cache_guias/`; files in `input_html/` take priority)
- **Smart Assignment** — fair load balancing, no repeating last month's role, a rest week
  after having a part, scarce roles (e.g. Chairman) filled first, and a guaranteed fill
  that relaxes rules step by step (absences and inactive members are never relaxed)
- **Split Workloads** — midweek and weekend meetings have separate pools and counters
- **Pairs Logic** — student parts prefer sisters, avoid repeating partners in the month,
  and allow one married-couple / brothers pair per month
- **Monthly History (SQLite)** — every final schedule is stored per week in `programa.db`,
  so next month continues the rotation across month boundaries

### Visual editor
- **One-click Reassignment** — searchable selectors filtered by role and sorted by workload
- **Duplicate Detection** — real-time red highlight when someone is double-booked
- **Draft Saving** — save progress and come back later
- **Configurable Meeting Days** — choose the midweek day (Mon–Fri) and weekend day (Sat/Sun);
  the weekend date is shown on its section row
- **Assembly Weeks** — one click blanks the whole week with a vertical "ASAMBLEA" banner;
  nobody is assigned and it's left out of the history
- **Circuit Overseer Visit** — moves that week's midweek meeting to Tuesday and tints the
  column pastel orange with a "VISITA" tag
- **Cleaning Rotation** — light (midweek) and deep (weekend) cleaning rows; groups rotate
  weekly and their two leaders alternate each cycle; editable groups, auto-filled leaders
  when you change a group, and free-text special cleanings (annual, monthly…)

### Output & insights
- **Image Export** — 2880 px PNG (2× retina) sized for letter paper, with a selectable
  header color; rendered with headless Chrome/Edge and clear error messages if capture fails
- **Statistics Panel** — parts per person and type over any period; distinguishes
  "not applicable" from zero, with sortable columns and filters
- **Desktop Control Window** — small tkinter window with an activity log; the server lives
  while the window is open
- **Windows-friendly** — detects folders blocked by ransomware protection and explains
  the fix; automatic database backups on every export

---

## 🛠️ Built With

| Technology | Role |
|---|---|
| Python + Flask | Local server, REST endpoints, assignment engine |
| SQLite | Staff catalog and assignment history |
| BeautifulSoup / lxml | Parsing the weekly meeting guide |
| Jinja2 | Templates for the editor and the print layout |
| Tailwind CSS | Responsive layout, modals, animations |
| Vanilla JavaScript | Editor logic, validation, Fetch API |
| Headless Chrome / Edge + Pillow | PNG capture and whitespace cropping |
| tkinter + PyInstaller | Desktop window and single-file `.exe` |
| pytest | 46 end-to-end tests (no internet or browser needed) |

---

## 🧩 Modules

1. **Staff Catalog** (`catalogo.html`) — manage personnel: roles, gender, spouse,
   avatars, temporary absences and active status.
2. **Schedule Editor** (`editar.html`) — interactive matrix of weeks × parts with
   multi-person slots, logistics, cleaning, assembly and visit weeks.
3. **Statistics** (`estadisticas.html`) — workload per person and part type.
4. **Output Template** (`programa.html`) — high-fidelity print layout: gradient header,
   circular avatars, section colors.

---

## 🚀 Getting Started

1. Download the latest `.exe` from Releases, or build it on Windows with `python build.py`
2. Put it in its own folder (e.g. `C:\ProgramaReuniones\`, not Documents/OneDrive) and run it
3. Click **Abrir Editor Web** — the UI opens in your browser
4. Add your staff in **Catálogo** and set up **Grupos de limpieza** once
5. In **Editar**, pick a month, adjust, and click **Generar Imagen Final**

From source:

```bash
pip install -r requirements.txt
python main.py               # control window + editor at http://127.0.0.1:5000/editar
python -m pytest tests -q    # test suite
```

> All data (staff, history, photos, settings) lives next to the `.exe` in `programa.db`,
> `fotos/` and `config.json`. An existing `Personal_nuevo.xlsx` is imported on first launch;
> `python setup_db.py --exportar respaldo.xlsx` exports the staff catalog to Excel.
