#!/usr/bin/env bash
# WSL2 preflight: increase inotify limits required by kind/K8s.
# Uses a privileged Docker container to avoid needing sudo.
set -euo pipefail

REQUIRED_INSTANCES=1024
REQUIRED_WATCHES=1048576

current=$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)
if [ "$current" -lt "$REQUIRED_INSTANCES" ]; then
  echo "==> Fixing inotify limits (current: $current, need: $REQUIRED_INSTANCES)"
  docker run --rm --privileged alpine sh -c \
    "sysctl -w fs.inotify.max_user_instances=${REQUIRED_INSTANCES} && \
     sysctl -w fs.inotify.max_user_watches=${REQUIRED_WATCHES}"
  echo "==> inotify limits updated: $(cat /proc/sys/fs/inotify/max_user_instances)"
else
  echo "==> inotify limits OK (max_user_instances=$current)"
fi
