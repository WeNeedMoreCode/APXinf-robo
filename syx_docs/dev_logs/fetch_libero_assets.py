"""Fetch lerobot/libero-assets into the libero package's expected assets path,
single-worker to dodge hf-mirror 429 rate limiting."""
import time

from huggingface_hub import snapshot_download

DEST = "/usr/local/lib/python3.11/site-packages/libero/libero/assets"

for attempt in range(8):
    try:
        p = snapshot_download(
            repo_id="lerobot/libero-assets",
            repo_type="dataset",
            local_dir=DEST,
            max_workers=2,
        )
        print("ASSETS_OK:", p)
        break
    except Exception as e:
        print(f"attempt {attempt}: {type(e).__name__}: {str(e)[:200]}")
        time.sleep(20 * (attempt + 1))
else:
    raise SystemExit("ASSETS_FAILED")
