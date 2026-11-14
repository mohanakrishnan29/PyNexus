import scrapy


class CrawledPageItem(scrapy.Item):
    """Raw-document schema consumed unchanged by ``backend.ingestion``."""
    url = scrapy.Field()
    title = scrapy.Field()
    text = scrapy.Field()
    headings = scrapy.Field()
