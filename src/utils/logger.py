"""Logger utility with rotation and multi-level logging."""
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

class ApplicationLogger:
    """Gère le logging de l'application avec rotation journalière."""
    
    def __init__(self, app_name="ApplicationMesure", log_dir="logs"):
        self.logger = logging.getLogger(app_name)
        self.logger.setLevel(logging.DEBUG)
        
        # Éviter les doublons si multiple instanciation
        if not self.logger.handlers:
            self._setup_handlers(log_dir)
    
    def _setup_handlers(self, log_dir):
        """Configure les handlers de logs (fichier + console)."""
        os.makedirs(log_dir, exist_ok=True)
        
        # Format des logs
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Handler fichier (rotation journalière, max 5MB)
        file_handler = RotatingFileHandler(
            f"{log_dir}/app_{datetime.now().strftime('%Y%m%d')}.log",
            maxBytes=5*1024*1024,
            backupCount=7
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        # Handler console (pour le debug en dev)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def log(self, level: str, message: str):
        """Log un message avec le niveau spécifié."""
        level = level.lower()
        if level == "debug":
            self.logger.debug(message)
        elif level == "info":
            self.logger.info(message)
        elif level == "warning":
            self.logger.warning(message)
        elif level == "error":
            self.logger.error(message)
        elif level == "critical":
            self.logger.critical(message)
        else:
            self.logger.info(message)
    
    def log_connection(self, device: str, action: str):
        """Log une connexion/déconnexion Bluetooth."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"[{timestamp}] {action} - {device}"
        self.logger.info(message)
