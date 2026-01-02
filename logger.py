"""
Logging configuration for Shift Scheduler application.
"""

import logging
import os
from datetime import datetime

# Log directory and file
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, f"scheduler_{datetime.now().strftime('%Y%m%d')}.log")


def setup_logging(level=logging.INFO, log_to_file=True):
    """
    Configure logging for the application.
    
    Args:
        level: Logging level (default: INFO)
        log_to_file: Whether to also log to a file (default: True)
    
    Returns:
        Logger instance
    """
    # Create logs directory if it doesn't exist
    if log_to_file and not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Get root logger
    logger = logging.getLogger('escala')
    logger.setLevel(level)
    
    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_to_file:
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name=None):
    """
    Get a logger instance.
    
    Args:
        name: Optional name for the logger (will be prefixed with 'escala.')
    
    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f'escala.{name}')
    return logging.getLogger('escala')


# Initialize logging when module is imported
logger = setup_logging()
