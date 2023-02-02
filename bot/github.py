import logging
from typing import Callable

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackContext, Application

from const import DEFAULT_TRUNCATION_LIMIT
from githubapi import github_api
from githubupdates import GithubAuthUpdate, GithubUpdate
from menu import edit_menu_by_id
from repo import Repo
from utils import link, encode_data_link
from truncator import github_cleaner, truncate

TRUNCATED_MESSAGE = '\n<b>[Truncated message, open on GitHub to read more]</b>'
REPLY_MESSAGE = '\n\n<i>Reply to this message to post a comment on GitHub (use ! to suppress).</i>'


def render_github_markdown(markdown, context: str):
    html = github_api.markdown(markdown, context)
    return github_cleaner.clean(html).strip('\n')


class GithubHandler:
    def __init__(self, application: Application):
        self.application = application
        self.logger = logging.getLogger(self.__class__.__qualname__)

    async def handle_auth_update(self, update: GithubAuthUpdate, context: CallbackContext.DEFAULT_TYPE):
        user_id = update.state[0]
        message_id = update.state[1]

        access_token = github_api.get_oauth_access_token(update.code, update.raw_state)

        context.bot_data[user_id]['access_token'] = access_token

        from bot.settings import login_menu
        context.menu_stack = ['settings', 'login']
        edit_menu_by_id(user_id, message_id, context, login_menu)

    def handle_update(self, update: GithubUpdate, context: CallbackContext):
        return getattr(self, update.event, self.unknown)(update, context)

    def unknown(self, update, _):
        self.logger.warning('Unknown event type %s. Data: %s', update.event, update.payload)

    def ping(self, update, _):
        self.logger.info('PING: %s', update.payload)

    def _iter_repos(self, repository):
        repo_id = repository['id']
        for chat_id, chat_data in self.application.chat_data.items():
            if 'repos' in chat_data:
                for repo in chat_data['repos'].values():
                    if repo.id == repo_id:
                        yield chat_id, chat_data, repo

    async def _send(self, repo, text, check_repo: Callable[[Repo], bool], suffix=REPLY_MESSAGE):
        truncated_text = {}

        for chat_id, chat_data, repo in self._iter_repos(repo):
            if check_repo(repo):
                truncation_limit = chat_data.get('truncation_limit', DEFAULT_TRUNCATION_LIMIT)
                try:
                    message_text = truncated_text[truncation_limit]
                except KeyError:
                    message_text = truncate(text, TRUNCATED_MESSAGE, suffix, max_length=truncation_limit)

                try:
                    await self.application.bot.send_message(chat_id=chat_id, text=message_text,
                                                     parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except TelegramError:
                    logging.error('error while sending github update', exc_info=1)

    async def issues(self, update, _):
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

            await self._send(repo, text, lambda r: r.issues)

    async def issue_comment(self, update, _):
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

            await self._send(repo, text, lambda r: r.pull_comments if is_pull_request else r.issue_comments)

    async def pull_request(self, update, _):
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

            await self._send(repo, text, lambda r: r.pulls)

    async def pull_request_review(self, update, _):
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
                await self._send(repo, text, lambda r: r.pull_reviews)

    async def pull_request_review_comment(self, update, _):
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

            await self._send(repo, text, lambda r: r.pull_review_comments)

    async def push(self, update, _):
        # Triggered on a push to a repository branch.
        # Branch pushes and repository tag pushes also trigger webhook push events.
        commits = update.payload['commits']
        ref = update.payload['ref']

        if commits and ref.startswith('refs/heads/'):
            branch = ref[len('refs/heads/'):]
            repo = update.payload['repository']
            compare = update.payload['compare']

            text = f'🔨 <a href="{compare}">{len(commits)} new commits</a> to {repo["full_name"]}:{branch}\n\n'

            for commit in commits:
                text += f'<a href="{commit["url"]}">{commit["id"][:7]}</a>: {commit["message"]} by {commit["author"]["name"]}\n'

            await self._send(repo, text, lambda r: (r.push_main or r.push) if branch == repo["default_branch"] else r.push,
                       suffix='')

    async def gollum(self, update, _):
        # Wiki page is created or updated.
        pages = update.payload['pages']
        repo = update.payload['repository']
        sender = update.payload['sender']

        text = f'🔨 {len(pages)} {repo["full_name"]} wiki page{"s" if len(pages) > 1 else ""} were updated '
        sender_link = link(sender['html_url'], '@' + sender['login'])
        text += f'by {sender_link}\n\n'

        for page in pages:
            compare_url = f'{page["html_url"]}/_compare/{page["sha"]}'
            text += f'<a href="{page["html_url"]}">{page["title"]}</a> (<a href="{compare_url}">compare</a>)\n'

        await self._send(repo, text, lambda r: r.wiki_pages, suffix='')

    async def commit_comment(self, update, _):
        if update.payload['action'] == 'created':
            repo = update.payload['repository']
            comment = update.payload['comment']
            author = comment['user']

            author_link = link(author['html_url'], '@' + author['login'])
            text = f'💬 <a href="{comment["html_url"]}">New comment</a> on commit {comment["commit_id"][:7]} by {author_link}'
            position, line, path = comment['position'], comment['line'], comment['path']
            if path:
                text += f'\nPath: {path}'
            if line:
                text += f'\nLine: {line}'
                if position == 1:
                    text += ' (before)'
                elif position == 2:
                    text += ' (after)'

            text += f'\n\n{comment["body"]}'

            await self._send(repo, text, lambda r: r.commit_comments, suffix='')

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
