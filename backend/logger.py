import logging
import sys
from pathlib import Path

def setup_logger(name: str, level: str = "INFO", log_file: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.propagate = False
    # Clear handlers để cho phép re-config
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    console_formatter = logging.Formatter(
        '[%(asctime)s] %(name)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(name)s - %(levelname)s - %(funcName)s:%(lineno)d: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Lấy logger đã được cấu hình
    
    Args:
        name: Tên logger
    
    Returns:
        Logger
    """
    return logging.getLogger(name)

# Logger mặc định
default_logger = setup_logger("default")
