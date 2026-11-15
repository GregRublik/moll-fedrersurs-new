from __future__ import annotations


class BrowserError(Exception):
    """Base error for the browser layer."""


class ProfileLockedError(BrowserError):
    pass


class SessionExpiredError(BrowserError):
    pass


class ChallengeTimeoutError(SessionExpiredError):
    pass


class PortalBlockedError(BrowserError):
    pass


class ManualInterventionRequired(BrowserError):
    pass
