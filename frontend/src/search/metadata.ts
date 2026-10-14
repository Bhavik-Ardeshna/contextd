const CONTEXTD_SYSTEM_METADATA_KEY = "contextd_system_metadata";

const SYSTEM_METADATA_PREFIXES = [
  `${CONTEXTD_SYSTEM_METADATA_KEY}.`,
];

type SearchPayload = Record<string, unknown>;

type SystemMetadata = {
  source_name?: string;
  entity_type?: string;
  [key: string]: unknown;
};

function isRecord(value: unknown): value is SearchPayload {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function getSystemMetadata(payload: SearchPayload | null | undefined): SystemMetadata {
  if (!payload) return {};
  const metadata = payload[CONTEXTD_SYSTEM_METADATA_KEY];
  return isRecord(metadata) ? (metadata as SystemMetadata) : {};
}

export function isSystemMetadataKey(key: string) {
  return key === CONTEXTD_SYSTEM_METADATA_KEY;
}

export function stripSystemMetadataPrefixFromFilter<T>(input: T): T {
  const clone = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(clone);
    if (isRecord(value)) {
      const output: SearchPayload = {};
      for (const key of Object.keys(value)) {
        output[key] = clone(value[key]);
      }
      if (typeof output.key === "string") {
        for (const prefix of SYSTEM_METADATA_PREFIXES) {
          if (output.key.startsWith(prefix)) {
            output.key = output.key.slice(prefix.length);
            break;
          }
        }
      }
      return output;
    }
    return value;
  };

  return clone(input) as T;
}
