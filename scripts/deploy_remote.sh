#!/usr/bin/env bash
# Deploy the auxiliary plugin on the AstrBot host.
#
# Run this ON THE SERVER, after uploading the archive produced by
# scripts/package.py:
#
#   bash deploy_remote.sh <git-short-sha> [plugin-name]
#
# It backs up the current plugin directory, extracts the archive, drops
# __pycache__, fixes permissions, runs an import pre-check inside the container
# so load-time errors surface before AstrBot is restarted, then restarts and
# waits for the WebUI (restarting once more if the known third-party
# update-check hang leaves it down).
set -euo pipefail

SHA="${1:?usage: deploy_remote.sh <git-short-sha> [plugin-name]}"
PLUGIN_NAME="${2:-bili_platform_aux}"
PLUGIN_ROOT="${PLUGIN_ROOT:-/root/astrbot/data/plugins}"
BACKUP_DIR="${BACKUP_DIR:-/root/astrbot/plugin-backups}"
CONTAINER="${CONTAINER:-astrbot}"
WEBUI_PORT="${WEBUI_PORT:-6185}"
ARCHIVE="$BACKUP_DIR/$PLUGIN_NAME-$SHA.tar.gz"
TS=$(date +%Y%m%d-%H%M%S)

[ -f "$ARCHIVE" ] || { echo "missing archive: $ARCHIVE"; exit 2; }

if [ -e "$PLUGIN_ROOT/$PLUGIN_NAME" ]; then
  mv "$PLUGIN_ROOT/$PLUGIN_NAME" "$BACKUP_DIR/$PLUGIN_NAME.backup-$TS"
  echo "backup: $BACKUP_DIR/$PLUGIN_NAME.backup-$TS"
fi

tar -xzf "$ARCHIVE" -C "$PLUGIN_ROOT"
rm -rf "$PLUGIN_ROOT/$PLUGIN_NAME/__pycache__" \
       "$PLUGIN_ROOT/$PLUGIN_NAME/tests/__pycache__"
chmod -R a+rX "$PLUGIN_ROOT/$PLUGIN_NAME"
echo "--- deployed files ---"
ls -1 "$PLUGIN_ROOT/$PLUGIN_NAME"

echo "--- preflight: import plugin module with real AstrBot decorators ---"
# 注意：必须在 /AstrBot 下执行，否则 AstrBot 的配置模块会把默认 data/ 写到相对路径里
docker exec -w /AstrBot "$CONTAINER" python -c \
  "import importlib; mod = importlib.import_module('data.plugins.$PLUGIN_NAME.main'); print('IMPORT_OK', mod.BiliPlatformAuxPlugin.__name__); print('LLM_METHODS', len([n for n in dir(mod.BiliPlatformAuxPlugin) if n.startswith('llm_')]))"

wait_webui() {
  local ok=0 code
  for _ in 1 2 3 4 5 6 7 8; do
    sleep 15
    code=$(curl -sS -m 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$WEBUI_PORT/" 2>/dev/null || true)
    echo "  webui http=${code:-000}"
    case "${code:-000}" in
      200|301|302|401) ok=1; break ;;
    esac
  done
  return $((1 - ok))
}

echo "--- restart container ---"
docker restart "$CONTAINER" >/dev/null
if ! wait_webui; then
  echo "webui not ready (known api.stardots.io update-check hang); restarting once more"
  docker restart "$CONTAINER" >/dev/null
  wait_webui || true
fi

echo "--- result ---"
docker ps --filter "name=$CONTAINER" --format '{{.Status}}'
docker logs "$CONTAINER" --tail 200 2>&1 | grep -a "Plugin $PLUGIN_NAME (" | tail -1 || true
