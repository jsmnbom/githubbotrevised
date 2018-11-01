from dataclasses import dataclass


@dataclass
class Repo:
    name: str
    id: int
    issues: bool = True
    issue_comments: bool = True
    pulls: bool = True
    pull_comments: bool = True
    pull_reviews: bool = True
    pull_review_comments: bool = True
    wiki_pages: bool = False
    push: bool = False
    push_main: bool = True
    commit_comments: bool = True
