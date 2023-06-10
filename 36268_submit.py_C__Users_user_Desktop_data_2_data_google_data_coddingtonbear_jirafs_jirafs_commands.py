from jirafs.plugin import CommandPlugin
from jirafs.utils import run_command_method_with_kwargs


class Command(CommandPlugin):
    """Commit current changes, push changes to JIRA, and pull changes"""
    MIN_VERSION = '1.15'
    MAX_VERSION = '1.99.99'

    def add_arguments(self, parser):
        parser.add_argument(
            '-m', '--message', dest='message', default='Untitled'
        )

    def handle(self, args, folder, **kwargs):
        return self.cmd(folder, args.message)

    def main(self, folder, message):
        commit_result = run_command_method_with_kwargs(
            'commit', folder=folder, message=message
        )
        push_result = run_command_method_with_kwargs(
            'push', folder=folder
        )

        return commit_result, push_result
