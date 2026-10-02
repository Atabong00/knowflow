import markdown
import bleach

def render_markdown_safely(content: str) -> str:
    """
    Renders Markdown content safely to HTML.
    Applies strict XSS filters to ensure no malicious JS is injected.
    """
    if not content:
        return ""

    # Convert Markdown to HTML using rich extensions (Fenced Code, Tables, Line Breaks)
    html = markdown.markdown(
        content,
        extensions=[
            "fenced_code",
            "tables",
            "nl2br"
        ]
    )

    # Define clean, safe tags allowed in internal documentation
    allowed_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr", "pre", "code", "blockquote",
        "ul", "ol", "li",
        "table", "thead", "tbody", "tr", "th", "td",
        "a", "img", "strong", "em", "span", "div"
    ]

    allowed_attrs = {
        "a": ["href", "title", "target", "rel"],
        "img": ["src", "alt", "title", "width", "height"],
        "code": ["class"],
        "span": ["class"]
    }

    # Clean the HTML to block cross-site scripting
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)
