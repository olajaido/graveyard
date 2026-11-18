#!/usr/bin/env bash
# Offline infrastructure checks from tool images pinned by digest.
# Design: .kiro/specs/infra-foundation/design.md section 0 (working rule), section 7.
#
# Every container gets the repository and a provider cache mounted, and no variable
# from the host environment. Nothing here talks to a cloud account or a state backend.
#
# Usage: scripts/ci/local-checks.sh <fmt|fmt-write|validate|test|tflint|checkov|actionlint|guards|lock DIR|all>
set -euo pipefail

# Single place for the image references (keep in step with infra/.tool-versions; checked below).
TERRAFORM_IMAGE="hashicorp/terraform:1.17.2@sha256:6e9c1e647c31a960dc9b59e13272f9111d90010c10b717f77ffb324767660475"
TFLINT_IMAGE="ghcr.io/terraform-linters/tflint:v0.66.0@sha256:65b9944a9274c4989492c1d79998c2801664bf8a55fddb4bd3a9e6d73a006ddc"
CHECKOV_IMAGE="bridgecrew/checkov:3.4.5@sha256:122602cf32cc72286155d39f1f234b7b594818f7b8d7fdf490701620e521368b"
ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/graveyard-tf-plugins"
ROOTS=(infra/bootstrap infra/envs/dev infra/envs/prod)

die() { printf '%s\n' "$*" >&2; exit 2; }

# Version of an image reference: text after the last colon of the name part, without a leading v.
image_version() {
  local ref="${1%%@*}" tag
  tag="${ref##*:}"
  printf '%s' "${tag#v}"
}

check_versions() {
  local file="$REPO/infra/.tool-versions" name want got
  [ -f "$file" ] || die "missing infra/.tool-versions"
  for pair in "terraform:$TERRAFORM_IMAGE" "tflint:$TFLINT_IMAGE" "checkov:$CHECKOV_IMAGE" "actionlint:$ACTIONLINT_IMAGE"; do
    name="${pair%%:*}"
    got="$(image_version "${pair#*:}")"
    want="$(awk -v n="$name" '$1 == n { print $2 }' "$file")"
    [ "$want" = "$got" ] || die "version mismatch for $name: infra/.tool-versions has '$want', script image has '$got'"
  done
}

# run_in IMAGE WORKDIR USE_CACHE [--entrypoint NAME] -- ARGS...
run_in() {
  local image="$1" workdir="$2" use_cache="$3"
  shift 3
  local extra=()
  if [ "${1:-}" = "--entrypoint" ]; then
    extra=(--entrypoint "$2")
    shift 2
  fi
  [ "${1:-}" = "--" ] && shift
  local cache_args=()
  if [ "$use_cache" = "cache" ]; then
    mkdir -p "$CACHE"
    cache_args=(-v "$CACHE:/plugin-cache" -e TF_PLUGIN_CACHE_DIR=/plugin-cache -e TFLINT_PLUGIN_DIR=/plugin-cache/tflint)
  fi
  docker run --rm --user "$(id -u):$(id -g)" -v "$REPO:/repo" ${cache_args[@]+"${cache_args[@]}"} -e TF_IN_AUTOMATION=1 -e CHECKPOINT_DISABLE=1 -e HOME=/tmp -w "/repo/$workdir" ${extra[@]+"${extra[@]}"} "$image" "$@"
}

tf() { local dir="$1"; shift; run_in "$TERRAFORM_IMAGE" "$dir" cache -- "$@"; }

# Roots and modules that exist and hold at least one .tf file.
existing_dirs() {
  local d
  for d in "${ROOTS[@]}" "$@"; do
    if [ -d "$REPO/$d" ] && compgen -G "$REPO/$d/*.tf" >/dev/null; then printf '%s\n' "$d"; fi
  done
}
module_dirs() {
  local d
  for d in "$REPO"/infra/modules/*/; do
    [ -d "$d" ] && printf '%s\n' "${d#"$REPO/"}" | sed 's#/$##'
  done
}
all_dirs() {
  { existing_dirs; module_dirs; } | sort -u
}

cmd_fmt() {
  [ -d "$REPO/infra" ] || die "no infra/ directory"
  tf infra fmt -check -recursive -diff
}

cmd_fmt_write() {
  [ -d "$REPO/infra" ] || die "no infra/ directory"
  tf infra fmt -recursive
}

cmd_validate() {
  local d found=0
  for d in $(all_dirs); do
    found=1
    echo "validate: $d"
    tf "$d" init -backend=false -lockfile=readonly -input=false >/dev/null
    tf "$d" validate
  done
  [ "$found" = 1 ] || echo "validate: no Terraform directories yet"
}

cmd_test() {
  local d found=0
  for d in $(module_dirs); do
    compgen -G "$REPO/$d/tests/*.tftest.hcl" >/dev/null || continue
    found=1
    echo "test: $d"
    tf "$d" init -backend=false -lockfile=readonly -input=false >/dev/null
    tf "$d" test
  done
  [ "$found" = 1 ] || echo "test: no module tests yet"
}

cmd_tflint() {
  [ -d "$REPO/infra" ] || die "no infra/ directory"
  local d found=0 config="--config=/repo/infra/.tflint.hcl"
  run_in "$TFLINT_IMAGE" infra cache -- --init "$config"
  # Roots: the tag rule runs here, because provider default_tags are visible and local module calls are followed.
  for d in $(existing_dirs); do
    found=1
    echo "tflint: $d"
    run_in "$TFLINT_IMAGE" "" cache -- "--chdir=/repo/$d" "$config"
  done
  # Modules, one by one: a module has no provider block, so the tag rule cannot see default_tags there.
  for d in $(module_dirs); do
    compgen -G "$REPO/$d/*.tf" >/dev/null || continue
    found=1
    echo "tflint: $d"
    run_in "$TFLINT_IMAGE" "" cache -- "--chdir=/repo/$d" "$config" --disable-rule=aws_resource_missing_tags
  done
  [ "$found" = 1 ] || echo "tflint: no Terraform directories yet"
}

cmd_checkov() {
  local args=(--compact --quiet --framework terraform,github_actions) found=0
  [ -d "$REPO/infra" ] && { args+=(--directory infra); found=1; }
  [ -d "$REPO/.github" ] && { args+=(--directory .github); found=1; }
  [ "$found" = 1 ] || { echo "checkov: nothing to scan yet"; return 0; }
  run_in "$CHECKOV_IMAGE" "" nocache --entrypoint checkov -- "${args[@]}"
}

cmd_actionlint() {
  if [ ! -d "$REPO/.github/workflows" ]; then echo "actionlint: no workflows yet"; return 0; fi
  run_in "$ACTIONLINT_IMAGE" "" nocache -- -color
}

cmd_guards() {
  (cd "$REPO" && python3 -m unittest discover -s scripts/ci/tests)
  if [ -f "$REPO/scripts/ci/guards.py" ]; then (cd "$REPO" && python3 scripts/ci/guards.py); fi
  if [ -f "$REPO/scripts/ci/check_kiro_not_ignored.py" ]; then (cd "$REPO" && python3 scripts/ci/check_kiro_not_ignored.py); fi
}

cmd_lock() {
  local dir="${1:-}"
  [ -n "$dir" ] || die "usage: local-checks.sh lock DIR"
  [ -d "$REPO/$dir" ] || die "no such directory: $dir"
  run_in "$TERRAFORM_IMAGE" "$dir" nocache -- providers lock -platform=linux_amd64 -platform=darwin_arm64 -platform=linux_arm64
}

main() {
  local sub="${1:-}"
  [ -n "$sub" ] || die "usage: local-checks.sh <fmt|fmt-write|validate|test|tflint|checkov|actionlint|guards|lock DIR|all>"
  shift || true
  check_versions
  case "$sub" in
    fmt) cmd_fmt ;;
    fmt-write) cmd_fmt_write ;;
    validate) cmd_validate ;;
    test) cmd_test ;;
    tflint) cmd_tflint ;;
    checkov) cmd_checkov ;;
    actionlint) cmd_actionlint ;;
    guards) cmd_guards ;;
    lock) cmd_lock "$@" ;;
    all) cmd_fmt; cmd_validate; cmd_test; cmd_tflint; cmd_checkov; cmd_actionlint; cmd_guards ;;
    *) die "unknown subcommand: $sub" ;;
  esac
}

main "$@"
