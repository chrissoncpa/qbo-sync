"""Pull reference data from QBO and write to the workbook's _ tabs.

Fetches all reference entities (Accounts, Vendors, Customers, Classes,
Departments, Items, Terms) and refreshes ONE_OF_RANGE dropdown validation
rules on every transaction tab so dropdowns stay in sync with QBO.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from src.config import Config
from src.qbo.client import get_qbo_client
from src.sheets.client import SheetsClient
from src.sheets.validation import refresh_validation_rules

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PullResult:
    tab: str
    rows_written: int


@dataclass(frozen=True)
class _PullSpec:
    entity_name: str
    tab_name: str
    headers: list[str]
    extractor: Callable[[Any], list[Any]]


def _account_row(a: Any) -> list[Any]:
    return [a.Id, a.Name, a.FullyQualifiedName, a.AccountType, a.AccountSubType, a.Active]


def _vendor_row(v: Any) -> list[Any]:
    return [v.Id, v.DisplayName, v.CompanyName, v.Active]


def _customer_row(c: Any) -> list[Any]:
    return [c.Id, c.DisplayName, c.CompanyName, c.Active]


def _class_row(k: Any) -> list[Any]:
    return [k.Id, k.Name, k.FullyQualifiedName, k.Active]


def _department_row(d: Any) -> list[Any]:
    return [d.Id, d.Name, d.FullyQualifiedName, d.Active]


def _item_row(i: Any) -> list[Any]:
    return [i.Id, i.Name, getattr(i, "FullyQualifiedName", i.Name), getattr(i, "Type", ""), i.Active]


def _term_row(t: Any) -> list[Any]:
    return [t.Id, t.Name, t.Active]


_PULL_SPECS: list[_PullSpec] = [
    _PullSpec(
        entity_name="Account",
        tab_name="_Accounts",
        headers=["Id", "Name", "FullyQualifiedName", "AccountType", "AccountSubType", "Active"],
        extractor=_account_row,
    ),
    _PullSpec(
        entity_name="Vendor",
        tab_name="_Vendors",
        headers=["Id", "DisplayName", "CompanyName", "Active"],
        extractor=_vendor_row,
    ),
    _PullSpec(
        entity_name="Customer",
        tab_name="_Customers",
        headers=["Id", "DisplayName", "CompanyName", "Active"],
        extractor=_customer_row,
    ),
    _PullSpec(
        entity_name="Class",
        tab_name="_Classes",
        headers=["Id", "Name", "FullyQualifiedName", "Active"],
        extractor=_class_row,
    ),
    _PullSpec(
        entity_name="Department",
        tab_name="_Departments",
        headers=["Id", "Name", "FullyQualifiedName", "Active"],
        extractor=_department_row,
    ),
    _PullSpec(
        entity_name="Item",
        tab_name="_Items",
        headers=["Id", "Name", "FullyQualifiedName", "Type", "Active"],
        extractor=_item_row,
    ),
    _PullSpec(
        entity_name="Term",
        tab_name="_Terms",
        headers=["Id", "Name", "Active"],
        extractor=_term_row,
    ),
]


def run_pull(cfg: Config) -> list[PullResult]:
    """Pull all reference entities from QBO and write them to the workbook.

    Returns one PullResult per tab written.
    """
    from quickbooks.objects import Account, Class, Customer, Department, Item, Term, Vendor

    _entity_map: dict[str, Any] = {
        "Account": Account,
        "Vendor": Vendor,
        "Customer": Customer,
        "Class": Class,
        "Department": Department,
        "Item": Item,
        "Term": Term,
    }

    qb = get_qbo_client(cfg)
    sheets = SheetsClient.from_credentials()

    results: list[PullResult] = []
    for spec in _PULL_SPECS:
        entity_cls = _entity_map[spec.entity_name]
        records = entity_cls.all(qb=qb, max_results=1000)
        rows = [spec.extractor(r) for r in records]
        sheets.write_reference_tab(cfg.workbook_id, spec.tab_name, spec.headers, rows)
        results.append(PullResult(tab=spec.tab_name, rows_written=len(rows)))
        log.info("pull: wrote %d %s rows to %s", len(rows), spec.entity_name, spec.tab_name)

    rules = refresh_validation_rules(cfg, sheets)
    log.info("pull: applied %d dropdown validation rules", rules)

    return results
