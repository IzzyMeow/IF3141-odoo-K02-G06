from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class WarkopStockBalance(models.Model):
    _name = "warkop.stock.balance"
    _description = "Branch Stock Balance"
    _rec_name = "product_id"

    branch_id = fields.Many2one("warkop.branch", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict")
    quantity = fields.Float(default=0, required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", readonly=True)
    last_updated = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("branch_product_unique", "unique(branch_id, product_id)",
         "A product can only have one balance per branch."),
    ]

    def adjust(self, delta):
        for balance in self:
            balance.write({"quantity": balance.quantity + delta,
                           "last_updated": fields.Datetime.now()})


class WarkopStockReportLine(models.Model):
    _name = "warkop.stock.report.line"
    _description = "Stock Report Line"

    report_id = fields.Many2one("warkop.stock.report", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(required=True)
    recorded_quantity = fields.Float(readonly=True)
    difference = fields.Float(compute="_compute_difference", store=True)

    @api.depends("quantity", "recorded_quantity")
    def _compute_difference(self):
        for line in self:
            line.difference = line.quantity - line.recorded_quantity

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity < 0:
                raise ValidationError(_("Quantity cannot be negative."))


class WarkopStockReport(models.Model):
    _name = "warkop.stock.report"
    _description = "Stock Opname and Waste Report"
    _inherit = ["mail.thread", "warkop.workflow.mixin"]
    _order = "report_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    branch_id = fields.Many2one("warkop.branch", required=True, tracking=True)
    report_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    report_type = fields.Selection(
        [("opname", "Stock Opname"), ("waste", "Waste")],
        required=True, default="opname", tracking=True,
    )
    reason = fields.Char()
    evidence = fields.Binary(attachment=True)
    state = fields.Selection([
        ("draft", "Draft"), ("submitted", "Waiting Verification"),
        ("returned", "Returned"), ("verified", "Verified"),
        ("waiting_approval", "Waiting Approval"), ("applied", "Applied"),
        ("closed", "Closed"),
    ], default="draft", required=True, tracking=True)
    rejection_reason = fields.Text(readonly=True)
    line_ids = fields.One2many("warkop.stock.report.line", "report_id", required=True)
    verifier_id = fields.Many2one("res.users", readonly=True)
    approver_id = fields.Many2one("res.users", readonly=True)
    submitted_at = fields.Datetime(readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("warkop.stock.report") or _("New")
        return super().create(vals_list)

    def action_submit(self):
        for report in self:
            if report.state not in ("draft", "returned"):
                raise UserError(_("Only draft or returned reports can be submitted."))
            if not report.line_ids:
                raise ValidationError(_("At least one stock line is required."))
            for line in report.line_ids:
                balance = self.env["warkop.stock.balance"].search([
                    ("branch_id", "=", report.branch_id.id),
                    ("product_id", "=", line.product_id.id),
                ], limit=1)
                line.recorded_quantity = balance.quantity if balance else 0
            report._transition(
                report.state, "submitted",
                {"submitted_at": fields.Datetime.now(), "rejection_reason": False},
            )

    def action_verify(self):
        self._require_group("warkop.group_team_leader")
        for report in self:
            if report.state != "submitted":
                raise UserError(_("Only submitted reports can be verified."))
            report._transition("submitted", "verified", {"verifier_id": self.env.uid})
            if report.report_type == "waste" or any(line.difference for line in report.line_ids):
                report.state = "waiting_approval"
            else:
                report.state = "closed"

    def action_return(self):
        self._require_group("warkop.group_team_leader")
        for report in self:
            if report.state != "submitted":
                raise UserError(_("Only submitted reports can be returned."))
            report._transition(
                "submitted", "returned",
                {"verifier_id": self.env.uid,
                 "rejection_reason": _("Returned by %s") % self.env.user.name},
            )

    def action_approve_adjustment(self):
        self._require_group("warkop.group_operations_manager")
        for report in self:
            if report.state != "waiting_approval":
                raise UserError(_("Only reports waiting for approval can be applied."))
            for line in report.line_ids:
                balance = self.env["warkop.stock.balance"].search([
                    ("branch_id", "=", report.branch_id.id),
                    ("product_id", "=", line.product_id.id),
                ], limit=1)
                if not balance:
                    balance = self.env["warkop.stock.balance"].create({
                        "branch_id": report.branch_id.id,
                        "product_id": line.product_id.id,
                        "quantity": 0,
                    })
                delta = -line.quantity if report.report_type == "waste" else line.difference
                self.env["warkop.stock.adjustment"].create({
                    "report_id": report.id, "branch_id": report.branch_id.id,
                    "product_id": line.product_id.id, "delta": delta,
                    "approved_by": self.env.uid,
                })
                balance.adjust(delta)
            report._transition(
                "waiting_approval", "applied",
                {"approver_id": self.env.uid, "approved_at": fields.Datetime.now()},
            )


class WarkopStockAdjustment(models.Model):
    _name = "warkop.stock.adjustment"
    _description = "Stock Adjustment Audit"
    _order = "approved_at desc"

    report_id = fields.Many2one("warkop.stock.report", required=True, ondelete="restrict")
    branch_id = fields.Many2one("warkop.branch", required=True)
    product_id = fields.Many2one("product.product", required=True)
    delta = fields.Float(required=True)
    approved_by = fields.Many2one("res.users", required=True, readonly=True)
    approved_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
