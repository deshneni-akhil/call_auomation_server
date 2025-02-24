import logging
import os
from typing import Optional, Literal

class MultiLogger:
    """
    A flexible logging class that supports configurable logging to console or file.
    
    Attributes:
        logger (logging.Logger): The configured logger instance
        log_file (Optional[str]): Path to the log file if file logging is enabled
    """
    
    def __init__(
        self, 
        name: str, 
        log_level: int = logging.INFO, 
        log_destination: Literal['console', 'file'] = 'console', 
        log_file: Optional[str] = None,
        log_format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ):
        """
        Initialize the flexible logger.
        
        Args:
            name (str): Name of the logger
            log_level (int, optional): Logging level. Defaults to logging.INFO.
            log_destination (str, optional): Where to log ('console' or 'file'). Defaults to 'console'.
            log_file (str, optional): Path to log file if logging to file. Defaults to None.
            log_format (str, optional): Format of log messages. Defaults to standard format.
        """
        # Create logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)
        
        # Clear any existing handlers to prevent duplicate logging
        self.logger.handlers.clear()
        
        # Create formatter
        self.formatter = logging.Formatter(log_format)
        
        # Configure logging destination
        self.log_file = log_file
        self.log_destination = log_destination
        
        # Set up handlers based on destination
        if log_destination == 'console':
            self._setup_console_logging()
        elif log_destination == 'file':
            self._setup_file_logging()
        else:
            raise ValueError("log_destination must be either 'console' or 'file'")
    
    def _setup_console_logging(self):
        """
        Set up console logging.
        """
        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.logger.level)
        console_handler.setFormatter(self.formatter)
        
        # Add handler to logger
        self.logger.addHandler(console_handler)
    
    def _setup_file_logging(self):
        """
        Set up file logging.
        """
        # If no log file is specified, use the logger name in the current directory
        if not self.log_file:
            self.log_file = f"{self.logger.name}.log"
        
        # Ensure log file path is absolute
        self.log_file = os.path.abspath(self.log_file)
        
        # Ensure directory exists
        log_dir = os.path.dirname(self.log_file)
        if log_dir:  # Only attempt to create directory if path is not empty
            os.makedirs(log_dir, exist_ok=True)
        
        # Create file handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(self.logger.level)
        file_handler.setFormatter(self.formatter)
        
        # Add handler to logger
        self.logger.addHandler(file_handler)
    
    def change_log_destination(
        self, 
        new_destination: Literal['console', 'file'], 
        log_file: Optional[str] = None
    ):
        """
        Change logging destination dynamically.
        
        Args:
            new_destination (str): New logging destination ('console' or 'file')
            log_file (str, optional): New log file path if switching to file logging
        """
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Update log destination and file
        self.log_destination = new_destination
        
        # Reconfigure logging
        if new_destination == 'console':
            self._setup_console_logging()
        elif new_destination == 'file':
            # Use provided log file or existing log file
            self.log_file = log_file or self.log_file
            self._setup_file_logging()
        else:
            raise ValueError("new_destination must be either 'console' or 'file'")
        
    def write_instruction_log(self, instruction: str, filename: str):
        """
        Write an instruction log message.
        
        Args:
            instruction (str): Instruction to log
        """
        file_path = os.path.join(os.path.dirname(__file__), 'logs', filename)

        with open(file_path, 'a') as file:
            file.write(f"{instruction}\n\n\n\n")
    
    def truncate_log_files(self, filename: str):
        """
        Truncate the log file.
        
        Args:
            filename (str): Name of the log file to truncate
        """
        file_path = os.path.join(os.path.dirname(__file__), 'logs', filename)
        
        with open(file_path, 'w') as file:
            file.write('')
    
    def get_logger(self) -> logging.Logger:
        """
        Get the configured logger instance.
        
        Returns:
            logging.Logger: Configured logger
        """
        return self.logger