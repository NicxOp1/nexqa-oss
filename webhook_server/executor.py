import logging
from typing import Any
from webhook_server.models import FunctionConfig, ConnectorType
from webhook_server.connectors import (
    CalcomConnector,
    AirtableConnector,
    RetellSMSConnector,
    RetellNativeConnector,
)

logger = logging.getLogger(__name__)

# Singletons for connectors (they are stateless mostly)
_connectors = {
    ConnectorType.CALCOM: CalcomConnector(),
    ConnectorType.AIRTABLE: AirtableConnector(),
    ConnectorType.RETELL_SMS: RetellSMSConnector(),
    ConnectorType.RETELL_NATIVE: RetellNativeConnector(),
}


async def execute_function(
    function_name: str,
    arguments: dict[str, Any],
    function_config: FunctionConfig,
) -> str:
    """
    Dispatch function execution to the appropriate connector.
    """
    connector = _connectors.get(function_config.connector)
    if not connector:
        logger.error(f"Unknown connector type: {function_config.connector}")
        return "I'm having a technical issue connecting to that service."
    
    try:
        logger.info(f"Executing {function_name} via {function_config.connector}")
        result = await connector.execute(
            function_name=function_name,
            arguments=arguments,
            config=function_config.config,
        )
        logger.info(f"Function result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Execution failed for {function_name}: {e}", exc_info=True)
        return "I ran into a problem processing that request. Could you try again?"
