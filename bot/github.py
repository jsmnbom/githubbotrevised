import logging

from telegram import ParseMode
from telegram.ext import CallbackContext, Dispatcher

from bot.githubapi import github_api
from bot.githubupdates import GithubAuthUpdate, GithubUpdate
from bot.menu import edit_menu_by_id
from bot.utils import github_cleaner, link, truncate, encode_data_link

TRUNCATED_MESSAGE = '\n<b>[Truncated message, open on GitHub to read more]</b>'
REPLY_MESSAGE = '\n\n<i>Reply to this message to post a comment on GitHub (use ! to suppress).</i>'


def render_github_markdown(markdown, context: str):
    html = github_api.markdown(markdown, context)
    return github_cleaner.clean(html).strip('\n')


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

    def _send(self, repo, text):
        text = truncate(text, TRUNCATED_MESSAGE, REPLY_MESSAGE)

        for chat_id in self._iter_chat_ids(repo):
            self.dispatcher.bot.send_message(chat_id=chat_id, text=text,
                                             parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    def issues(self, update, _):
        # Issue opened, edited, closed, reopened, assigned, unassigned, labeled,
        # unlabeled, milestoned, or demilestoned.
        # TODO: Possibly support editing, closing, reopening, etc. of issues
        if update.payload['action'] == 'opened':
            issue = update.payload['issue']
            author = issue['user']
            repo = update.payload['repository']

            text = render_github_markdown(issue['body'], repo['full_name'])

            issue_link = link(issue['html_url'], f'{repo["full_name"]}#{issue["number"]} {issue["title"]}')
            author_link = link(author['html_url'], '@' + author['login'])
            data_link = encode_data_link(('issue', repo['full_name'], issue['number'], author['login']))
            text = f'{data_link}🐛 New issue {issue_link}\nby {author_link}\n\n{text}'

            self._send(repo, text)

    def issue_comment(self, update, context):
        # Any time a comment on an issue or pull request is created, edited, or deleted.
        # TODO: Possibly support editing and closing of comments?
        if update.payload['action'] == 'created':
            issue = update.payload['issue']
            comment = update.payload['comment']
            author = comment['user']
            repo = update.payload['repository']
            is_pull_request = 'pull_request' in issue

            text = render_github_markdown(comment['body'], repo['full_name'])

            issue_link = link(issue['html_url'], f'{repo["full_name"]}#{issue["number"]} {issue["title"]}')
            author_link = link(author['html_url'], '@' + author['login'])
            data_link = encode_data_link(('pull request' if is_pull_request else 'issue',
                                          repo['full_name'], issue['number'], author['login']))
            text = f'{data_link}💬 New comment on {issue_link}\nby {author_link}\n\n{text}'

            self._send(repo, text)

    def pull_request(self, update, context):
        # Pull request opened, closed, reopened, edited, assigned, unassigned, review requested,
        # review request removed, labeled, unlabeled, or synchronized.
        # TODO: Possibly support closed, reopened, edited, assigned etc.
        if update.payload['action'] == 'opened':
            pull_request = update.payload['pull_request']
            author = pull_request['user']
            repo = update.payload['repository']

            text = render_github_markdown(pull_request['body'], repo['full_name'])

            pull_request_link = link(pull_request['html_url'],
                                     f'{repo["full_name"]}#{pull_request["number"]} {pull_request["title"]}')
            author_link = link(author['html_url'], '@' + author['login'])
            data_link = encode_data_link(('pull request', repo['full_name'], pull_request['number'], author['login']))
            text = f'{data_link}🔌 New pull request {pull_request_link}\nby {author_link}\n\n{text}'

            self._send(repo, text)

    def pull_request_review(self, update, context):
        # Pull request review submitted, edited, or dismissed.
        # TODO: Possibly support edited and dismissed?
        if update.payload['action'] == 'submitted':
            review = update.payload['review']
            pull_request = update.payload['pull_request']
            author = review['user']
            repo = update.payload['repository']

            if not review['body']:
                return

            text = render_github_markdown(review['body'], repo['full_name'])

            review_link = link(review['html_url'],
                               f'{repo["full_name"]}#{pull_request["number"]} {pull_request["title"]}')
            author_link = link(author['html_url'], '@' + author['login'])
            data_link = encode_data_link(('pull request', repo['full_name'], pull_request['number'], author['login']))

            if review['state'] in ('commented', 'approved', 'request_changes'):
                if review['state'] == 'commented':
                    state = 'Commented'
                    emoji = '💬'
                elif review['state'] == 'approved':
                    state = 'Approved'
                    emoji = '✅'
                elif review['state'] == 'request_changes':
                    state = 'Changes requested'
                    emoji = '‼️'

                text = f'{data_link}{emoji} New pull request review {review_link}\n{state} by {author_link}\n\n{text}'
                self._send(repo, text)

    def pull_request_review_comment(self, update, context):
        # Pull request diff comment created, edited, or deleted.
        if update.payload['action'] == 'created':
            pull_request = update.payload['pull_request']
            comment = update.payload['comment']
            author = comment['user']
            repo = update.payload['repository']

            diff_hunk = f'<pre>{comment["path"]}\n{comment["diff_hunk"]}</pre>'

            text = render_github_markdown(comment['body'], repo['full_name'])

            issue_link = link(comment['html_url'],
                              f'{repo["full_name"]}#{pull_request["number"]} {pull_request["title"]}')
            author_link = link(author['html_url'], '@' + author['login'])
            data_link = encode_data_link(('pull request review comment',
                                          repo['full_name'],
                                          pull_request['number'],
                                          comment['in_reply_to_id'] if 'in_reply_to_id' in comment else comment['id'],
                                          author['login'],))
            text = f'{data_link}💬 New pull request review comment {issue_link}\nby {author_link}\n{diff_hunk}\n\n{text}'

            self._send(repo, text)

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
