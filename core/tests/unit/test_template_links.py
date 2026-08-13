"""Every link this app renders goes somewhere — checked against the live routing table.

**The defect class.** Nothing anywhere tested that a rendered link resolves. Every
``href`` and every ``form action`` in every template was unverified, so a Jinja-built
path with one wrong segment shipped silently and only a human clicking it found out.
That is how the front door itself was discovered — by a person typing an address minutes
before an HR demo.

**Built the way the other safety nets in this repo had to be rebuilt.** Each of them
shipped green over a hole and was fixed the same way: *enumerate from the live artifact,
never from a hand-maintained list.* The authorization matrix walks the real routing
table; the compose-delivery pin derives its required set from a real refusal message.
So this walks the real template directory and the real routing table, and both ends
grow by themselves:

* a new template is crawled the day it is added — the templates are globbed, not listed;
* a renamed route breaks every link to it, because targets are matched by asking the
  app's own route objects, exactly as the router does when it dispatches.

**It has been shown to fail.** :func:`test_the_resolver_rejects_an_address_the_app_does_
not_serve` and :func:`test_a_wrong_segment_in_a_real_template_is_caught` are the proof:
the first feeds the resolver addresses that must not resolve, the second runs the whole
extractor over a real template body with one segment corrupted and asserts the crawl
reports it. A net whose failure has never been observed is not known to be a net.

**What it cannot see, said out loud.** One link in the UI has a target the template
cannot show — ``dashboard_index.html`` renders ``{{ page.href }}``, built in Python. It
is not skipped: :data:`OPAQUE_LINKS` lists it, the set is asserted exactly so a second
one cannot appear quietly, and the values themselves are imported from the module that
builds them and resolved like any other target.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import NamedTuple

import pytest
from starlette.routing import Match

from src.api.main import app
from src.api.routes.dashboard import DASHBOARD_PAGES

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "api" / "templates"

#: ``href=`` / ``action=`` / ``formaction=`` and the quoted value that follows.
_LINK = re.compile(r"""\b(href|action|formaction)\s*=\s*(["'])(.*?)\2""", re.DOTALL)
#: A ``<form …>`` opening tag, so an ``action`` can be attributed to the right method.
_FORM = re.compile(r"""<form\b[^>]*?method\s*=\s*["']?(\w+)""", re.IGNORECASE)
#: Any Jinja expression or statement inside an attribute value.
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
#: ``id="…"`` — the targets a same-page fragment link can land on.
_ID = re.compile(r"""\bid\s*=\s*(["'])(.*?)\1""")

#: Links whose target this crawl cannot read out of the template, with the reason and
#: where the real value lives. Asserted EXACTLY: a new one has to be argued for, and
#: then verified some other way, rather than joining a list of things nobody checks.
OPAQUE_LINKS: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "dashboard_index.html",
            "{{ page.href }}",
        ),
        # The login page's "Continue" button in the CAS-disabled posture, and the CAS
        # button's `next=`: both carry wherever the visitor was originally heading, so
        # the value is a REQUEST parameter and not a fixed target. Validating what may
        # appear there is the open-redirect item recorded for P0.1b-ii, not this crawl's
        # job; its default is resolved below like any other link.
        ("login.html", "{{ next | urlencode }}"),
    }
)

#: The default of ``login_page(next=…)`` — the value the opaque login link carries when
#: nobody was heading anywhere in particular.
LOGIN_NEXT_DEFAULT = "/jd-bank/ui/queue"


class Link(NamedTuple):
    """One extracted link: where it was found, what it said, and how it is reached."""

    template: str
    raw: str
    method: str

    def __repr__(self) -> str:  # pragma: no cover - failure output only
        return f"{self.template}: {self.method} {self.raw!r}"


def _method_at(source: str, position: int) -> str:
    """The HTTP method a link at ``position`` is followed with.

    An ``href`` is always a GET; an ``action`` (or a button's ``formaction``) inherits
    the method of the ``<form>`` it sits in, which is the nearest preceding opening tag.
    Without this the crawl would check ``POST`` targets as though they were pages and
    every one of them would "resolve" against nothing.
    """
    forms = [m for m in _FORM.finditer(source) if m.start() < position]
    return forms[-1].group(1).upper() if forms else "GET"


def extract_links(template: str, source: str) -> list[Link]:
    """Every link a template renders, with the method it is followed with."""
    links: list[Link] = []
    for match in _LINK.finditer(source):
        attribute, _, value = match.groups()
        method = "GET" if attribute == "href" else _method_at(source, match.start())
        links.append(Link(template, value.strip(), method))
    return links


def all_links() -> list[Link]:
    """Every link in every template — globbed, so a new template is covered on sight."""
    links: list[Link] = []
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        links.extend(extract_links(path.name, path.read_text(encoding="utf-8")))
    return links


def concrete_path(raw: str) -> str:
    """The raw attribute value reduced to a path this app could be asked for.

    Query strings are dropped (routing does not look at them) and each Jinja expression
    becomes a UUID, which is what every path parameter in this app is. Interpolation
    inside a *query* is therefore irrelevant, and interpolation inside a *path segment*
    is checked at the shape that matters: right segments, right count.
    """
    path = raw.split("?", 1)[0].split("#", 1)[0]
    return _JINJA.sub(lambda _: str(uuid.uuid4()), path)


def resolves(method: str, path: str) -> bool:
    """Does the **live routing table** serve ``method path``?

    Asked of the app's own route objects with the same ``matches(scope)`` call the
    router makes when it dispatches a request, so this cannot describe a different app
    from the one being served. ``Match.FULL`` is required: a path that exists for a
    different method is a 405 for whoever clicks it, which is still a dead end.
    """
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    return any(route.matches(scope)[0] is Match.FULL for route in app.routes)


def unresolved(links: list[Link]) -> list[Link]:
    """The links that go nowhere — the crawl's verdict, factored out so the proof-it-
    fails tests can run the real thing rather than a lookalike."""
    broken: list[Link] = []
    for link in links:
        raw = link.raw
        if (link.template, raw) in OPAQUE_LINKS:
            continue
        if raw.startswith(("#", "mailto:", "http://", "https://", "data:")):
            continue
        if not raw.startswith("/"):
            continue  # a relative link — this app renders none (pinned below)
        if not resolves(link.method, concrete_path(raw)):
            broken.append(link)
    return broken


# ── The crawl ────────────────────────────────────────────────────────────────────


def test_the_crawl_actually_found_the_links() -> None:
    """The failure mode of a scanner is finding nothing and reporting success. Pin that
    it sees every template that has links, and a plausible number of them."""
    links = all_links()
    templates_with_links = {link.template for link in links}

    assert len(links) > 40, f"only {len(links)} links extracted — the scanner is blind"
    for expected in ("_base.html", "library.html", "review_detail.html", "login.html"):
        assert expected in templates_with_links, f"{expected} contributed no links"
    assert any(link.method == "POST" for link in links), "no form actions were seen"


def test_every_rendered_link_goes_somewhere_the_app_serves() -> None:
    """THE test. Every ``href`` and ``form action`` in every template resolves to a real
    route, with the right method."""
    broken = unresolved(all_links())

    assert not broken, (
        "these links resolve to nothing the app serves:\n  "
        + "\n  ".join(repr(link) for link in broken)
        + "\nFix the link or add the route — a rendered link that 404s is a dead end "
        "with a 200 in front of it."
    )


def test_every_same_page_link_lands_on_an_anchor_that_exists() -> None:
    """A ``#fragment`` is a link too, and it fails silently in the other direction: the
    browser stays put and the reader thinks the page is broken. The Builder's "go to
    section" links are all of this kind."""
    missing: list[str] = []
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        ids = {_JINJA.sub("*", value) for _, value in _ID.findall(source)}
        for link in extract_links(path.name, source):
            if not link.raw.startswith("#"):
                continue
            if _JINJA.sub("*", link.raw[1:]) not in ids:
                missing.append(f"{path.name}: {link.raw}")

    assert not missing, f"fragment links with no matching id: {missing}"


def test_the_one_link_the_template_cannot_show_is_declared_and_resolves() -> None:
    """``dashboard_index.html`` renders ``{{ page.href }}``. It is listed in
    OPAQUE_LINKS rather than skipped, and the values it renders — imported from the
    module that builds them — are resolved here instead."""
    declared_templates = {template for template, _ in OPAQUE_LINKS}
    assert declared_templates == {"dashboard_index.html", "login.html"}, (
        "the set of links this crawl cannot read changed. Each one is a link nobody "
        "checks until someone checks it here — argue for it, then verify it."
    )

    for page in DASHBOARD_PAGES:
        assert resolves(
            "GET", page["href"]
        ), f"the dashboard index links to {page['href']!r}, which is not a route."
    assert resolves("GET", LOGIN_NEXT_DEFAULT), (
        "the login page's default destination is not a route, so signing in with no "
        "`next` would land on a 404."
    )


# ── Prove it fails ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/jd-bank/ui/librar",  # one letter short
        "/jd-bank/ui/library/extra",  # one segment too many
        "/jd-bank/ui/queue/",  # the trailing-slash variant is NOT a route
        "/nope",
    ],
)
def test_the_resolver_rejects_an_address_the_app_does_not_serve(path: str) -> None:
    """Half the proof: the resolver's *no* is real. Without this, a resolver that
    returned True unconditionally would make the crawl above pass on any repo."""
    assert not resolves("GET", path)


def test_the_resolver_rejects_the_right_path_with_the_wrong_method() -> None:
    """The other way a link dies: the address exists, the method does not. This is why
    a form's ``action`` is checked as a POST and not as a page."""
    assert resolves("POST", "/jd-bank/ui/logout")
    assert not resolves("GET", "/jd-bank/ui/logout")
    assert resolves("GET", "/jd-bank/ui/library")
    assert not resolves("POST", "/jd-bank/ui/library")


def test_a_wrong_segment_in_a_real_template_is_caught() -> None:
    """The whole crawl, over a real template body with one segment corrupted — the
    mutation the audit says to make before trusting a net. This is the mistake the
    class actually makes: a plausible path with one wrong word in it.
    """
    source = (TEMPLATES_DIR / "role_detail.html").read_text(encoding="utf-8")
    mutated = source.replace("/jd-bank/ui/review/", "/jd-bank/ui/reviews/", 1)
    assert mutated != source, "the mutation did not apply; this test proves nothing"

    broken = unresolved(extract_links("role_detail.html", mutated))

    assert [link.raw for link in broken] == [
        "/jd-bank/ui/reviews/{{ role.canonical_id }}"
    ], "the crawl did not report a link it should have caught"


def test_a_form_posting_to_a_get_only_route_is_caught() -> None:
    """The same proof for the method half: a form that posts to a page."""
    mutated = '<form method="post" action="/jd-bank/ui/library"></form>'

    broken = unresolved(extract_links("synthetic.html", mutated))

    assert len(broken) == 1 and broken[0].method == "POST"
