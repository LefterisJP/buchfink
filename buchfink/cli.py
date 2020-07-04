import logging
import os.path
import shutil
from datetime import date, datetime
from pathlib import Path

import click
import coloredlogs
import yaml
from prettytable import PrettyTable

from buchfink.datatypes import FVal
from buchfink.db import BuchfinkDB
from buchfink.serialization import deserialize_trade, serialize_trades

from .config import ReportConfig
from .report import run_report

logger = logging.getLogger(__name__)

epoch_start_ts = datetime(2011, 1, 1).timestamp()
epoch_end_ts = datetime(2031, 1, 1).timestamp()


@click.group()
@click.option('--log-level', '-l', type=str, default='INFO')
def buchfink(log_level):
    coloredlogs.install(level=log_level, fmt='%(asctime)s %(levelname)s %(message)s')


@buchfink.command()
@click.option('--directory', '-d', type=str, default='.')
def init(directory):
    "Initialize new Buchfink directory"

    target_config = os.path.join(directory, 'buchfink.yaml')

    if os.path.exists(target_config):
        click.echo(click.style('Already initialized (buchfink.yaml exists), aborting.', fg='red'))
        return

    initial_config = os.path.join(os.path.dirname(__file__), 'data', 'buchfink.initial.yaml')
    shutil.copyfile(initial_config, target_config)

    buchfink_db = BuchfinkDB(directory)

    click.echo(click.style('Successfully initialized in {0}.'.format(buchfink_db.data_directory.absolute()), fg='green'))


@buchfink.command()
@click.option('--keyword', '-k', type=str, default=None)
def balances(keyword):
    "Show balances across all accounts"

    buchfink_db = BuchfinkDB()
    balances_sum = {}

    for account in buchfink_db.get_all_accounts():
        if keyword is not None and keyword not in account['name']:
            continue

        if 'exchange' not in account:
            continue

        exchange = buchfink_db.get_exchange(account['name'])

        api_key_is_valid, error = exchange.validate_api_key()

        if not api_key_is_valid:
            logger.critical('Skipping exchange %s because API key is not valid (%s)', account['name'], error)
            continue

        balances, error = exchange.query_balances()

        if not error:
            logger.info('Fetched balances for %d assets from %s', len(balances.keys()), account['name'])
            for asset, balance in balances.items():
                amount = balance['amount']
                balances_sum[asset] = balances_sum.get(asset, FVal(0)) + amount

    table = PrettyTable()
    table.field_names = ['Asset', 'Amount', 'Symbol']
    for asset, balance in balances_sum.items():
        table.add_row([asset, balance, asset.symbol])
    print(table)


@buchfink.command()
@click.option('--keyword', '-k', type=str, default=None)
def fetch(keyword):
    "Fetch trades for configured accounts"

    buchfink_db = BuchfinkDB()

    for account in buchfink_db.get_all_accounts():
        if keyword is not None and keyword not in account['name']:
            continue

        if 'exchange' not in account:
            continue

        click.echo('Fetching trades for ' + account['name'])

        exchange = buchfink_db.get_exchange(account['name'])

        api_key_is_valid, error = exchange.validate_api_key()

        if not api_key_is_valid:
            logger.critical('Skipping exchange %s because API key is not valid (%s)', account['name'], error)
            continue

        name = account.get('name')

        trades = exchange.query_online_trade_history(
            start_ts=epoch_start_ts,
            end_ts=epoch_end_ts
        )

        logger.info('Fetched %d trades from %s', len(trades), name)

        with open("trades/" + name + ".yaml", "w") as f:
            yaml.dump({"trades": serialize_trades(trades)}, stream=f)


@buchfink.command()
@click.option('--name', '-n', type=str, required=True)
@click.option('--from', '-f', 'from_', type=str, required=True)
@click.option('--to', '-t', type=str, required=True)
def report(name, from_, to):
    "Run an ad-hoc report on your data"

    start_ts = datetime.fromisoformat(from_).timestamp()
    end_ts = datetime.fromisoformat(to).timestamp()

    buchfink_db = BuchfinkDB()

    result = run_report(buchfink_db, ReportConfig(
        name=name,
        from_dt=datetime.fromisoformat(from_),
        to_dt=datetime.fromisoformat(to)
    ))

    logger.info("Overview: %s", result['overview'])


@buchfink.command()
@click.option('--keyword', '-k', type=str, default=None)
def run(keyword):
    "Generate reports for all report definition and output overview table"

    buchfink_db = BuchfinkDB()

    num_matched_reports = 0
    results = {}

    for report in buchfink_db.get_all_reports():
        name = str(report.name)

        if keyword is not None and keyword not in name:
            continue
        num_matched_reports += 1

        results[name] = run_report(buchfink_db, report)

    table = PrettyTable()
    table.field_names = ['Report', 'Profit/Loss', 'Taxable P/L']
    for report_name, result in results.items():
        table.add_row([report_name, result['overview']['total_profit_loss'], result['overview']['total_taxable_profit_loss']])
    print(table)


if __name__ == '__main__':
    buchfink()
