#!/usr/bin/env bash
# Installs the shared git hooks into .git/hooks
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
cp scripts/git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "pre-commit secret scanner installed."
