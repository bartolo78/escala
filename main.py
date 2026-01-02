#!/usr/bin/env python3
"""
Main entry point for the Shift Scheduler application.
"""

import tkinter as tk
from app_ui import ShiftSchedulerApp
from logger import get_logger

logger = get_logger('main')


def main():
    """Initialize and run the Shift Scheduler application."""
    logger.info("Starting Shift Scheduler application")
    try:
        root = tk.Tk()
        app = ShiftSchedulerApp(root)
        logger.info("Application initialized successfully")
        root.mainloop()
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        raise
    finally:
        logger.info("Shift Scheduler application closed")


if __name__ == "__main__":
    main()
