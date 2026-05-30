#!/bin/bash
# Aliases for agent commands

tfrg() {
  local p1="$1"
  trussflow requirement get "$p1" --json
}

trfl() {
  local p1="$1"
  trussflow requirement list --include ruid,scope,text --parent "$p1" --json
}

trfla() {
  local p1="$1"
  trussflow requirement list --parent "$p1" --json
}

trflr() {
  trussflow requirement list --root --json
}

trfcr() {
  local p1="$1"
  local p2="$2"
  local p3="$3:in"
  trussflow requirement create-root --rs p --text "$p1" --rationale "$p2" --scope "$p3" --json
}
