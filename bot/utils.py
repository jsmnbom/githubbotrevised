import base64
import hashlib
import hmac
import itertools
import pickle
from typing import Any

import base65536
import html5lib
import telegram
from bleach.sanitizer import Cleaner
from html5lib.filters.base import Filter
from html5lib.serializer import HTMLSerializer
from telegram import MessageEntity
from telegram.ext import BaseFilter

from bot.const import HMAC_SECRET

URL_BASE = 'https://ghbot.test/'


class HMACException(Exception):
    pass


def secure_encode_64(input_data: Any, secret: bytes) -> str:
    pickled = pickle.dumps(input_data)
    length = str(len(pickled)).encode('ascii')
    hmac_hash = hmac.new(secret, pickled, hashlib.sha256).digest()
    return base64.b64encode(length + b'\0' + pickled + hmac_hash).decode('ascii')


def secure_decode_64(input_data: str, secret: bytes) -> Any:
    # Str -> bytes
    decoded_data = base64.b64decode(input_data)
    length, _, data_and_hash = decoded_data.partition(b'\0')
    length = int(length.decode('ascii'))
    raw_data, hmac_hash = data_and_hash[:length], data_and_hash[length:]
    if not hmac.compare_digest(hmac.new(secret, raw_data, hashlib.sha256).digest(), hmac_hash):
        raise HMACException('Data has been tampered with.')
    return pickle.loads(raw_data)


def secure_encode_65536(input_data, secret):
    pickled = pickle.dumps(input_data)
    length = str(len(pickled)).encode('ascii')
    hmac_hash = hmac.new(secret, pickled, hashlib.sha256).digest()
    return base65536.encode(length + b'\0' + pickled + hmac_hash)


def secure_decode_65536(input_data, secret):
    decoded_data = base65536.decode(input_data)
    length, _, data_and_hash = decoded_data.partition(b'\0')
    length = int(length.decode('ascii'))
    raw_data, hmac_hash = data_and_hash[:length], data_and_hash[length:]
    if not hmac.compare_digest(hmac.new(secret, raw_data, hashlib.sha256).digest(), hmac_hash):
        raise HMACException('Data link has been tampered with.')
    return pickle.loads(raw_data)


def encode_data_link(data):
    return f'<a href="{URL_BASE}{secure_encode_65536(data, HMAC_SECRET)}">\u200b</a>'


def decode_data_link(url):
    return secure_decode_65536(url[len(URL_BASE):], HMAC_SECRET)


def decode_data_entity(entity):
    return decode_data_link(entity.url)


def decode_first_data_entity(entities):
    for entity in entities:
        if entity.type == MessageEntity.TEXT_LINK and entity.url.startswith(URL_BASE):
            return decode_data_entity(entity)


def deep_link(bot, data):
    return f'https://telegram.me/{bot.username}?start={data}'


class _ReplyDataLinkFilter(BaseFilter):
    def filter(self, message):
        for entity in message.reply_to_message.entities:
            if entity.type == MessageEntity.TEXT_LINK:
                return entity.url.startswith(URL_BASE)
            break


reply_data_link_filter = _ReplyDataLinkFilter()


class _GithubFilter(Filter):
    def __iter__(self):
        in_quote = False
        in_tag = 0
        for token in super().__iter__():
            if token['type'] == 'StartTag' and token['name'] == 'pre':
                if not in_tag:
                    token['data'] = {}
                    yield {
                        'data': 'Suggestion:\n',
                        'type': 'Characters'
                    }

            if token['type'] == 'StartTag' and token['name'] == 'li':
                if not (token['data'] and token['data'].get('class') != 'task-list-item'):
                    yield {
                        'data': '- ',
                        'type': 'Characters'
                    }
            elif token['type'] == 'StartTag' and token['name'] == 'blockquote':
                in_quote = True
            elif token['type'] == 'EndTag' and token['name'] == 'blockquote':
                in_quote = False
            elif token['type'] == 'StartTag' and token['name'] == 'p':
                if in_quote:
                    yield {
                        'data': '> ',
                        'type': 'Characters'
                    }
            elif token['type'] == 'EmptyTag' and token['name'] == 'hr':
                yield {
                    'data': '\n────────────────────\n',
                    'type': 'Characters'
                }
            elif token['type'] == 'EmptyTag' and token['name'] == 'input':
                if token['data'].get('checked'):
                    yield {
                        'data': '☑ ',
                        'type': 'Characters'
                    }
                else:
                    yield {
                        'data': '☐ ',
                        'type': 'Characters'
                    }
            elif (token['type'] in ('StartTag', 'EndTag', 'EmptyTag') and
                  token['name'] in ('li', 'blockquote', 'input', 'hr', 'p')):
                pass
            elif token['type'] == 'StartTag':
                if not in_tag:
                    yield token
                in_tag += 1
            elif token['type'] == 'EndTag':
                in_tag -= 1
                if not in_tag:
                    yield token
            else:
                yield token


# "This cleaner is not designed to use to transform content to be used in non-web-page contexts."
# ...is a warning from the bleach docs... that we are gonna totally ignore...
# TODO: THIS IS NOT THREADSAFE
github_cleaner = Cleaner(
    tags=[
        'a', 'b', 'code', 'em', 'i', 'pre', 'strong',
        'li', 'input', 'blockquote', 'p', 'hr'  # Stripped in _GithubFilter
    ],
    attributes={
        'a': ['href'],
        'li': ['class'],  # Stripped in _GithubFilter
        'input': ['checked'],  # Stripped in _GithubFilter
        'pre': ['lang'],  # Stripped in _GithubFilter
    },
    strip=True,
    filters=[_GithubFilter]
)


class TelegramTruncator(Filter):
    def __init__(self, source,
                 truncated_message,
                 suffix,
                 max_entities=None,
                 max_length=None):
        super().__init__(source)
        self.truncated_message = truncated_message or []
        self.suffix = suffix or []
        self.max_entities = max_entities or telegram.constants.MAX_MESSAGE_ENTITIES
        self.max_length = max_length or telegram.constants.MAX_MESSAGE_LENGTH

    def __iter__(self):
        for token in itertools.chain(self.truncated_message, self.suffix):
            if token['type'] == 'StartTag':
                self.max_entities -= 1
            elif token['type'] in ('Characters', 'SpaceCharacters'):
                self.max_length -= len(token['data'])

        entity_count = 0
        current_length = 0
        current_tag_stack = []
        for token in iter(self.source):
            if entity_count >= self.max_entities:
                for tag in reversed(current_tag_stack):
                    yield {
                        'type': 'EndTag',
                        'name': tag
                    }
                yield from iter(self.truncated_message)
                break
            if token['type'] in ('Characters', 'SpaceCharacters'):
                if (current_length + len(token['data'])) > self.max_length:
                    yield {
                        'data': token['data'][:self.max_length - current_length],
                        'type': 'Characters'
                    }
                    for tag in reversed(current_tag_stack):
                        yield {
                            'type': 'EndTag',
                            'name': tag
                        }
                    yield from iter(self.truncated_message)
                    break
                else:
                    current_length += len(token['data'])
            elif token['type'] == 'EmptyTag':
                entity_count += 1
            elif token['type'] == 'StartTag':
                entity_count += 1
                current_tag_stack.append(token['name'])
            elif token['type'] == 'EndTag':
                current_tag_stack.pop()

            yield token

        yield from iter(self.suffix)


def truncate(html, truncated_message, suffix, max_entities=None, max_length=None):
    walker = html5lib.getTreeWalker('etree')
    html_stream = walker(html5lib.parseFragment(html, treebuilder='etree'))
    truncated_message_stream = walker(html5lib.parseFragment(truncated_message, treebuilder='etree'))
    suffix_stream = walker(html5lib.parseFragment(suffix, treebuilder='etree'))
    truncated = TelegramTruncator(html_stream, truncated_message=truncated_message_stream, suffix=suffix_stream,
                                  max_entities=max_entities, max_length=max_length)
    return HTMLSerializer().render(truncated).strip('\n')


def link(url, text):
    return f'<a href="{url}">{text}</a>'
