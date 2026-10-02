"""Convert a beehiiv issue's HTML into readable, markdown-ish text."""
import re
from html.parser import HTMLParser

BLOCK = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "div", "br", "tr"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
        if tag in BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    p = _Text()
    p.feed(html)
    text = "".join(p.out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"^(#+|-)\n+", r"\1 ", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
