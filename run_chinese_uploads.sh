#!/usr/bin/env bash
# Batch upload four junior-high Chinese textbooks to Ximalaya.
# Runs sequentially with the persistent login profile.
set -u

PROJECT_DIR="/Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya-bulk-uploader"
PROFILE="/Users/yezi/WorkBuddy/2026-08-11-22-09-49/ximalaya_uploader/xmly_profile"
PY="/Users/yezi/.workbuddy/binaries/python/envs/default/bin/python"
LOG="/tmp/xmly_chinese_uploads.log"

# album_name:folder:album_id
JOBS=(
  "八上语文-课文:/Users/yezi/Downloads/八上语文:129010581"
  "八下语文-课本:/Users/yezi/Downloads/八下语文:129010693"
  "九下语文-课文:/Users/yezi/Downloads/九下语文:129010714"
  "九上语文-课本:/Users/yezi/Downloads/九上语文:129010739"
)

cd "$PROJECT_DIR" || exit 1
: > "$LOG"

for spec in "${JOBS[@]}"; do
  IFS=: read -r album folder album_id <<< "$spec"
  {
    echo ""
    echo "============================================================"
    echo "Job: $album  ($folder)  album_id=$album_id"
    echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
  } >> "$LOG"

  "$PY" uploader.py \
    --folder "$folder" \
    --album "$album" \
    --album-id "$album_id" \
    --profile "$PROFILE" \
    --order chapter-first \
    --visibility public \
    --yes \
    >> "$LOG" 2>&1

  rc=$?
  {
    echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')  exit=$rc"
  } >> "$LOG"
done

echo "All jobs finished. Log: $LOG"
