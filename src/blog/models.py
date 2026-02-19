"""Data models for blog posts and site configuration."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class Post:
    """A blog post parsed from a markdown file with YAML frontmatter."""

    title: str
    date: datetime
    content: str  # raw markdown body (no frontmatter)
    slug: str
    source_path: Path
    post_type: str = "post"  # "post" or "note"
    tags: list[str] = field(default_factory=list)
    draft: bool = False
    unlisted: bool = False  # built but not shown in index/archive/tags/RSS
    description: str = ""
    subtitle: str = ""
    html: str = ""  # rendered HTML, set during build

    @property
    def url_path(self) -> str:
        """URL path like /2026/02/10/my-post/."""
        return f"/{self.date.year}/{self.date.month:02d}/{self.date.day:02d}/{self.slug}/"

    @property
    def date_display(self) -> str:
        """Human-readable date like 2026-02-10."""
        return self.date.strftime("%Y-%m-%d")

    @property
    def date_rfc822(self) -> str:
        """RFC 822 date for RSS feeds."""
        return self.date.strftime("%a, %d %b %Y %H:%M:%S +0000")

    @property
    def date_iso(self) -> str:
        """ISO 8601 date for Atom feeds and HTML."""
        return self.date.isoformat()

    @property
    def preview_html(self) -> str:
        """First paragraph of rendered HTML, for index page previews."""
        if not self.html:
            return ""
        # Find first <p>...</p> block
        match = re.search(r"<p>(.*?)</p>", self.html, re.DOTALL)
        if match:
            return f"<p>{match.group(1)}</p>"
        return ""

    @property
    def has_code(self) -> bool:
        """Whether the rendered HTML contains syntax-highlighted code."""
        return '<pre><code class="language-' in self.html


@dataclass
class SiteConfig:
    """Site-wide configuration loaded from config.yaml."""

    title: str = "My Blog"
    description: str = ""
    author: str = ""
    url: str = "https://example.com"
    posts_per_page: int = 20
    content_dir: Path = field(default_factory=lambda: Path("content"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    templates_dir: Path = field(default_factory=lambda: Path("templates"))
    static_dir: Path = field(default_factory=lambda: Path("static"))


FRONTMATTER_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_text).
    """
    text = text.strip()
    if not text.startswith(FRONTMATTER_DELIMITER):
        return {}, text

    # Find the closing delimiter
    end_index = text.find(FRONTMATTER_DELIMITER, len(FRONTMATTER_DELIMITER))
    if end_index == -1:
        return {}, text

    yaml_text = text[len(FRONTMATTER_DELIMITER) : end_index].strip()
    body = text[end_index + len(FRONTMATTER_DELIMITER) :].strip()

    metadata = yaml.safe_load(yaml_text) or {}
    return metadata, body


def load_post(filepath: Path) -> Post:
    """Load a single post from a markdown file."""
    text = filepath.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)

    # Extract slug from filename: 2026-02-10-my-post.md -> my-post
    stem = filepath.stem
    # Try to strip date prefix (YYYY-MM-DD-)
    parts = stem.split("-", 3)
    if len(parts) >= 4 and len(parts[0]) == 4 and parts[0].isdigit():
        slug = parts[3]
    else:
        slug = stem

    # Parse date from frontmatter or filename
    date_raw = metadata.get("date")
    if isinstance(date_raw, datetime):
        date = date_raw
    elif isinstance(date_raw, str):
        # Try common formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                date = datetime.strptime(date_raw, fmt)
                break
            except ValueError:
                continue
        else:
            date = _date_from_filename(stem)
    else:
        date = _date_from_filename(stem)

    tags_raw = metadata.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",")]
    else:
        tags = list(tags_raw)

    return Post(
        title=metadata.get("title", slug.replace("-", " ").title()),
        date=date,
        content=body,
        slug=slug,
        source_path=filepath,
        post_type=metadata.get("type", "post"),
        tags=tags,
        draft=metadata.get("draft", False),
        unlisted=metadata.get("unlisted", False),
        description=metadata.get("description", ""),
        subtitle=metadata.get("subtitle", ""),
    )


def _date_from_filename(stem: str) -> datetime:
    """Extract date from filename like 2026-02-10-slug."""
    parts = stem.split("-", 3)
    if len(parts) >= 3:
        try:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
    return datetime.now()


def load_config(project_root: Path) -> SiteConfig:
    """Load site config from config.yaml in the project root."""
    config_path = project_root / "config.yaml"
    if not config_path.exists():
        return SiteConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return SiteConfig(
        title=raw.get("title", "My Blog"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        url=raw.get("url", "https://example.com").rstrip("/"),
        posts_per_page=raw.get("posts_per_page", 20),
        content_dir=Path(raw.get("content_dir", "content")),
        output_dir=Path(raw.get("output_dir", "output")),
        templates_dir=Path(raw.get("templates_dir", "templates")),
        static_dir=Path(raw.get("static_dir", "static")),
    )


def load_all_posts(content_dir: Path, include_drafts: bool = False) -> list[Post]:
    """Load all posts from content directory, sorted by date descending."""
    posts_dir = content_dir / "posts"
    if not posts_dir.exists():
        return []

    posts = []
    for md_file in sorted(posts_dir.glob("*.md")):
        post = load_post(md_file)
        if not post.draft or include_drafts:
            posts.append(post)

    # Sort newest first
    posts.sort(key=lambda p: p.date, reverse=True)
    return posts
