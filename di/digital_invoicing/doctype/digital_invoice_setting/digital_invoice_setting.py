import frappe
from frappe.model.document import Document


class DigitalInvoiceSetting(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from di.digital_invoicing.doctype.company_sandbox_scenario.company_sandbox_scenario import CompanySandboxScenario
		from frappe.types import DF

		access_token: DF.Password | None
		annexure_id: DF.Data | None
		auto_post_invoices_on_submit: DF.Check
		company: DF.Link
		enabled: DF.Check
		sandbox: DF.Check
		scenarios: DF.Table[CompanySandboxScenario]
	# end: auto-generated types
	pass


@frappe.whitelist()
def is_enabled(company):
	"""Check if Digital Invoicing is enabled for the given company."""
	return frappe.db.get_value("Digital Invoice Setting", {"company": company}, "enabled")


def get_settings(company):
	"""Get Digital Invoice Setting document for the given company."""
	if not frappe.db.exists("Digital Invoice Setting", {"company": company}):
		return None
	return frappe.get_doc("Digital Invoice Setting", company)
