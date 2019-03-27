import hashlib
import hmac
import json
import logging
from threading import Thread
from typing import Dict

from telegram import Update
from telegram.ext import Updater
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler, HTTPError

from bot.const import GITHUB_WEBHOOK_SECRET, SERVER_HOSTNAME_PATTERN, SERVER_PORT, TELEGRAM_WEBHOOK_URL, HMAC_SECRET, DEBUG
from bot.githubupdates import GithubUpdate, GithubAuthUpdate
from bot.utils import secure_decode_64, HMACException


# noinspection PyAbstractClass
class BaseWebhookHandler(RequestHandler):
    SUPPORTED_METHODS = ['POST']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__qualname__)

    def post(self):
        self.logger.debug('Webhook triggered')
        self.validate()
        json_string = self.request.body.decode('utf-8')
        data = json.loads(json_string)
        self.set_status(200)
        self.logger.debug('Webhook received data: ' + json_string)
        self.process_data(data)

    def process_data(self, data: Dict):
        raise NotImplementedError

    def validate(self):
        ct_header = self.request.headers.get("Content-Type", None)
        if ct_header != 'application/json':
            raise HTTPError(403, reason='Content type must be application/json!')

    def write_error(self, status_code, **kwargs):
        super().write_error(status_code, **kwargs)
        self.logger.debug('%s - - %s' % (self.request.remote_ip, 'Exception in WebhookHandler'),
                          exc_info=kwargs['exc_info'])


# noinspection PyAbstractClass
class TelegramWebhookHandler(BaseWebhookHandler):
    bot = None
    update_queue = None

    # noinspection PyMethodOverriding
    def initialize(self, bot, update_queue):
        self.bot = bot
        self.update_queue = update_queue

    def process_data(self, data):
        update = Update.de_json(data, self.bot)
        self.logger.debug('Received telegram.Update with ID %d on Webhook', update.update_id)
        self.update_queue.put(update)


# noinspection PyAbstractClass
class GithubWebhookHandler(BaseWebhookHandler):
    update_queue = None

    # noinspection PyMethodOverriding
    def initialize(self, update_queue):
        self.update_queue = update_queue

    def process_data(self, data):
        guid = self.request.headers.get('X-GitHub-Delivery')
        event = self.request.headers.get('X-GitHub-Event')
        update = GithubUpdate(data, guid, event)
        self.logger.debug('Received GithubUpdate %s with GUID %s on Webhook', update.event, update.guid)
        self.update_queue.put(update)

    def validate(self):
        super().validate()

        received_signature = self.request.headers.get('X-Hub-Signature')
        if not received_signature:
            raise HTTPError(403, reason='Signature missing!')
        received_signature = received_signature[5:]  # remove sha1=
        signature = hmac.new(GITHUB_WEBHOOK_SECRET, self.request.body, hashlib.sha1).hexdigest()
        if not hmac.compare_digest(received_signature, signature):
            raise HTTPError(403, reason='Signature does not match!')


# noinspection PyAbstractClass
class GithubAuthHandler(RequestHandler):
    SUPPORTED_METHODS = ['GET']
    bot = None
    update_queue = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__qualname__)

    # noinspection PyMethodOverriding
    def initialize(self, bot, update_queue):
        self.bot = bot
        self.update_queue = update_queue

    def _send_error(self):
        raise HTTPError(400)

    def _send_redirect(self):
        self.redirect(f'https://telegram.me/{self.bot.username}?start=settings')

    def get(self):
        self.logger.debug('GitHub Auth triggered')
        code = self.get_argument('code', None)
        raw_state = self.get_argument('state', None)
        if code is None or raw_state is None:
            self.logger.warning('Missing code or state in GithubAuthUpdate')
            return self._send_error()

        try:
            state = secure_decode_64(raw_state, HMAC_SECRET)
        except HMACException:
            self.logger.warning('HMACException when decoding state in GithubAuthUpdate')
            return self._send_error()

        self.logger.debug('Received GithubAuthUpdate. code=%s state=%s', code, state)

        self.update_queue.put(GithubAuthUpdate(code=code, raw_state=raw_state, state=state))

        return self._send_redirect()


class WebhookUpdater(object):
    def __init__(self, token, updater_kwargs=None):
        self.logger = logging.getLogger(self.__class__.__qualname__)

        if updater_kwargs is None:
            updater_kwargs = {}

        self.updater = Updater(token=token, user_sig_handler=self.signal_handler, **updater_kwargs)

        self.bot = self.updater.bot
        self.dispatcher = self.updater.dispatcher
        self.update_queue = self.updater.update_queue

        self.app = Application(debug=DEBUG)
        self.app.add_handlers(SERVER_HOSTNAME_PATTERN, [
            (
                r'/{}/?'.format(token),
                TelegramWebhookHandler,
                {'bot': self.bot, 'update_queue': self.update_queue}
            ), (
                r'/github/webhook/?',
                GithubWebhookHandler,
                {'update_queue': self.update_queue}
            ), (
                r'/github/auth',
                GithubAuthHandler,
                {'bot': self.bot, 'update_queue': self.update_queue}
            )
        ])

        self.http_server = HTTPServer(self.app)

    def _start_http_server(self):
        IOLoop().make_current()
        self.logger.debug('Webhook Server started.')
        self.http_server.listen(SERVER_PORT)
        self.http_server_loop = IOLoop.current()
        self.http_server_loop.start()
        self.logger.debug('Webhook Server stopped.')

    def signal_handler(self, *_):
        self.http_server_loop.add_callback(self.http_server_loop.stop)

    def start(self):
        self.updater.job_queue.start()
        self.updater.running = True
        # noinspection PyProtectedMember
        self.updater._init_thread(self.dispatcher.start, 'dispatcher')

        thr = Thread(target=self._start_http_server, name='webhook_server')
        thr.start()

        self.bot.set_webhook(TELEGRAM_WEBHOOK_URL)

        self.updater.idle()
        self.updater.stop()
