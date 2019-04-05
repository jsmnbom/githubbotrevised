import re
from collections import OrderedDict

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, ParseMode
from telegram.ext import CallbackContext, Handler

from bot.utils import encode_data_link, decode_first_data_entity

SEPARATOR = '/'


class Action:
    GOTO = 0
    SET = 1


class Menu(object):
    def __init__(self, name, text, buttons, pattern=None, set_data=None):
        self.name = name

        if pattern:
            self.pattern = pattern
        else:
            self.pattern = (self.name,)

        self._set_data = set_data

        if not callable(text):
            def _text(_update, _context):
                return text

            self.text = _text
        else:
            self.text = text

        if not callable(buttons):
            def _buttons(_update, _context):
                return buttons

            self.buttons = _buttons
        else:
            self.buttons = buttons

    def _keyboard(self, update, context):
        buttons = []
        i = 0
        callback_data = {}
        for row in self.buttons(update, context):
            buttons.append([])
            for button in row:
                inline_button = button.inline_keyboard_button(update, context)
                if inline_button.callback_data and not isinstance(inline_button.callback_data, str):
                    callback_data[str(i)] = inline_button.callback_data
                    inline_button.callback_data = context.menu_stack[0] + SEPARATOR + str(i)
                    i += 1
                buttons[-1].append(inline_button)
        return InlineKeyboardMarkup(buttons), callback_data

    def handle_update(self, update, context):
        if context.menu_action == Action.SET:
            context.key, context.value = context.menu_other
            self._set_data(update, context)

        return self.edit(update, context)

    def _attrs(self, update, context):
        text = self.text(update, context)
        keyboard, callback_data = self._keyboard(update, context)
        data = {
            'callback_data': callback_data
        }
        text = encode_data_link(data) + text

        return {
            'text': text,
            'reply_markup': keyboard,
            'parse_mode': ParseMode.HTML,
            'disable_web_page_preview': True
        }

    def reply(self, update, context):
        context.menu_stack = getattr(context, 'menu_stack', []) + [self.name]
        return update.effective_message.reply_text(
            **self._attrs(update, context),
            disable_notification=True
        )

    def send(self, chat_id, context):
        context.menu_stack = getattr(context, 'menu_stack', []) + [self.name]
        update = Update(0)
        return context.bot.send_message(
            chat_id,
            **self._attrs(update, context),
            disable_notification=True
        )

    def edit(self, update, context):
        msg = update.effective_message.edit_text(
            **self._attrs(update, context)
        )
        if update.callback_query:
            update.callback_query.answer()
        return msg

    def edit_by_id(self, chat_id, message_id, context):
        update = Update(0)
        msg = context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            **self._attrs(update, context)
        )
        if update.callback_query:
            update.callback_query.answer()
        return msg

    def matches(self, stack, root=False):
        if root:
            return re.match(self.pattern[-1], stack)
        # TODO: convert self.pattern to a single regex
        match = None
        for i, pattern in enumerate(self.pattern):
            match = re.match(pattern, stack[-len(self.pattern) + i])
            if not match:
                return
        return match


class Button(object):
    def __init__(self,
                 text=None,
                 menu=None,
                 url=None,
                 callback_data=None,
                 switch_inline_query=None,
                 switch_inline_query_current_chat=None,
                 callback_game=None):
        if not callable(text):
            def _text(_update, _context):
                return text

            self.text = _text
        else:
            self.text = text

        self.menu = str(menu) if menu else None

        self.url = url
        self.callback_data = callback_data
        self.switch_inline_query = switch_inline_query
        self.switch_inline_query_current_chat = switch_inline_query_current_chat
        self.callback_game = callback_game

    def _callback_data(self, update, context):
        if self.menu:
            return Action.GOTO, getattr(context, 'menu_stack', []) + [self.menu]
        else:
            return self.callback_data

    def inline_keyboard_button(self, update, context):
        return InlineKeyboardButton(self.text(update, context),
                                    self.url,
                                    self._callback_data(update, context),
                                    self.switch_inline_query,
                                    self.switch_inline_query_current_chat,
                                    self.callback_game)


class BackButton(Button):
    def __init__(self, text, depth=1):
        super().__init__(text)
        self.depth = depth

    def _callback_data(self, update, context):
        return Action.GOTO, context.menu_stack[:-self.depth]


class ToggleButton(Button):
    def __init__(self, key, value, text=None, states=None, default=None):
        self.key = key

        if (text is None and states is None) or (text is not None and states is not None):
            raise RuntimeError
        if text is not None:
            states = ((False, text), (True, '\u2714' + text))
        if default is None:
            default = states[0][0]
        self.default = default
        self.state_dict = OrderedDict(states)
        self.state_keys = list(self.state_dict.keys())

        self.value = value

        super().__init__(lambda u, c: self.state_dict[value])

    def _callback_data(self, update, context):
        next_index = ((self.state_keys.index(self.value) + 1) % len(self.state_keys))
        next_value = self.state_keys[next_index]
        return Action.SET, context.menu_stack, self.key, next_value


class SetButton(Button):
    def __init__(self, key, value, text):
        self.key = key

        self.value = value

        super().__init__(text)

    def _callback_data(self, update, context):
        return Action.SET, context.menu_stack, self.key, self.value


class MenuHandler(Handler):
    def __init__(self, root_menu, menus):
        if root_menu not in menus:
            menus.insert(0, root_menu)

        self.menus = menus
        self.root_menu = root_menu

        super(MenuHandler, self).__init__(
            None,
            pass_update_queue=None,
            pass_job_queue=None,
            pass_user_data=None,
            pass_chat_data=None)

    def check_update(self, update):
        if isinstance(update, Update) and update.callback_query and update.callback_query.data:
            root, _, index = update.callback_query.data.partition(SEPARATOR)

            if root and self.root_menu.matches(root, root=True):
                data = decode_first_data_entity(update.callback_query.message.entities)
                callback_data = data['callback_data']
                action, stack, *other = callback_data[index]

                for menu in self.menus:
                    match = menu.matches(stack)
                    if match:
                        break
                else:
                    return

                return stack, menu, match, action, other

    def handle_update(self, update, dispatcher, check_result, context=None):
        stack, menu, match, action, other = check_result

        self.collect_additional_context(context, update, dispatcher, (action, stack, other, match))

        return menu.handle_update(update, context)

    def collect_additional_context(self, context, update, dispatcher, check_result):
        action, stack, other, match = check_result
        context.menu_action = action
        context.menu_other = other
        context.menu_stack = stack
        context.matches = [match]


def reply_menu(update, context, menu: Menu):
    return menu.reply(update, context)


def send_menu(chat_id, context, menu: Menu):
    return menu.send(chat_id, context)


def edit_menu_by_id(chat_id, message_id, context, menu: Menu):
    return menu.edit_by_id(chat_id, message_id, context)
