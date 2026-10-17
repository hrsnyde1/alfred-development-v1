#!/usr/bin/env bash
# Reviewed operator transaction for the existing Development Intake only.
set -Eeuo pipefail

if [[ $# -ne 1 || ( $1 != install && $1 != rollback ) ]]; then
  printf 'usage: %s install|rollback\n' "$0" >&2
  exit 2
fi
if [[ $EUID -ne 0 ]]; then
  printf 'BLOCKED: run as the host administrator\n' >&2
  exit 2
fi

MODE=$1
STAGE=/home/alfred/alfred-development-lab/milestone2/task-a
ROOT=/opt/alfred-developer-v1
PACKAGE=$ROOT/developer_v1
INTAKE=/usr/local/lib/alfred-v1.1/trusted_intake.py
BACKUP=$ROOT/publication-approval-backup-v1
PLAN=/var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json
AUTH=/var/lib/alfred-draft-pr-authorizations/T-0002.json
SYSTEMCTL=/usr/bin/systemctl
OLD_RELEASE=586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c
OLD_INTAKE=cef079f4041aea439a3bb58f4ea728e9dd38ae45b4258a1183c962670b0c4a6f
NEW_RELEASE=32f6b3c717b044a9e516314984dea314c9d448b4d1c59b9bc1407932e269f568
NEW_INTAKE=01c8911332d2314ccbe8db187a4a6d3ba63ceb9d2475c2ad252af7c9a1855ef0
PLAN_SHA=511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903
FILES=(owner_grants.py trusted_intake_development.py publication_approval.py stage_publication.py host_install.py install_config.py release.sha256)
MUTATION_STARTED=0
COMMITTED=0
GATEWAY_BEFORE=

hash_is() {
  [[ $(/usr/bin/sha256sum "$2" | /usr/bin/cut -d ' ' -f 1) == "$1" ]]
}
release_is() {
  hash_is "$1" "$2/release.sha256" || return 1
  (cd "$(/usr/bin/dirname "$2")" && /usr/bin/sha256sum -c "$(/usr/bin/basename "$2")/release.sha256" >/dev/null)
}
services_healthy() {
  "$SYSTEMCTL" is-active --quiet alfred-development-intake.service alfred-photon.service alfred-hermes.service
}
gateway_state() {
  "$SYSTEMCTL" show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer | /usr/bin/sha256sum | /usr/bin/cut -d ' ' -f 1
}

authorization_absent() {
  [[ ! -e $AUTH && ! -L $AUTH ]]
}

precheck_install() {
  [[ ! -e $BACKUP && ! -L $BACKUP ]] || return 1
  [[ -f $ROOT/active && ! -L $ROOT/active ]] || return 1
  [[ $(/usr/bin/stat -c %u:%a "$ROOT/active") == 0:644 ]] || return 1
  authorization_absent || return 1
  hash_is "$PLAN_SHA" "$PLAN" || return 1
  release_is "$OLD_RELEASE" "$PACKAGE" || return 1
  hash_is "$OLD_INTAKE" "$INTAKE" || return 1
  release_is "$NEW_RELEASE" "$STAGE/developer_v1" || return 1
  hash_is "$NEW_INTAKE" "$STAGE/developer_v1/trusted_intake_development.py" || return 1
  services_healthy || return 1
  GATEWAY_BEFORE=$(gateway_state) || return 1
}

precheck_rollback() {
  [[ -d $BACKUP/developer_v1 && -f $BACKUP/trusted_intake.py ]] || return 1
  release_is "$OLD_RELEASE" "$BACKUP/developer_v1" || return 1
  hash_is "$OLD_INTAKE" "$BACKUP/trusted_intake.py" || return 1
  [[ -f $ROOT/active || -f $BACKUP/active ]] || return 1
  if [[ -z $GATEWAY_BEFORE ]]; then
    GATEWAY_BEFORE=$(gateway_state) || return 1
  fi
}

restore_previous() {
  # Each command is checked explicitly because this function runs in an EXIT trap.
  precheck_rollback || return 1
  if [[ -f $ROOT/active ]]; then
    [[ ! -e $BACKUP/active ]] || return 1
    /usr/bin/mv -T "$ROOT/active" "$BACKUP/active" || return 1
  fi
  if [[ -d $PACKAGE ]] && release_is "$OLD_RELEASE" "$PACKAGE"; then
    : # A prior rollback restored code but stopped before service verification.
  else
    if [[ -d $PACKAGE ]]; then
      [[ ! -e $BACKUP/developer_v1.failed ]] || return 1
      /usr/bin/mv -T "$PACKAGE" "$BACKUP/developer_v1.failed" || return 1
    fi
    /usr/bin/cp -a "$BACKUP/developer_v1" "$PACKAGE" || return 1
  fi
  /usr/bin/install -m 0644 "$BACKUP/trusted_intake.py" "$INTAKE.next" || return 1
  /usr/bin/mv -T "$INTAKE.next" "$INTAKE" || return 1
  release_is "$OLD_RELEASE" "$PACKAGE" || return 1
  hash_is "$OLD_INTAKE" "$INTAKE" || return 1
  "$SYSTEMCTL" restart alfred-development-intake.service || return 1
  services_healthy || return 1
  [[ $(gateway_state) == "$GATEWAY_BEFORE" ]] || return 1
  /usr/bin/mv -T "$BACKUP/active" "$ROOT/active" || return 1
  [[ $(/usr/bin/stat -c %u:%a "$ROOT/active") == 0:644 ]] || return 1
}

on_exit() {
  local status=$?
  trap - EXIT
  if [[ $status -eq 0 && $COMMITTED -eq 1 ]]; then
    exit 0
  fi
  if [[ $MODE == install && $MUTATION_STARTED -eq 1 ]]; then
    printf 'Installation failed; attempting the pinned rollback.\n' >&2
    if restore_previous; then
      printf 'ROLLED_BACK: previous Intake and development activation restored.\n' >&2
      exit 1
    fi
  fi
  printf 'BLOCKED: transaction incomplete; inspect %s/active and %s/active. Do not run a worker.\n' "$ROOT" "$BACKUP" >&2
  exit 1
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ $MODE == rollback ]]; then
  restore_previous
  COMMITTED=1
  printf 'ROLLED_BACK: previous Intake and development activation restored.\n'
  exit 0
fi

precheck_install
/usr/bin/install -d -m 0700 "$BACKUP"
/usr/bin/cp -a "$PACKAGE" "$BACKUP/developer_v1"
/usr/bin/cp -a "$INTAKE" "$BACKUP/trusted_intake.py"
/usr/bin/install -d -m 0700 "$BACKUP/staged"
for name in "${FILES[@]}"; do
  /usr/bin/install -m 0644 "$STAGE/developer_v1/$name" "$BACKUP/staged/$name"
done
hash_is "$NEW_RELEASE" "$BACKUP/staged/release.sha256"
for name in "${FILES[@]}"; do
  if [[ $name == release.sha256 ]]; then continue; fi
  expected=$(/usr/bin/awk -v target="developer_v1/$name" '$2 == target { print $1 }' "$BACKUP/staged/release.sha256")
  [[ $expected =~ ^[0-9a-f]{64}$ ]] && hash_is "$expected" "$BACKUP/staged/$name"
done
precheck_rollback
MUTATION_STARTED=1
/usr/bin/mv -T "$ROOT/active" "$BACKUP/active"
for name in "${FILES[@]}"; do
  /usr/bin/install -m 0644 "$BACKUP/staged/$name" "$PACKAGE/$name.next"
  /usr/bin/mv -T "$PACKAGE/$name.next" "$PACKAGE/$name"
done
/usr/bin/install -m 0644 "$BACKUP/staged/trusted_intake_development.py" "$INTAKE.next"
/usr/bin/mv -T "$INTAKE.next" "$INTAKE"
release_is "$NEW_RELEASE" "$PACKAGE"
hash_is "$NEW_INTAKE" "$INTAKE"
"$SYSTEMCTL" restart alfred-development-intake.service
services_healthy
[[ $(gateway_state) == "$GATEWAY_BEFORE" ]]
/usr/bin/mv -T "$BACKUP/active" "$ROOT/active"
[[ $(/usr/bin/stat -c %u:%a "$ROOT/active") == 0:644 ]]
COMMITTED=1
printf 'INSTALLED: existing Intake only; publication challenge remains unstaged.\n'
