class GithubUpdate(object):
    effective_chat = None
    effective_user = None

    def __init__(self, payload, guid, event):
        self.payload = payload
        self.guid = guid
        self.event = event


class GithubAuthUpdate(object):
    effective_chat = None
    effective_user = None

    def __init__(self, code, raw_state, state):
        self.code = code
        self.raw_state = raw_state
        self.state = state
