import unittest
from lxml import etree
import html5lib
from html5lib import sanitizer

from import_mediawiki import normalize_html


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


def is_html_equal(h1, h2):
    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    h1_parsed = p.parseFragment(h1, encoding='UTF-8')
    h2_parsed = p.parseFragment(h2, encoding='UTF-8')
    return _convert_to_string(h1_parsed) == _convert_to_string(h2_parsed)


class TestHTMLNormalization(unittest.TestCase):
    def setUp(self):
        pass

    def test_internal_links(self):
        # Make sure we turn mediawiki internal links into our-style
        # internal wiki links.

        # A link to a page that doesn't exist.
        html = """<p>Some text here</p>
<p>And now a link: <a href="/mediawiki-1.16.0/index.php?title=Waverly_Road&amp;action=edit&amp;redlink=1" class="new" title="Waverly Road (page does not exist)">Waverly Road</a> woo!</p>"""
        expected_html = """<p>Some text here</p>
<p>And now a link: <a href="Waverly%20Road">Waverly Road</a> woo!</p>"""
        self.assertTrue(is_html_equal(normalize_html(html), expected_html))

        # A link to a page that does exist.
        html = """<p>Some text here</p>
<p>And now a link: <a href="/mediawiki-1.16.0/index.php/Ann_Arbor" title="Ann Arbor">Ann Arbor</a> woo!</p>"""
        expected_html = """<p>Some text here</p>
<p>And now a link: <a href="Ann%20Arbor">Ann Arbor</a> woo!</p>"""
        self.assertTrue(is_html_equal(normalize_html(html), expected_html))

        # A link to a redirect in MW.
        html = """<a href="/mediawiki-1.16.0/index.php/Ypsilanti" title="Ypsilanti" class="mw-redirect">Ypsilanti</a>"""
        expected_html = """<a href="Ypsilanti">Ypsilanti</a>"""

    #def test_choice(self):
    #    element = random.choice(self.seq)
    #    self.assertTrue(element in self.seq)

    #def test_sample(self):
    #    with self.assertRaises(ValueError):
    #        random.sample(self.seq, 20)
    #    for element in random.sample(self.seq, 5):
    #        self.assertTrue(element in self.seq)


def run():
    unittest.main()

if __name__ == '__main__':
    run()
