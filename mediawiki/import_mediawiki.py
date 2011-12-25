import hashlib
import html5lib
from lxml import etree
from xml.dom import minidom
from urlparse import urljoin, urlsplit
import urllib
import re
from html5lib import sanitizer
from wikitools import *

MEDIAWIKI_URL = 'http://127.0.0.1/mediawiki-1.16.0/index.php'


def guess_api_endpoint(url):
    return urljoin(url, 'api.php')


def guess_script_path(url):
    mw_path = urlsplit(MEDIAWIKI_URL).path
    if mw_path.endswith('.php'):
        return mw_path
    return urljoin(mw_path, '.')

API_ENDPOINT = guess_api_endpoint(MEDIAWIKI_URL)

site = wiki.Wiki(API_ENDPOINT)
SCRIPT_PATH = guess_script_path(MEDIAWIKI_URL)
redirects = []
include_pages_to_create = []
mapdata_objects_to_create = []


def get_robot_user():
    from django.contrib.auth.models import User

    try:
        u = User.objects.get(username="LocalWikiRobot")
    except User.DoesNotExist:
        u = User(name='LocalWiki Robot', username='LocalWikiRobot',
                 email='editrobot@localwiki.org')
        u.save()
    return u


def import_users():
    from django.contrib.auth.models import User

    request = api.APIRequest(site, {
        'action': 'query',
        'list': 'allusers',
    })
    for item in request.query()['query']['allusers']:
        username = item['name'][:30]

        # TODO: how do we get their email address here? I don't think
        # it's available via the API. Maybe we'll have to fill in the
        # users' emails in a separate step.
        # We require users to have an email address, so we fill this in with a
        # dummy value for now.
        name_hash = hashlib.sha1(username).hexdigest()
        email = "%s@FIXME.localwiki.org" % name_hash

        if User.objects.filter(username=username):
            continue

        print "Importing user %s" % username
        u = User(username=username, email=email)
        u.save()


def add_redirect(page):
    global redirects

    request = api.APIRequest(site, {
        'action': 'parse',
        'title': page.title,
        'text': page.wikitext,
    })
    links = request.query()['parse']['links']
    if not links:
        return
    to_pagename = links[0]['*']

    redirects.append((page.title, to_pagename))


def process_redirects():
    # We create the Redirects here.  We don't try and port over the
    # version information for the formerly-page-text-based redirects.
    global redirects

    from pages.models import Page, slugify
    from redirects.models import Redirect

    u = get_robot_user()

    for from_pagename, to_pagename in redirects:
        try:
            to_page = Page.objects.get(slug=slugify(to_pagename))
        except Page.DoesNotExist:
            print "Error creating redirect: %s --> %s" % (
                from_pagename, to_pagename)
            print "  (page %s does not exist)" % to_pagename
            continue

        if slugify(from_pagename) == to_page.slug:
            continue
        if not Redirect.objects.filter(source=slugify(from_pagename)):
            r = Redirect(source=slugify(from_pagename), destination=to_page)
            r.save(user=u, comment="Automated edit. Creating redirect.")
            print "Redirect %s --> %s created" % (from_pagename, to_pagename)


def process_mapdata():
    # We create the MapData models here.  We can't create them until the
    # Page objects are created.
    global mapdata_objects_to_create

    from maps.models import MapData
    from pages.models import Page, slugify
    from django.contrib.gis.geos import Point, MultiPoint

    for item in mapdata_objects_to_create:
        print "Adding mapdata for", item['pagename']
        p = Page.objects.get(slug=slugify(item['pagename']))

        mapdata = MapData.objects.filter(page=p)
        y = float(item['lat'])
        x = float(item['lon'])
        point = Point(x, y)
        if mapdata:
            m = mapdata[0]
            points = m.points
            points.append(point)
            m.points = points
        else:
            points = MultiPoint(point)
            m = MapData(page=p, points=points)
        m.save()


def render_wikitext(title, s):
    """
    Attrs:
        title: Page title.
        s: MediaWiki wikitext string.

    Returns:
        HTML string of the rendered wikitext.
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'title': title,
        'text': s,
    })
    result = request.query()['parse']
    # There's a lot more in result, like page links and category
    # information.  For now, let's just grab the html text.
    return result['text']['*']


def _convert_to_string(l):
    s = ''
    for e in l:
        if isinstance(e, basestring):
            s += e
        elif isinstance(e, list):
            s += _convert_to_string(e)
        else:
            s += etree.tostring(e, encoding='UTF-8')
    return s


def _is_wiki_page_url(href):
    if href.startswith(SCRIPT_PATH):
        return True
    else:
        split_url = urlsplit(href)
        # If this is a relative url and has 'index.php' in it we'll say
        # it's a wiki link.
        if not split_url.scheme and split_url.path.endswith('index.php'):
            return True
    return False


def _get_wiki_link(link):
    """
    If the provided link is a wiki link then we return the name of the
    page to link to.  If it's not a wiki link then we return None.
    """
    pagename = None
    if 'href' in link.attrib:
        href = link.attrib['href']
        if _is_wiki_page_url(href):
            title = link.attrib.get('title')
            if 'new' in link.attrib.get('class', '').split():
                # It's a link to a non-existent page, so we parse the
                # page name from the title attribute in a really
                # hacky way.  Titles for non-existent links look
                # like <a ... title="Page name (page does not exist)">
                pagename = title[:title.rfind('(') - 1]
            else:
                pagename = title

    return pagename


def fix_internal_links(tree):
    def _process(item):
        pagename = _get_wiki_link(link)
        if pagename:
            # Set href to quoted pagename and clear out other attributes
            for k in link.attrib:
                del link.attrib[k]
            link.attrib['href'] = urllib.quote(pagename)

    for elem in tree:
        if elem.tag == 'a':
            _process(elem)
        for link in elem.findall('.//a'):
            _process(link)
    return tree


def fix_basic_tags(tree):
    for elem in tree:
        # Replace i, b with em, strong.
        if elem.tag == 'b':
            elem.tag = 'strong'
        for item in elem.findall('.//b'):
            item.tag = 'strong'

        if elem.tag == 'i':
            elem.tag = 'em'
        for item in elem.findall('.//i'):
            item.tag = 'em'
    return tree


def remove_edit_links(tree):
    for elem in tree:
        if (elem.tag == 'span' and
            ('editsection' in elem.attrib.get('class').split())):
            elem.tag = 'removeme'
        for item in elem.findall(".//span[@class='editsection']"):
            item.tag = 'removeme'  # hack to easily remove a bunch of elements
    return tree


def throw_out_tags(tree):
    throw_out = ['small']
    for elem in tree:
        for parent in elem.getiterator():
            for child in parent:
                if (child.tag in throw_out):
                    parent.text = parent.text or ''
                    parent.tail = parent.tail or ''
                    if child.text:
                        parent.text += (child.text + child.tail)
                    child.tag = 'removeme'
    return tree


def remove_headline_labels(tree):
    for elem in tree:
        for parent in elem.getiterator():
            for child in parent:
                if (child.tag == 'span' and
                    'mw-headline' in child.attrib.get('class', '').split()):
                    parent.text = parent.text or ''
                    parent.tail = parent.tail or ''
                    if child.text:
                        # We strip() here b/c mediawiki pads the text with a
                        # space for some reason.
                        tail = child.tail or ''
                        parent.text += (child.text.strip() + tail)
                    child.tag = 'removeme'
    return tree


def remove_elements_tagged_for_removal(tree):
    new_tree = []
    for elem in tree:
        if elem.tag == 'removeme':
            continue
        for parent in elem.getiterator():
            for child in parent:
                if child.tag == 'removeme':
                    parent.remove(child)
        new_tree.append(elem)
    return new_tree


def replace_mw_templates_with_includes(tree):
    """
    Replace {{templatethings}} inside of pages with our page include plugin.

    We can safely do this when the template doesn't have any arguments.
    When it does have arguments we just import it as raw HTML for now.
    """
    # We use the API to figure out what templates are being used on a given
    # page, and then translate them to page includes.  This can be done for
    # templates without arguments.
    #
    # The API doesn't tell us whether or not a template has arguments,
    # but we can figure this out by rendering the template and comparing the
    # resulting HTML to the HTML inside the rendered page.  If it's identical,
    # then we know we can replace it with an include.

    # TODO

    return tree


def process_non_html_elements(html, pagename):
    """
    Some MediaWiki extensions (e.g. google maps) output custom tags like
    &lt;googlemap&gt;.  We process those here.
    """
    def _repl_googlemap(match):
        global mapdata_objects_to_create
        xml = '<googlemap %s></googlemap>' % match.group('attribs')
        dom = minidom.parseString(xml)
        elem = dom.getElementsByTagName('googlemap')[0]
        lon = elem.getAttribute('lon')
        lat = elem.getAttribute('lat')

        d = {'pagename': pagename, 'lat': lat, 'lon': lon}
        mapdata_objects_to_create.append(d)

        return ''  # Clear out the googlemap tag nonsense.

    html = re.sub(
        '(?P<map>&lt;googlemap (?P<attribs>.+?)&gt;'
            '((.|\n)+?)'
        '&lt;/googlemap&gt;)',
        _repl_googlemap, html)
    return html


def process_html(html, pagename=None):
    """
    This is the real workhorse.  We take an html string which represents
    a rendered MediaWiki page and process bits and pieces of it, normalize
    elements / attributes and return cleaned up HTML.
    """
    html = process_non_html_elements(html, pagename)
    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    tree = p.parseFragment(html, encoding='UTF-8')
    tree = replace_mw_templates_with_includes(tree)
    tree = fix_internal_links(tree)
    tree = fix_basic_tags(tree)
    tree = remove_edit_links(tree)
    tree = remove_headline_labels(tree)
    tree = throw_out_tags(tree)

    tree = remove_elements_tagged_for_removal(tree)
    return _convert_to_string(tree)


def import_pages():
    from pages.models import Page, slugify

    request = api.APIRequest(site, {
        'action': 'query',
        'list': 'allpages',
        'aplimit': '50',
    })
    print "Getting master page list (this may take a bit).."
    response_list = request.query(querycontinue=False)['query']['allpages']
    pages = pagelist.listFromQuery(site, response_list)
    print "Got master page list."
    for mw_p in pages[:100]:
        print "Importing %s" % mw_p.title
        wikitext = mw_p.getWikiText()
        if mw_p.isRedir():
            add_redirect(mw_p)
            continue
        html = render_wikitext(mw_p.title, wikitext)

        if Page.objects.filter(slug=slugify(mw_p.title)):
            # Page already exists with this slug.  This is probably because
            # MediaWiki has case-sensitive pagenames.
            other_page = Page.objects.get(slug=slugify(mw_p.title))
            if len(html) > other_page.content:
                # *This* page has more content.  Let's use it instead.
                for other_page_version in other_page.versions.all():
                    other_page_version.delete()
                other_page.delete(track_changes=False)

        p = Page(name=mw_p.title, content=html)
        p.content = process_html(p.content, p.name)
        p.clean_fields()
        p.save()


def clear_out_existing_data():
    """
    A utility function that clears out existing pages, users, files,
    etc before running the import.
    """
    from pages.models import Page
    from redirects.models import Redirect

    for p in Page.objects.all():
        print 'Clearing out', p
        p.delete(track_changes=False)
        for p_h in p.versions.all():
            p_h.delete()
    for r in Redirect.objects.all():
        print 'Clearing out', r
        r.delete(track_changes=False)
        for r_h in r.versions.all():
            r_h.delete()


def run():
    clear_out_existing_data()
    import_users()
    import_pages()
    process_redirects()
    process_mapdata()
