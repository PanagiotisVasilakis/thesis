"""Subscription validation utilities."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def check_expiration_time(expire_time: str) -> bool:
    """
    Check if a subscription has expired.
    
    Args:
        expire_time: ISO 8601 formatted datetime string (e.g., '2026-01-13T12:00:00')
    
    Returns:
        True if the subscription is still valid (not expired), False otherwise.
    """
    try:
        # Parse ISO 8601 datetime - handles both with and without timezone
        expiry = datetime.fromisoformat(expire_time.replace('Z', '+00:00'))
        now = datetime.now(expiry.tzinfo) if expiry.tzinfo else datetime.now()
        
        is_valid = expiry >= now
        logger.debug("Expiration check: expire_time=%s, now=%s, is_valid=%s", 
                     expiry, now, is_valid)
        return is_valid
    except (ValueError, AttributeError) as e:
        logger.error("Failed to parse expiration time '%s': %s", expire_time, e)
        return False


def check_numberOfReports(maximum_number_of_reports: int) -> bool:
    """
    Check if subscription has remaining reports.
    
    Args:
        maximum_number_of_reports: Number of reports remaining.
    
    Returns:
        True if reports remain, False otherwise.
    """
    if maximum_number_of_reports >= 1:
        return True
    else:
        logger.warning("Subscription has expired (maximum number of reports reached)")
        return False
