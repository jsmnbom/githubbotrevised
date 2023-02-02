import base64
import hashlib
import hmac
import pickle
from typing import Any

import base65536
from telegram import MessageEntity
from telegram.ext.filters import MessageFilter

from const import HMAC_SECRET

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


class _ReplyDataLinkFilter(MessageFilter):
    def filter(self, message):
        if message.reply_to_message:
            for entity in message.reply_to_message.entities:
                if entity.type == MessageEntity.TEXT_LINK:
                    return entity.url.startswith(URL_BASE)
                break


reply_data_link_filter = _ReplyDataLinkFilter()


def link(url, text):
    return f'<a href="{url}">{text}</a>'
