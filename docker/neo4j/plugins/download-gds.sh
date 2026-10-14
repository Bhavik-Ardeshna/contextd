#!/bin/bash
set -euo pipefail

GDS_URL="https://graphdatascience.ninja/neo4j-graph-data-science-2.25.0.jar"
GDS_JAR="/plugins/neo4j-graph-data-science-2.25.0.jar"

if [ ! -f "$GDS_JAR" ]; then
  if ! command -v curl >/dev/null 2>&1; then
    apt-get update && apt-get install -y curl
  fi
  echo "Downloading GDS 2.25.0..."
  curl -L -o "$GDS_JAR" "$GDS_URL"
fi
