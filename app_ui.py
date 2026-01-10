import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkcalendar import Calendar, DateEntry
from calendar import month_name, monthrange, day_name
from datetime import datetime, timedelta, date
import tkinter.font as tkfont
import csv
import json  # For potential saves
import yaml
import os
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# Import the scheduler service (clean API layer)
from scheduler_service import SchedulerService, ScheduleResult, WorkerStats
from utils import Tooltip
from constants import EQUITY_STATS
from logger import get_logger

logger = get_logger('ui')

# Configuration file path
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RULES.md")


def get_contrast_color(hex_color: str) -> str:
    """Calculate a contrasting text color (black or white) for a given background color.
    
    Uses the relative luminance formula from WCAG guidelines to determine
    whether black or white text provides better contrast.
    
    Args:
        hex_color: Background color in hex format (e.g., '#FF5733' or 'FF5733')
    
    Returns:
        '#000000' for dark text on light backgrounds, '#FFFFFF' for light text on dark backgrounds
    """
    # Remove '#' if present
    hex_color = hex_color.lstrip('#')
    
    # Handle short hex format (e.g., 'FFF' -> 'FFFFFF')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    
    # Convert to RGB
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except (ValueError, IndexError):
        return '#000000'  # Default to black on parsing error
    
    # Calculate relative luminance using the formula from WCAG
    # First linearize the sRGB values
    def linearize(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    
    luminance = 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
    
    # Return black text for light backgrounds, white for dark backgrounds
    return '#000000' if luminance > 0.179 else '#FFFFFF'

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
        self.rowconfigure(1, weight=1)  # Changed from 0 to 1 to accommodate legend

        # Worker color legend frame at the top
        self.legend_frame = ttk.LabelFrame(self, text="Worker Colors", padding="5")
        self.legend_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.app.schedule_legend_frame = self.legend_frame

        # Create a scrollable frame for the schedule grid
        self.schedule_container = ttk.Frame(self)
        self.schedule_container.grid(row=1, column=0, sticky="nsew")
        self.schedule_container.columnconfigure(0, weight=1)
        self.schedule_container.rowconfigure(0, weight=1)
        
        # Canvas for scrolling
        self.schedule_canvas = tk.Canvas(self.schedule_container, highlightthickness=0)
        self.schedule_canvas.grid(row=0, column=0, sticky="nsew")
        
        # Scrollbars
        vsb = ttk.Scrollbar(self.schedule_container, orient="vertical", command=self.schedule_canvas.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(self.schedule_container, orient="horizontal", command=self.schedule_canvas.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        
        self.schedule_canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Frame inside canvas for the grid
        self.app.schedule_grid_frame = ttk.Frame(self.schedule_canvas)
        self.schedule_canvas_window = self.schedule_canvas.create_window((0, 0), window=self.app.schedule_grid_frame, anchor="nw")
        
        # Bind resize events
        self.app.schedule_grid_frame.bind("<Configure>", self._on_grid_configure)
        self.schedule_canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Enable mouse wheel scrolling
        self.schedule_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.schedule_canvas.bind_all("<Button-4>", self._on_mousewheel)  # Linux scroll up
        self.schedule_canvas.bind_all("<Button-5>", self._on_mousewheel)  # Linux scroll down
        
        # Store reference for scrolling
        self.app.schedule_canvas = self.schedule_canvas
        
        # Initialize the grid structure
        self.app._schedule_cells = {}  # Store cell labels for editing
        self.app._schedule_data = []   # Store row data for export/save
        self.app.update_schedule_columns()

        save_btn = ttk.Button(self, text="Save Manual Changes", command=self.app.save_manual_changes)
        save_btn.grid(row=3, column=0, pady=10, sticky="ew")
        Tooltip(save_btn, "Save any manual edits to the schedule")
    
    def _on_grid_configure(self, event):
        """Update scroll region when grid changes."""
        self.schedule_canvas.configure(scrollregion=self.schedule_canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Update grid width when canvas is resized."""
        # Make the grid frame at least as wide as the canvas
        canvas_width = event.width
        self.schedule_canvas.itemconfig(self.schedule_canvas_window, width=canvas_width)
    
    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling."""
        # Check if this canvas is visible
        if not self.schedule_canvas.winfo_viewable():
            return
        if event.num == 4:  # Linux scroll up
            self.schedule_canvas.yview_scroll(-1, "units")
        elif event.num == 5:  # Linux scroll down
            self.schedule_canvas.yview_scroll(1, "units")
        else:  # Windows/Mac
            self.schedule_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

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

        for stat, weight in self.app.scheduler.equity_weights.items():
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
        self.dow_scale = ttk.Scale(dow_frame, from_=0, to=10, orient="horizontal", 
                                   value=self.app.scheduler.dow_equity_weight,
                                   command=lambda v: setattr(self.app.scheduler, 'dow_equity_weight', float(v)))
        self.dow_scale.pack(side="left", fill="x", expand=True, padx=10)
        dow_value_label = ttk.Label(dow_frame, text=f"{self.app.scheduler.dow_equity_weight:.1f}")
        dow_value_label.pack(side="left", padx=10)
        self.dow_scale.bind("<Motion>", lambda e: dow_value_label.config(text=f"{self.dow_scale.get():.1f}"))

        solver_frame = ttk.LabelFrame(self, text="Solver", padding="10")
        solver_frame.pack(fill="x", pady=15)

        lex_cb = ttk.Checkbutton(
            solver_frame,
            text="Lexicographic optimization (strict rule priority)",
            variable=self.app.lexicographic_var,
            command=self.update_lexicographic,
        )
        lex_cb.pack(anchor="w")
        Tooltip(lex_cb, "When enabled, the solver optimizes flexible rules in strict RULES.md order")

    def update_weight(self, stat, value):
        self.app.scheduler.set_equity_weight(stat, value)

    def update_lexicographic(self):
        self.app.scheduler.lexicographic_mode = bool(self.app.lexicographic_var.get())

class ShiftSchedulerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Shift Scheduler")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        # Initialize the scheduler service (clean API layer)
        self.scheduler = SchedulerService()

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
        # Solver mode: weighted sum optimization is the default.
        self.lexicographic_var = tk.BooleanVar(value=self.scheduler.lexicographic_mode)
        
        # UI state variables (workers/history/etc. are now managed by scheduler service)
        self.worker_var = tk.StringVar()
        self.stats_labels = {}
        self.unavailable_list = None
        self.required_list = None
        self.schedule_grid_frame = None  # Custom grid frame for schedule display
        self.schedule_canvas = None  # Canvas for scrollable schedule
        self.schedule_legend_frame = None  # Legend frame for worker colors
        self._schedule_cells = {}  # Store cell labels for editing
        self._schedule_data = []   # Store row data for export/save
        self.reports_tree = None
        self.holidays_var = None  # Initialize to None
        
        # Last schedule result for dashboard updates
        self._last_result: ScheduleResult = None

    # Property aliases for backwards compatibility with tab classes
    @property
    def workers(self):
        return [w.to_dict() for w in self.scheduler.workers]

    @property
    def unavail(self):
        return {w.name: self.scheduler.get_unavailable(w.name) for w in self.scheduler.workers}

    @property
    def req(self):
        return {w.name: self.scheduler.get_required(w.name) for w in self.scheduler.workers}

    @property
    def history(self):
        return self.scheduler.history

    @property
    def thresholds(self):
        return self.scheduler.thresholds

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
        file_menu.add_command(label="Save Configuration", command=self.save_workers_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Rules", command=self.open_rules)

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

        view_history_btn = ttk.Button(control_frame, text="View History",
                                      command=self.view_history_wrapper)
        view_history_btn.grid(row=0, column=5, padx=10, pady=5)
        Tooltip(view_history_btn, "View the historical schedule for the selected month")

        # Add Today button
        today_btn = ttk.Button(control_frame, text="Today", command=self.set_today)
        today_btn.grid(row=0, column=6, padx=10, pady=5)
        Tooltip(today_btn, "Reset to current month and year")

        # Add manual holiday button
        add_holiday_btn = ttk.Button(control_frame, text="Add Holiday", command=self.add_manual_holiday)
        add_holiday_btn.grid(row=0, column=7, padx=10, pady=5)
        Tooltip(add_holiday_btn, "Add a manual holiday for the selected month")

        # Add export history button
        export_btn = ttk.Button(control_frame, text="Export History", command=self.export_history)
        export_btn.grid(row=0, column=8, padx=10, pady=5)
        Tooltip(export_btn, "Export the scheduling history to a JSON file")

        # Add import history button
        import_btn = ttk.Button(control_frame, text="Import History", command=self.import_history)
        import_btn.grid(row=0, column=9, padx=10, pady=5)
        Tooltip(import_btn, "Import scheduling history from a JSON file")

        # Holidays display
        ttk.Label(control_frame, text="Holidays:").grid(row=1, column=0, padx=10, pady=5)
        self.holidays_var = tk.StringVar()
        ttk.Label(control_frame, textvariable=self.holidays_var).grid(row=1, column=1, columnspan=3, sticky="w", padx=10, pady=5)

    def open_rules(self):
        """Open a window displaying the scheduling rules from RULES.md."""
        try:
            if not os.path.exists(RULES_FILE):
                messagebox.showwarning("Rules", "Rules file not found: RULES.md")
                return
            with open(RULES_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Could not read RULES.md: {e}", exc_info=True)
            messagebox.showerror("Rules", f"Could not read rules file: {e}")
            return

        win = tk.Toplevel(self.root)
        win.title("Scheduling Rules")
        win.geometry("800x600")
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        text = tk.Text(frame, wrap="word")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vsb.set)
        text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        text.insert("1.0", content)
        text.config(state="disabled")

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

        self.progress.grid()
        self.progress.start()
        self.status_var.set("Generating schedule...")

        self.root.after(100, lambda: self._run_generate_schedule(year, month))

    def view_history_wrapper(self):
        try:
            month = list(month_name).index(self.month_var.get())
            year = self.year_var.get()
        except ValueError:
            messagebox.showerror("Error", "Invalid month or year")
            return

        self.progress.grid()
        self.progress.start()
        self.status_var.set("Loading history...")

        self.root.after(100, lambda: self._run_view_history(year, month))

    def _run_generate_schedule(self, year, month):
        logger.info(f"Generating schedule for {month}/{year} with {len(self.scheduler.workers)} workers")
        
        # Use the scheduler service to generate
        result = self.scheduler.generate(year, month)
        self._last_result = result

        self.progress.stop()
        self.progress.grid_remove()

        if result.success:
            self.status_var.set("Schedule generated")
            logger.info(f"Schedule generated successfully with {len(result.assignments)} assignments")
            all_holidays = self.scheduler.get_holidays(year, month)
            self.update_schedule_display(result.schedule, all_holidays)
            self.generate_report()
        else:
            self.status_var.set("Schedule failed")
            logger.warning(f"Schedule generation failed: {result.error_message}")
            error_msg = result.error_message or "No feasible schedule found"
            
            # Show diagnostic info if available
            if result.diagnostic_report:
                error_msg += "\n\nDiagnostic Report:\n" + result.diagnostic_report.format_report()[:1000]
            
            messagebox.showerror("Error", error_msg)

    def _run_view_history(self, year, month):
        logger.info(f"Viewing history for {month}/{year}")
        
        # Get history for the month
        from history_view import HistoryView
        history_view = HistoryView(self.scheduler._history)
        assignments_by_date = history_view.assignments_by_date()
        
        # Build schedule dict
        schedule = {}
        assignments = []
        for date_str, entries in assignments_by_date.items():
            try:
                d = date.fromisoformat(date_str)
                if d.year == year and d.month == month:
                    schedule[date_str] = {}
                    for entry in entries:
                        schedule[date_str][entry["shift"]] = entry["worker"]
                        assignments.append({
                            "worker": entry["worker"],
                            "date": date_str,
                            "shift": entry["shift"],
                            "dur": entry.get("dur", 0),
                        })
            except ValueError:
                continue
        
        self._last_result = None  # Not a generated result

        self.progress.stop()
        self.progress.grid_remove()
        self.status_var.set("History loaded")

        logger.info(f"History loaded with {len(assignments)} assignments")
        all_holidays = self.scheduler.get_holidays(year, month)
        self.update_schedule_display(schedule, all_holidays)
        # Optionally generate report
        # self.generate_report()

    def update_worker_stats(self, event=None):
        worker = self.worker_var.get()
        if not worker:
            return

        # Get stats from the service
        stats = self.scheduler.get_worker_stats(worker)

        self.stats_labels["Total Hours"].config(text=stats.total_hours)
        self.stats_labels["Weekend Shifts"].config(text=stats.weekend_holiday_shifts)
        self.stats_labels["Night Shifts"].config(text=stats.night_shifts)

        # Update unavailable list from service
        self.unavailable_list.delete(0, tk.END)
        for item in self.scheduler.get_unavailable(worker):
            self.unavailable_list.insert(tk.END, item)

        # Update required list from service
        self.required_list.delete(0, tk.END)
        for item in self.scheduler.get_required(worker):
            self.required_list.insert(tk.END, item)

    def generate_report(self):
        self.reports_tree.delete(*self.reports_tree.get_children())
        columns = ("Worker", "Total Hours", "Day Shifts", "Night Shifts", "Weekend+Holiday Shifts", "Sat Night", "Sat Day", "Sun+Holiday Night", "Sun+Holiday Day", "Fri Night")
        self.reports_tree["columns"] = columns
        for col in columns:
            self.reports_tree.heading(col, text=col)
            self.reports_tree.column(col, anchor="center")

        # Use the service to generate all worker stats
        all_stats = self.scheduler.generate_all_worker_stats(weeks_lookback=52)
        
        for stats in all_stats:
            self.reports_tree.insert("", "end", values=(
                stats.name, stats.total_hours, stats.day_shifts, stats.night_shifts,
                stats.weekend_holiday_shifts, stats.sat_night, stats.sat_day,
                stats.sun_holiday_night, stats.sun_holiday_day, stats.fri_night
            ))
        self.update_dashboard()

    def update_dashboard(self):
        if self._last_result is None or not self._last_result.current_stats:
            return

        workers_names = self.scheduler.worker_names
        equity_totals = self.scheduler.get_equity_totals()
        
        if not equity_totals:
            return
            
        fig = self.notebook.nametowidget(self.notebook.tabs()[2]).figure  # Get figure from ReportsTab
        fig.clear()

        rows, cols = 4, 3  # For 10 stats (4 rows x 3 cols = 12 slots)
        for idx, stat in enumerate(EQUITY_STATS):
            ax = fig.add_subplot(rows, cols, idx + 1)
            totals = equity_totals.get(stat, [0] * len(workers_names))
            ax.bar(workers_names, totals, color='skyblue')
            ax.set_title(stat.replace('_', ' ').title())
            ax.tick_params(axis='x', rotation=45)
            imbalance = max(totals) - min(totals) if totals else 0
            threshold = self.scheduler.thresholds.get(stat, 5)
            if imbalance > threshold:
                ax.set_facecolor('lightcoral')
            ax.set_ylabel('Count')

        fig.tight_layout()
        self.notebook.nametowidget(self.notebook.tabs()[2]).canvas.draw()

    def update_holidays_display(self):
        try:
            month = list(month_name).index(self.month_var.get())
            year = self.year_var.get()
            all_holidays = self.scheduler.get_holidays(year, month)
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

        if self.scheduler.load_history(file_path):
            self.status_var.set("Historic data loaded successfully")
            self.update_worker_stats()  # Refresh UI if needed
            self.generate_report()  # Optional: Refresh reports
        else:
            messagebox.showerror("Error", "Failed to load history file")

    def save_schedule(self):
        if not self.scheduler.history:
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

        if self.scheduler.save_history(file_path):
            self.status_var.set("Schedule saved successfully")
        else:
            messagebox.showerror("Error", "Failed to save schedule file")

    def save_workers_config(self):
        """Save current workers and thresholds to config.yaml file."""
        if self.scheduler.save_config():
            self.status_var.set("Configuration saved to config.yaml")
            messagebox.showinfo("Success", "Configuration saved successfully to config.yaml")
        else:
            messagebox.showerror("Error", "Failed to save configuration file")

    def show_import_format_dialog(self, title, format_info, example):
        """Show a dialog with file format information before importing.
        
        Returns True if user clicks Continue, False if Cancel.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("450x300")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (450 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (300 // 2)
        dialog.geometry(f"+{x}+{y}")
        
        result = {"continue": False}
        
        # Main frame with padding
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title label
        title_label = ttk.Label(main_frame, text="Expected File Format", 
                                font=('TkDefaultFont', 11, 'bold'))
        title_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Format description
        format_label = ttk.Label(main_frame, text=format_info, wraplength=400, justify=tk.LEFT)
        format_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Example section
        example_title = ttk.Label(main_frame, text="Example:", 
                                  font=('TkDefaultFont', 10, 'bold'))
        example_title.pack(anchor=tk.W, pady=(0, 5))
        
        # Example in a frame with border
        example_frame = ttk.Frame(main_frame, relief=tk.SUNKEN, borderwidth=1)
        example_frame.pack(fill=tk.X, pady=(0, 20))
        
        example_text = tk.Text(example_frame, height=4, width=50, wrap=tk.NONE,
                               font=('Courier', 10), bg='#f5f5f5', relief=tk.FLAT)
        example_text.insert('1.0', example)
        example_text.config(state=tk.DISABLED)
        example_text.pack(padx=5, pady=5)
        
        # Button frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        def on_continue():
            result["continue"] = True
            dialog.destroy()
        
        def on_cancel():
            result["continue"] = False
            dialog.destroy()
        
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=on_cancel, width=12)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        continue_btn = ttk.Button(btn_frame, text="Continue", command=on_continue, width=12)
        continue_btn.pack(side=tk.RIGHT)
        
        # Handle window close button
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result["continue"]

    def import_workers(self):
        format_info = (
            "The file should be a CSV (Comma-Separated Values) file with one worker name per row.\n\n"
            "• Each row should contain a single worker name in the first column\n"
            "• Additional columns are ignored\n"
            "• Empty rows are skipped\n"
            "• Duplicate workers will not be added"
        )
        example = "John Smith\nMaria Garcia\nAhmed Hassan\nEmma Johnson"
        
        if not self.show_import_format_dialog("Import Workers", format_info, example):
            return
        
        file = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file:
            logger.info(f"Importing workers from {file}")
            with open(file, 'r') as f:
                reader = csv.reader(f)
                new_names = [row[0] for row in reader if row]
            added_count = 0
            for name in new_names:
                if self.scheduler.add_worker(name):
                    added_count += 1
            self.update_worker_combo()
            self.status_var.set(f"Workers imported: {added_count} new workers added")

    def import_holidays(self):
        format_info = (
            "The file should be a CSV (Comma-Separated Values) file with one day number per row.\n\n"
            "• Each row should contain a day of the month (1-31) in the first column\n"
            "• Days are added to the currently selected month/year\n"
            "• Additional columns are ignored\n"
            "• This will replace any existing manual holidays"
        )
        example = "1\n15\n25\n31"
        
        if not self.show_import_format_dialog("Import Holidays", format_info, example):
            return
        
        file = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file:
            self.scheduler.clear_manual_holidays()
            with open(file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        self.scheduler.add_manual_holiday(int(row[0]))
            self.update_schedule_columns()  # Refresh
            self.update_holidays_display()
            self.status_var.set("Holidays imported")

    def export_schedule(self):
        formats = [("PDF", ".pdf"), ("Excel", ".xlsx"), ("CSV", ".csv")]
        file = filedialog.asksaveasfilename(filetypes=formats)
        if file:
            ext = file.split('.')[-1]
            columns = ["Day", "M1", "M2", "Night"]
            if ext == 'pdf':
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(file, pagesize=letter)
                c.drawString(100, 750, "Schedule Export")
                y = 700
                for row in self._schedule_data:
                    c.drawString(100, y, ' | '.join(str(v) for v in row))
                    y -= 20
                c.save()
            elif ext == 'xlsx':
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.append(columns)
                for row in self._schedule_data:
                    ws.append(row)
                wb.save(file)
            elif ext == 'csv':
                import csv
                with open(file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    for row in self._schedule_data:
                        writer.writerow(row)
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
            self.scheduler.add_manual_holiday(day)
            self.update_schedule_columns()  # Refresh
            self.update_holidays_display()
            top.destroy()

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)
        ttk.Button(top, text="Cancel", command=top.destroy).pack(pady=5)

    def export_history(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export History"
        )
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(self.scheduler._history, f, indent=2)
                messagebox.showinfo("Success", "History exported successfully")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export history: {e}")

    def import_history(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import History"
        )
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    loaded_history = json.load(f)
                self.scheduler._history = loaded_history
                messagebox.showinfo("Success", "History imported successfully")
                # Optionally refresh the display
                self.update_holidays_display()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import history: {e}")

    def add_worker(self):
        top = tk.Toplevel(self.root)
        top.title("Add Worker")
        top.geometry("300x150")
        ttk.Label(top, text="Worker Name:").pack(pady=5)
        name_var = tk.StringVar()
        ttk.Entry(top, textvariable=name_var).pack(pady=5)

        def confirm():
            name = name_var.get().strip()
            if name and self.scheduler.add_worker(name):
                self.worker_var.set(name)
                self.update_worker_combo()
                top.destroy()
            else:
                messagebox.showwarning("Warning", "Invalid or duplicate name")

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)

    def remove_worker(self):
        worker = self.worker_var.get()
        if worker and messagebox.askyesno("Confirm", f"Remove {worker}?"):
            self.scheduler.remove_worker(worker)
            names = self.scheduler.worker_names
            self.worker_var.set(names[0] if names else "")
            self.update_worker_combo()

    def update_worker_combo(self):
        self.worker_combo['values'] = self.scheduler.worker_names
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

        target_list = self.unavailable_list if mode == "unavailable" else self.required_list
        add_func = self.scheduler.add_unavailable if mode == "unavailable" else self.scheduler.add_required

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
                    if add_func(worker, entry):
                        target_list.insert(tk.END, entry)
                else:
                    for sh in shifts:
                        entry = f"{selected_date} {sh}"
                        if add_func(worker, entry):
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
            remove_func = self.scheduler.remove_unavailable if mode == "unavailable" else self.scheduler.remove_required
            if remove_func(worker, idx):
                target_list.delete(idx)
        else:
            messagebox.showwarning("Warning", "Please select an entry to remove")

    def edit_shift(self, row_index, col_index):
        """Handle double-click edit for a schedule cell.
        
        Args:
            row_index: The row index (0-based, not including header)
            col_index: The column index (0=Day, 1=M1, 2=M2, 3=Night)
        """
        if col_index == 0:  # Day column isn't editable
            return
        
        if row_index < 0 or row_index >= len(self._schedule_data):
            return

        shift_types = ["M1", "M2", "Night"]
        shift = shift_types[col_index - 1]
        day_text = self._schedule_data[row_index][0]
        day = day_text.split(' (')[0]  # Extract day number

        # Open edit dialog
        top = tk.Toplevel(self.root)
        top.title(f"Edit {shift} Shift for Day {day}")
        top.geometry("300x300")
        top.transient(self.root)
        top.grab_set()

        ttk.Label(top, text="Select Workers:").pack(pady=5)
        worker_list = tk.Listbox(top, selectmode="multiple", height=10, font=self.body_font)
        worker_names = self.scheduler.worker_names
        for name in worker_names:
            worker_list.insert(tk.END, name)
        worker_list.pack(pady=5, padx=10, fill="both", expand=True)

        # Pre-select current workers if any
        current_worker = self._schedule_data[row_index][col_index]
        for i, name in enumerate(worker_names):
            if name == current_worker:
                worker_list.select_set(i)

        def confirm():
            selected = [worker_list.get(i) for i in worker_list.curselection()]
            new_value = selected[0] if selected else ""
            
            # Update the data
            self._schedule_data[row_index][col_index] = new_value
            
            # Update the cell display
            cell_key = (row_index, col_index)
            if cell_key in self._schedule_cells:
                cell_label = self._schedule_cells[cell_key]
                worker_colors = {w.name: w.color for w in self.scheduler.workers}
                
                if new_value and new_value in worker_colors:
                    bg_color = worker_colors[new_value]
                    fg_color = get_contrast_color(bg_color)
                    cell_label.configure(text=new_value, background=bg_color, foreground=fg_color)
                else:
                    # Determine row background
                    is_odd = row_index % 2 == 1
                    day_text = self._schedule_data[row_index][0]
                    weekday = day_text.split('(')[1].rstrip(')') if '(' in day_text else ''
                    if weekday in ['Sat', 'Sun']:
                        bg = '#e0f7fa'
                    elif is_odd:
                        bg = '#f0f0f0'
                    else:
                        bg = '#ffffff'
                    cell_label.configure(text=new_value, background=bg, foreground='red' if not new_value else '#000000')
            
            self.status_var.set(f"Updated {shift} shift for Day {day}")
            top.destroy()

        ttk.Button(top, text="Confirm", command=confirm).pack(pady=5)
        ttk.Button(top, text="Cancel", command=top.destroy).pack(pady=5)

    def save_manual_changes(self):
        # Placeholder: Extract data from grid and save/update history (logic later)
        self.status_var.set("Manual changes saved (placeholder)")
        messagebox.showinfo("Info", "Manual changes would be saved")

    def update_schedule_columns(self):
        """Initialize or reset the schedule grid with headers."""
        # Clear existing grid content
        for widget in self.schedule_grid_frame.winfo_children():
            widget.destroy()
        
        self._schedule_cells = {}
        self._schedule_data = []
        
        # Define column headers
        columns = ["Day", "M1", "M2", "Night"]
        col_widths = [120, 150, 150, 150]
        
        # Create header row with style
        for col_idx, (col_name, width) in enumerate(zip(columns, col_widths)):
            header = tk.Label(
                self.schedule_grid_frame,
                text=col_name,
                font=self.heading_font,
                relief="raised",
                borderwidth=1,
                width=width // 10,  # Approximate character width
                anchor="center",
                bg="#d0d0d0"
            )
            header.grid(row=0, column=col_idx, sticky="nsew", padx=1, pady=1)
            self.schedule_grid_frame.columnconfigure(col_idx, weight=1, minsize=width)

        try:
            month = list(month_name).index(self.month_var.get())
            year = int(self.year_var.get())
            _, num_days = monthrange(year, month)
        except (ValueError, TypeError):
            month, year, num_days = datetime.now().month, datetime.now().year, 31

        all_holidays = self.scheduler.get_holidays(year, month)

        for row_idx, day in enumerate(range(1, num_days + 1)):
            dt = datetime(year, month, day)
            weekday = day_name[dt.weekday()][:3]
            day_text = f"{day} ({weekday})"
            
            # Determine row background color
            is_odd = row_idx % 2 == 1
            if weekday in ['Sat', 'Sun']:
                row_bg = '#e0f7fa'  # Light cyan for weekends
            elif day in all_holidays:
                row_bg = '#ffebee'  # Light red for holidays
            elif is_odd:
                row_bg = '#f0f0f0'  # Alternating gray
            else:
                row_bg = '#ffffff'  # White
            
            row_data = [day_text, "", "", ""]
            self._schedule_data.append(row_data)
            
            # Create cells for this row
            for col_idx in range(4):
                cell_text = day_text if col_idx == 0 else ""
                cell = tk.Label(
                    self.schedule_grid_frame,
                    text=cell_text,
                    font=self.body_font,
                    relief="solid",
                    borderwidth=1,
                    anchor="center",
                    bg=row_bg,
                    padx=5,
                    pady=3
                )
                cell.grid(row=row_idx + 1, column=col_idx, sticky="nsew", padx=0, pady=0)
                self._schedule_cells[(row_idx, col_idx)] = cell
                
                # Bind double-click for editing (except Day column)
                if col_idx > 0:
                    cell.bind("<Double-1>", lambda e, r=row_idx, c=col_idx: self.edit_shift(r, c))
        
        # Update worker color legend
        self._update_worker_legend()

    def sort_schedule_grid(self, col_name, reverse=False):
        """Sort the schedule grid by column (placeholder for future implementation)."""
        # Sorting would require re-rendering the grid
        pass

    def update_schedule_display(self, schedule, all_holidays):
        """Update the schedule grid with colored worker cells.
        
        Args:
            schedule: Dictionary mapping date strings to shift assignments
            all_holidays: Set of holiday days in the month
        """
        # Clear existing grid content
        for widget in self.schedule_grid_frame.winfo_children():
            widget.destroy()
        
        self._schedule_cells = {}
        self._schedule_data = []
        
        # Build a mapping of worker names to colors
        worker_colors = {w.name: w.color for w in self.scheduler.workers}
        
        # Define column headers
        columns = ["Day", "M1", "M2", "Night"]
        col_widths = [120, 150, 150, 150]
        
        # Create header row
        for col_idx, (col_name, width) in enumerate(zip(columns, col_widths)):
            header = tk.Label(
                self.schedule_grid_frame,
                text=col_name,
                font=self.heading_font,
                relief="raised",
                borderwidth=1,
                width=width // 10,
                anchor="center",
                bg="#d0d0d0"
            )
            header.grid(row=0, column=col_idx, sticky="nsew", padx=1, pady=1)
            self.schedule_grid_frame.columnconfigure(col_idx, weight=1, minsize=width)
        
        # Sort schedule by date
        sorted_days = sorted(schedule.keys())
        
        for row_idx, day_str in enumerate(sorted_days):
            dt = datetime.fromisoformat(day_str)
            day = dt.day
            weekday = day_name[dt.weekday()][:3]
            day_text = f"{day} ({weekday})"
            
            # Get worker names for each shift
            m1_name = schedule[day_str].get('M1', '')
            m2_name = schedule[day_str].get('M2', '')
            n_name = schedule[day_str].get('N', '')
            
            # Store row data for export/editing
            row_data = [day_text, m1_name, m2_name, n_name]
            self._schedule_data.append(row_data)
            
            # Determine base row background color (for Day column)
            is_odd = row_idx % 2 == 1
            if weekday in ['Sat', 'Sun']:
                base_bg = '#e0f7fa'  # Light cyan for weekends
            elif day in all_holidays:
                base_bg = '#ffebee'  # Light red for holidays
            elif is_odd:
                base_bg = '#f0f0f0'  # Alternating gray
            else:
                base_bg = '#ffffff'  # White
            
            # Create cells for this row
            cell_data = [
                (day_text, base_bg, '#000000'),  # Day column
                (m1_name, worker_colors.get(m1_name, base_bg) if m1_name else base_bg, None),
                (m2_name, worker_colors.get(m2_name, base_bg) if m2_name else base_bg, None),
                (n_name, worker_colors.get(n_name, base_bg) if n_name else base_bg, None),
            ]
            
            for col_idx, (text, bg_color, fg_override) in enumerate(cell_data):
                # Calculate foreground color for contrast
                if fg_override:
                    fg_color = fg_override
                elif text and col_idx > 0 and text in worker_colors:
                    fg_color = get_contrast_color(bg_color)
                elif not text and col_idx > 0:
                    # Empty shift cell - mark as understaffed
                    fg_color = 'red'
                else:
                    fg_color = '#000000'
                
                cell = tk.Label(
                    self.schedule_grid_frame,
                    text=text,
                    font=self.body_font,
                    relief="solid",
                    borderwidth=1,
                    anchor="center",
                    bg=bg_color,
                    fg=fg_color,
                    padx=5,
                    pady=3
                )
                cell.grid(row=row_idx + 1, column=col_idx, sticky="nsew", padx=0, pady=0)
                self._schedule_cells[(row_idx, col_idx)] = cell
                
                # Bind double-click for editing (except Day column)
                if col_idx > 0:
                    cell.bind("<Double-1>", lambda e, r=row_idx, c=col_idx: self.edit_shift(r, c))
        
        # Update the worker color legend
        self._update_worker_legend()

    def _update_worker_legend(self):
        """Update the worker color legend in the Schedule tab."""
        if not hasattr(self, 'schedule_legend_frame'):
            return
        
        # Clear existing legend items
        for widget in self.schedule_legend_frame.winfo_children():
            widget.destroy()
        
        # Create legend items for each worker
        for i, worker in enumerate(self.scheduler.workers):
            # Create a frame for each worker entry
            worker_frame = ttk.Frame(self.schedule_legend_frame)
            worker_frame.pack(side="left", padx=5, pady=2)
            
            # Create a colored label (using a small canvas for the color box)
            color_canvas = tk.Canvas(worker_frame, width=16, height=16, highlightthickness=1, highlightbackground="gray")
            color_canvas.create_rectangle(0, 0, 16, 16, fill=worker.color, outline=worker.color)
            color_canvas.pack(side="left", padx=(0, 3))
            
            # Worker name label
            name_label = ttk.Label(worker_frame, text=worker.name, font=("TkDefaultFont", 9))
            name_label.pack(side="left")

if __name__ == "__main__":
    root = tk.Tk()
    app = ShiftSchedulerApp(root)
    root.mainloop()