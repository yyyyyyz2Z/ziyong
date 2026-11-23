#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
  printf 'Usage: bash scripts/export-github.sh ~/piano-coach-github\n' >&2
  exit 2
fi

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
destination=$1
if [[ -e "$destination" || -L "$destination" ]]; then
  printf 'Destination already exists: %s\n' "$destination" >&2
  exit 2
fi

manifest=$(mktemp)
trap 'rm -f -- "$manifest"' EXIT
git -c "safe.directory=$source_root" -C "$source_root" ls-files -z --cached --others --exclude-standard -- \
  .gitignore .dockerignore README.md backend deploy frontend tests training_sites pianocv_lab docs > "$manifest"

mkdir -- "$destination"
destination=$(cd -- "$destination" && pwd -P)
while IFS= read -r -d '' file; do
  case "$file" in
    .gitignore|.dockerignore|README.md|backend/*.py|backend/requirements.txt|backend/analysis/piano_technique_graph.json|\
    deploy/.env.example|deploy/Caddyfile|deploy/Dockerfile|deploy/compose.yml|\
    docs/人工验收报告.md|docs/后端接入与测试说明.md|docs/数据库与部署.md|\
    pianocv_lab/README.md|pianocv_lab/index.html|pianocv_lab/package.json|pianocv_lab/package-lock.json|\
    pianocv_lab/vite.config.js|pianocv_lab/src/*.js|pianocv_lab/src/*.css|pianocv_lab/scripts/download-model.mjs|\
    frontend/.npmrc|frontend/.openai/hosting.json|frontend/index.html|frontend/README.md|\
    frontend/package.json|frontend/package-lock.json|frontend/vite.config.mjs|\
    frontend/src/*.jsx|frontend/src/*.css|frontend/src/pianocv/*.js|frontend/scripts/*.mjs|frontend/tests/*.mjs|frontend/worker/*.js|\
    frontend/public/assets/piano-hero.png|frontend/public/assets/reference.jpg|frontend/public/assets/performance-preview.jpg|\
    tests/test_*.py|training_sites/*.py|training_sites/requirements.txt|training_sites/README.md|\
    training_sites/web/*.html|training_sites/web/*.js|training_sites/web/*.css)
      if [[ ! -f "$source_root/$file" || -L "$source_root/$file" ]]; then
        printf 'Expected a regular file: %s\n' "$file" >&2
        exit 1
      fi
      install -D -m 0644 -- "$source_root/$file" "$destination/$file"
      ;;
  esac
done < "$manifest"

for required in README.md deploy/.env.example backend/api_server.py frontend/package-lock.json training_sites/server.py pianocv_lab/package-lock.json; do
  if [[ ! -f "$destination/$required" ]]; then
    printf 'Export is missing a required file: %s\n' "$required" >&2
    exit 1
  fi
done

printf 'Exported release files to %s\n' "$destination"
