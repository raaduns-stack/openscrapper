"""HTTP collection interfaces for discovery candidates."""

from src.collector.collection_controller import CollectionController
from src.collector.scrapy_runner import CollectedPage, ScrapyCollector

__all__ = ["CollectedPage", "CollectionController", "ScrapyCollector"]
