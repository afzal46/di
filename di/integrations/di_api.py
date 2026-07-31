import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import flt, now

from di.constants import (
	DI_BASE_URL,
	DI_POST_PROD,
	DI_POST_SANDBOX,
	DI_VALIDATE_PROD,
	DI_VALIDATE_SANDBOX,
	INVOICE_TYPE_DEBIT_NOTE,
	INVOICE_TYPE_SALE,
)
from di.digital_invoicing.doctype.integration_log.integration_log import create_log

TAX_MISMATCH_ERROR = (
	"Provided sales tax amount does not match the calculated sales tax amount. "
	"Please ensure that the provided Sale Value is used to calculate the Sales Tax Amount for the provided Rate."
)


@dataclass
class Invoice:
	invoiceType: str
	invoiceDate: str
	sellerBusinessName: str
	sellerNTNCNIC: str
	sellerProvince: str
	sellerAddress: str
	buyerNTNCNIC: str
	buyerBusinessName: str
	buyerRegistrationType: str
	buyerProvince: str
	buyerAddress: str
	invoiceRefNo: str
	items: list


@dataclass
class InvoiceItem:
	discount: float
	fedPayable: float
	furtherTax: float
	hsCode: str
	extraTax: str
	productDescription: str
	quantity: float
	rate: str
	salesTaxApplicable: float
	salesTaxWithheldAtSource: float
	sroItemSerialNo: str
	sroScheduleNo: str
	totalValues: float
	uoM: str
	valueSalesExcludingST: float
	saleType: str
	fixedNotifiedValueOrRetailPrice: float


def as_decimal(value) -> Decimal:
	if value in (None, ""):
		return Decimal("0")
	return Decimal(str(value))


def cascade_round(value, places=2) -> float:
	return float(as_decimal(value).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def is_exempted_item(sale_type) -> bool:
	return sale_type == "Exempt goods"


def is_reduced_rate_item(sale_type) -> bool:
	return sale_type == "Goods at Reduced Rate"


def format_rate(percentage, sale_type) -> str:
	if is_exempted_item(sale_type):
		return "Exempt"
	return f"{int(flt(percentage))}%"


def safe_str(value) -> str:
	return "" if value in (None, "") else str(value)


def post_invoice(doc, resync=False):
	"""Submit invoice to FBR DI API."""
	settings = _get_settings(doc.company)
	if not settings:
		return
	if not resync and not settings.auto_post_invoices_on_submit:
		return

	item_logs = _get_item_logs_for_doc(doc)
	payload = build_di_payload(doc, item_logs=item_logs)
	url = _get_post_url(settings)
	token = settings.get_password("access_token")

	if settings.sandbox and doc.get("di_scenario_id"):
		payload["scenarioId"] = doc.di_scenario_id

	try:
		response = _make_request(url, payload, token)
	except Exception as e:
		create_log(
			doc.doctype,
			doc.name,
			payload,
			str(e),
			status="Error",
			api_type="DI Post",
			title=f"DI Post Error: {doc.doctype} {doc.name}",
		)
		frappe.throw(_("FBR DI API request failed: {0}").format(str(e)))

	invoice_number = response.get("invoiceNumber")
	if invoice_number:
		_handle_success(doc, payload, response, invoice_number, resync)
	else:
		_handle_error(doc, payload, response)


def validate_invoice(doc):
	"""Validate invoice with FBR without posting (validateinvoicedata)."""
	settings = _get_settings(doc.company)
	if not settings:
		frappe.throw(_("Digital Invoice Setting not found for company {0}").format(doc.company))

	item_logs = _get_item_logs_for_doc(doc)
	payload = build_di_payload(doc, item_logs=item_logs)
	url = _get_validate_url(settings)
	token = settings.get_password("access_token")

	if settings.sandbox and doc.get("di_scenario_id"):
		payload["scenarioId"] = doc.di_scenario_id

	try:
		response = _make_request(url, payload, token)
	except Exception as e:
		create_log(
			doc.doctype,
			doc.name,
			payload,
			str(e),
			status="Error",
			api_type="DI Validate",
			title=f"DI Validate Error: {doc.doctype} {doc.name}",
		)
		frappe.throw(_("FBR DI validation request failed: {0}").format(str(e)))

	if not _is_valid_response(response):
		_process_error_response(doc, response)

	create_log(
		doc.doctype,
		doc.name,
		payload,
		response,
		status="Success" if _is_valid_response(response) else "Error",
		api_type="DI Validate",
		title=f"DI Validate: {doc.doctype} {doc.name}",
	)
	return response


def build_di_payload(doc, item_logs=None):
	"""Build the DI API JSON payload from an ERPNext invoice document."""
	info = get_configurations(
		doc.get("customer", default=None),
		doc.get("supplier", default=None),
		doc.company,
	)
	is_purchase = doc.doctype == "Purchase Invoice"

	invoice_type = INVOICE_TYPE_SALE
	invoice_ref_no = ""
	if doc.get("is_return") and doc.get("return_against"):
		invoice_type = INVOICE_TYPE_DEBIT_NOTE
		invoice_ref_no = frappe.db.get_value(doc.doctype, doc.return_against, "integration_id") or ""

	invoice = Invoice(
		invoiceType=invoice_type if not is_purchase else "Purchase Invoice",
		invoiceDate=(
			doc.posting_date.strftime("%Y-%m-%d")
			if hasattr(doc.posting_date, "strftime")
			else str(doc.posting_date)
		),
		sellerBusinessName=(
			info["supplier"]["business_name"] if is_purchase else info["company"]["business_name"]
		),
		sellerNTNCNIC=(info["supplier"]["ntncnic"] if is_purchase else info["company"]["ntncnic"]),
		sellerProvince=(info["supplier"]["province"] if is_purchase else info["company"]["province"]),
		sellerAddress=(info["supplier"]["address"] if is_purchase else info["company"]["address"]),
		buyerNTNCNIC=(info["customer"]["ntncnic"] if not is_purchase else info["company"]["ntncnic"]),
		buyerBusinessName=(
			info["customer"]["business_name"] if not is_purchase else info["company"]["business_name"]
		),
		buyerRegistrationType=(
			info["customer"].get("registration_type", "") if not is_purchase else "Registered"
		),
		buyerProvince=(info["customer"]["province"] if not is_purchase else info["company"]["province"]),
		buyerAddress=(info["customer"]["address"] if not is_purchase else info["company"]["address"]),
		invoiceRefNo=invoice_ref_no,
		items=build_invoice_items(doc, item_logs=item_logs),
	)

	return asdict(invoice)


def _get_settings(company):
	from di.digital_invoicing.doctype.digital_invoice_setting.digital_invoice_setting import (
		get_settings,
		is_enabled,
	)

	if not is_enabled(company):
		return None
	return get_settings(company)


def _get_post_url(settings):
	path = DI_POST_SANDBOX if settings.sandbox else DI_POST_PROD
	return f"{DI_BASE_URL}{path}"


def _get_validate_url(settings):
	path = DI_VALIDATE_SANDBOX if settings.sandbox else DI_VALIDATE_PROD
	return f"{DI_BASE_URL}{path}"


def _make_request(url, payload, token):
	import requests

	response = requests.post(
		url,
		json=payload,
		headers={
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		},
		timeout=30,
	)
	if response.status_code == 401:
		frappe.throw(_("FBR API returned 401 Unauthorized. Check your access token."))
	if response.status_code == 500:
		frappe.throw(_("FBR API returned 500 Internal Server Error. Contact FBR administrator."))
	try:
		return response.json()
	except requests.exceptions.JSONDecodeError:
		import re

		# FBR API sometimes returns JSON with trailing commas
		text = re.sub(r",\s*([}\]])", r"\1", response.text)
		return json.loads(text)


def _is_valid_response(response):
	vr = response.get("validationResponse", {})
	return vr.get("statusCode") == "00" and vr.get("status", "").lower() == "valid"


def _handle_success(doc, payload, response, invoice_number, resync):
	dated = response.get("dated", now())

	if resync:
		doc.db_set("integration_id", invoice_number, update_modified=False)
		doc.db_set("is_posted", 1, update_modified=False)
		doc.db_set("posting_datetime", dated, update_modified=False)
	else:
		doc.integration_id = invoice_number
		doc.is_posted = 1
		doc.posting_datetime = dated

	create_log(
		doc.doctype,
		doc.name,
		payload,
		response,
		status="Success",
		api_type="DI Post",
		title=f"DI Post Success: {doc.doctype} {doc.name}",
		fbr_invoice_number=invoice_number,
	)


def _handle_error(doc, payload, response):
	error_parts = []
	vr = response.get("validationResponse", {})

	if vr.get("error"):
		error_parts.append(vr["error"])

	for item_status in vr.get("invoiceStatuses") or []:
		if item_status.get("status") != "Valid" and item_status.get("error"):
			error_parts.append(f"Item {item_status.get('itemSNo', '?')}: {item_status['error']}")

	error_msg = "\n".join(error_parts) if error_parts else str(response)

	_process_error_response(doc, response)

	create_log(
		doc.doctype,
		doc.name,
		payload,
		response,
		status="Error",
		api_type="DI Post",
		title=f"DI Post Error: {doc.doctype} {doc.name}",
		error_code=vr.get("errorCode", ""),
		error_message=error_msg,
	)
	frappe.throw(_("Digital Invoicing Error:\n{0}").format(error_msg))


def _process_error_response(doc, response):
	"""Record a tax-rounding self-heal hint when FBR rejects an item for the
	exact sales-tax-amount-mismatch error, so the next attempt can nudge that
	item's computed tax by +0.01 (see get_items())."""
	vr = response.get("validationResponse", {}) or {}
	for item_status in vr.get("invoiceStatuses") or []:
		if item_status.get("status") == "Valid":
			continue
		if item_status.get("error") != TAX_MISMATCH_ERROR:
			continue
		idx = item_status.get("itemSNo")
		if not idx:
			continue
		if frappe.db.exists(
			"Item Log",
			{"reference_doctype": doc.doctype, "reference_document": doc.name, "index": idx},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Item Log",
				"reference_doctype": doc.doctype,
				"reference_document": doc.name,
				"index": idx,
			}
		).insert(ignore_permissions=True)


def _get_item_logs_for_doc(doc):
	"""Return [{item_code: idx}, ...] for lines that previously failed FBR's
	tax-rounding validation, so get_items() can apply the self-heal."""
	item_logs = []
	for line in doc.items:
		item_code = line.get("item_code")
		idx = line.get("idx")
		if frappe.db.exists(
			"Item Log",
			{"reference_doctype": doc.doctype, "reference_document": doc.name, "index": idx},
		):
			item_logs.append({item_code: idx})
	return item_logs


def get_configurations(customer, supplier, company):
	customer_doc = frappe.get_doc("Customer", customer) if customer else None
	supplier_doc = frappe.get_doc("Supplier", supplier) if supplier else None
	company_doc = frappe.get_doc("Company", company)

	blank = {"ntncnic": "", "business_name": "", "registration_type": "", "province": "", "address": ""}

	return {
		"customer": (
			{
				"ntncnic": safe_str(customer_doc.get("ntn")),
				"business_name": safe_str(customer_doc.get("customer_name")),
				"registration_type": safe_str(customer_doc.get("registration_type")),
				"province": safe_str(customer_doc.get("province")),
				"address": safe_str(customer_doc.get("address")),
			}
			if customer_doc
			else blank
		),
		"supplier": (
			{
				"ntncnic": safe_str(supplier_doc.get("tax_id")),
				"business_name": safe_str(supplier_doc.get("supplier_name")),
				"registration_type": safe_str(supplier_doc.get("registration_type")),
				"province": safe_str(supplier_doc.get("province")),
				"address": safe_str(supplier_doc.get("address")),
			}
			if supplier_doc
			else blank
		),
		"company": {
			"ntncnic": safe_str(company_doc.get("tax_id")),
			"business_name": safe_str(company_doc.get("company_name")),
			"province": safe_str(company_doc.get("province")),
			"address": safe_str(company_doc.get("address")),
		},
	}


def get_taxes(taxes_lines):
	"""Organize item-wise tax data keyed by tax_type."""
	itemised_tax = {}

	for tax in taxes_lines:
		item_tax_map = json.loads(tax.get("item_wise_tax_detail") or "{}")
		if not item_tax_map:
			continue

		tax_type_key = tax.get("tax_type") or ""
		if not tax_type_key:
			continue

		for item_code, tax_data in item_tax_map.items():
			tax_rate = 0.0
			tax_amount = 0.0

			if isinstance(tax_data, list):
				tax_rate = flt(tax_data[0])
				tax_amount = flt(tax_data[1])
			else:
				tax_rate = flt(tax_data)

			if item_code not in itemised_tax:
				itemised_tax[item_code] = {}

			itemised_tax[item_code][tax_type_key] = {
				"percentage": tax_rate,
				"amount": tax_amount,
			}

	return itemised_tax


def _get_item_unit_packet_size(item_code):
	if not item_code:
		return 1, 1
	values = frappe.db.get_value("Item", item_code, ["unit_size", "custom_packet_size"])
	if not values:
		return 1, 1
	unit_size, packet_size = values
	return flt(unit_size) or 1, flt(packet_size) or 1


def get_di_quantity(line, qty):
	hs_uom = safe_str(line.get("uom", "")).lower()
	if hs_uom == "bag":
		unit_size, _packet_size = _get_item_unit_packet_size(line.get("item_code"))
		return cascade_round(qty * unit_size)
	if hs_uom == "packet":
		_unit_size, packet_size = _get_item_unit_packet_size(line.get("item_code"))
		return cascade_round(qty * packet_size)
	return cascade_round(qty)
 
 
def build_invoice_items(doc, item_logs=None):
	"""Transform invoice line items to FBR DI format."""
	item_taxes = get_taxes(doc.taxes)
	invoice_items = []

	for line in doc.items:
		item_code = line.get("item_code")
		tax_data = item_taxes.get(item_code, {})
		gst = tax_data.get("Sales Tax", {"percentage": 0.0, "amount": 0.0})
		further_tax = tax_data.get("Further Tax", {"percentage": 0.0, "amount": 0.0})
		extra_tax = tax_data.get("Advance Tax", {"percentage": 0.0, "amount": 0.0})

		qty = flt(line.get("qty", 0))
		sale_type = line.get("sales_type") or ""
		net_amount = cascade_round(line.get("base_net_amount") or line.get("net_amount", 0))

		if is_exempted_item(sale_type):
			sales_tax_amount = 0.0
		else:
			sales_tax_amount = cascade_round(
				as_decimal(net_amount) * as_decimal(gst["percentage"]) / Decimal("100")
			)

		item_log_index = None
		for log_entry in item_logs or []:
			if item_code in log_entry:
				item_log_index = log_entry[item_code]
				break
		if item_log_index and sales_tax_amount > 0:
			sales_tax_amount = cascade_round(as_decimal(sales_tax_amount) + Decimal("0.01"))

		further_tax_amount = cascade_round(further_tax["amount"])
		extra_tax_amount = cascade_round(extra_tax["amount"])

		quantity = get_di_quantity(line, qty)
		quantity_decimal = as_decimal(quantity)
		fixed_price = (
			cascade_round(as_decimal(net_amount) / quantity_decimal) if quantity_decimal else 0.0
		)

		discount_amount = line.get("discount_amount", 0)
		discount = cascade_round(as_decimal(discount_amount) * as_decimal(qty)) if flt(discount_amount) >= 0 else 0

		total_values = cascade_round(
			as_decimal(net_amount)
			+ as_decimal(sales_tax_amount)
			+ as_decimal(further_tax_amount)
			+ as_decimal(extra_tax_amount)
		)

		invoice_item = InvoiceItem(
			discount=discount,
			fedPayable=cascade_round(line.get("fed_payable", 0)),
			furtherTax=further_tax_amount,
			hsCode=safe_str(line.get("hs_code", "")),
			extraTax="" if is_reduced_rate_item(sale_type) else "0",
			productDescription=f'{line.get("item_code")}: {safe_str(line.get("item_name", ""))} ({line.get("idx", "")})',
			quantity=quantity,
			rate=format_rate(gst["percentage"], sale_type),
			salesTaxApplicable=sales_tax_amount,
			salesTaxWithheldAtSource=0,
			sroItemSerialNo=safe_str(line.get("sro_serial_no", "")),
			sroScheduleNo=safe_str(line.get("schedule_no", "")),
			totalValues=total_values,
			uoM=safe_str(line.get("hs_uom", "")),
			valueSalesExcludingST=net_amount,
			saleType=sale_type,
			fixedNotifiedValueOrRetailPrice=fixed_price,
		)

		invoice_items.append(asdict(invoice_item))

	return invoice_items
