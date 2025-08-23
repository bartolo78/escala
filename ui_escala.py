import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkcalendar import Calendar, DateEntry
from calendar import month_name, monthrange, day_name
from datetime import datetime, timedelta, date
import tkinter.font as tkfont
import csv
import json  # For potential saves
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# Import from logic_g4.py (adjust path if needed)
from logic_g4 import generate_schedule, update_history, _compute_past_stats
from utils import Tooltip, compute_holidays, easter_date
from constants import EQUITY_WEIGHTS, DOW_EQUITY_WEIGHT, EQUITY_STATS

class WorkerTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding="10")
        self.app = app
        self.build_ui()

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Select Worker:", font=self.app.heading_font).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.app.worker_combo = ttk.Combobox(self, textvariable=self.app.worker_var,
                                             values=[w['name'] for w in self.app.workers], state="readonly")
        self.app.worker_combo.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.app.worker_combo.bind("<<ComboboxSelected>>", self.app.update_worker_stats)
        Tooltip(self.app.worker_combo, "Select a worker to view stats and manage availability")

        add_worker_btn = ttk.Button(self, text="Add Worker", command=self.app.add_worker)
        add_worker_btn.grid(row=0, column=2, padx=10, pady=5)
        Tooltip(add_worker_btn, "Add a new worker")

        remove_worker_btn = ttk.Button(self, text="Remove Worker", command=self.app.remove_worker)
        remove_worker_btn.grid(row=0, column=3, padx=10, pady=5)
        Tooltip(remove_worker_btn, "Remove the selected worker")

        stats_frame = ttk.LabelFrame(self, text="Shift Statistics", padding="10")
        stats_frame.grid(row=1, column=0, columnspan=2, pady=10, sticky="nsew")

        self.app.stats_labels = {}
        stats = ["Total Hours", "Weekend Shifts", "Night Shifts"]
        for i, stat in enumerate(stats):
            ttk.Label(stats_frame, text=f"{stat}:").grid(row=i, column=0, sticky="w", padx=10, pady=5)
            self.app.stats_labels[stat] = ttk.Label(stats_frame, text="0")
            self.app.stats_labels[stat].grid(row=i, column=1, sticky="w", padx=10, pady=5)

        unavailable_frame = ttk.LabelFrame(self, text="Unavailable Shifts", padding="10")
        unavailable_frame.grid(row=2, column=0, columnspan=2, pady=10, sticky="nsew")
        unavailable_frame.rowconfigure(0, weight=1)
        unavailable_frame.columnconfigure(0, weight=1)

        self.app.unavailable_list = tk.Listbox(unavailable_frame, height=5, font=self.app.body_font)
        self.app.unavailable_list.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=5)

        add_unavail_btn = ttk.Button(unavailable_frame, text="Add Unavailable Shift",
                                     command=lambda: self.app.add_shift_availability("unavailable"))
        add_unavail_btn.grid(row=1, column=0, padx=10, pady=5)
        Tooltip(add_unavail_btn, "Open calendar to select a day and unavailable shifts (optional)")

        remove_unavail_btn = ttk.Button(unavailable_frame, text="Remove Selected",
                                        command=lambda: self.app.remove_shift_availability(self.app.unavailable_list, "unavailable"))
        remove_unavail_btn.grid(row=1, column=1, padx=10, pady=5)
        Tooltip(remove_unavail_btn, "Remove the selected unavailable shift")

        required_frame = ttk.LabelFrame(self, text="Required Shifts", padding="10")
        required_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky="nsew")
        required_frame.rowconfigure(0, weight=1)
        required_frame.columnconfigure(0, weight=1)

        self.app.required_list = tk.Listbox(required_frame, height=5, font=self.app.body_font)
        self.app.required_list.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=5)

        add_req_btn = ttk.Button(required_frame, text="Add Required Shift",
                                 command=lambda: self.app.add_shift_availability("required"))
        add_req_btn.grid(row=1, column=0, padx=10, pady=5)
        Tooltip(add_req_btn, "Open calendar to select a day and required shifts (optional)")

        remove_req_btn = ttk.Button(required_frame, text="Remove Selected",
                                    command=lambda: self.app.remove_shift_availability(self.app.required_list, "required"))
        remove_req_btn.grid(row=1, column=1, padx=10, pady=5)
        Tooltip(remove_req_btn, "Remove the selected required shift")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=2)
        self.rowconfigure(3, weight=2)


class ScheduleTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding="10")
        self.app = app
        self.build_ui()

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.app.schedule_tree = ttk.Treeview(self, show="headings")
        self.app.schedule_tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.app.schedule_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.app.schedule_tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")

        self.app.schedule_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.app.update_schedule_columns()

        self.app.schedule_tree.bind("<Double-1>", self.app.edit_shift)

        save_btn = ttk.Button(self, text="Save Manual Changes", command=self.app.save_manual_changes)
        save_btn.grid(row=2, column=0, pady=10, sticky="ew")
        Tooltip(save_btn, "Save any manual edits to the schedule")

        def resize_treeview(event):
            width = self.app.schedule_tree.winfo_width() // 4  # Divide equally among 4 columns
            for col in self.app.schedule_tree["columns"]:
                self.app.schedule_tree.column(col, width=width)

        self.app.root.bind("<Configure>", resize_treeview)

class ReportsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding="10")
        self.app = app
        self.build_ui()

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.app.reports_tree = ttk.Treeview(self, show="headings")
        self.app.reports_tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.app.reports_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.app.reports_tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")

        self.app.reports_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        generate_report_btn = ttk.Button(self, text="Generate Report", command=self.app.generate_report)
        generate_report_btn.grid(row=2, column=0, pady=10, sticky="ew")

        # Add dashboard
        dashboard_frame = ttk.LabelFrame(self, text="Fairness Dashboard", padding="10")
        dashboard_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky="nsew")
        dashboard_frame.columnconfigure(0, weight=1)
        dashboard_frame.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(10, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=dashboard_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding="10")
        self.app = app
        self.build_ui()

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(self, text="Equity Weights Adjustment", font=self.app.heading_font).pack(pady=10)

        for stat, weight in self.app.equity_weights.items():
            frame = ttk.Frame(self)
            frame.pack(fill="x", pady=5)
            ttk.Label(frame, text=stat.capitalize().replace('_', ' '), width=20).pack(side="left", padx=10)
            scale = ttk.Scale(frame, from_=0, to=500, orient="horizontal", value=weight,
                              command=lambda v, s=stat: self.update_weight(s, float(v)))
            scale.pack(side="left", fill="x", expand=True, padx=10)
            value_label = ttk.Label(frame, text=f"{weight:.1f}")
            value_label.pack(side="left", padx=10)
            scale.bind("<Motion>", lambda e, vl=value_label: vl.config(text=f"{scale.get():.1f}"))

        dow_frame = ttk.Frame(self)
        dow_frame.pack(fill="x", pady=5)
        ttk.Label(dow_frame, text="Day of Week Equity", width=20).pack(side="left", padx=10)
        self.dow_scale = ttk.Scale(dow_frame, from_=0, to=10, orient="horizontal", value=self.app.dow_equity_weight,
                                   command=lambda v: setattr(self.app, 'dow_equity_weight', float(v)))
        self.dow_scale.pack(side="left", fill="x", expand=True, padx=10)
        dow_value_label = ttk.Label(dow_frame, text=f"{self.app.dow_equity_weight:.1f}")
        dow_value_label.pack(side="left", padx=10)
        self.dow_scale.bind("<Motion>", lambda e: dow_value_label.config(text=f"{self.dow_scale.get():.1f}"))

    def update_weight(self, stat, value):
        self.app.equity_weights[stat] = value

class ShiftSchedulerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Shift Scheduler")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        self.setup_fonts_and_styles()
        self.setup_data()

        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.create_menu()
        self.create_control_frame()
        self.create_tabbed_content()
        self.update_schedule_columns()
        self.setup_status_and_progress()
        self.update_holidays_display()  # Moved after control_frame to ensure holidays_var exists
        self.ask_load_historic_data()

    def setup_fonts_and_styles(self):
        self.heading_font = tkfont.Font(family="Arial", size=12, weight="bold")
        self.body_font = tkfont.Font(family="Arial", size=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=25, font=self.body_font)
        style.configure("Treeview.Heading", font=self.heading_font)
        style.map("Treeview", background=[("selected", "#d3d3d3")])
        style.configure("TLabel", font=self.body_font)
        style.configure("TButton", font=self.body_font)
        style.configure("TCombobox", font=self.body_font)
        style.configure("TFrame", padding=10)

    def setup_data(self):
        self.manual_holidays = []
        self.workers = [
            {"name": "Tome", "id": "ID001", "color": "#ff0000", "can_night": True, "weekly_load": 12},
            {"name": "Rosa", "id": "ID002", "color": "#ff5400", "can_night": True, "weekly_load": 18},
            {"name": "Lucas", "id": "ID003", "color": "#ffaa00", "can_night": True, "weekly_load": 18},
            {"name": "Bartolo", "id": "ID004", "color": "#ffff00", "can_night": True, "weekly_load": 18},
            {"name": "Gilberto", "id": "ID005", "color": "#aaff00", "can_night": True, "weekly_load": 18},
            {"name": "Pego", "id": "ID006", "color": "#ff0055", "can_night": True, "weekly_load": 18},
            {"name": "Celeste", "id": "ID007", "color": "#00ff55", "can_night": True, "weekly_load": 12},
            {"name": "Sofia", "id": "ID008", "color": "#00ffa9", "can_night": True, "weekly_load": 18},
            {"name": "Lucilia", "id": "ID009", "color": "#00ffff", "can_night": True, "weekly_load": 12},
            {"name": "Teresa", "id": "ID010", "color": "#00a9ff", "can_night": True, "weekly_load": 18},
            {"name": "Fernando", "id": "ID011", "color": "#0054ff", "can_night": False, "weekly_load": 12},
            {"name": "Rosario", "id": "ID012", "color": "#0000ff", "can_night": True, "weekly_load": 12},
            {"name": "Nuno", "id": "ID013", "color": "#5400ff", "can_night": True, "weekly_load": 18},
            {"name": "Filomena", "id": "ID014", "color": "#aa00ff", "can_night": False, "weekly_load": 12},
            {"name": "Angela", "id": "ID015", "color": "#ff00ff", "can_night": True, "weekly_load": 18}
        ]
        self.unavail = {w['name']: [] for w in self.workers}
        self.req = {w['name']: [] for w in self.workers}
        self.history = {}
        self.worker_var = tk.StringVar()
        self.stats_labels = {}
        self.unavailable_list = None
        self.required_list = None
        self.schedule_tree = None
        self.reports_tree = None
        self.holidays_var = None  # Initialize to None
        self.equity_weights = EQUITY_WEIGHTS.copy()
        self.dow_equity_weight = DOW_EQUITY_WEIGHT
        self.thresholds = {
            'weekend_shifts': 2,
            'sat_shifts': 1,
            'sun_shifts': 1,
            'weekend_day': 3,
            'weekend_night': 1,
            'weekday_day': 5,
            'weekday_night': 2,
            'total_night': 2,
            'fri_night': 1
        }
        self.current_stats_computed = None
        self.past_stats = None

    def setup_status_and_progress(self):
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w", padding=5)
        status_bar.grid(row=1, column=0, sticky="ew")

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew")
        self.progress.grid_remove()

    def create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Historic Data", command=self.load_historic_data)
        file_menu.add_command(label="Import Workers", command=self.import_workers)
        file_menu.add_command(label="Import Holidays", command=self.import_holidays)
        file_menu.add_command(label="Save Schedule", command=self.save_schedule)
        file_menu.add_command(label="Export Schedule", command=self.export_schedule)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

    def create_control_frame(self):
        control_frame = ttk.LabelFrame(self.main_frame, text="Schedule Controls", padding="10")
        control_frame.grid(row=0, column=0, sticky="ew", pady=10)
        self.main_frame.columnconfigure(0, weight=1)

        ttk.Label(control_frame, text="Month:").grid(row=0, column=0, padx=10, pady=5)
        self.month_var = tk.StringVar()
        month_combo = ttk.Combobox(control_frame, textvariable=self.month_var,
                                   values=list(month_name)[1:], state="readonly")
        month_combo.grid(row=0, column=1, padx=10, pady=5)
        month_combo.set(datetime.now().strftime("%B"))
        Tooltip(month_combo, "Select the month for the schedule")

        ttk.Label(control_frame, text="Year:").grid(row=0, column=2, padx=10, pady=5)
        current_year = datetime.now().year
        self.year_var = tk.IntVar(value=current_year)
        year_spin = ttk.Spinbox(control_frame, from_=current_year - 5, to=current_year + 5,
                                textvariable=self.year_var, state="readonly")
        year_spin.grid(row=0, column=3, padx=10, pady=5)
        Tooltip(year_spin, "Select or increment the year")

        self.month_var.trace("w", lambda *args: self.update_holidays_display())
        self.year_var.trace("w", lambda *args: self.update_holidays_display())

        generate_btn = ttk.Button(control_frame, text="Generate Schedule",
                                  command=self.generate_schedule_wrapper)
        generate_btn.grid(row=0, column=4, padx=10, pady=5)
        Tooltip(generate_btn, "Generate the shift schedule for the selected month")

        # Add Today button
        today_btn = ttk.Button(control_frame, text="Today", command=self.set_today)
        today_btn.grid(row=0, column=5, padx=10, pady=5)
        Tooltip(today_btn, "Reset to current month and year")

        # Add manual holiday button
        add_holiday_btn = ttk.Button(control_frame, text="Add Holiday", command=self.add_manual_holiday)
        add_holiday_btn.grid(row=0, column=6, padx=10, pady=5)
        Tooltip(add_holiday_btn, "Add a manual holiday for the selected month")

        # Holidays display
        ttk.Label(control_frame, text="Holidays:").grid(row=1, column=0, padx=10, pady=5)
        self.holidays_var = tk.StringVar()
        ttk.Label(control_frame, textvariable=self.holidays_var).grid(row=1, column=1, columnspan=3, sticky="w", padx=10, pady=5)

    def create_tabbed_content(self):
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.main_frame.rowconfigure(1, weight=1)

        self.notebook.add(WorkerTab(self.notebook, self), text="Workers")
        self.notebook.add(ScheduleTab(self.notebook, self), text="Schedule")
        self.notebook.add(ReportsTab(self.notebook, self), text="Reports")
        self.notebook.add(SettingsTab(self.notebook, self), text="Settings")

    def generate_schedule_wrapper(self):
        try:
            month = list(month_name).index(self.month_var.get())
            year = self.year_var.get()
        except ValueError:
            messagebox.showerror("Error", "Invalid month or year")
            return

        auto_holidays = compute_holidays(year, month)
        all_holidays = sorted(set(auto_holidays + self.manual_holidays))

        self.progress.grid()
        self.progress.start()
        self.status_var.set("Generating schedule...")

        self.root.after(100, lambda: self._run_generate_schedule(year, month, all_holidays))

    def _run_generate_schedule(self, year, month, all_holidays):
        schedule, weekly, assignments, stats, self.current_stats_computed = generate_schedule(
            year, month, self.unavail, self.req, self.history, self.workers, holidays=all_holidays,
            equity_weights=self.equity_weights, dow_equity_weight=self.dow_equity_weight
        )

        self.past_stats = _compute_past_stats(self.history, self.workers)

        self.progress.stop()
        self.progress.grid_remove()
        self.status_var.set("Schedule generated")

        if schedule:
            self.update_schedule_display(schedule, all_holidays)
            self.check_imbalances()
            self.generate_report()
        else:
            messagebox.showerror("Error", "No feasible schedule found")

        if assignments:
            self.history = update_history(assignments, self.history)

    def check_imbalances(self):
        alerts = []
        workers_names = [w['name'] for w in self.workers]
        for stat in EQUITY_STATS:
            totals = [self.past_stats[workers_names[i]][stat] + self.current_stats_computed[stat][i] for i in range(len(self.workers))]
            imb = max(totals) - min(totals) if totals else 0
            threshold = self.thresholds.get(stat, 5)
            if imb > threshold:
                alerts.append(f"{stat}: imbalance {imb} > {threshold}")
        if alerts:
            messagebox.showwarning("Fairness Alert", "\n".join(alerts))

    def update_worker_stats(self, event=None):
        worker = self.worker_var.get()
        if not worker:
            return

        total_hours = 0
        weekend_shifts = 0
        night_shifts = 0

        if worker in self.history:
            for my in self.history[worker]:
                try:
                    year, month = map(int, my.split('-'))
                except ValueError:
                    continue
                holidays = set(compute_holidays(year, month))
                for ass in self.history[worker][my]:
                    try:
                        d = datetime.fromisoformat(ass['date'])
                        total_hours += ass.get('dur', 0)
                        if ass['shift'] == 'N':
                            night_shifts += 1
                        weekday = d.weekday()
                        day = d.day
                        if weekday >= 5 or day in holidays:
                            weekend_shifts += 1
                    except (ValueError, KeyError):
                        continue

        self.stats_labels["Total Hours"].config(text=total_hours)
        self.stats_labels["Weekend Shifts"].config(text=weekend_shifts)
        self.stats_labels["Night Shifts"].config(text=night_shifts)

        self.unavailable_list.delete(0, tk.END)
        for item in self.unavail.get(worker, []):
            self.unavailable_list.insert(tk.END, item)

        self.required_list.delete(0, tk.END)
        for item in self.req.get(worker, []):
            self.required_list.insert(tk.END, item)

    def generate_report(self):
        self.reports_tree.delete(*self.reports_tree.get_children())
        columns = ("Worker", "Total Hours", "Day Shifts", "Night Shifts", "Weekend+Holiday Shifts", "Sat Night", "Sat Day", "Sun+Holiday Night", "Sun+Holiday Day", "Fri Night")
        self.reports_tree["columns"] = columns
        for col in columns:
            self.reports_tree.heading(col, text=col)
            self.reports_tree.column(col, anchor="center")
        # Compute the maximum date in history
        all_dates = []
        for worker_hist in self.history.values():
            for month_assignments in worker_hist.values():
                for ass in month_assignments:
                    if 'date' in ass:
                        all_dates.append(date.fromisoformat(ass['date']))

        if all_dates:
            current_date = max(all_dates)
            last_iso = current_date.isocalendar()  # (year, week, weekday)
            monday_last = current_date - timedelta(days=last_iso[2] - 1)
            start_date = monday_last - timedelta(weeks=52)
        else:
            current_date = date.today()
            start_date = current_date - timedelta(weeks=52)
        for worker in sorted(w['name'] for w in self.workers):
            total_hours = 0
            day_shifts = 0
            night_shifts = 0
            weekend_holiday_shifts = 0
            sat_night = 0
            sat_day = 0
            sun_hol_night = 0
            sun_hol_day = 0
            fri_night = 0
            if worker in self.history:
                for my in self.history[worker]:
                    try:
                        y, m = map(int, my.split('-'))
                    except:
                        continue
                    holidays = set(compute_holidays(y, m))
                    for ass in self.history[worker][my]:
                        ass_date_str = ass.get('date')
                        if not ass_date_str:
                            continue
                        ass_date = datetime.fromisoformat(ass_date_str).date()
                        if ass_date < start_date or ass_date > current_date:
                            continue
                        shift = ass['shift']
                        dur = ass.get('dur', 0)
                        total_hours += dur
                        weekday = ass_date.weekday()
                        is_holiday = ass_date.day in holidays
                        is_weekend_hol = (weekday >= 5 or is_holiday)
                        is_day = shift in ['M1', 'M2']
                        is_night = shift == 'N'
                        if is_day:
                            day_shifts += 1
                        if is_night:
                            night_shifts += 1
                        if is_weekend_hol:
                            weekend_holiday_shifts += 1
                        if weekday == 5:
                            if is_night:
                                sat_night += 1
                            if is_day:
                                sat_day += 1
                        if weekday == 6 or is_holiday:
                            if is_night:
                                sun_hol_night += 1
                            if is_day:
                                sun_hol_day += 1
                        if weekday == 4 and is_night:
                            fri_night += 1
            self.reports_tree.insert("", "end", values=(worker, total_hours, day_shifts, night_shifts, weekend_holiday_shifts, sat_night, sat_day, sun_hol_night, sun_hol_day, fri_night))
        self.update_dashboard()

    def update_dashboard(self):
        if self.current_stats_computed is None or self.past_stats is None:
            return

        workers_names = [w['name'] for w in self.workers]
        fig = self.notebook.nametowidget(self.notebook.tabs()[2]).figure  # Get figure from ReportsTab
        fig.clear()

        rows, cols = 3, 3  # For 9 stats
        for idx, stat in enumerate(EQUITY_STATS):
            ax = fig.add_subplot(rows, cols, idx + 1)
            totals = [self.past_stats[workers_names[i]][stat] + self.current_stats_computed[stat][i] for i in range(len(workers_names))]
            ax.bar(workers_names, totals, color='skyblue')
            ax.set_title(stat.replace('_', ' ').title())
            ax.tick_params(axis='x', rotation=45)
            imbalance = max(totals) - min(totals) if totals else 0
            threshold = self.thresholds.get(stat, 5)
            if imbalance > threshold:
                ax.set_facecolor('lightcoral')
            ax.set_ylabel('Count')

        fig.tight_layout()
        self.notebook.nametowidget(self.notebook.tabs()[2]).canvas.draw()

    def update_holidays_display(self):
        try:
            month = list(month_name).index(self.month_var.get())
            year = self.year_var.get()
            auto_holidays = compute_holidays(year, month)
            all_holidays = sorted(set(auto_holidays + self.manual_holidays))
            if all_holidays:
                display = ", ".join(map(str, all_holidays))
            else:
                display = "None"
            self.holidays_var.set(display)
        except (ValueError, TypeError):
            self.holidays_var.set("Invalid month/year")

    # Placeholder methods for completeness (based on truncated code)
    def ask_load_historic_data(self):
        if messagebox.askyesno("Load Historic Data", "Do you want to load historic schedule data from a file?"):
            self.load_historic_data()

    def load_historic_data(self):
        file_path = filedialog.askopenfilename(
            title="Load Historic Data",
            filetypes=[("JSON files", "*.json")],
            defaultextension=".json"
        )
        if not file_path:
            return  # User canceled

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_history = json.load(f)

            # Merge loaded data into self.history (avoid overwriting existing)
            for worker, worker_data in loaded_history.items():
                if worker not in self.history:
                    self.history[worker] = {}
                for month_year, assignments in worker_data.items():
                    if month_year not in self.history[worker]:
                        self.history[worker][month_year] = []
                    # Append assignments, avoiding duplicates by date/shift
                    existing_dates_shifts = {(ass['date'], ass['shift']) for ass in self.history[worker][month_year]}
                    for ass in assignments:
                        if (ass['date'], ass['shift']) not in existing_dates_shifts:
                            self.history[worker][month_year].append(ass)

            self.status_var.set("Historic data loaded successfully")
            self.update_worker_stats()  # Refresh UI if needed
            self.generate_report()  # Optional: Refresh reports
        except json.JSONDecodeError:
            messagebox.showerror("Error", "Invalid JSON file format")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {str(e)}")

    def save_schedule(self):
        if not self.history:
            messagebox.showwarning("Warning", "No schedule data to save")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save Schedule",
            filetypes=[("JSON files", "*.json")],
            defaultextension=".json",
            initialfile=f"schedule_history_{datetime.now().strftime('%Y%m%d')}.json"
        )
        if not file_path:
            return  # User canceled

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=4, default=str)  # default=str handles any non-serializable types
            self.status_var.set("Schedule saved successfully")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {str(e)}")

    def import_workers(self):
        file = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file:
            with open(file, 'r') as f:
                reader = csv.reader(f)
                new_names = [row[0] for row in reader if row]
            for name in new_names:
                if not any(w['name'] == name for w in self.workers):
                    next_num = max((int(w['id'][2:]) for w in self.workers), default=0) + 1
                    new_id = f"ID{next_num:03d}"
                    new_worker = {
                        "name": name,
                        "id": new_id,
                        "color": "#000000",  # Default color: black
                        "can_night": True,  # Adapted
                        "weekly_load": 18  # Adapted
                    }
                    self.workers.append(new_worker)
                    self.unavail[name] = []
                    self.req[name] = []
            self.update_worker_combo()
            self.status_var.set("Workers imported")

    def import_holidays(self):
        file = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file:
            with open(file, 'r') as f:
                reader = csv.reader(f)
                self.manual_holidays = [int(row[0]) for row in reader if row]
            self.update_schedule_columns()  # Refresh
            self.update_holidays_display()
            self.status_var.set("Holidays imported")

    def export_schedule(self):
        formats = [("PDF", ".pdf"), ("Excel", ".xlsx"), ("CSV", ".csv")]
        file = filedialog.asksaveasfilename(filetypes=formats)
        if file:
            ext = file.split('.')[-1]
            if ext == 'pdf':
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(file, pagesize=letter)
                c.drawString(100, 750, "Schedule Export")
                y = 700
                for item in self.schedule_tree.get_children():
                    values = self.schedule_tree.item(item, "values")
                    c.drawString(100, y, ' | '.join(values))
                    y -= 20
                c.save()
            elif ext == 'xlsx':
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.append(self.schedule_tree["columns"])
                for item in self.schedule_tree.get_children():
                    ws.append(self.schedule_tree.item(item, "values"))
                wb.save(file)
            elif ext == 'csv':
                import csv
                with open(file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.schedule_tree["columns"])
                    for item in self.schedule_tree.get_children():
                        writer.writerow(self.schedule_tree.item(item, "values"))
            self.status_var.set(f"Schedule exported to {file}")
            messagebox.showinfo("Info", f"Exported to {file}")

    def set_today(self):
        now = datetime.now()
        self.month_var.set(now.strftime("%B"))
        self.year_var.set(now.year)
        self.update_holidays_display()

    def add_manual_holiday(self):
        top = tk.Toplevel(self.root)
        top.title("Add Manual Holiday")
        top.geometry("300x200")
        top.transient(self.root)
        top.grab_set()

        try:
            month = list(month_name).index(self.month_var.get())
            year = int(self.year_var.get())
        except (ValueError, TypeError):
            month, year = datetime.now().month, datetime.now().year

        cal = Calendar(top, selectmode="day", year=year, month=month, date_pattern="yyyy-mm-dd")
        cal.pack(pady=10, padx=10)

        def confirm():
            selected_date = cal.get_date()
            if not selected_date:
                messagebox.showwarning("Warning", "Please select a date")
                return

            day = int(selected_date.split('-')[2])
            if day not in self.manual_holidays:
                self.manual_holidays.append(day)
            self.update_schedule_columns()  # Refresh
            self.update_holidays_display()
            top.destroy()

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)
        ttk.Button(top, text="Cancel", command=top.destroy).pack(pady=5)

    def add_worker(self):
        top = tk.Toplevel(self.root)
        top.title("Add Worker")
        top.geometry("300x150")
        ttk.Label(top, text="Worker Name:").pack(pady=5)
        name_var = tk.StringVar()
        ttk.Entry(top, textvariable=name_var).pack(pady=5)

        def confirm():
            name = name_var.get().strip()
            if name and not any(w['name'] == name for w in self.workers):
                next_num = max((int(w['id'][2:]) for w in self.workers), default=0) + 1
                new_id = f"ID{next_num:03d}"
                new_worker = {
                    "name": name,
                    "id": new_id,
                    "color": "#000000",
                    "can_night": True,  # Changed from "can_work_nights"
                    "weekly_load": 18  # Changed from "standard_weekly_hours"
                }
                self.workers.append(new_worker)
                self.unavail[name] = []
                self.req[name] = []
                self.worker_var.set(name)
                self.update_worker_combo()
                top.destroy()
            else:
                messagebox.showwarning("Warning", "Invalid or duplicate name")

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)

    def remove_worker(self):
        worker = self.worker_var.get()
        if worker and messagebox.askyesno("Confirm", f"Remove {worker}?"):
            self.workers = [w for w in self.workers if w['name'] != worker]
            del self.unavail[worker]
            del self.req[worker]
            self.worker_var.set(self.workers[0]['name'] if self.workers else "")
            self.update_worker_combo()

    def update_worker_combo(self):
        self.worker_combo['values'] = [w['name'] for w in self.workers]
        self.update_worker_stats()

    def add_shift_availability(self, mode):
        worker = self.worker_var.get()
        if not worker:
            messagebox.showwarning("Warning", "Select a worker first")
            return

        top = tk.Toplevel(self.root)
        top.title(f"Select {mode.capitalize()} Shift(s)")
        top.geometry("400x250")
        top.transient(self.root)
        top.grab_set()

        try:
            month = list(month_name).index(self.month_var.get())
            year = int(self.year_var.get())
        except (ValueError, TypeError):
            month, year = datetime.now().month, datetime.now().year

        # Start date
        ttk.Label(top, text="Start Date:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        cal_start = DateEntry(top, selectmode="day", year=year, month=month, date_pattern="yyyy-mm-dd")
        cal_start.grid(row=0, column=1, padx=10, pady=5)

        # Range checkbox
        range_var = tk.BooleanVar(value=False)
        range_check = ttk.Checkbutton(top, text="Add Range (Specify End Date)", variable=range_var)
        range_check.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        # End date (initially hidden)
        end_label = ttk.Label(top, text="End Date:")
        end_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        cal_end = DateEntry(top, selectmode="day", year=year, month=month, date_pattern="yyyy-mm-dd")
        cal_end.grid(row=2, column=1, padx=10, pady=5)

        # Hide end date initially
        end_label.grid_remove()
        cal_end.grid_remove()

        # Toggle function
        def toggle_end(*args):
            if range_var.get():
                end_label.grid()
                cal_end.grid()
            else:
                end_label.grid_remove()
                cal_end.grid_remove()

        range_var.trace("w", toggle_end)
        toggle_end()  # Initial state

        # Shift selection
        shift_frame = ttk.Frame(top)
        shift_frame.grid(row=3, column=0, columnspan=2, pady=5)
        m1_var = tk.BooleanVar(value=False)
        m2_var = tk.BooleanVar(value=False)
        night_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(shift_frame, text="M1", variable=m1_var).grid(row=0, column=0, padx=5)
        ttk.Checkbutton(shift_frame, text="M2", variable=m2_var).grid(row=0, column=1, padx=5)
        ttk.Checkbutton(shift_frame, text="Night", variable=night_var).grid(row=0, column=2, padx=5)

        target_dict = self.unavail if mode == "unavailable" else self.req
        target_list = self.unavailable_list if mode == "unavailable" else self.required_list

        def daterange(start_date, end_date):
            for n in range(int((end_date - start_date).days) + 1):
                yield start_date + timedelta(n)

        def confirm():
            start_dt = cal_start.get_date()  # Returns date object
            if not start_dt:
                messagebox.showwarning("Warning", "Please select a start date")
                return

            if range_var.get():
                end_dt = cal_end.get_date()
                if not end_dt:
                    messagebox.showwarning("Warning", "Please select an end date")
                    return
                if end_dt < start_dt:
                    messagebox.showwarning("Warning", "End date must be after or equal to start date")
                    return
            else:
                end_dt = start_dt

            shifts = []
            if m1_var.get():
                shifts.append("M1")
            if m2_var.get():
                shifts.append("M2")
            if night_var.get():
                shifts.append("N")  # Logic uses 'N' for night

            for dt in daterange(start_dt, end_dt):
                selected_date = dt.strftime("%Y-%m-%d")
                if not shifts:
                    entry = selected_date
                    if entry not in target_dict[worker]:
                        target_dict[worker].append(entry)
                        target_list.insert(tk.END, entry)
                else:
                    for sh in shifts:
                        entry = f"{selected_date} {sh}"
                        if entry not in target_dict[worker]:
                            target_dict[worker].append(entry)
                            target_list.insert(tk.END, entry)

            top.destroy()

        ttk.Button(top, text="Confirm", command=confirm).grid(row=4, column=0, columnspan=2, pady=5)
        ttk.Button(top, text="Cancel", command=top.destroy).grid(row=5, column=0, columnspan=2, pady=5)

    def remove_shift_availability(self, target_list, mode):
        worker = self.worker_var.get()
        if not worker:
            return

        selected = target_list.curselection()
        if selected:
            idx = selected[0]
            target_dict = self.unavail if mode == "unavailable" else self.req
            del target_dict[worker][idx]
            target_list.delete(idx)
        else:
            messagebox.showwarning("Warning", "Please select an entry to remove")

    def edit_shift(self, event):
        item = self.schedule_tree.identify_row(event.y)
        column = self.schedule_tree.identify_column(event.x)
        if not item or column == '#0':  # Ignore if not a valid cell
            return

        col_index = int(column.replace('#', '')) - 1  # 0=Day, 1=M1, 2=M2, 3=Night
        if col_index == 0:  # Day column isn't editable
            return

        shift_types = ["M1", "M2", "Night"]
        shift = shift_types[col_index - 1]
        day = self.schedule_tree.item(item, "values")[0].split(' (')[0]  # Extract day number

        # Open edit dialog
        top = tk.Toplevel(self.root)
        top.title(f"Edit {shift} Shift for Day {day}")
        top.geometry("300x300")
        top.transient(self.root)
        top.grab_set()

        ttk.Label(top, text="Select Workers:").pack(pady=5)
        worker_list = tk.Listbox(top, selectmode="multiple", height=10, font=self.body_font)
        for w in self.workers:
            worker_list.insert(tk.END, w['name'])
        worker_list.pack(pady=5, padx=10, fill="both", expand=True)

        # Pre-select current workers if any
        current_workers = self.schedule_tree.item(item, "values")[col_index].split(', ')
        for i, w in enumerate(self.workers):
            if w['name'] in current_workers:
                worker_list.select_set(i)

        def confirm():
            selected = [worker_list.get(i) for i in worker_list.curselection()]
            new_value = ', '.join(selected) if selected else ""
            values = list(self.schedule_tree.item(item, "values"))
            values[col_index] = new_value
            self.schedule_tree.item(item, values=values)
            self.status_var.set(f"Updated {shift} shift for Day {day}")
            top.destroy()

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)
        ttk.Button(top, text="Cancel", command=top.destroy).pack(pady=5)

    def save_manual_changes(self):
        # Placeholder: Extract data from Treeview and save/update history (logic later)
        self.status_var.set("Manual changes saved (placeholder)")
        messagebox.showinfo("Info", "Manual changes would be saved")

    def update_schedule_columns(self):
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        self.schedule_tree["columns"] = ("Day", "M1", "M2", "Night")

        self.schedule_tree.heading("Day", text="Day", command=lambda: self.sort_treeview("Day", False))
        self.schedule_tree.heading("M1", text="M1", command=lambda: self.sort_treeview("M1", False))
        self.schedule_tree.heading("M2", text="M2", command=lambda: self.sort_treeview("M2", False))
        self.schedule_tree.heading("Night", text="Night", command=lambda: self.sort_treeview("Night", False))

        self.schedule_tree.column("Day", width=120, anchor="center")
        self.schedule_tree.column("M1", width=150, anchor="center")
        self.schedule_tree.column("M2", width=150, anchor="center")
        self.schedule_tree.column("Night", width=150, anchor="center")

        self.schedule_tree.tag_configure("oddrow", background="#f0f0f0")
        self.schedule_tree.tag_configure("evenrow", background="#ffffff")
        self.schedule_tree.tag_configure('weekend', background='#e0f7fa')  # Light cyan
        self.schedule_tree.tag_configure('holiday', background='#ffebee')  # Light red
        self.schedule_tree.tag_configure('understaffed', foreground='red')

        try:
            month = list(month_name).index(self.month_var.get())
            year = int(self.year_var.get())
            _, num_days = monthrange(year, month)
        except (ValueError, TypeError):
            month, year, num_days = datetime.now().month, datetime.now().year, 31

        auto_holidays = compute_holidays(year, month)  # Adapted to new naming

        for day in range(1, num_days + 1):
            dt = datetime(year, month, day)
            weekday = day_name[dt.weekday()][:3]
            day_text = f"{day} ({weekday})"
            tag = "evenrow" if day % 2 == 0 else "oddrow"
            if weekday in ['Sat', 'Sun']:
                tag = (tag, 'weekend')
            elif day in (auto_holidays + self.manual_holidays):
                tag = (tag, 'holiday')
            self.schedule_tree.insert("", "end", values=(day_text, "", "", ""), tags=tag)

    def sort_treeview(self, col, reverse):
        l = [(self.schedule_tree.set(k, col), k) for k in self.schedule_tree.get_children('')]
        l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            self.schedule_tree.move(k, '', index)
        self.schedule_tree.heading(col, command=lambda: self.sort_treeview(col, not reverse))

    def update_schedule_display(self, schedule, all_holidays):
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        for day_str in sorted(schedule):
            dt = datetime.fromisoformat(day_str)
            day = dt.day
            weekday = day_name[dt.weekday()][:3]
            day_text = f"{day} ({weekday})"
            m1 = schedule[day_str].get('M1', '')
            m2 = schedule[day_str].get('M2', '')
            n = schedule[day_str].get('N', '')
            tag = "evenrow" if day % 2 == 0 else "oddrow"
            if weekday in ['Sat', 'Sun']:
                tag = (tag, 'weekend')
            elif day in all_holidays:
                tag = (tag, 'holiday')
            if not m1 or not m2 or not n:
                tag = (tag, 'understaffed')
            self.schedule_tree.insert("", "end", values=(day_text, m1, m2, n), tags=tag)

if __name__ == "__main__":
    root = tk.Tk()
    app = ShiftSchedulerApp(root)
    root.mainloop()