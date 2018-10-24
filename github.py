import logging
import secrets
import time
from urllib.parse import urlencode, parse_qs

import jwt
import requests
from bleach.sanitizer import Cleaner
from cachecontrol import CacheControl
from html5lib.filters.base import Filter
from requests.auth import AuthBase
from telegram.ext import CallbackContext

from const import (GITHUB_PRIVATE_KEY_PATH, GITHUB_APP_ID, HMAC_SECRET, GITHUB_OAUTH_CLIENT_ID,
                   GITHUB_OAUTH_CLIENT_SECRET, GITHUB_OAUTH_REDIRECT_URI)
from menu import edit_menu_by_id
from utils import secure_encode_64

GITHUB_API_ACCEPT = {'Accept': 'application/vnd.github.machine-man-preview+json'}


class GithubUpdate(object):
    effective_chat = None
    effective_user = None

    def __init__(self, payload, guid, event):
        self.payload = payload
        self.guid = guid
        self.event = event


class GithubAuthUpdate(object):
    effective_chat = None
    effective_user = None

    def __init__(self, code, raw_state, state):
        self.code = code
        self.raw_state = raw_state
        self.state = state


class _GithubFilter(Filter):
    def __iter__(self):
        in_quote = False
        for token in super().__iter__():
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
            else:
                yield token


# This cleaner is not designed to use to transform content to be used in non-web-page contexts.
# Is a warning from the bleach docs... that we are gonna totally ignore...
# TODO: THIS IS NOT THREADSAFE
_cleaner = Cleaner(
    tags=[
        'a',
        'b',
        'code',
        'em',
        'i',
        'pre',
        'strong',
        'li',  # Stripped in _GithubFilter
        'input',  # Stripped in _GithubFilter
        'blockquote',  # Stripped in _GithubFilter
        'p',  # Stripped in _GithubFilter
        'hr'  # Stripped in _GithubFilter
    ],
    attributes={
        'a': ['href'],
        'li': ['class'],
        'input': ['checked']
    },
    strip=True,
    filters=[_GithubFilter]
)


class GithubHandler:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__qualname__)

    def handle_auth_update(self, update: GithubAuthUpdate, context: CallbackContext):
        user_id = update.state[0]
        message_id = update.state[1]
        # noinspection PyProtectedMember
        context.user_data = context._dispatcher.user_data[user_id]

        access_token = github_api.get_oauth_access_token(update.code, update.raw_state)

        self.logger.debug('Access token for user %s: %s', user_id, access_token)

        context.user_data['access_token'] = access_token

        from settings import login_menu
        context.menu_stack = ['settings', 'login']
        edit_menu_by_id(user_id, message_id, context, login_menu)

    def handle_update(self, update: GithubUpdate, context: CallbackContext):
        return getattr(self, update.event, self.unknown)(update, context)

    def unknown(self, update, context):
        self.logger.warning('Unknown event type %s. Data: %s', update.event, update.payload)

    def ping(self, update, context):
        self.logger.info('PING: %s', update.payload)

    # def integration_installation_repositories(self, update, context):
    #     new_repos = [{'id': repo['id'], 'full_name': repo['full_name']} for repo in
    #                  update.payload['repositories_added']]
    #     # TODO: Implement repositories_removed
    #
    #     self.logger.debug('New installation repos: %s', new_repos)
    #
    #     context.github_data.setdefault('repos', []).extend(new_repos)
    #
    # def integration_installation(self, update, context):
    #     new_repos = [{'id': repo['id'], 'full_name': repo['full_name']} for repo in update.payload['repositories']]
    #
    #     self.logger.debug('New installation. Repos: %s', new_repos)
    #
    #     context.github_data.setdefault('repos', []).extend(new_repos)


class JWTAuth(AuthBase):
    def __init__(self, app_id):
        self.iss = app_id
        with open(GITHUB_PRIVATE_KEY_PATH, 'rb') as f:
            self.private_key = f.read()

    def __call__(self, r):
        payload = {
            'iat': int(time.time()),
            'exp': int(time.time()) + 5 * 60,
            'iss': self.iss
        }
        encoded = jwt.encode(payload, self.private_key, algorithm='RS256')

        r.headers['Authorization'] = f'Bearer {encoded.decode("ascii")}'

        return r


class GithubAPI:
    def __init__(self):
        self.s = CacheControl(requests.session())

        self.app_id = GITHUB_APP_ID
        self.jwt_auth = JWTAuth(GITHUB_APP_ID)

        self.oauth_client_id = GITHUB_OAUTH_CLIENT_ID
        self.oauth_client_secret = GITHUB_OAUTH_CLIENT_SECRET
        self.oauth_redirect_uri = GITHUB_OAUTH_REDIRECT_URI

    def post(self, url, *args, api=True, jwt_bearer=False, oauth_server_auth=None, access_token=None, **kwargs):
        headers = kwargs.pop('headers', {})
        auth = kwargs.pop('auth', None)
        data = kwargs.pop('data', None)
        json = kwargs.pop('json', None)
        if api:
            headers.update(GITHUB_API_ACCEPT)
        if jwt_bearer:
            auth = self.jwt_auth
        if access_token:
            headers.update({'Authorization': f'token {access_token}'})
        if oauth_server_auth and (data or json):
            (data or json)['client_id'] = GITHUB_OAUTH_CLIENT_ID
            (data or json)['client_secret'] = GITHUB_OAUTH_CLIENT_SECRET

        return self.s.post(url, *args, data=data, json=json, headers=headers, auth=auth, **kwargs)

    def get(self, url, *args, api=True, jwt_bearer=False, oauth_server_auth=None, access_token=None, **kwargs):
        headers = kwargs.pop('headers', {})
        auth = kwargs.pop('auth', None)
        data = kwargs.pop('data', None)
        json = kwargs.pop('json', None)
        if api:
            headers.update(GITHUB_API_ACCEPT)
        if jwt_bearer:
            auth = self.jwt_auth
        if access_token:
            headers.update({'Authorization': f'token {access_token}'})
        if oauth_server_auth and (data or json):
            (data or json)['client_id'] = GITHUB_OAUTH_CLIENT_ID
            (data or json)['client_secret'] = GITHUB_OAUTH_CLIENT_SECRET

        return self.s.get(url, *args, data=data, json=json, headers=headers, auth=auth, **kwargs)

    def get_paginated(self, key, url, *args, **kwargs):
        r = self.get(url, *args, **kwargs)
        r.raise_for_status()
        data = r.json()[key]
        while 'link' in r.links.keys():
            r = self.get(url, headers=r.request.headers)
            r.raise_for_status()
            data.extend(r.json()[key])
        return data

    def oauth_authorize_url(self, *args):
        payload = {
            'client_id': self.oauth_client_id,
            'redirect_uri': self.oauth_redirect_uri,
            'state': secure_encode_64((*args, secrets.token_bytes(10)), HMAC_SECRET)
        }
        # noinspection SpellCheckingInspection
        return f'https://github.com/login/oauth/authorize?{urlencode(payload)}'

    def get_oauth_access_token(self, code, state):
        payload = {
            'client_id': self.oauth_client_id,
            'client_secret': self.oauth_client_secret,
            'code': code,
            'redirect_uri': self.oauth_redirect_uri,
            'state': state
        }
        r = self.post('https://github.com/login/oauth/access_token', data=payload, api=False)

        r.raise_for_status()

        data = parse_qs(r.text)

        access_token = data['access_token'][0]

        return access_token

    def get_user(self, access_token):
        r = self.get('https://api.github.com/user', access_token=access_token)

        r.raise_for_status()

        return r.json()

    def get_installations_for_user(self, access_token):
        data = self.get_paginated('installations',
                                  'https://api.github.com/user/installations',
                                  access_token=access_token)
        return data

    def get_repositories_for_installation(self, installation_id, access_token):
        data = self.get_paginated('repositories',
                                  f'https://api.github.com/user/installations/{installation_id}/repositories',
                                  access_token=access_token)
        return data

    def get_repository(self, repo_id, access_token):
        r = self.get(f'https://api.github.com/repositories/{repo_id}', access_token=access_token)

        r.raise_for_status()

        return r.json()

    def markdown(self, markdown, context):
        r = self.post(f'https://api.github.com/markdown', json={
            'text': markdown,
            'mode': 'gfm',
            'context': context
        }, oauth_server_auth=True)

        r.raise_for_status()

        return r.text


github_api = GithubAPI()
