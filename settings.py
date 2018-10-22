from dataclasses import dataclass
from itertools import zip_longest
from uuid import uuid4

from telegram import Chat, InlineQueryResultArticle, InputTextMessageContent, ParseMode
from telegram.ext import Dispatcher, InlineQueryHandler, CommandHandler

from github import github_api
from menu import Button, Menu, BackButton, reply_menu, MenuHandler, ToggleButton, SetButton


@dataclass
class Repo:
    name: str
    id: int
    enabled: bool = True


class InlineQueries(object):
    add_repo = 'Add repository:'


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks"""
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


def settings_text(update, context):
    private = update.effective_chat.type == Chat.PRIVATE

    text = f'Settings for {context.bot.name}\n\n'

    if private:
        access_token = context.user_data.get('access_token')

        if access_token:
            github_user = github_api.get_user(access_token)

            text += ('You are currently logged in as '
                     f'<a href="{github_user["html_url"]}">{github_user["login"]} ({github_user["name"]})</a>'
                     '.\n')
        else:
            text += f'You are currently not logged in.\n'

    text += '\nNo repositories have been set up for this chat.\n'

    return text


def settings_buttons(update, context):
    private = update.effective_chat.type == Chat.PRIVATE

    buttons = []
    if private:
        access_token = context.user_data.get('access_token')

        if access_token:
            buttons.append(SetButton('login', None, 'Logout'))
        else:
            buttons.append(Button('Login', menu='login'))
    else:
        buttons.append(Button('User settings', url=f'https://telegram.me/{context.bot.username}?start=settings'))

    buttons.append(Button('Repositories', menu='repos'))

    return [[button] for button in buttons]


def settings_set_data(_, context):
    if context.key == 'login' and context.value is None:
        del context.user_data['access_token']


settings_menu = Menu(
    name='settings',
    text=settings_text,
    buttons=settings_buttons,
    set_data=settings_set_data
)


def login_text(update, context):
    access_token = context.user_data.get('access_token')

    if access_token:
        github_user = github_api.get_user(access_token)

        return ('Successfully logged in as '
                f'<a href="{github_user["html_url"]}">{github_user["login"]} ({github_user["name"]})</a>'
                '.\n')
    else:
        oauth_link = github_api.oauth_authorize_url(update.effective_user.id,
                                                    update.effective_message.message_id)

        return f'Please click this link to login using GitHub: {oauth_link}'


login_menu = Menu(
    name='login',
    text=login_text,
    buttons=lambda _, c: [[BackButton('OK' if c.user_data.get('access_token') else 'Back')]]
)


def repos_buttons(update, context):
    repos = context.chat_data.get('repos', {})
    buttons = []

    for row in grouper(repos.values(), 2):
        buttons.append([Button(repo.name, menu=repo.id) for repo in row if repo is not None])

    buttons.append([Button('Add repository', switch_inline_query_current_chat=InlineQueries.add_repo + ' ')])
    buttons.append([BackButton('Back')])

    return buttons


repos_menu = Menu(
    name='repos',
    text='Please choose a repository from the the list below, or press "New Repository" to add a new repository.',
    buttons=repos_buttons
)


def repo_text(update, context):
    try:
        repo = context.chat_data['repos'][int(context.match.group(1))]
    except KeyError:
        # TODO: Allow two actions for a button: both deleting and going back
        return 'Repository deleted successfully.'

    return f'Menu for {repo.name}'


def repo_buttons(update, context):
    try:
        repo = context.chat_data['repos'][int(context.match.group(1))]
    except KeyError:
        return [[BackButton('OK')]]

    return [
        [ToggleButton('enabled', value=repo.enabled, text='Enabled')],
        [SetButton('delete', None, 'Delete')],
        [BackButton('Back')]
    ]


def repo_set_data(update, context):
    repo_id = int(context.match.group(1))

    if context.key == 'delete':
        del context.chat_data['repos'][repo_id]
    else:
        repo = context.chat_data['repos'][repo_id]
        setattr(repo, context.key, context.value)


repo_menu = Menu(
    name='repo',
    pattern=('repos', r'(\d+)'),
    text=repo_text,
    buttons=repo_buttons,
    set_data=repo_set_data
)


def settings_command(update, context):
    if context.args:
        context.menu_stack = context.args

    reply_menu(update, context, settings_menu)


def inline_add_repo(update, context):
    offset = update.inline_query.offset
    installation_offset, repo_offset = -1, -1
    if offset:
        installation_offset, _, repo_offset = offset.partition('|')
        installation_offset, repo_offset = int(installation_offset), int(repo_offset)

    access_token = context.user_data.get('access_token')

    results = []
    if access_token:
        filtered_repositories = []
        search = context.match.group(1).strip()
        installations = github_api.get_installations_for_user(access_token)
        for installation_index, installation in enumerate(installations):
            if installation_index <= installation_offset:
                continue
            repositories = github_api.get_repositories_for_installation(installation['id'],
                                                                        access_token)
            for repo_index, repo in enumerate(repositories):
                if repo_index <= repo_offset:
                    continue
                if repo['full_name'].startswith(search) or repo['name'].startswith(search):
                    filtered_repositories.append(repo)
                if len(filtered_repositories) >= 50:
                    break
            if len(filtered_repositories) >= 50:
                break

        results = []
        for repo in filtered_repositories:
            results.append(InlineQueryResultArticle(
                id=repo['id'],
                title=repo['full_name'],
                description='Add this repository',
                input_message_content=InputTextMessageContent(
                    message_text=f'/add_repo {repo["id"]}',
                    parse_mode=ParseMode.HTML
                )
            ))
        if not results and not offset:
            results.append(InlineQueryResultArticle(
                id=uuid4(),
                title='No results.',
                description='Tab me to learn how to add your repositories.',
                input_message_content=InputTextMessageContent(
                    message_text=f'/help add_repo',
                )
            ))

    update.inline_query.answer(
        results,
        switch_pm_text=('Not seeing your repository? Tab here.'
                        if access_token else
                        'You are not logged in. Tab here to continue.'),
        switch_pm_parameter='help__add_repo',
        cache_time=15,
        is_personal=True,
        next_offset=f'{installation_index-1}|{repo_index}' if results else ''
    )


def add_repo_command(update, context):
    repos = context.chat_data.setdefault('repos', {})
    access_token = context.user_data['access_token']
    repo_id = context.args[0]
    repository = github_api.get_repository(repo_id, access_token=access_token)

    repos[repository['id']] = Repo(name=repository['full_name'], id=repository['id'])

    context.menu_stack = ['settings']
    reply_menu(update, context, repos_menu)


def add_handlers(dp: Dispatcher):
    dp.add_handler(CommandHandler(('settings', 'options', 'config'), settings_command))

    dp.add_handler(MenuHandler(settings_menu, [
        repos_menu,
        repo_menu,
        login_menu
    ]))

    dp.add_handler(InlineQueryHandler(inline_add_repo, pattern=InlineQueries.add_repo + r'(.*)'))
    dp.add_handler(CommandHandler('add_repo', add_repo_command))
