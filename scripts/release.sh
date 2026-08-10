#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: bash scripts/release.sh VERSION" >&2
  echo "example: bash scripts/release.sh 0.1.0" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
VERSION="$1"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "error: VERSION must be MAJOR.MINOR.PATCH, got: $VERSION" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

bash "$SCRIPT_DIR/release-check.sh" "$VERSION"

command -v gh >/dev/null 2>&1 || {
  echo "error: GitHub CLI (gh) is required to create the GitHub Release" >&2
  echo "install it, then run: gh auth login" >&2
  exit 2
}
gh auth status >/dev/null

TAG="robo-papyro-v${VERSION}"
NOTES="docs/releases/${TAG}.md"
COMMIT="$(git rev-parse HEAD)"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "error: GitHub Release already exists: $TAG" >&2
  gh release view "$TAG" --repo "$REPO" --json url --jq .url >&2 || true
  exit 1
fi

REMOTE_DIRECT="$(git ls-remote --tags origin "refs/tags/$TAG" | awk 'NR==1 {print $1}')"
REMOTE_PEELED="$(git ls-remote --tags origin "refs/tags/${TAG}^{}" | awk 'NR==1 {print $1}')"
REMOTE_COMMIT="${REMOTE_PEELED:-$REMOTE_DIRECT}"

if [[ -n "$REMOTE_COMMIT" && "$REMOTE_COMMIT" != "$COMMIT" ]]; then
  echo "error: remote tag $TAG already exists and does not point to current main" >&2
  echo "  current main: $COMMIT" >&2
  echo "  remote tag:   $REMOTE_COMMIT" >&2
  echo "tags are permanent release identifiers; refusing to move it" >&2
  exit 1
fi

cat <<EOF

Ready to publish beta release:
  repository: $REPO
  version:    $VERSION
  tag:        $TAG
  commit:     $COMMIT
  notes:      $NOTES
EOF

read -r -p "Create this GitHub pre-release? [y/N] " ANSWER
case "$ANSWER" in
  y|Y|yes|YES) ;;
  *) echo "release cancelled"; exit 0 ;;
esac

if [[ -z "$REMOTE_COMMIT" ]]; then
  if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    LOCAL_TAG_COMMIT="$(git rev-list -n 1 "$TAG")"
    [[ "$LOCAL_TAG_COMMIT" == "$COMMIT" ]] || {
      echo "error: local tag $TAG exists and points to $LOCAL_TAG_COMMIT, not $COMMIT" >&2
      exit 1
    }
    echo "==> Pushing existing local tag $TAG"
  else
    echo "==> Creating annotated tag $TAG"
    git tag -a "$TAG" -m "robo-papyro $VERSION beta"
  fi
  git push origin "$TAG"
else
  echo "==> Remote tag $TAG already exists at this commit; reusing it"
fi

echo "==> Creating GitHub pre-release"
gh release create "$TAG" \
  --repo "$REPO" \
  --verify-tag \
  --title "robo-papyro $VERSION — Beta" \
  --prerelease \
  --notes-file "$NOTES"

echo
echo "Release created:"
gh release view "$TAG" --repo "$REPO" --json url --jq .url
