# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Reminders arrived after Signature Settings existed: turn them on at the
default (every 3 days) on sites that haven't chosen a value yet."""

import frappe


def execute():
	if not frappe.db.get_single_value("Signature Settings", "reminder_interval_days"):
		frappe.db.set_single_value("Signature Settings", "reminder_interval_days", 3)
