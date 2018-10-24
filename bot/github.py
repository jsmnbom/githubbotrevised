import logging

from telegram import ParseMode
from telegram.ext import CallbackContext, Dispatcher

from bot.githubapi import github_api
from bot.githubupdates import GithubAuthUpdate, GithubUpdate
from bot.menu import edit_menu_by_id
from bot.utils import github_cleaner

GITHUB_API_ACCEPT = {'Accept': 'application/vnd.github.machine-man-preview+json'}


def render_github_markdown(markdown, context: str):
    html = github_api.markdown(markdown, context)
    return github_cleaner.clean(html)


class GithubHandler:
    def __init__(self, dispatcher: Dispatcher):
        self.dispatcher = dispatcher
        self.logger = logging.getLogger(self.__class__.__qualname__)

    def handle_auth_update(self, update: GithubAuthUpdate, context: CallbackContext):
        user_id = update.state[0]
        message_id = update.state[1]
        # noinspection PyProtectedMember
        context.user_data = self.dispatcher.user_data[user_id]

        access_token = github_api.get_oauth_access_token(update.code, update.raw_state)

        self.logger.debug('Access token for user %s: %s', user_id, access_token)

        context.user_data['access_token'] = access_token

        from bot.settings import login_menu
        context.menu_stack = ['settings', 'login']
        edit_menu_by_id(user_id, message_id, context, login_menu)

    def handle_update(self, update: GithubUpdate, context: CallbackContext):
        return getattr(self, update.event, self.unknown)(update, context)

    def unknown(self, update, _):
        self.logger.warning('Unknown event type %s. Data: %s', update.event, update.payload)

    def ping(self, update, _):
        self.logger.info('PING: %s', update.payload)

    def _iter_chat_ids(self, repository):
        repo_id = repository['id']
        for chat_id, chat_data in self.dispatcher.chat_data.items():
            if 'repos' in chat_data:
                for repo in chat_data['repos'].keys():
                    if repo == repo_id:
                        yield chat_id

    def issues(self, update, _):
        # Issue opened, edited, closed, reopened, assigned, unassigned, labeled,
        # unlabeled, milestoned, or demilestoned.
        # TODO: Possibly support editing, closing, reopening, etc. of issues
        issue = update.payload['issue']
        repo = update.payload['repository']

        text = render_github_markdown(issue['body'], repo['full_name'])

        for chat_id in self._iter_chat_ids(repo):
            self.dispatcher.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

    def issue_comment(self, update, context):
        # Any time a comment on an issue is created, edited, or deleted.
        # TODO: Possibly support editing and closing of comments?
        pass

    def pull_request(self, update, context):
        # Pull request opened, closed, reopened, edited, assigned, unassigned, review requested,
        # review request removed, labeled, unlabeled, or synchronized.
        pass

    def pull_request_review(self, update, context):
        # Pull request review submitted, edited, or dismissed.
        pass

    def pull_request_review_comment(self, update, context):
        # Pull request diff comment created, edited, or deleted.
        pass

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
