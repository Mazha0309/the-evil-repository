#!/usr/bin/env sh
set -eu

project_version="$(tr -d '[:space:]' < VERSION)"
root_version="$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' package.json | head -n 1)"
web_version="$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' apps/web/package.json | head -n 1)"
api_version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' apps/api/pyproject.toml | head -n 1)"
runtime_version="$(sed -n 's/^VERSION = "\([^"]*\)"/\1/p' apps/api/app/version.py | head -n 1)"

for candidate in "$root_version" "$web_version" "$api_version" "$runtime_version"; do
  if [ "$candidate" != "$project_version" ]; then
    echo "Version mismatch: VERSION=$project_version but found $candidate" >&2
    exit 1
  fi
done

echo "Platform version $project_version is synchronized."
