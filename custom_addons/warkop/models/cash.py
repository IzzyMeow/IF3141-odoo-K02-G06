from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class WarkopCashClosing(models.Model):
    _name = "warkop.cash.closing"
    _description = "Shift Cash Closing"
    _inherit = ["mail.thread", "warkop.workflow.mixin"]

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    branch_id = fields.Many2one("warkop.branch", required=True)
    closing_date = fields.Date(default=fields.Date.context_today, required=True)
    shift = fields.Selection([("morning", "Morning"), ("afternoon", "Afternoon"),
                              ("night", "Night")], required=True)
    opening_balance = fields.Monetary(required=True)
    cash_counted = fields.Monetary(required=True)
    qris_amount = fields.Monetary(required=True)
    debit_amount = fields.Monetary(required=True)
    deposit_amount = fields.Monetary(required=True)
    expected_total = fields.Monetary(compute="_compute_total", store=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    state = fields.Selection([("draft", "Draft"), ("submitted", "Waiting Verification"),
                              ("returned", "Returned"), ("verified", "Verified")],
                             default="draft", required=True, tracking=True)
    rejection_reason = fields.Text(readonly=True)
    verifier_id = fields.Many2one("res.users", readonly=True)
    reported_by = fields.Many2one("res.users", default=lambda self: self.env.user,
                                  readonly=True, copy=False)

    _sql_constraints = [
        ("closing_shift_unique", "unique(branch_id, closing_date, shift)",
         "A branch can only have one closing report per date and shift."),
    ]

    @api.depends("cash_counted", "qris_amount", "debit_amount", "deposit_amount")
    def _compute_total(self):
        for closing in self:
            closing.expected_total = (closing.cash_counted + closing.qris_amount +
                                      closing.debit_amount - closing.deposit_amount)

    @api.constrains("opening_balance", "cash_counted", "qris_amount", "debit_amount",
                    "deposit_amount")
    def _check_non_negative(self):
        for closing in self:
            if any(value < 0 for value in (closing.opening_balance, closing.cash_counted,
                                           closing.qris_amount, closing.debit_amount,
                                           closing.deposit_amount)):
                raise ValidationError(_("Cash amounts cannot be negative."))

    def action_submit(self):
        for closing in self:
            if closing.state not in ("draft", "returned"):
                raise UserError(_("Only draft or returned closings can be submitted."))
            closing._transition(closing.state, "submitted")

    def action_verify(self):
        self._require_group("warkop.group_team_leader")
        for closing in self:
            if closing.reported_by == self.env.user:
                raise UserError(_("The person who submitted a closing cannot verify it."))
        self._transition("submitted", "verified", {"verifier_id": self.env.uid})

    def action_return(self):
        self._require_group("warkop.group_team_leader")
        self._transition(
            "submitted", "returned",
            {"rejection_reason": _("Returned by %s") % self.env.user.name},
        )


class WarkopCashConsolidation(models.Model):
    _name = "warkop.cash.consolidation"
    _description = "Daily Cash Consolidation"

    name = fields.Char(required=True)
    consolidation_date = fields.Date(required=True)
    closing_ids = fields.Many2many("warkop.cash.closing")
    total_cash = fields.Monetary(compute="_compute_totals", store=True)
    total_qris = fields.Monetary(compute="_compute_totals", store=True)
    total_debit = fields.Monetary(compute="_compute_totals", store=True)
    total_deposit = fields.Monetary(compute="_compute_totals", store=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ("draft", "Draft"), ("posted", "Posted"),
        ("needs_review", "Needs Review"), ("reconciled", "Reconciled"),
    ], default="draft")
    pos_total = fields.Monetary(compute="_compute_reconciliation", store=True)
    variance = fields.Monetary(compute="_compute_reconciliation", store=True)
    reconciliation_note = fields.Text()

    @api.depends("closing_ids", "closing_ids.cash_counted", "closing_ids.qris_amount",
                 "closing_ids.debit_amount", "closing_ids.deposit_amount")
    def _compute_totals(self):
        for consolidation in self:
            closings = consolidation.closing_ids.filtered(lambda closing: closing.state == "verified")
            consolidation.total_cash = sum(closings.mapped("cash_counted"))
            consolidation.total_qris = sum(closings.mapped("qris_amount"))
            consolidation.total_debit = sum(closings.mapped("debit_amount"))
            consolidation.total_deposit = sum(closings.mapped("deposit_amount"))

    @api.depends(
        "consolidation_date", "closing_ids", "closing_ids.state",
        "closing_ids.cash_counted", "closing_ids.qris_amount", "closing_ids.debit_amount",
    )
    def _compute_reconciliation(self):
        for consolidation in self:
            lines = self.env["warkop.sales.import.line"].search([
                ("import_id.state", "=", "processed"),
                ("sale_date", "=", consolidation.consolidation_date),
            ])
            consolidation.pos_total = sum(lines.mapped("total_amount"))
            received = (consolidation.total_cash + consolidation.total_qris +
                        consolidation.total_debit)
            consolidation.variance = received - consolidation.pos_total

    def action_post(self):
        if not self.env.user.has_group("warkop.group_finance_manager"):
            raise AccessError(_("Only the Finance Manager can post a consolidation."))
        for consolidation in self:
            if not consolidation.closing_ids or any(
                closing.state != "verified" for closing in consolidation.closing_ids
            ):
                raise UserError(_("Only verified cash closings can be consolidated."))
            consolidation.state = "posted" if not consolidation.variance else "needs_review"

    def action_reconcile(self):
        if not self.env.user.has_group("warkop.group_finance_manager"):
            raise AccessError(_("Only the Finance Manager can reconcile a consolidation."))
        for consolidation in self:
            if consolidation.state != "needs_review":
                raise UserError(_("Only consolidations needing review can be reconciled."))
            if not consolidation.reconciliation_note:
                raise UserError(_("Explain the variance before reconciling the consolidation."))
            consolidation.state = "reconciled"
