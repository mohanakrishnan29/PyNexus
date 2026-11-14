"""Safe defaults for the PyNexus Scrapy project."""
from backend.utils.config import settings

BOT_NAME = "pynexus"
SPIDER_MODULES = ["backend.scrapy_project.spiders"]
NEWSPIDER_MODULE = "backend.scrapy_project.spiders"
ROBOTSTXT_OBEY = True
USER_AGENT = settings.crawler_user_agent
DOWNLOAD_TIMEOUT = settings.crawler_request_timeout
DOWNLOAD_DELAY = settings.crawler_download_delay
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS_PER_DOMAIN = settings.crawler_concurrent_requests_per_domain
DEPTH_LIMIT = settings.crawler_depth_limit
DEPTH_PRIORITY = 1
RETRY_ENABLED = True
RETRY_TIMES = settings.crawler_retry_times
RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504]
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = settings.crawler_download_delay
AUTOTHROTTLE_MAX_DELAY = settings.crawler_autothrottle_max_delay
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
ITEM_PIPELINES = {"backend.scrapy_project.pipelines.RawJsonPipeline": 300}
LOG_LEVEL = "INFO"
FEED_EXPORT_ENCODING = "utf-8"
