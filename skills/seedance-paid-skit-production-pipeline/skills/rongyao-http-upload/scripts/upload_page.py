"""Observed native multipart and HTML parser; no credentials or business defaults."""
import secrets
from html.parser import HTMLParser
class Stop(ValueError):pass
def multipart(fields, content):
    boundary = 'RongyaoUpload' + secrets.token_hex(16)
    chunks = []
    for key, value in fields:
        chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key +
                       '"\r\n\r\n' + str(value) + '\r\n').encode())
    chunks.extend([('--' + boundary + '\r\nContent-Disposition: form-data; name="data"; '
                    'filename="blob"\r\nContent-Type: application/octet-stream\r\n\r\n').encode(),
                   content, ('\r\n--' + boundary + '--\r\n').encode()])
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children, self.data = [], []

    def all(self, tag=None):
        found = [self] if tag is None or self.tag == tag else []
        for child in self.children: found.extend(child.all(tag))
        return found

    def text(self):
        return ' '.join(self.data + [x.text() for x in self.children]).strip()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.inputs, self.selects, self.scripts, self.links = [], {}, [], []
        self.inline = []
        self.root = Node('root')
        self._stack = [self.root]
        self._select = self._option = self._script = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = Node(tag, a, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in {'input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'area', 'base', 'wbr'}:
            self._stack.append(node)
        if tag == 'input': self.inputs.append(a)
        if tag == 'a' and a.get('href'): self.links.append(a['href'])
        if tag == 'select':
            self._select = a.get('id') or a.get('name')
            self.selects[self._select] = {'attrs': a, 'options': []}
        if tag == 'option' and self._select:
            self._option = dict(a, text='')
            self.selects[self._select]['options'].append(self._option)
        if tag == 'script':
            if a.get('src'): self.scripts.append(a['src'])
            else:
                self._script = []

    def handle_data(self, data):
        self._stack[-1].data.append(data)
        if self._option is not None: self._option['text'] += data
        if self._script is not None: self._script.append(data)

    def handle_endtag(self, tag):
        for i in range(len(self._stack)-1, 0, -1):
            if self._stack[i].tag == tag:
                self._stack = self._stack[:i]
                break
        if tag == 'option': self._option = None
        if tag == 'select': self._select = None
        if tag == 'script' and self._script is not None:
            self.inline.append(''.join(self._script)); self._script = None

    def field(self, key):
        v = [x.get('value', '') for x in self.inputs if x.get('id') == key]
        if len(v) != 1: raise Stop('FORM_FIELD_NOT_UNIQUE_' + key)
        return v[0]


