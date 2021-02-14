# Create Dev Setup

## Define some names

will be later referred using the right notation

 * Github app name:  `<github-app>` e.g., GithubBot Revised
 * Localtunnel custom domain: `<custom-domain>` e.g., githubbot-revised 
 * telegram bot name: `<telegram-bot>` e.g., githubrevised_bot 
 * random webhook url secret: `<webhook-secret>` e.g., abcde 

create an `.env` file in the repo directory and enter the following values:

```
DEBUG=True

SERVER_SUBDOMAIN=<custom-domain>
SERVER_URL_BASE=https://<custom-domain>.localtunnel.me
```

## Register new Github app

### Define App

Go to: https://github.com/settings/apps/new

enter following values while replacing the corresponding chosen names:

* name: `<github-app>`
* url: `https://t.me/<telegram-bot>`
* webhook url: `https://<custom-domain>.localtunnel.me`
* user callback url: `https://<custom-domain>.localtunnel.me/github/auth`
* setup url: `https://t.me/<telegram-bot>`

permissions:
 * repo admin -> read
 * repository contents -> read
 * deployments -> read
 * issues -> read+write
 * repo meta -> read
 * pages -> read
 * pr -> read
 * repo projects -> read
 * security vulneratibly alerts -> read
 * commit status -> read
 * organizatin projects -> read
 * team discussions -> read

events
 * all

This will results in values for the following ids:

```
App ID: e.g., 12345
(OAuth) Client ID: e.g., Iv1.abcd...
(OAuth) Client secret: e.g., 123...
```

### Generate private key
create a new private key and store it in the repo directory as `private-key.pem`

### Configure repo
extend the `.env` file with: 

```
GITHUB_APP_NAME=telegramgithubbot-sam
GITHUB_APP_ID=
GITHUB_WEBHOOK_SECRET=<webhook-secret>
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
```

## Create Telegram bot

### Create via BotFather
Use bot father to create a new bot named `<telegram-bot>`

```
/newbot
```

e.g., results in `https://t.me/githubrevised_sam_bot` along with a secret token

```
token: 34334:adff3f...
```

### Advanced BotFather settings

enable inline mode
```
/setinline ... to inline query enable
```

add available commands for better autocompletion

```
start - Start the bot
help - Show help
login - Login to Github
privacy - Privacy Policy
settings - Settings
```

### Configure bot
extend the `.env` file with the received token
```
TELEGRAM_BOT_TOKEN=
```

## Launch docker-compose 


```
docker-compose up
```

now you should be able to chat with the bot. 