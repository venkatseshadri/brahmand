#!/bin/bash
# Pull latest git code from all repos in a parent directory.
# Usage: cd ~/GitHub && bash pull_all.sh
#
# Repos expected in the current directory (update these names):
REPOS=("brahmand" "antariksh" "python-trader" "ShoonyaApi-py")

set -euo pipefail

PARENT="$(pwd)"
echo "Pulling latest from ${#REPOS[@]} repos in $PARENT"
echo ""

for repo in "${REPOS[@]}"; do
    if [ ! -d "$PARENT/$repo/.git" ]; then
        echo "  ⚠ $repo — not a git repo, skipping"
        continue
    fi
    cd "$PARENT/$repo"
    BRANCH=$(git branch --show-current)
    echo "  📂 $repo ($BRANCH)"
    git pull --ff-only 2>&1 | sed 's/^/    /'
    echo ""
done

echo "Done."
