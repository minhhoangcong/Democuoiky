import logging
import sys
from pathlib import Path

def setup_logger(name: str, level: str = "INFO", log_file: str = None) -> logging.Logger:
    """
    Thiết lập logger với cấu hình chuẩn
    
    Args:
        name: Tên logger
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Đường dẫn file log (optional)
    
    Returns:
        Logger đã được cấu hình
    """
    # Tạo logger
    logger = logging.getLogger(name)
    
    # Tránh duplicate handlers
    if logger.handlers:
        return logger
    
    # Set level
    logger.setLevel(getattr(logging, level.upper()))
    
    # Format cho console
    console_formatter = logging.Formatter(
        '[%(asctime)s] %(name)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Format cho file (chi tiết hơn)
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(name)s - %(levelname)s - %(funcName)s:%(lineno)d: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler (nếu có)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
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
