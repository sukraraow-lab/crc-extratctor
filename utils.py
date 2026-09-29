# ZeroTrace Bot — utils.py
import datetime
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Separator used when writing "title|||url" lines.
# Must NOT appear in titles or URLs — triple pipe is safe.
LINE_SEP = "|||"


def get_datetime_str() -> str:
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")


def encode_line(title: str, url: str) -> str:
    """Encode a title/URL pair into a single line for .txt files."""
    safe_title = title.replace(LINE_SEP, " ")
    return f"{safe_title}{LINE_SEP}{url}"


def decode_line(line: str):
    """
    Decode a line back into (title, url).
    Falls back to splitting on the first ':' for legacy lines.
    """
    line = line.strip()
    if LINE_SEP in line:
        title, url = line.split(LINE_SEP, 1)
        return title.strip(), url.strip()
    # Legacy format: title:https://...  — split on ': ' or first colon-then-slash
    # Handles "My Video:https://..." correctly by splitting ONLY on ':' that is NOT
    # followed by '/' (i.e. not the scheme colon in the URL).
    import re
    m = re.match(r'^(.+?):(?!//)(.+)$', line)
    if m:
        return m.group(1).strip(), (m.group(2)).strip()
    # Last resort: naive split
    parts = line.split(":", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return line, ""


def create_html_file(file_name: str, batch_name: str, contents: list):
    """
    Build an HTML table from a list of raw content lines.
    Each line should be in `encode_line` format or the legacy title:url format.
    """
    tbody = ""
    for line in contents:
        line = line.strip()
        if not line:
            continue
        title, url = decode_line(line)
        if url:
            tbody += f'<tr><td><a href="{url}">{title}</a></td></tr>\n'

    template_path = os.path.join(_HERE, "template.html")
    if not os.path.exists(template_path):
        raise FileNotFoundError(
            f"template.html not found at {template_path}. "
            "Place it in the same directory as utils.py."
        )

    with open(template_path, encoding="utf-8") as fp:
        file_content = fp.read()

    with open(file_name, "w", encoding="utf-8") as fp:
        fp.write(
            file_content
            .replace("tbody_content", tbody)
            .replace("batch_name", batch_name)
        )
