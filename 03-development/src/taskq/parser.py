"""taskq CLI argument parser.

[FR-05] Isolated argparse configuration and subcommand setup.
"""
import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build ArgumentParser with all subcommands.

    [FR-05] Configures submit, run, status, list, clear subcommands.
    """
    parser = argparse.ArgumentParser(prog="taskq", description="Local task queue CLI")
    parser.add_argument("--json", action="store_true", default=False, help="Machine-readable JSON output")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_submit = sub.add_parser("submit", help="Submit a new task")
    p_submit.add_argument("command", help="Shell command to queue")
    p_submit.add_argument("--name", default=None, help="Optional task name (must be unique)")

    p_run = sub.add_parser("run", help="Execute a task or all pending tasks")
    g = p_run.add_mutually_exclusive_group(required=True)
    g.add_argument("id", nargs="?", default=None, help="Task id to run")
    g.add_argument("--all", action="store_true", default=False, help="Run all pending tasks")
    p_run.add_argument("--cached", action="store_true", default=False, help="Use TTL cache if available")

    p_status = sub.add_parser("status", help="Show all fields for a task")
    p_status.add_argument("id", help="Task id")

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--status", default=None, dest="status_filter", help="Filter by status")

    sub.add_parser("clear", help="Clear all data files")

    return parser
