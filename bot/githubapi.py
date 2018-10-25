import secrets
import time
from urllib.parse import urlencode, parse_qs

import jwt
import requests
from cachecontrol import CacheControl
from requests.auth import AuthBase

from bot.const import (GITHUB_PRIVATE_KEY_PATH, GITHUB_APP_ID, HMAC_SECRET, GITHUB_OAUTH_CLIENT_ID,
                       GITHUB_OAUTH_CLIENT_SECRET, GITHUB_OAUTH_REDIRECT_URI)
from bot.utils import secure_encode_64

GITHUB_API_ACCEPT = {'Accept': 'application/vnd.github.machine-man-preview+json'}


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

    def add_issue_comment(self, repo, number, body, access_token):
        r = self.post(f'https://api.github.com/repos/{repo}/issues/{number}/comments', json={
            'body': body
        }, access_token=access_token)

        r.raise_for_status()

        return r.text

    def add_review_comment(self, repo, number, in_reply_to, body, access_token):
        r = self.post(f'https://api.github.com/repos/{repo}/pulls/{number}/comments', json={
            'body': body,
            'in_reply_to': in_reply_to
        }, access_token=access_token)

        r.raise_for_status()

        return r.text


github_api = GithubAPI()
