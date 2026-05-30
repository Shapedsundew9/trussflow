#!/bin/bash

set -eu

LOG_FILE="/tmp/devcontainer-post-start.log"
echo "--- Running post-start script ---" | tee -a "$LOG_FILE"