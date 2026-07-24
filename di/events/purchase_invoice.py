"""Purchase Invoice event handlers for Digital Invoicing."""

import frappe
from frappe import _


def before_submit(doc, method=None):
	"""Hook: before_submit on Purchase Invoice."""
	from di.digital_invoicing.doctype.digital_invoice_setting.digital_invoice_setting import (
		get_settings,
		is_enabled,
	)

	if not is_enabled(doc.company):
		return

	settings = get_settings(doc.company)
	if not settings:
		return

	# _validate_items(doc)

	# if settings.auto_post_invoices_on_submit:
	# 	from di.integrations.di_api import post_invoice

	# 	post_invoice(doc)


def _validate_items(doc):
	"""Validate that items have required DI fields."""
	for item in doc.items:
		if not item.get("hs_code"):
			frappe.throw(
				_("Row {0}: HS Code is required for Digital Invoicing (Item: {1})").format(
					item.idx, item.item_name
				)
			)
