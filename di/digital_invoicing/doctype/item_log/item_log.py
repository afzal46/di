import frappe
from frappe.model.document import Document


class ItemLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		increment: DF.Check
		index: DF.Int
		reference_doctype: DF.Link | None
		reference_document: DF.DynamicLink | None
	# end: auto-generated types
	pass
