import hangups
import re
import importlib
import html

from html.parser import HTMLParser
from html.entities import name2codepoint

def text_to_segments(text):
    """Create list of message segments from text"""
    # Replace two consecutive spaces with space and non-breakable space,
    # then split text to lines
    lines = text.replace('  ', ' \xa0').splitlines()
    if not lines:
        return []

    # Generate line segments
    segments = []
    for line in lines[:-1]:
        if line:
            segments.append(hangups.ChatMessageSegment(line))
        segments.append(hangups.ChatMessageSegment('\n', hangups.SegmentType.LINE_BREAK))
    if lines[-1]:
        segments.append(hangups.ChatMessageSegment(lines[-1]))

    return segments

class simpleHTMLParser(HTMLParser):
    def __init__(self, debug=False, **kwargs):
        super().__init__(kwargs)

        self._debug = debug

        self._flags = {"bold" : False, 
                       "italic" : False,
                       "underline" : False, 
                       "link_target" : None}

        self._link_text = None

        self._allow_extra_html_tag = False;

    def feed(self, html):
        self._segments = list()
        super().feed(html)
        return self._segments

    def handle_starttag(self, tag, attrs):
        if tag == 'html':
            if self._allow_extra_html_tag:
                self.segments_extend(self.get_starttag_text(), "starttag")
            else:
                # skip the first <html> tag added by simple_parse_to_segments()
                self._allow_extra_html_tag = True
        elif tag == 'b':
            self._flags["bold"] = True
        elif tag == 'i':
            self._flags["italic"] = True
        elif tag == 'u':
            self._flags["underline"] = True
        elif tag == 'a':
            self._link_text = ""
            for attr in attrs:
                if attr[0] == "href":
                    self._flags["link_target"] = attr[1]
                    break
        else:
            # preserve the full text of the tag
            self.segments_extend(self.get_starttag_text(), "starttag")

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.segments_linebreak()
        else:
            # preserve the full text of the tag
            self.segments_extend(self.get_starttag_text(), "startendtag")

    def handle_endtag(self, tag):
        if tag == 'html':
            # XXX: any closing html tag will always go missing!
            pass
        elif tag == 'b':
            self._flags["bold"] = False
        elif tag == 'i':
            self._flags["italic"] = False
        elif tag == 'u':
            self._flags["underline"] = False
        elif tag == 'a':
            self._segments.append(
              hangups.ChatMessageSegment(
                self._link_text,
                hangups.SegmentType.LINK,
                link_target=self._flags["link_target"],
                is_bold=self._flags["bold"], 
                is_italic=self._flags["italic"], 
                is_underline=self._flags["underline"]))
            self._flags["link_target"] = None
        else:
            # xxx: this removes any attributes inside the tag
            self.segments_extend("</" + tag + ">", "endtag")

    def handle_entityref(self, name):
        if self._flags["link_target"] is not None:
            if(self._debug): print("simpleHTMLParser(): [LINK] entityref {}".format(name))
            self._link_text += "&" + name 
        else:
            _unescaped = html.unescape("&" + name)
            self.segments_extend(_unescaped, "entityref")

    def handle_data(self, data):
        if self._flags["link_target"] is not None:
            if(self._debug): print("simpleHTMLParser(): [LINK] data \"{}\"".format(data))
            self._link_text += data 
        else:
            self.segments_extend(data, "data")

    def segments_linebreak(self):
        self._segments.append(
            hangups.ChatMessageSegment(
                "\n", 
                hangups.SegmentType.LINE_BREAK))

    def segments_extend(self, text, type, forceNew=False):
        if len(self._segments) == 0 or forceNew is True:
            if(self._debug): print("simpleHTMLParser(): [NEW] {} {}".format(type, text))
            self._segments.append(
              hangups.ChatMessageSegment(
                text,
                is_bold=self._flags["bold"], 
                is_italic=self._flags["italic"], 
                is_underline=self._flags["underline"], 
                link_target=self._flags["link_target"]))
        else:
            if(self._debug): print("simpleHTMLParser(): [APPEND] {} {}".format(type, text))
            previous_segment = self._segments[-1]
            if (previous_segment.is_bold != self._flags["bold"] or
                    previous_segment.is_italic != self._flags["italic"] or
                    previous_segment.is_underline != self._flags["underline"] or
                    previous_segment.link_target != self._flags["link_target"] or
                    previous_segment.text == "\n"):
                self.segments_extend(text, type, forceNew=True)
            else:
                previous_segment.text += text

def simple_parse_to_segments(html, debug=False, **kwargs):
    html = fix_urls(html)
    html = '<html>' + html + '</html>' # html.parser seems to ignore the final entityref without html closure
    parser = simpleHTMLParser(debug)
    return parser.feed(html)

def class_from_name(module_name, class_name):
    """adapted from http://stackoverflow.com/a/13808375"""
    # load the module, will raise ImportError if module cannot be loaded
    m = importlib.import_module(module_name)
    # get the class, will raise AttributeError if class cannot be found
    c = getattr(m, class_name)
    return c

def fix_urls(text):
    tokens = text.split() # "a  b" => (a,b)
    urlified = []
    for token in tokens:
        # analyse each token for a url-like pattern
        if token.startswith(("http://", "https://")):
            token = '<a href="' + token + '">' + token + '</a>'
        urlified.append(token)
    text = " ".join(urlified)
    return text

def test_parser():
    test_strings = [
        ["hello world", 
            'hello world', # expected return by fix_urls()
            [1]], # expected number of segments returned by simple_parse_to_segments()
        ["http://www.google.com/",
            '<a href="http://www.google.com/">http://www.google.com/</a>',
            [1]],
        ["https://www.google.com/?a=b&c=d&e=f",
            '<a href="https://www.google.com/?a=b&c=d&e=f">https://www.google.com/?a=b&c=d&e=f</a>',
            [1]],
        ["&lt;html-encoded test&gt;",
            '&lt;html-encoded test&gt;',
            [1]],
        ["A&B&C&D&E",
            'A&B&C&D&E',
            [1]],
        ["A&<b>B</b>&C&D&E",
            'A&<b>B</b>&C&D&E',
            [3]],
        ["A&amp;B&amp;C&amp;D&amp;E",
            'A&amp;B&amp;C&amp;D&amp;E',
            [1]],
        ["C&L",
            'C&L',
            [1]],
        ["<in a fake tag>",
            '<in a fake tag>',
            [1]],
        ['<img src="http://i.imgur.com/E3gxs.gif"/>',
            '<img src="http://i.imgur.com/E3gxs.gif"/>',
            [1]],
        ['<img src="http://i.imgur.com/E3gxs.gif" />',
            '<img src="http://i.imgur.com/E3gxs.gif" />',
            [1]],
        ['<img src="http://i.imgur.com/E3gxs.gif" abc />',
            '<img src="http://i.imgur.com/E3gxs.gif" abc />',
            [1]],
        ['<in "a"="abc" fake tag>',
            '<in "a"="abc" fake tag>',
            [1]],
        ['<in a=abc fake tag>',
            '<in a=abc fake tag>',
            [1]],
        ["abc <some@email.com>",
            'abc <some@email.com>',
            [1]],
        ['</in "a"="xyz" fake tag>', # XXX: fails due to HTMLParser limitations
            '</in "a"="xyz" fake tag>',
            [1]],
        ['<html><html><b></html></b><b>ABC</b>', # XXX: </html> is consumed
            '<html><html><b></html></b><b>ABC</b>',
            [2]],
        ["go here: http://www.google.com/",
            'go here: <a href="http://www.google.com/">http://www.google.com/</a>',
            [2]],
        ['go here: <a href="http://google.com/">http://www.google.com/</a>',
            'go here: <a href="http://google.com/">http://www.google.com/</a>',
            [2]],
        ["go here: http://www.google.com/ abc",
            'go here: <a href="http://www.google.com/">http://www.google.com/</a> abc',
            [3]],
        ['http://i.imgur.com/E3gxs.gif',
            '<a href="http://i.imgur.com/E3gxs.gif">http://i.imgur.com/E3gxs.gif</a>',
            [1]]
    ]

    print("*** TEST: utils.fix_urls() ***")
    DEVIATION = False
    for test in test_strings:
        original = test[0]
        expected_urlified = test[1]
        actual_urlified = fix_urls(original)

        if actual_urlified != expected_urlified:
            print("ORIGINAL: {}".format(original))
            print("EXPECTED: {}".format(expected_urlified))
            print(" RESULTS: {}".format(actual_urlified))
            print()
            DEVIATION = True
    if DEVIATION is False:
        print("*** TEST: utils.fix_urls(): PASS ***")

    if DEVIATION is False:
        print("*** TEST: simple_parse_to_segments() ***")
        for test in test_strings:
            original = test[0]
            expected_segment_count = test[2][0]

            segments = simple_parse_to_segments(original)
            actual_segment_count = len(segments)

            if expected_segment_count != actual_segment_count:
                print("ORIGINAL: {}".format(original))
                print("EXPECTED/ACTUAL COUNT: {}/{}".format(expected_segment_count, actual_segment_count))
                for segment in segments:
                    is_bold = 0
                    is_link = 0
                    if segment.is_bold: is_bold = 1
                    if segment.link_target: is_link = 1
                    print(" B L TXT: {} {} {}".format(is_bold, is_link, segment.text))
                print()
                DEVIATION = True
    if DEVIATION is False:
        print("*** TEST: simple_parse_to_segments(): PASS ***")

if __name__ == '__main__':
    test_parser()