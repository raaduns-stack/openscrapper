from src.models.criteria import CrawlerConfig
from src.collector.collection_controller import CollectionController
from src.models.criteria import CrawlerConfig


def test_crawl_pages_and_urls_are_independent():
    config = CrawlerConfig(max_crawl_pages=25, max_crawl_urls=250)
    controller = CollectionController(config=config)
    assert controller.config.max_crawl_pages == 25
    assert controller.config.max_crawl_urls == 250
    assert controller.collector.max_pages == 25
    assert controller.collector.max_urls == 250
    assert controller.collector.max_urls == 250


def test_crawler_config_defaults_are_explicit():
    config = CrawlerConfig()
    assert config.max_crawl_pages is None
    assert config.max_crawl_urls is None
    assert config.max_crawl_depth is None
    assert config.max_pagination_pages is None


def test_independent_limits_validate_positive_values():
    import pytest

    with pytest.raises(ValueError):
        CrawlerConfig(max_crawl_urls=0)
