import datetime
import logging
import os.path
from functools import lru_cache
from pathlib import Path
from typing import List

import yaml
from jinja2 import Environment, FileSystemLoader
from rotkehlchen.db.reports import DBAccountingReports
from rotkehlchen.db.filtering import ReportDataFilterQuery

from buchfink.datatypes import Timestamp
from buchfink.db import BuchfinkDB
from buchfink.serialization import deserialize_fval, serialize_fval

from .models import Account, ReportConfig

logger = logging.getLogger(__name__)


def run_report(buchfink_db: BuchfinkDB, accounts: List[Account], report_config: ReportConfig):
    name = report_config.name
    start_ts = Timestamp(int(report_config.from_dt.timestamp()))
    end_ts = Timestamp(int(report_config.to_dt.timestamp()))
    num_matched_accounts = 0
    all_trades = []
    all_actions = []

    root_logger = logging.getLogger('')
    formatter = logging.Formatter('%(levelname)s: %(message)s')

    folder = buchfink_db.reports_directory / Path(name)
    folder.mkdir(exist_ok=True)

    logfile = folder / 'report.log'
    if logfile.exists():
        logfile.unlink()
    file_handler = logging.FileHandler(logfile)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logfile = folder / 'errors.log'
    if logfile.exists():
        logfile.unlink()
    error_handler = logging.FileHandler(logfile)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    logger.info('Generating report "%s"...', name)

    for account in accounts:
        num_matched_accounts += 1
        all_trades.extend(buchfink_db.get_local_trades_for_account(account))
        all_actions.extend(buchfink_db.get_local_ledger_actions_for_account(account))

    logger.info('Collected %d trades / %d actions from %d exchange account(s)',
            len(all_trades), len(all_actions), num_matched_accounts)

    def timestamp(act):
        return act.get_timestamp()

    all_events = sorted(all_trades + all_actions, key=timestamp)
    accountant = buchfink_db.get_accountant()
    report_id = accountant.process_history(start_ts, end_ts, all_events)

    root_logger.removeHandler(file_handler)
    root_logger.removeHandler(error_handler)

    accountant.export(buchfink_db.reports_directory / Path(name))

    dbpnl = DBAccountingReports(accountant.csvexporter.database)
    results, _ = dbpnl.get_reports(report_id=report_id, with_limit=False)
    report_data = results[0]

    def get_total_pnl_from_overview(pnl_overview):
        return {
            'free': serialize_fval(
                sum(deserialize_fval(entry['free']) for entry in pnl_overview.values())
            ),
            'taxable': serialize_fval(
                sum(deserialize_fval(entry['taxable']) for entry in pnl_overview.values())
            )
        }

    report_data['pnl_totals'] = get_total_pnl_from_overview(report_data['overview'])

    with (folder / 'report.yaml').open('w') as report_file:
        yaml.dump(report_data, stream=report_file)

    logger.info('Report information has been written to: %s',
            buchfink_db.reports_directory / Path(name)
    )

    return report_data


def render_report(buchfink_db: BuchfinkDB, report_config: ReportConfig):
    name = report_config.name
    folder = buchfink_db.reports_directory / Path(name)

    assert folder.exists()
    if report_config.template is None:
        raise ValueError('No template defined in report')

    # This is a little hacky and breaks our philosophy as we explicitely deal
    # with DB identifier here
    with (folder / 'report.yaml').open('r') as report_file:
        overview_data = yaml.load(report_file, Loader=yaml.SafeLoader)
        report_id = overview_data['identifier']

    @lru_cache
    def asset_symbol(symbol):
        if not symbol:
            return ''
        asset = buchfink_db.get_asset_by_symbol(symbol)
        return asset.symbol

    # Look for templates relative to the data_directory, that is the directory where
    # the buchfink.yaml is residing.
    env = Environment(loader=FileSystemLoader(buchfink_db.data_directory))
    env.globals['datetime'] = datetime
    env.globals['float'] = float
    env.globals['str'] = str
    env.globals['asset_symbol'] = asset_symbol
    template = env.get_template(report_config.template)

    accountant = buchfink_db.get_accountant()
    dbpnl = DBAccountingReports(accountant.csvexporter.database)
    report_data = dbpnl.get_report_data(
        filter_=ReportDataFilterQuery.make(report_id=report_id),
        with_limit=False,
    )
    events = report_data[0]

    rendered_report = template.render({
        "name": report_config.name,
        "title": report_config.title,
        "overview": overview_data,
        "events": events
    })

    _, ext = os.path.splitext(report_config.template)

    # to save the results
    with open(buchfink_db.reports_directory / Path(name) / ('report' + ext), "w") as reportf:
        reportf.write(rendered_report)

    logger.info("Rendered temmplate to 'report%s'.", ext)
