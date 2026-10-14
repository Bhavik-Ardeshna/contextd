"""Factory for creating graph components."""
import logging
from typing import Optional

from .config import GraphConfig, get_graph_config
from .constructor import GraphConstructor
from .driver.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)

# Singleton instances
_driver_instance: Optional[Neo4jDriver] = None
_constructor_instance: Optional[GraphConstructor] = None


async def get_graph_driver(config: Optional[GraphConfig] = None) -> Neo4jDriver:
    """Get or create Neo4j driver instance.

    Args:
        config: Graph configuration (uses default if not provided)

    Returns:
        Neo4j driver instance
    """
    global _driver_instance

    if _driver_instance is None:
        if config is None:
            config = get_graph_config()

        _driver_instance = Neo4jDriver(
            uri=config.uri,
            user=config.user,
            password=config.password,
            database=config.database,
        )

        # Connect and build indices
        await _driver_instance.connect()
        await _driver_instance.build_indices()

        logger.info("Neo4j driver initialized and connected")

    return _driver_instance


async def get_graph_constructor(config: Optional[GraphConfig] = None) -> GraphConstructor:
    """Get or create graph constructor instance.

    Args:
        config: Graph configuration (uses default if not provided)

    Returns:
        GraphConstructor instance
    """
    global _constructor_instance

    if _constructor_instance is None:
        if config is None:
            config = get_graph_config()

        driver = await get_graph_driver(config)
        _constructor_instance = GraphConstructor(
            driver=driver,
            batch_size=config.batch_size,
        )

        logger.info("Graph constructor initialized")

    return _constructor_instance


async def close_graph_connections():
    """Close all graph connections.

    Should be called on application shutdown.
    """
    global _driver_instance, _constructor_instance

    if _constructor_instance:
        await _constructor_instance.close()
        _constructor_instance = None

    if _driver_instance:
        await _driver_instance.close()
        _driver_instance = None

    logger.info("Graph connections closed")
