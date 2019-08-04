import logging
import urllib
from datetime import datetime
from datetime import timezone
from typing import Dict
from typing import Optional
from typing import Tuple
from urllib.parse import urlparse

import bleach
import emoji_unicode
import flask
import html2text
import timeago
from little_boxes import activitypub as ap
from little_boxes.activitypub import _to_list
from little_boxes.errors import ActivityGoneError
from little_boxes.errors import ActivityNotFoundError

from config import EMOJI_TPL
from config import ID
from config import MEDIA_CACHE
from core.activitypub import _answer_key
from utils import parse_datetime
from utils.media import Kind

_logger = logging.getLogger(__name__)

H2T = html2text.HTML2Text()
H2T.ignore_links = True
H2T.ignore_images = True


filters = flask.Blueprint("filters", __name__)


@filters.app_template_filter()
def visibility(v: str) -> str:
    try:
        return ap.Visibility[v].value.lower()
    except Exception:
        return v


@filters.app_template_filter()
def visibility_is_public(v: str) -> bool:
    return v in [ap.Visibility.PUBLIC.name, ap.Visibility.UNLISTED.name]


@filters.app_template_filter()
def emojify(text):
    return emoji_unicode.replace(
        text, lambda e: EMOJI_TPL.format(filename=e.code_points, raw=e.unicode)
    )


# HTML/templates helper
ALLOWED_TAGS = [
    "a",
    "abbr",
    "acronym",
    "b",
    "br",
    "blockquote",
    "code",
    "pre",
    "em",
    "i",
    "li",
    "ol",
    "strong",
    "ul",
    "span",
    "div",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
]


def clean_html(html):
    try:
        return bleach.clean(html, tags=ALLOWED_TAGS)
    except Exception:
        return ""


@filters.app_template_filter()
def gtone(n):
    return n > 1


@filters.app_template_filter()
def gtnow(dtstr):
    return ap.format_datetime(datetime.now(timezone.utc)) > dtstr


@filters.app_template_filter()
def clean(html):
    out = clean_html(html)
    return emoji_unicode.replace(
        out, lambda e: EMOJI_TPL.format(filename=e.code_points, raw=e.unicode)
    )


@filters.app_template_filter()
def permalink_id(val):
    return str(hash(val))


@filters.app_template_filter()
def quote_plus(t):
    return urllib.parse.quote_plus(t)


@filters.app_template_filter()
def is_from_outbox(t):
    return t.startswith(ID)


@filters.app_template_filter()
def html2plaintext(body):
    return H2T.handle(body)


@filters.app_template_filter()
def domain(url):
    return urlparse(url).netloc


@filters.app_template_filter()
def format_time(val):
    if val:
        dt = parse_datetime(val)
        return datetime.strftime(dt, "%B %d, %Y, %H:%M %p")
    return val


@filters.app_template_filter()
def format_ts(val):
    return datetime.fromtimestamp(val).strftime("%B %d, %Y, %H:%M %p")


@filters.app_template_filter()
def gt_ts(val):
    return datetime.now() > datetime.fromtimestamp(val)


@filters.app_template_filter()
def format_timeago(val):
    if val:
        dt = parse_datetime(val)
        return timeago.format(dt.astimezone(timezone.utc), datetime.now(timezone.utc))
    return val


@filters.app_template_filter()
def url_or_id(d):
    if isinstance(d, dict):
        if "url" in d:
            return d["url"]
        else:
            return d["id"]
    return ""


@filters.app_template_filter()
def get_url(u):
    print(f"GET_URL({u!r})")
    if isinstance(u, list):
        for l in u:
            if l.get("mimeType") == "text/html":
                u = l
    if isinstance(u, dict):
        return u["href"]
    elif isinstance(u, str):
        return u
    else:
        return u


@filters.app_template_filter()
def get_actor(url):
    if not url:
        return None
    if isinstance(url, list):
        url = url[0]
    if isinstance(url, dict):
        url = url.get("id")
    print(f"GET_ACTOR {url}")
    try:
        return ap.get_backend().fetch_iri(url)
    except (ActivityNotFoundError, ActivityGoneError):
        return f"Deleted<{url}>"
    except Exception as exc:
        return f"Error<{url}/{exc!r}>"


@filters.app_template_filter()
def get_answer_count(choice, obj, meta):
    count_from_meta = meta.get("question_answers", {}).get(_answer_key(choice), 0)
    print(count_from_meta)
    print(choice, obj, meta)
    if count_from_meta:
        return count_from_meta
    for option in obj.get("oneOf", obj.get("anyOf", [])):
        if option.get("name") == choice:
            return option.get("replies", {}).get("totalItems", 0)


@filters.app_template_filter()
def get_total_answers_count(obj, meta):
    cached = meta.get("question_replies", 0)
    if cached:
        return cached
    cnt = 0
    for choice in obj.get("anyOf", obj.get("oneOf", [])):
        print(choice)
        cnt += choice.get("replies", {}).get("totalItems", 0)
    return cnt


_GRIDFS_CACHE: Dict[Tuple[Kind, str, Optional[int]], str] = {}


def _get_file_url(url, size, kind):
    k = (kind, url, size)
    cached = _GRIDFS_CACHE.get(k)
    if cached:
        return cached

    doc = MEDIA_CACHE.get_file(url, size, kind)
    if doc:
        u = f"/media/{str(doc._id)}"
        _GRIDFS_CACHE[k] = u
        return u

    # MEDIA_CACHE.cache(url, kind)
    _logger.error(f"cache not available for {url}/{size}/{kind}")
    return url


@filters.app_template_filter()
def get_actor_icon_url(url, size):
    return _get_file_url(url, size, Kind.ACTOR_ICON)


@filters.app_template_filter()
def get_attachment_url(url, size):
    return _get_file_url(url, size, Kind.ATTACHMENT)


@filters.app_template_filter()
def get_og_image_url(url, size=100):
    try:
        return _get_file_url(url, size, Kind.OG_IMAGE)
    except Exception:
        return ""


@filters.app_template_filter()
def remove_mongo_id(dat):
    if isinstance(dat, list):
        return [remove_mongo_id(item) for item in dat]
    if "_id" in dat:
        dat["_id"] = str(dat["_id"])
    for k, v in dat.items():
        if isinstance(v, dict):
            dat[k] = remove_mongo_id(dat[k])
    return dat


@filters.app_template_filter()
def get_video_link(data):
    for link in data:
        if link.get("mimeType", "").startswith("video/"):
            return link.get("href")
    return None


@filters.app_template_filter()
def has_type(doc, _types):
    for _type in _to_list(_types):
        if _type in _to_list(doc["type"]):
            return True
    return False


@filters.app_template_filter()
def has_actor_type(doc):
    # FIXME(tsileo): skipping the last one "Question", cause Mastodon sends question restuls as an update coming from
    # the question... Does Pleroma do that too?
    for t in ap.ACTOR_TYPES[:-1]:
        if has_type(doc, t.value):
            return True
    return False


def _is_img(filename):
    filename = filename.lower()
    if (
        filename.endswith(".png")
        or filename.endswith(".jpg")
        or filename.endswith(".jpeg")
        or filename.endswith(".gif")
        or filename.endswith(".svg")
    ):
        return True
    return False


@filters.app_template_filter()
def not_only_imgs(attachment):
    for a in attachment:
        if isinstance(a, dict) and not _is_img(a["url"]):
            return True
        if isinstance(a, str) and not _is_img(a):
            return True
    return False


@filters.app_template_filter()
def is_img(filename):
    return _is_img(filename)
