# GitHubBot Revised
(temporary name)

Telegram Bot that notifies you about events your public GitHub repositories.

I am an improved version of the Telegram GitHub Bot. See below for more details.

[Tab here](https://t.me/githubrevisedbot) to go to telegram and talk to me.

## Features
*Features marked with a star \* are improvement over the telegram GitHub Bot.*

- Provides notifications for the following events
  - New issues
  - Comments on issues
  - New pull requests
  - Comments on pull requests
  - New pull request reviews *
  - Pull request review comments *
  - Comment on a commit/diff *
  - Wiki page updated *
  - Commits pushed
    - Either to any branch or only master *
- Reply to issues, PRs, or comments in Telegram to easily post a comment on github
- Fancy (and hopefully intuitive) settings interface using InlineKeyboardButtons + switch_inline_current_chat *
- Uses GitHub Apps instead of complicated manual webhooks *
- An actual privacy policy (/privacy) *
- Notification message length is truncated to configurable account of character to reduce visual spam *
- Uses GitHub API to render markdown meaning the notification text should more closely resemble the actual text on github *

The two last ones mean that where the Telegram GitHub Bot simply stays silent (weird html/markdown or more than 4000 characters), this improved version handles with grace!

## Running
To use the bot you do not need to clone the source code or anything, simply [tab here](https://t.me/githubrevisedbot) to get started. The guide below is only if you would like to host the bot yourself.

TODO: Guide

## Contributing

TODO: Contributing guide  
TLDR: Contributions (both issues or PRs) are very welcome!

## License

The source code of this Telegram Bot is provided under the [MIT license](./LICENSE). 


