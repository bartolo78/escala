#!/usr/bin/env python3
"""
Main entry point for the Shift Scheduler application.
"""

import tkinter as tk
from ui_escala import ShiftSchedulerApp


def main():
    """Initialize and run the Shift Scheduler application."""
    root = tk.Tk()
    app = ShiftSchedulerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
