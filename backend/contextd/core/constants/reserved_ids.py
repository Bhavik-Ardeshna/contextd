"""Constants for native connections."""

import uuid

# Native connection UUIDs - these must match the ones in init_db_native.py
NATIVE_NEO4J_UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# String versions for use in frontend code or string contexts
NATIVE_NEO4J_UUID_STR = str(NATIVE_NEO4J_UUID)

# Entity definition UUIDs - these must match the ones in init_db_native.py
# Disparate from the native connection UUIDs
RESERVED_TABLE_ENTITY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
RESERVED_TABLE_ENTITY_ID_STR = str(RESERVED_TABLE_ENTITY_ID)
