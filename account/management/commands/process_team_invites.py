import time

from django.core.management.base import BaseCommand

from team_dashboard.utils import process_next_team_driver_invitation


class Command(BaseCommand):
    help = "Process the durable Team Dashboard driver-invitation email queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling for queued invitations.",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=5.0,
            help="Seconds to wait when the queue is empty (default: 5).",
        )

    def handle(self, *args, **options):
        keep_running = options["loop"]
        poll_interval = max(0.5, options["poll_interval"])

        while True:
            processed_any = False
            while process_next_team_driver_invitation():
                processed_any = True

            if not keep_running:
                if processed_any:
                    self.stdout.write(self.style.SUCCESS("Invitation queue processed."))
                return
            time.sleep(poll_interval)
