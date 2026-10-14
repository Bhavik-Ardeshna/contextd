/**
 * Constants for native connections.
 * These MUST match the UUIDs defined in backend/contextd/core/constants/native_connections.py
 */

// Native connection UUIDs
export const NATIVE_NEO4J_UUID = "22222222-2222-2222-2222-222222222222";

// Map of connection short names to their UUIDs
export const NATIVE_CONNECTION_UUIDS = {
  neo4j_native: NATIVE_NEO4J_UUID,
};
