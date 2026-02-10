"""CLI interface for the blog."""

import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click

from blog.build import build_site
from blog.models import load_all_posts, load_config

CLOUDFLARE_PROJECT_NAME = "blog"
CLOUDFLARE_PRODUCTION_BRANCH = "main"

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Find project root by looking for config.yaml or content/ dir."""
    cwd = Path.cwd()
    # Walk up looking for config.yaml or content/
    for directory in [cwd, *cwd.parents]:
        if (directory / "config.yaml").exists() or (directory / "content").exists():
            return directory
    return cwd


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose output")
@click.pass_context
def main(ctx, verbose):
    """Minimal static blog generator."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@main.command()
@click.argument("title")
@click.option("--note", is_flag=True, help="Create a short note instead of a post")
@click.option("--tags", "-t", default="", help="Comma-separated tags")
@click.option("--no-edit", is_flag=True, help="Don't open editor")
def new(title: str, note: bool, tags: str, no_edit: bool):
    """Create a new post or note."""
    root = _find_project_root()
    config = load_config(root)
    content_dir = root / config.content_dir / "posts"
    content_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    slug = title.lower().strip()
    # Replace non-alphanumeric with hyphens
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")

    filename = f"{now.strftime('%Y-%m-%d')}-{slug}.md"
    filepath = content_dir / filename

    # Handle duplicate filenames
    counter = 2
    while filepath.exists():
        filename = f"{now.strftime('%Y-%m-%d')}-{slug}-{counter}.md"
        filepath = content_dir / filename
        counter += 1

    post_type = "note" if note else "post"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    tag_str = f"\ntags: [{', '.join(tag_list)}]" if tag_list else ""

    frontmatter = f"""---
title: "{title}"
date: {now.strftime("%Y-%m-%dT%H:%M:%S")}
type: {post_type}{tag_str}
draft: false
---

"""
    filepath.write_text(frontmatter, encoding="utf-8")
    click.echo(f"Created: {filepath.relative_to(root)}")

    if not no_edit:
        editor = os.environ.get("EDITOR", "vim")
        try:
            subprocess.run([editor, str(filepath)], check=False)
        except FileNotFoundError:
            click.echo(f"Editor '{editor}' not found. Set $EDITOR to your preferred editor.")


@main.command()
@click.option("--drafts", is_flag=True, help="Include draft posts")
def build(drafts: bool):
    """Build the static site."""
    root = _find_project_root()
    config = load_config(root)
    build_site(root, config, include_drafts=drafts)
    output_dir = root / config.output_dir
    click.echo(f"Site built to {output_dir.relative_to(root)}/")


@main.command()
@click.option("--port", "-p", default=8000, help="Port number")
@click.option("--drafts", is_flag=True, help="Include draft posts")
def serve(port: int, drafts: bool):
    """Start local dev server with auto-rebuild."""
    from blog.server import serve as run_server

    root = _find_project_root()
    config = load_config(root)

    def do_build():
        build_site(root, config, include_drafts=drafts)

    run_server(
        project_root=root,
        output_dir=root / config.output_dir,
        build_fn=do_build,
        port=port,
    )


@main.command(name="list")
@click.option("--drafts", is_flag=True, help="Include draft posts")
@click.option("-n", "--count", default=20, help="Number of posts to show")
def list_posts(drafts: bool, count: int):
    """List recent posts."""
    root = _find_project_root()
    config = load_config(root)
    posts = load_all_posts(root / config.content_dir, include_drafts=drafts)

    if not posts:
        click.echo("No posts found.")
        return

    for post in posts[:count]:
        draft_marker = " [DRAFT]" if post.draft else ""
        type_marker = f" ({post.post_type})" if post.post_type != "post" else ""
        click.echo(f"  {post.date_display}  {post.title}{type_marker}{draft_marker}")
        click.echo(f"              {post.source_path.relative_to(root)}")


@main.command()
@click.option("--skip-build", is_flag=True, help="Deploy without rebuilding first")
@click.option("--dry-run", is_flag=True, help="Build only, show what would be deployed")
def deploy(skip_build: bool, dry_run: bool):
    """Build and deploy to Cloudflare Pages."""
    root = _find_project_root()
    config = load_config(root)
    output_dir = root / config.output_dir

    # Build step
    if not skip_build:
        click.echo("Building site...")
        build_site(root, config, include_drafts=False)
        click.echo(f"Built to {output_dir.relative_to(root)}/")

    if not output_dir.exists():
        click.echo("Error: output directory does not exist. Run 'blog build' first.", err=True)
        raise SystemExit(1)

    # Count files to deploy
    file_count = sum(1 for _ in output_dir.rglob("*") if _.is_file())
    click.echo(f"Deploying {file_count} files...")

    if dry_run:
        click.echo("Dry run — skipping deploy.")
        return

    # Check npx/wrangler availability
    npx = shutil.which("npx")
    if npx is None:
        click.echo("Error: npx not found. Install Node.js to use wrangler.", err=True)
        raise SystemExit(1)

    result = subprocess.run(
        [
            npx,
            "wrangler",
            "pages",
            "deploy",
            str(output_dir),
            "--project-name",
            CLOUDFLARE_PROJECT_NAME,
            "--branch",
            CLOUDFLARE_PRODUCTION_BRANCH,
        ],
        cwd=root,
        check=False,
    )

    if result.returncode != 0:
        click.echo("Deploy failed.", err=True)
        raise SystemExit(result.returncode)

    click.echo("Deployed successfully.")
