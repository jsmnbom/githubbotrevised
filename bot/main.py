import http.client
import logging

from telegram import Update, ParseMode
from telegram.ext import TypeHandler, CallbackContext, CommandHandler

from bot import settings
from bot.const import TELEGRAM_BOT_TOKEN, DATABASE_FILE
from bot.github import GithubHandler
from bot.githubupdates import GithubUpdate, GithubAuthUpdate
from bot.menu import reply_menu
from bot.persistence import Persistence
from bot.text import HELP_ADD_REPO
from bot.webhookupdater import WebhookUpdater

http.client.HTTPConnection.debuglevel = 5

logging.basicConfig(level=logging.DEBUG,
                    # [%(filename)s:%(lineno)d]
                    format='%(asctime)s %(levelname)-8s %(name)s - %(message)s')


def error_handler(update, context: CallbackContext):
    logging.warning('Update "%s" caused error "%s"' % (update, context.error))


def start_handler(update: Update, context: CallbackContext):
    msg = update.effective_message

    if context.args:
        args = context.args[0].split('__')
        update.effective_message.text = '/' + ' '.join(args)
        update.effective_message.entities[0].length = len(args[0]) + 1
        context.update_queue.put(update)
        return

    msg.reply_text(f'Hello, I am {context.bot.name}. I can do things!')


def help_handler(update: Update, context: CallbackContext):
    msg = update.effective_message

    if context.args and context.args[0] == 'add_repo':
        msg.reply_text(HELP_ADD_REPO, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        # TODO: Add proper general help
        msg.reply_text(f'NYI')


def privacy_handler(update: Update, _):
    msg = update.effective_message
    msg.reply_text(f'You have no privacy.')


def login_handler(update: Update, context):
    context.menu_stack = ['settings']
    reply_menu(update, context, settings.login_menu)


def test_handler(update: Update, context: CallbackContext):
    pass


if __name__ == '__main__':
    persistence = Persistence(DATABASE_FILE)
    updater = WebhookUpdater(TELEGRAM_BOT_TOKEN,
                             updater_kwargs={'use_context': True,
                                             'persistence': persistence})
    dp = updater.dispatcher

    CallbackContext.github_data = property(lambda self: persistence.github_data)

    dp.job_queue.run_repeating(lambda *_: persistence.flush(), 5 * 60)

    dp.add_handler(CommandHandler('start', start_handler))
    dp.add_handler(CommandHandler('help', help_handler))
    dp.add_handler(CommandHandler('privacy', privacy_handler))
    dp.add_handler(CommandHandler('login', login_handler))
    dp.add_handler(CommandHandler('test', test_handler))

    settings.add_handlers(dp)

    github_handler = GithubHandler(dp)
    dp.add_handler(TypeHandler(GithubUpdate, github_handler.handle_update))
    dp.add_handler(TypeHandler(GithubAuthUpdate, github_handler.handle_auth_update))

    dp.add_error_handler(error_handler)

    updater.start()
