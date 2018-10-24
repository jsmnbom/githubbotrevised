import pickle
from collections import defaultdict

from telegram.ext import PicklePersistence


class Persistence(PicklePersistence):
    def __init__(self, filename):
        super().__init__(filename, store_user_data=True, store_chat_data=True, singe_file=True, on_flush=True)

        self.github_data = None

    def load_singlefile(self):
        filename = self.filename
        try:
            with open(self.filename, "rb") as f:
                all = pickle.load(f)
                self.user_data = defaultdict(dict, all['user_data'])
                self.chat_data = defaultdict(dict, all['chat_data'])
                self.conversations = all['conversations']
                self.github_data = all['github_data']
        except IOError:
            self.conversations = {}
            self.user_data = defaultdict(dict)
            self.chat_data = defaultdict(dict)
            self.github_data = {}
        except pickle.UnpicklingError:
            raise TypeError("File {} does not contain valid pickle data".format(filename))
        except Exception:
            raise TypeError("Something went wrong unpickling {}".format(filename))

    def dump_singlefile(self):
        with open(self.filename, "wb") as f:
            all = {'conversations': self.conversations, 'user_data': self.user_data,
                   'chat_data': self.chat_data, 'github_data': self.github_data}
            pickle.dump(all, f)
