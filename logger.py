"""
Logging configuration for Shift Scheduler application.
"""

import logging
import os
import time
import functools
from contextlib import contextmanager
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


@contextmanager
def log_timing(operation_name: str, logger_instance=None):
    """
    Context manager to measure and log execution time of a code block.
    
    Usage:
        with log_timing("constraint creation"):
            create_constraints()
    
    Args:
        operation_name: Name to identify the operation in logs
        logger_instance: Optional logger (uses default if not provided)
    """
    log = logger_instance or get_logger('perf')
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info(f"⏱️ {operation_name}: {elapsed:.4f}s")


def timed(func=None, *, name=None):
    """
    Decorator to measure and log function execution time.
    
    Usage:
        @timed
        def my_function():
            ...
        
        @timed(name="custom operation name")
        def another_function():
            ...
    """
    def decorator(fn):
        op_name = name or fn.__qualname__
        
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log = get_logger('perf')
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.perf_counter() - start
                log.info(f"⏱️ {op_name}: {elapsed:.4f}s")
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                log.error(f"⏱️ {op_name}: {elapsed:.4f}s (failed with {type(e).__name__})")
                raise
        
        return wrapper
    
    if func is not None:
        return decorator(func)
    return decorator


class PerformanceTracker:
    """
    Cumulative performance tracker for repeated operations.
    
    Usage:
        tracker = PerformanceTracker()
        
        for item in items:
            with tracker.track("processing"):
                process(item)
        
        tracker.report()  # Logs summary of all tracked operations
    """
    
    def __init__(self, logger_instance=None):
        self.logger = logger_instance or get_logger('perf')
        self.timings = {}  # {operation: [elapsed_times]}
    
    @contextmanager
    def track(self, operation_name: str):
        """Track time for an operation (can be called multiple times)."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            if operation_name not in self.timings:
                self.timings[operation_name] = []
            self.timings[operation_name].append(elapsed)
    
    def report(self, title: str = "Performance Summary"):
        """Log a summary of all tracked operations."""
        self.logger.info(f"\n{'='*50}")
        self.logger.info(f"📊 {title}")
        self.logger.info(f"{'='*50}")
        
        for op, times in sorted(self.timings.items(), key=lambda x: -sum(x[1])):
            total = sum(times)
            count = len(times)
            avg = total / count if count > 0 else 0
            min_t = min(times) if times else 0
            max_t = max(times) if times else 0
            
            self.logger.info(
                f"  {op:40s} | total: {total:8.4f}s | count: {count:5d} | "
                f"avg: {avg:.4f}s | min: {min_t:.4f}s | max: {max_t:.4f}s"
            )
        
        self.logger.info(f"{'='*50}\n")
        return self.timings


# Initialize logging when module is imported
logger = setup_logging()
