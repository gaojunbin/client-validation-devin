"""Exit codes and the exceptions that map onto them."""

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2
EXIT_RUNNING = 3
EXIT_USAGE = 4
EXIT_HUMAN = 5


class QaError(Exception):
    """An expected failure with a message meant for the agent or the human."""

    exit_code = EXIT_USAGE


class ConfigError(QaError):
    exit_code = EXIT_USAGE


class GitError(QaError):
    exit_code = EXIT_USAGE


class InfraError(QaError):
    exit_code = EXIT_BLOCKED


class NeedsHumanError(QaError):
    exit_code = EXIT_HUMAN


class DevinApiError(InfraError):
    def __init__(self, method: str, path: str, status: int, title: str, detail: str):
        self.method = method
        self.path = path
        self.status = status
        self.title = title
        self.detail = detail
        super().__init__(f"Devin API {method} {path} failed: HTTP {status} {title}: {detail}".strip())
