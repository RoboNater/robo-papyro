# Releasing robo-papyro

robo-papyro is a monorepo containing independently versioned Python distributions. Suite
releases identify a tested combination of those distributions; individual distributions may
have different version numbers.

## Version and tag policy

The umbrella distribution follows semantic versioning. While it is pre-1.0:

- `0.1.1` is an incremental bug-fix release of the `0.1` line.
- `0.2.0` is appropriate for a significant feature increment or an incompatible interface
  change.
- `1.0.0` means the public CLI and Python interfaces are considered stable enough to support
  with normal semantic-versioning compatibility expectations.

Suite tags are namespaced so they cannot be confused with independently versioned leaf
packages:

```text
robo-papyro-v0.1.0
```

If a leaf package later needs its own release tag, use the same explicit namespace, for
example `rp-pdf-v0.4.1`.

Tags are permanent release identifiers and must never be moved after publication.

## Prerequisites

Release from a clean checkout with:

- `git`
- `uv`
- GitHub CLI (`gh`), authenticated with `gh auth login`

The release script performs its own preflight checks before it creates or pushes a tag.

## Prepare a release

Before merging release preparation:

1. Update the umbrella version in `packages/robo-papyro/pyproject.toml` if needed.
2. Update `CHANGELOG.md` with the suite version and exact component versions.
3. Add `docs/releases/robo-papyro-v<VERSION>.md` with release notes and known limitations.
4. Ensure CI is green.

For the first beta, those files describe `robo-papyro` 0.1.0 and the tag
`robo-papyro-v0.1.0`.

## Validate locally

From the repository root:

```sh
bash scripts/release-check.sh 0.1.0
```

The check refuses to pass unless:

- the checkout is on `main`, clean, and exactly matches `origin/main`;
- the requested version matches the umbrella package version;
- matching changelog and release-notes entries exist;
- the locked environment syncs;
- the license gate, ruff checks, and full pytest suite pass;
- the umbrella CLI starts and `rp doctor` runs.

Some tests are intentionally skipped when optional external binaries are unavailable. CI is
the authoritative cross-environment gate; do not release unless the `main` CI run is green.

## Create the tag and GitHub Release

Run:

```sh
bash scripts/release.sh 0.1.0
```

The script:

1. runs `release-check.sh`;
2. confirms `gh` authentication;
3. shows the exact `main` commit being released;
4. asks for confirmation;
5. creates and pushes annotated tag `robo-papyro-v<VERSION>` if it does not already exist;
6. creates a GitHub **pre-release** using the matching file in `docs/releases/`.

The operation is deliberately recoverable. If the tag reaches GitHub but GitHub Release
creation fails, rerun the same command: the script reuses the existing tag rather than trying
to move or replace it.

After 1.0, remove `--prerelease` from `scripts/release.sh` when stable releases become the
default policy.

## PyPI

GitHub beta releases and PyPI publication are intentionally separate. Do not publish the
suite to PyPI until the inter-package dependency-version policy and automated publication
workflow are defined. A repository/tag-based beta does not require PyPI.
