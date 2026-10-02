import logging
import sys
from typing import Optional
from fastapi import Request

def setup_logging():
    """Configure structured logging for the application."""
    logger = logging.getLogger("kenhub")
    logger.setLevel(logging.INFO)
    
    # Console handler with structured format
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '{"time": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    return logger

logger = setup_logging()

def log_request(request: Request, user_id: Optional[str] = None):
    """Log incoming request details."""
    logger.info(
        f"Request: {request.method} {request.url.path} "
        f"client={request.client.host if request.client else 'unknown'} "
        f"user={user_id or 'anonymous'}"
    )

def log_error(message: str, exc: Optional[Exception] = None):
    """Log error with optional exception details."""
    if exc:
        logger.error(f"{message}: {str(exc)}")
    else:
        logger.error(message)

def log_auth_event(event: str, user_id: Optional[str] = None, success: bool = True, detail: Optional[str] = None):
    """Log authentication events."""
    status = "success" if success else "failed"
    msg = f"Auth {event}: user={user_id or 'unknown'} status={status}"
    if detail:
        msg += f" detail={detail}"
    logger.info(msg)

def log_business_event(event: str, details: str, user_id: Optional[str] = None):
    """Log business logic events."""
    logger.info(f"Business {event}: {details} user={user_id or 'unknown'}")
