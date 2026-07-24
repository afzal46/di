"""Sales Invoice event handlers for Digital Invoicing."""

import frappe
from frappe import _
from frappe.utils import cint

from di.constants import SRO_REQUIRED_SALE_TYPES


def before_submit(doc, method=None):
	"""Hook: before_submit on Sales Invoice."""
	from di.digital_invoicing.doctype.di_settings.di_settings import get_settings, is_enabled

	if not is_enabled(doc.company):
		return

	settings = get_settings(doc.company)
	if not settings:
		return

	if cint(doc.is_pos):
		return

	if doc.customer and not cint(frappe.db.get_value("Customer", doc.customer, "enable_digital_invoicing")):
		return

	_validate_di_items(doc)

	if settings.auto_post_on_submit:
		from di.integrations.di_api import post_invoice

		post_invoice(doc)


def _validate_di_items(doc):
	"""Validate that items have required DI fields."""
	for item in doc.items:
		if not item.get("hs_code"):
			frappe.throw(
				_("Row {0}: HS Code is required for Digital Invoicing (Item: {1})").format(
					item.idx, item.item_name
				)
			)

		sale_type = item.get("sales_type") or ""
		if sale_type in SRO_REQUIRED_SALE_TYPES:
			if not item.get("sro_serial_no") and not item.get("schedule_no"):
				frappe.throw(
					_(
						"Row {0}: SRO Serial No or Schedule No is required for sale type '{1}' (Item: {2})"
					).format(item.idx, sale_type, item.item_name)
				)
