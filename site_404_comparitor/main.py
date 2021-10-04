import csv
import hashlib
import logging
import pathlib
import pickle
import sys
import typing
from dataclasses import dataclass

import coloredlogs
import furl
import httpx
import tqdm
import typer
from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class URL:
    host: str
    path: pathlib.Path
    scheme: str = "https"

    @property
    def furl(self) -> furl.furl:
        return furl.furl(scheme=self.scheme, host=self.host, path=str(self.path))

    def set_host(self, host: str) -> "URL":
        """Return a new URL with the given host"""
        return URL(host=host, path=self.path)

    def join_path(self, other: typing.Union[str, pathlib.Path]) -> "URL":
        """Join the given path and return a new URL"""
        new_path = self.path / other
        return URL(host=self.host, path=new_path)


@dataclass
class Site:
    url: URL
    pages: dict[URL, "Page"]


@dataclass
class Page:
    url: URL
    response: httpx.Response

    @property
    def status_code(self) -> int:
        return self.response.status_code

    def get_urls(self) -> typing.Iterable[URL]:
        soup = BeautifulSoup(self.response.content, features="html.parser")
        for a in soup.find_all("a"):
            if "href" not in a.attrs:
                continue
            href = furl.furl(a["href"])
            # Skip urls with different hosts
            if (href.host is not None) and (href.host != self.url.host):
                continue
            # Skip paths with @, usually mailtos
            if "@" in str(href.path):
                continue
            path = pathlib.Path(str(href.path.normalize()))
            yield self.url.join_path(path)


@dataclass
class PageCache:
    path: pathlib.Path

    def get_page(self, url: URL) -> Page:
        url_hash = hashlib.sha256(url.furl.tostr().encode("UTF-8")).hexdigest()
        cache_path = self.path / f"{url_hash}.pickle"
        LOG.debug(f"Reading {url=} from {cache_path=}")
        if cache_path.is_file():
            try:
                with cache_path.open("rb") as fp:
                    return pickle.load(fp)
            except Exception as e:
                LOG.exception(
                    f"Problem loading {cache_path=}: {e}. Deleting cache entry and re-downloading."
                )
                cache_path.unlink()

        if not cache_path.is_file():
            LOG.debug(f"Fetching {url=} and writing to {cache_path=}")
            self.path.mkdir(parents=True, exist_ok=True)
            page = get_page(url)
            with cache_path.open("wb") as fp:
                pickle.dump(page, fp)

        LOG.debug(f"Reading {url=} from {cache_path=} (2nd attempt)")
        with cache_path.open("rb") as fp:
            return pickle.load(fp)


def get_page(url: URL) -> Page:
    response = httpx.get(url.furl.tostr())
    LOG.debug(f"{url=} => {response=}")

    return Page(url, response)


def process_page(site: Site, page: Page, cache: PageCache):
    LOG.debug(f"process_page {page=}")
    for url in tqdm.tqdm(list(page.get_urls()), desc=str(page.url.path)):
        LOG.debug(
            f"process_page for {page=} processing {url=} ({str(url) in site.pages=})"
        )
        if url not in site.pages:
            LOG.debug(f"Fetching {url=}")
            new_page = cache.get_page(url)
            site.pages[new_page.url] = new_page
            process_page(site, new_page, cache)


app = typer.Typer()


def walk_site(site: Site, cache: PageCache):
    LOG.debug(f"Walking {site=}")
    root = cache.get_page(site.url)
    site.pages[root.url] = root
    process_page(site, root, cache)


@app.command()
def main(
    original_site: str,
    target_site: str,
    cache_path: pathlib.Path = pathlib.Path("/tmp/site_404_comparitor_cache"),
    debug: bool = False,
):
    coloredlogs.install(level="DEBUG" if debug else "INFO")
    if not original_site.endswith("/"):
        original_site += "/"
    if not target_site.endswith("/"):
        target_site += "/"
    original = Site(
        URL(
            furl.furl(original_site).host,
            pathlib.Path(str(furl.furl(original_site).path.normalize())),
        ),
        {},
    )
    target = Site(
        URL(
            furl.furl(target_site).host,
            pathlib.Path(str(furl.furl(target_site).path.normalize())),
        ),
        {},
    )
    LOG.info(f"Comparing original site {original=} against {target=}")

    cache = PageCache(cache_path)

    walk_site(original, cache)

    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "original",
            "target",
            "original_status_code",
            "target_status_code",
            "original_path",
            "target_path",
        ],
    )
    writer.writeheader()
    for url, page in tqdm.tqdm(original.pages.items(), desc="404 check"):
        target_url = page.url.set_host(target.url.host)
        LOG.debug(f"Checking for 404 with {url=} -> {target_url=}")
        target_page = cache.get_page(target_url)
        row = {
            "original": page.url.furl.tostr(),
            "target": target_page.url.furl.tostr(),
            "original_status_code": page.status_code,
            "target_status_code": target_page.status_code,
            "original_path": str(page.url.path),
            "target_path": str(target_page.url.path),
        }
        writer.writerow(row)


if __name__ == "__main__":
    app()
