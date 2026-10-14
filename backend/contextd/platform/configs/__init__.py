"""Platform configuration modules."""

from contextd.platform.configs._base import (
    BaseConfig,
    ConfigField,
    ConfigValues,
    Fields,
    RequiredTemplateConfig,
)
from contextd.platform.configs.index import (
    FulltextIndexConfig,
    IndexConfig,
    get_index_config,
)

__all__ = [
    # Base config
    "BaseConfig",
    "ConfigField",
    "ConfigValues",
    "Fields",
    "RequiredTemplateConfig",
    # Index config
    "IndexConfig",
    "FulltextIndexConfig",
    "get_index_config",
]
