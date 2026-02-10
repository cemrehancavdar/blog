"""RSS/Atom feed generation."""

from xml.etree.ElementTree import Element, SubElement, tostring

from blog.models import Post, SiteConfig


def render_feed(posts: list[Post], config: SiteConfig) -> str:
    """Generate an RSS 2.0 feed as XML string."""
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    rss.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = config.title
    SubElement(channel, "description").text = config.description or config.title
    SubElement(channel, "link").text = config.url

    # Self-referencing atom link (required for valid RSS)
    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", f"{config.url}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    if config.author:
        SubElement(channel, "managingEditor").text = config.author

    for post in posts:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = post.title
        SubElement(item, "link").text = f"{config.url}{post.url_path}"
        SubElement(item, "guid", isPermaLink="true").text = f"{config.url}{post.url_path}"
        SubElement(item, "pubDate").text = post.date_rfc822
        SubElement(item, "description").text = post.html

        if config.author:
            SubElement(item, "dc:creator").text = config.author

        for tag in post.tags:
            SubElement(item, "category").text = tag

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes
