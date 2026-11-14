from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def raw_filename(url: str) -> str:
    """Return the legacy stable filename format for a crawled URL."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    path = urlparse(url).path.strip("/").replace("/", "_") or "index"
    path = re.sub(r"[^A-Za-z0-9._-]", "_", path)[:80]
    return f"{path}_{digest}.json"


class RawJsonPipeline:
    """Persist Scrapy items in the JSON schema expected by the ingestor."""
    def open_spider(self, spider):
        self.output_dir = Path(spider.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_item(self, item, spider):
        payload = {key: item.get(key) for key in ("url", "title", "text", "headings")}
        with (self.output_dir / raw_filename(payload["url"])).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        spider.pages_saved += 1
        spider.logger.info("Saved %s", payload["url"])
        return item


