import logging
import json
import os
import requests

try:
    from evolved5g.sdk import CAPIFProviderConnector
except (ImportError, AttributeError):
    class CAPIFProviderConnector:  # pragma: no cover - optional dependency fallback
        """Minimal stub when evolved5g SDK is unavailable."""

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def register_and_onboard_provider(self):
            logging.getLogger(__name__).warning(
                "evolved5g SDK not installed; skipping CAPIF provider onboarding"
            )
            return False

        def publish_services(self, service_api_description_json_full_path: str):
            logging.getLogger(__name__).info(
                "Skipping CAPIF publish for %s", service_api_description_json_full_path
            )
            return False
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.core.config import settings

try:
    from logging_config import configure_logging  # type: ignore
except ImportError:
    def configure_logging(level=None, log_file=None):
        logging.basicConfig(level=level or logging.INFO)

logger = logging.getLogger(__name__)


def init() -> None:
    db = SessionLocal()
    init_db(db)


def capif_nef_connector():
    """Connect to CAPIF and register NEF as a provider."""
    try:
        # All CAPIF credentials from environment variables (with defaults for backward compat)
        capif_connector = CAPIFProviderConnector(
            certificates_folder="app/core/certificates",
            capif_host=settings.CAPIF_HOST,
            capif_http_port=settings.CAPIF_HTTP_PORT,
            capif_https_port=settings.CAPIF_HTTPS_PORT,
            capif_netapp_username=os.getenv("CAPIF_NETAPP_USERNAME", "test_nef01"),
            capif_netapp_password=os.getenv("CAPIF_NETAPP_PASSWORD", "test_netapp_password"),
            description=os.getenv("CAPIF_APP_DESCRIPTION", "NEF Emulator"),
            csr_common_name=os.getenv("CAPIF_CSR_COMMON_NAME", "apfExpapfoser1502"),
            csr_organizational_unit=os.getenv("CAPIF_CSR_OU", "NEF"),
            csr_organization=os.getenv("CAPIF_CSR_ORG", "5G-Network-Optimization"),
            crs_locality=os.getenv("CAPIF_CSR_LOCALITY", "Madrid"),
            csr_state_or_province_name=os.getenv("CAPIF_CSR_STATE", "Madrid"),
            csr_country_name=os.getenv("CAPIF_CSR_COUNTRY", "ES"),
            csr_email_address=os.getenv("CAPIF_CSR_EMAIL", "admin@nef.local"),
        )
                                                

        capif_connector.register_and_onboard_provider()

        capif_connector.publish_services(service_api_description_json_full_path="app/core/capif_files/service_monitoring_event.json")
        capif_connector.publish_services(service_api_description_json_full_path="app/core/capif_files/service_as_session_with_qos.json")
        return True
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 409:
            logger.error("Http Error: %s", err.response.json())
        return False
    except requests.exceptions.ConnectionError as err:
        logger.error("Error Connecting: %s", err)
        return False
    except requests.exceptions.Timeout as err:
        logger.error("Timeout Error: %s", err)
        return False
    except requests.exceptions.RequestException as err:
        logger.error("Request Error: %s", err)
        return False
    
# Module-level cache for prepared service descriptions (avoids modifying source files)
_SERVICE_DESCRIPTIONS: dict = {}


def _prepare_aef_profile(json_data: dict) -> dict:
    """Apply environment-based AEF profile configuration.
    
    Modifies the aefProfiles in the given JSON structure based on
    PRODUCTION environment variable.
    
    Args:
        json_data: The parsed service description JSON.
        
    Returns:
        Modified JSON data (modified in-place, also returned for convenience).
    """
    is_production = os.environ.get("PRODUCTION", "").lower() == "true"
    
    if is_production:
        json_data["aefProfiles"][0]["domainName"] = os.environ.get("DOMAIN_NAME", "")
        json_data["aefProfiles"][0].pop("interfaceDescriptions", None)
    else:
        nginx_host = os.environ.get("NGINX_HOST", "localhost")
        nginx_https = os.environ.get("NGINX_HTTPS", "443")
        try:
            nginx_port = int(nginx_https)
        except (ValueError, TypeError):
            nginx_port = 443
            
        json_data["aefProfiles"][0]["interfaceDescriptions"] = [{
            "ipv4Addr": nginx_host,
            "port": nginx_port,
            "securityMethods": ["OAUTH"]
        }]
        json_data["aefProfiles"][0].pop("domainName", None)
    
    return json_data


def get_service_description(service_name: str) -> dict:
    """Get a prepared service description by name.
    
    Args:
        service_name: Either "monitoring_event" or "as_session_with_qos".
        
    Returns:
        The prepared service description dict.
        
    Raises:
        KeyError: If service descriptions haven't been initialized.
    """
    if not _SERVICE_DESCRIPTIONS:
        capif_service_description()
    return _SERVICE_DESCRIPTIONS.get(service_name, {})


def capif_service_description() -> None:
    """Prepare CAPIF service descriptions in memory.
    
    Reads the base JSON templates and applies environment-specific
    modifications. Results are stored in _SERVICE_DESCRIPTIONS for
    later retrieval - source files are NOT modified.
    """
    global _SERVICE_DESCRIPTIONS
    
    base_path = os.path.join(
        os.path.dirname(__file__), 
        'core', 'capif_files'
    )
    
    services = {
        "monitoring_event": "service_monitoring_event.json",
        "as_session_with_qos": "service_as_session_with_qos.json"
    }
    
    try:
        for service_key, filename in services.items():
            filepath = os.path.join(base_path, filename)
            with open(filepath, 'r') as file:
                json_data = json.load(file)
            
            # Prepare the service description in memory (no file write)
            _prepare_aef_profile(json_data)
            _SERVICE_DESCRIPTIONS[service_key] = json_data
            
        logger.info("Service descriptions prepared in memory successfully")
        
    except FileNotFoundError as e:
        logger.error("Service description file not found: %s", e)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in service description file: %s", e)
    except (KeyError, IndexError) as e:
        logger.error("Malformed service description structure: %s", e)

def main() -> None:
    logger.info("Creating initial data")
    init()
    capif_service_description()
    logger.info("Initial data created")
    logger.info("Trying to connect with CAPIF Core Function")
    if capif_nef_connector():
        logger.info("Successfully onboard NEF in the CAPIF Core Function")
    else:
        logger.info("Failed to onboard NEF in the CAPIF Core Function")


if __name__ == "__main__":
    configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
    main()
