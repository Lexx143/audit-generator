#!/usr/bin/env bash
# Pinned upstream release; no GitHub or production credentials are required.
set -euo pipefail
mode=${1:-git}
case "$mode" in git|tree) ;; *) echo "usage: $0 [git|tree]" >&2; exit 2 ;; esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  -o "$tmp/gitleaks.tar.gz"
echo "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  $tmp/gitleaks.tar.gz" | sha256sum --check --status
tar -xzf "$tmp/gitleaks.tar.gz" -C "$tmp" gitleaks
if [[ $mode == tree ]]; then
  mkdir "$tmp/tree"
  git archive HEAD | tar -xf - -C "$tmp/tree"
  "$tmp/gitleaks" dir --no-banner --redact=100 --exit-code 1 "$tmp/tree"
else
  "$tmp/gitleaks" git --no-banner --redact=100 --exit-code 1 .
fi
