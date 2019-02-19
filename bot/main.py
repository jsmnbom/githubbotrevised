import http.client
import logging

from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, Chat
from telegram.ext import TypeHandler, CallbackContext, CommandHandler, MessageHandler, Filters

from bot import settings
from bot.const import TELEGRAM_BOT_TOKEN, DATABASE_FILE, DEBUG
from bot.github import GithubHandler
from bot.githubapi import github_api
from bot.githubupdates import GithubUpdate, GithubAuthUpdate
from bot.menu import reply_menu
from bot.persistence import Persistence
from bot.utils import decode_first_data_entity, deep_link, reply_data_link_filter
from bot.webhookupdater import WebhookUpdater

if DEBUG:
    http.client.HTTPConnection.debuglevel = 5

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                    # [%(filename)s:%(lineno)d]
                    format='%(asctime)s %(levelname)-8s %(name)s - %(message)s')


def error_handler(update, context: CallbackContext):
    logging.warning('Update "%s" caused error "%s"' % (update, context.error))


def start_handler(update: Update, context: CallbackContext):
    msg = update.effective_message

    # For deep linking
    if context.args:
        # Get the deep link argument and treat it as a command
        args = context.args[0].split('__')
        update.effective_message.text = '/' + ' '.join(args)
        update.effective_message.entities[0].length = len(args[0]) + 1
        context.update_queue.put(update)
        return

    msg.reply_text(f'👋 Hello, I am {context.bot.name}.\n'
                   f'I can notify you about events in your public GitHub repositories. '
                   f'You can also reply to my messages to post comments to GitHub right from Telegram. '
                   f'I am an improved version of the Telegram GitHub Bot.\n\n'
                   f'Use /settings to get started.',
                   disable_notification=True)


def help_handler(update: Update, context: CallbackContext):
    msg = update.effective_message
    private = update.effective_chat.type == Chat.PRIVATE
    steps = [
        f'First you must allow me access to the repositories in question. To do this, <a href="https://github.com/apps/telegram-githubbot-revised/installations/new">install</a> my <a href="https://github.com/apps/telegram-githubbot-revised">GitHub App</a> on your account or organisation, and make sure that it has access to the desired repositories.',
        f'Use the command /settings to open my settings interface and press the login button. This way I will know who you are.',
        f'Add me ({context.bot.name}) to the chat/group in which you would like to receive notifications.',
        f'In that chat use /settings to add the repositories you would like to receive notifications for.'
    ]
    if not private:
        steps.insert(1, f'Go to a private chat with me, by clicking here: {context.bot.name}.')
    text = '\n\n'.join(f'{i+1}️⃣ {step}' for i, step in enumerate(steps))
    msg.reply_text(f'<b>Github notification guide.</b>\n\n{text}\n\n'
                   f'Note that GitHub Help has more in depth guides on how to install GitHub Apps <a href="https://help.github.com/articles/installing-an-app-in-your-personal-account/#installing-a-github-app-in-your-personal-account">in your personal account</a> or <a href="https://help.github.com/articles/installing-an-app-in-your-organization/#installing-a-github-app-in-your-organization">in your organisation</a> if you are having trouble with step 1.',
                   reply_markup=InlineKeyboardMarkup([
                       [InlineKeyboardButton('Add me to a group',
                                             url=f'https://telegram.me/{context.bot.username}?startgroup=start')]
                   ]),
                   parse_mode=ParseMode.HTML,
                   disable_web_page_preview=True,
                   disable_notification=True)


def privacy_handler(update: Update, context: CallbackContext):
    msg = update.effective_message
    msg.reply_text(
        f'🔏 Privacy policy for {context.bot.name}\n\n'
        f'GithubBot Revised is an open source bot built by <a href="https://telegram.me/jsmnbom">Jasmin Bom</a>.\n\n'
        f'GithubBot revised stores GitHub login tokens - if you logout they will be deleted from the server.\n'
        f'To prevent overloading GitHub servers, data received from GitHub is also cached according to GitHub server headers.\n\n'
        f'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT '
        f'LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. '
        f'IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, '
        f'WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE '
        f'OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n\n'
        f'The MIT-licensed source code for GithubBot revised can be found at <a href="https://github.com/jsmnbom/githubbotrevised">GitHub</a>.',
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        disable_notification=True
    )


def login_handler(update: Update, context):
    context.menu_stack = ['settings']
    reply_menu(update, context, settings.login_menu)

def delete_job(context: CallbackContext):
    context.job.context.delete()


def reply_handler(update: Update, context: CallbackContext):
    msg = update.effective_message

    if msg.text[0] == '!':
        return

    data = decode_first_data_entity(msg.reply_to_message.entities)

    if not data:
        return

    comment_type, *data = data

    access_token = context.user_data.get('access_token')

    if not access_token:
        sent_msg = msg.reply_text(f'Cannot reply to {comment_type}, since you are not logged in. '
                                  f'Press button below to go to a private chat with me and login.\n\n'
                                  f'<i>This message will self destruct in 30 sec.</i>',
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton('Login', url=deep_link(context.bot, 'login'))
                                  ]]),
                                  parse_mode=ParseMode.HTML,
                                  disable_notification=True)
        context.job_queue.run_once(delete_job, 30, sent_msg)
        return

    if comment_type in ('issue', 'pull request'):
        repo, number, author = data

        text = f'@{author} {msg.text_markdown}'

        github_api.add_issue_comment(repo, number, text, access_token=access_token)
    elif comment_type == 'pull request review comment':
        repo, number, comment_id, author = data

        text = f'@{author} {msg.text_markdown}'

        github_api.add_review_comment(repo, number, comment_id, text, access_token=access_token)


if __name__ == '__main__':
    # Not strictly needed anymore since we no longer have custom persistent data
    # But since we likely will want it in the future, we keep our custom persistence
    persistence = Persistence(DATABASE_FILE)
    # Init our very custom webhook handler
    updater = WebhookUpdater(TELEGRAM_BOT_TOKEN,
                             updater_kwargs={'use_context': True,
                                             'persistence': persistence})
    dp = updater.dispatcher

    # See persistence note above
    CallbackContext.github_data = property(lambda self: persistence.github_data)

    # Save data every five (5) min
    dp.job_queue.run_repeating(lambda *_: persistence.flush(), 5 * 60)

    # Telegram updates
    dp.add_handler(CommandHandler('start', start_handler))
    dp.add_handler(CommandHandler('help', help_handler))
    dp.add_handler(CommandHandler('privacy', privacy_handler))
    dp.add_handler(CommandHandler('login', login_handler))

    settings.add_handlers(dp)

    # For commenting on issues/PR/reviews
    dp.add_handler(MessageHandler(Filters.reply & reply_data_link_filter, reply_handler,
                                  channel_post_updates=False, edited_updates=False))

    # Non-telegram updates
    github_handler = GithubHandler(dp)
    dp.add_handler(TypeHandler(GithubUpdate, github_handler.handle_update))
    dp.add_handler(TypeHandler(GithubAuthUpdate, github_handler.handle_auth_update))

    dp.add_error_handler(error_handler)

    updater.start()
