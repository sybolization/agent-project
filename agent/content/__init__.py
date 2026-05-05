def __getattr__(name):
    if name == "WebContentFetcher":
        from .fetcher import WebContentFetcher
        return WebContentFetcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "WebContentFetcher",
]
