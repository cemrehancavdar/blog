"""Build static site from markdown content."""

import logging
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from blog.models import Post, SiteConfig, load_all_posts

logger = logging.getLogger(__name__)


def _highlight_code(code: str, lang: str) -> str:
    """Syntax highlight a code block."""
    try:
        if lang:
            lexer = get_lexer_by_name(lang, stripall=True)
        else:
            lexer = guess_lexer(code)
    except Exception:
        return f"<pre><code>{code}</code></pre>"
    formatter = HtmlFormatter(nowrap=True)
    highlighted = highlight(code, lexer, formatter)
    return f'<pre><code class="language-{lang}">{highlighted}</code></pre>'


def create_markdown_renderer() -> MarkdownIt:
    """Create a markdown-it renderer with syntax highlighting."""
    md = MarkdownIt("commonmark", {"html": True, "typographer": True})
    md.enable("table")

    # Override fence renderer for syntax highlighting
    def fence_renderer(tokens, idx, options, env):
        token = tokens[idx]
        lang = token.info.strip() if token.info else ""
        code = token.content
        return _highlight_code(code, lang)

    md.renderer.rules["fence"] = fence_renderer
    return md


def render_posts(posts: list[Post], md: MarkdownIt) -> list[Post]:
    """Render markdown content to HTML for all posts."""
    for post in posts:
        post.html = md.render(post.content)
    return posts


def build_site(
    project_root: Path,
    config: SiteConfig,
    include_drafts: bool = False,
) -> None:
    """Build the entire static site."""
    content_dir = project_root / config.content_dir
    output_dir = project_root / config.output_dir
    templates_dir = project_root / config.templates_dir
    static_dir = project_root / config.static_dir

    # Clean output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # Load and render posts
    posts = load_all_posts(content_dir, include_drafts=include_drafts)
    md = create_markdown_renderer()
    posts = render_posts(posts, md)

    logger.info("Loaded %d posts", len(posts))

    # Set up Jinja2
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
    )
    env.globals["site"] = config
    env.globals["now"] = __import__("datetime").datetime.now()

    # Unlisted posts get pages built but are excluded from all listings
    listed_posts = [p for p in posts if not p.unlisted]

    # Separate post types (listed only)
    regular_posts = [p for p in listed_posts if p.post_type == "post"]
    notes = [p for p in listed_posts if p.post_type == "note"]

    # Build individual post pages (ALL posts, including unlisted)
    post_template = env.get_template("post.html")
    for post in posts:
        post_dir = output_dir / post.url_path.strip("/")
        post_dir.mkdir(parents=True, exist_ok=True)
        html = post_template.render(post=post, posts=listed_posts)
        (post_dir / "index.html").write_text(html, encoding="utf-8")
        logger.info("Built %s", post.url_path)

    # Build index page (listed only)
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        posts=listed_posts[: config.posts_per_page],
        regular_posts=regular_posts,
        notes=notes,
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    logger.info("Built index.html")

    # Build archive page (listed only)
    archive_template = env.get_template("archive.html")
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_html = archive_template.render(posts=listed_posts)
    (archive_dir / "index.html").write_text(archive_html, encoding="utf-8")
    logger.info("Built archive/index.html")

    # Build tag pages (listed only)
    tags: dict[str, list[Post]] = {}
    for post in listed_posts:
        for tag in post.tags:
            tags.setdefault(tag, []).append(post)

    tag_template = env.get_template("tag.html")
    tags_dir = output_dir / "tags"
    tags_dir.mkdir(exist_ok=True)
    for tag_name, tag_posts in sorted(tags.items()):
        tag_dir = tags_dir / tag_name
        tag_dir.mkdir(exist_ok=True)
        tag_html = tag_template.render(tag=tag_name, posts=tag_posts)
        (tag_dir / "index.html").write_text(tag_html, encoding="utf-8")
        logger.info("Built tags/%s/", tag_name)

    # Build tags index (listed only)
    tags_index_html = env.get_template("tags_index.html").render(
        tags=sorted(tags.items(), key=lambda x: len(x[1]), reverse=True)
    )
    (tags_dir / "index.html").write_text(tags_index_html, encoding="utf-8")

    # Build RSS feed (listed only)
    from blog.feed import render_feed

    feed_xml = render_feed(listed_posts[:20], config)
    (output_dir / "feed.xml").write_text(feed_xml, encoding="utf-8")
    logger.info("Built feed.xml")

    # Build pages (about, etc.)
    pages_dir = content_dir / "pages"
    if pages_dir.exists():
        page_template = env.get_template("page.html")
        for md_file in pages_dir.glob("*.md"):
            from blog.models import parse_frontmatter

            text = md_file.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(text)
            page_html_content = md.render(body)
            page_slug = md_file.stem
            page_out_dir = output_dir / page_slug
            page_out_dir.mkdir(exist_ok=True)
            page_html = page_template.render(
                title=metadata.get("title", page_slug.replace("-", " ").title()),
                content=page_html_content,
            )
            (page_out_dir / "index.html").write_text(page_html, encoding="utf-8")
            logger.info("Built %s/", page_slug)

    # Copy static files
    if static_dir.exists():
        shutil.copytree(static_dir, output_dir / "static", dirs_exist_ok=True)
        logger.info("Copied static files")

    # Copy robots.txt to site root
    robots_src = static_dir / "robots.txt"
    if robots_src.exists():
        shutil.copy2(robots_src, output_dir / "robots.txt")
        logger.info("Copied robots.txt to root")

    # Generate syntax highlighting CSS (light + dark), stripping background colors
    # so code blocks inherit the background from style.css
    syntax_prefixes = [".post-body pre code", ".entry-body pre code"]
    light_css = HtmlFormatter(style="default", nowrap=True).get_style_defs(syntax_prefixes)
    dark_css = HtmlFormatter(style="monokai", nowrap=True).get_style_defs(syntax_prefixes)
    bg_pattern = re.compile(r"\s*background(?:-color)?:\s*[^;}]+;?")
    light_css = bg_pattern.sub("", light_css)
    dark_css = bg_pattern.sub("", dark_css)
    syntax_css = f"{light_css}\n@media (prefers-color-scheme: dark) {{\n{dark_css}\n}}"
    (output_dir / "static" / "syntax.css").write_text(syntax_css, encoding="utf-8")
    logger.info("Generated syntax.css")

    logger.info("Build complete: %d posts, %d tags", len(posts), len(tags))
