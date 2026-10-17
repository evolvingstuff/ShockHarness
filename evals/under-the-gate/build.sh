#!/usr/bin/env bash
# The under-the-gate experiment's builds: every spec in specs/, built twice by the same
# agent (Claude Code headless, its default model), once with ShockHarness (strict
# configuration, skills, edit-time hook) and once without. The builder sees only
# SPEC.md (and, gated, the ShockHarness files); never this script or the review rubric.
#
#   evals/under-the-gate/build.sh OUT_DIR SHOCKHARNESS_BIN_DIR CLAUDE_BIN MODEL
#
# Each builder starts with a clean environment (HOME, USER, TERM, PATH only), so a
# Claude desktop app's session variables cannot redirect its authentication.
#
# OUT_DIR/<spec>-<variant>/ is the build; OUT_DIR/logs/<spec>-<variant>.jsonl is the
# builder's tool-call stream (stream-json), from which hook blocks are extracted.
set -euo pipefail

out="$1"
shockharness_bin="$2"
claude_bin="$3"
model="$4"
# The PATH builders get: system tools and node, never ShockHarness (unless gated).
BASE_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out/logs"

prompt_ungated="Build what SPEC.md describes, in this directory. You are done when the tests pass."
prompt_gated="$prompt_ungated This repository uses ShockHarness: \`shockharness check .\` must report \`gate: PASS\` before you are done."

prepare() {
  local spec="$1" variant="$2" dir="$out/$(basename "$spec" .md)-$variant"
  rm -rf "$dir"
  mkdir -p "$dir"
  cp "$spec" "$dir/SPEC.md"
  if [ "$variant" = gated ]; then
    cat > "$dir/.shockharness.toml" <<'TOML'
[tool.shockharness]
profile = "strict"
include = ["**/*.py", "**/*.js", "**/*.mjs"]
exclude = ["**/node_modules/**", ".claude/**", "**/.venv/**"]
TOML
    PATH="$shockharness_bin:$PATH" shockharness skills install --agent claude --project "$dir" --hook > /dev/null
  fi
  git -C "$dir" init -q
  echo "$dir"
}

build() {
  local dir="$1" name variant prompt path
  name="$(basename "$dir")"
  variant="${name##*-}"
  if [ "$variant" = gated ]; then
    prompt="$prompt_gated"
    path="$shockharness_bin:$BASE_PATH"
  else
    prompt="$prompt_ungated"
    path="$BASE_PATH"
  fi
  local started
  started="$(date +%s)"
  (cd "$dir" && env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" TERM=xterm PATH="$path" \
    timeout 3600 "$claude_bin" -p "$prompt" --model "$model" --output-format stream-json \
    --verbose --permission-mode bypassPermissions > "$out/logs/$name.jsonl" 2> "$out/logs/$name.err") \
    || echo "exit $?" > "$out/logs/$name.exit"
  echo "$name $(( $(date +%s) - started ))s" >> "$out/logs/durations.txt"
}
export -f build
export out shockharness_bin claude_bin model BASE_PATH prompt_gated prompt_ungated

dirs=()
for spec in "$here"/specs/*.md; do
  for variant in gated ungated; do
    dirs+=("$(prepare "$spec" "$variant")")
  done
done
if [ "${DRY_RUN:-0}" = 1 ]; then printf "%s\n" "${dirs[@]}"; exit 0; fi
printf '%s\n' "${dirs[@]}" | xargs -P 4 -I{} bash -c 'build "$@"' _ {}
echo "done: ${#dirs[@]} builds in $out"
