import http.client
import logging

from telegram import Update, ParseMode
from telegram.ext import TypeHandler, CallbackContext, CommandHandler

import github
import settings
from const import TELEGRAM_BOT_TOKEN, DATABASE_FILE
from persistence import Persistence
from text import HELP_ADD_REPO
from webhookupdater import WebhookUpdater

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

    if context.args[0] == 'add_repo':
        msg.reply_text(HELP_ADD_REPO, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        # TODO: Add proper general help
        msg.reply_text(f'NYI')


def privacy_handler(update: Update, _):
    msg = update.effective_message
    msg.reply_text(f'You have no privacy.')


def login_handler(update: Update, _):
    link = github.github_api.oauth_authorize_url(update.effective_message.from_user.id)
    update.effective_message.reply_text(f'Click this link please: {link}')


def test_handler(update: Update, context: CallbackContext):
    # TODO: If exists
    access_token = context.user_data['access_token']

    installations = github.github_api.get_installations_for_user(access_token=access_token)

    repos = []

    for installation in installations:
        repos.extend(github.github_api.get_repositories_for_installation(installation['id'],
                                                                         access_token=access_token))

    update.effective_message.reply_text('Repositories:\n' +
                                        '\n'.join(f'<a href="{repo["html_url"]}">{repo["full_name"]}</a>'
                                                  for repo in repos),
                                        parse_mode=ParseMode.HTML)


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

    dp.add_handler(TypeHandler(github.GithubUpdate, github.GithubHandler().handle_update))
    dp.add_handler(TypeHandler(github.GithubAuthUpdate, github.GithubHandler().handle_auth_update))

    dp.add_error_handler(error_handler)

    updater.start()
