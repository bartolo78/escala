import tkinter as tk
from datetime import timedelta, datetime
from constants import FIXED_HOLIDAYS, MOVABLE_HOLIDAY_OFFSETS



class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event):
        # Handle different widget types
        if hasattr(self.widget, 'bbox') and 'Listbox' in str(type(self.widget)):
            # For listboxes, use event coordinates
            x = event.x + self.widget.winfo_rootx() + 25
            y = event.y + self.widget.winfo_rooty() + 25
        else:
            # For other widgets (like text widgets), use bbox with "insert"
            try:
                bbox = self.widget.bbox("insert")
                if bbox:
                    x, y, _, _ = bbox
                    x += self.widget.winfo_rootx() + 25
                    y += self.widget.winfo_rooty() + 25
                else:
                    # Fallback to event coordinates
                    x = event.x + self.widget.winfo_rootx() + 25
                    y = event.y + self.widget.winfo_rooty() + 25
            except:
                # Fallback to event coordinates for widgets that don't support bbox
                x = event.x + self.widget.winfo_rootx() + 25
                y = event.y + self.widget.winfo_rooty() + 25

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(self.tooltip_window, text=self.text, background="#ffffe0",
                         relief="solid", borderwidth=1, font=("Arial", 10))
        label.pack()

    def hide_tooltip(self, event):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = (19 * a + b - b // 4 - ((b - (b + 8) // 25 + 1) // 3) + 15) % 30
    e = (32 + 2 * (b % 4) + 2 * (c // 4) - d - (c % 4)) % 7
    f = d + e - 7 * ((a + 11 * d + 22 * e) // 451) + 114
    month = f // 31
    day = f % 31 + 1
    return datetime(year, month, day)

def compute_holidays(year: int, month: int) -> list[int]:
    fixed_holidays = FIXED_HOLIDAYS

    # Movable holidays
    easter = easter_date(year)
    auto_days = fixed_holidays.get(month, [])[:]
    for offset in MOVABLE_HOLIDAY_OFFSETS.values():
        dt = easter + timedelta(days=offset)
        if dt.month == month and dt.year == year:
            auto_days.append(dt.day)
    return sorted(list(set(auto_days)))


