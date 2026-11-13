from math import ceil

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class WarkopPurchaseParameter(models.Model):
    _name = "warkop.purchase.parameter"
    _description = "Branch Purchase Parameter"

    branch_id = fields.Many2one("warkop.branch", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict")
    safety_stock = fields.Float(required=True)
    planning_days = fields.Float(default=3, required=True)
    lead_time_days = fields.Float(default=1, required=True)
    purchase_uom_qty = fields.Float(default=1, required=True)

    _sql_constraints = [
        ("parameter_unique", "unique(branch_id, product_id)",
         "A purchase parameter must be unique per branch and product."),
    ]

    @api.constrains("safety_stock", "planning_days", "lead_time_days", "purchase_uom_qty")
    def _check_positive_parameters(self):
        for parameter in self:
            if any(value < 0 for value in (
                parameter.safety_stock, parameter.planning_days, parameter.lead_time_days,
            )) or parameter.purchase_uom_qty <= 0:
                raise ValidationError(_("Purchase parameters must be non-negative and the purchase unit must be positive."))


class WarkopSalesImport(models.Model):
    _name = "warkop.sales.import"
    _description = "POS Sales Import"

    name = fields.Char(required=True)
    branch_id = fields.Many2one("warkop.branch", required=True)
    imported_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    line_ids = fields.One2many("warkop.sales.import.line", "import_id")
    state = fields.Selection([("draft", "Draft"), ("processed", "Processed")],
                             default="draft", required=True)

    def action_process(self):
        for batch in self:
            if not batch.line_ids:
                raise UserError(_("A sales import must contain at least one line."))
            duplicate = self.env["warkop.sales.import.line"].search([
                ("import_id.branch_id", "=", batch.branch_id.id),
                ("import_id.state", "=", "processed"),
                ("external_ref", "in", batch.line_ids.mapped("external_ref")),
            ], limit=1)
            if duplicate:
                raise UserError(
                    _("Sales line %s was already imported for this branch.") % duplicate.external_ref
                )
            batch.state = "processed"


class WarkopSalesImportLine(models.Model):
    _name = "warkop.sales.import.line"
    _description = "POS Sales Import Line"

    import_id = fields.Many2one("warkop.sales.import", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(required=True)
    external_ref = fields.Char(required=True)
    sale_date = fields.Date(required=True)
    total_amount = fields.Float(default=0, required=True)
    payment_method = fields.Selection([
        ("cash", "Cash"), ("qris", "QRIS"), ("debit", "Debit"),
    ], default="cash", required=True)

    _sql_constraints = [
        ("external_ref_unique", "unique(import_id, external_ref)",
         "The same POS transaction line cannot be imported twice in one batch."),
    ]

    @api.constrains("quantity", "total_amount")
    def _check_sales_values(self):
        for line in self:
            if line.quantity <= 0 or line.total_amount < 0:
                raise ValidationError(_("Sales quantity must be positive and amount cannot be negative."))


class WarkopPurchaseRecommendation(models.Model):
    _name = "warkop.purchase.recommendation"
    _description = "Purchase Recommendation"
    _order = "create_date desc"

    name = fields.Char(default=lambda self: _("Purchase Recommendation"), required=True)
    branch_id = fields.Many2one("warkop.branch", required=True)
    product_id = fields.Many2one("product.product", required=True)
    projected_usage = fields.Float(readonly=True)
    safety_stock = fields.Float(readonly=True)
    available_stock = fields.Float(readonly=True)
    open_orders = fields.Float(readonly=True)
    recommended_qty = fields.Float(readonly=True)
    purchase_qty = fields.Float(readonly=True)
    last_import_at = fields.Datetime(readonly=True)
    ignored = fields.Boolean(default=False, readonly=True)
    ignore_reason = fields.Text(readonly=True)

    def action_ignore(self, reason):
        if not self.env.user.has_group("warkop.group_purchasing_manager"):
            raise AccessError(_("Only the Purchasing Manager can ignore recommendations."))
        if not reason:
            raise UserError(_("An ignore reason is required."))
        self.write({"ignored": True, "ignore_reason": reason})

    @api.model
    def action_calculate(self, branch, products=None):
        if not self.env.user.has_group("warkop.group_purchasing_manager"):
            raise AccessError(_("Only the Purchasing Manager can calculate recommendations."))
        parameters = self.env["warkop.purchase.parameter"].search([
            ("branch_id", "=", branch.id),
            *([("product_id", "in", products.ids)] if products else []),
        ])
        self.search([("branch_id", "=", branch.id)]).unlink()
        result = self.env[self._name]
        for parameter in parameters:
            lines = self.env["warkop.sales.import.line"].search([
                ("import_id.branch_id", "=", branch.id),
                ("import_id.state", "=", "processed"),
                ("product_id", "=", parameter.product_id.id),
            ])
            days = max(parameter.planning_days, 1)
            projected = sum(lines.mapped("quantity")) / 7 * days
            balance = self.env["warkop.stock.balance"].search([
                ("branch_id", "=", branch.id), ("product_id", "=", parameter.product_id.id),
            ], limit=1)
            open_orders = sum(self.env["warkop.purchase.order"].search([
                ("branch_id", "=", branch.id), ("product_id", "=", parameter.product_id.id),
                ("state", "=", "issued"),
            ]).mapped("quantity"))
            recommended = projected + parameter.safety_stock - (balance.quantity if balance else 0) - open_orders
            if recommended <= 0:
                continue
            purchase_qty = ceil(recommended / parameter.purchase_uom_qty) * parameter.purchase_uom_qty
            latest = max(lines.mapped("import_id.imported_at")) if lines else False
            result |= self.create({
                "branch_id": branch.id, "product_id": parameter.product_id.id,
                "projected_usage": projected, "safety_stock": parameter.safety_stock,
                "available_stock": balance.quantity if balance else 0,
                "open_orders": open_orders, "recommended_qty": recommended,
                "purchase_qty": purchase_qty, "last_import_at": latest,
            })
        return result


class WarkopPurchaseOrder(models.Model):
    _name = "warkop.purchase.order"
    _description = "Warkop Purchase Order"
    _inherit = ["mail.thread", "warkop.workflow.mixin"]

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    branch_id = fields.Many2one("warkop.branch", required=True)
    product_id = fields.Many2one("product.product", required=True)
    vendor_id = fields.Many2one("res.partner", required=True)
    quantity = fields.Float(required=True)
    unit_price = fields.Float(required=True)
    amount = fields.Monetary(compute="_compute_amount", store=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    approval_limit = fields.Monetary(default=1000000, required=True)
    state = fields.Selection([
        ("draft", "Draft"), ("waiting_approval", "Waiting Approval"),
        ("issued", "Issued"), ("rejected", "Rejected"), ("cancelled", "Cancelled"),
    ], default="draft", tracking=True)
    rejection_reason = fields.Text(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.depends("quantity", "unit_price")
    def _compute_amount(self):
        for order in self:
            order.amount = order.quantity * order.unit_price

    def action_confirm(self):
        for order in self:
            if order.state not in ("draft", "rejected"):
                raise UserError(_("Only draft or rejected orders can be confirmed."))
            if order.amount >= order.approval_limit:
                order._transition(order.state, "waiting_approval")
            else:
                order._transition(
                    order.state, "issued",
                    {"approved_by": self.env.uid, "approved_at": fields.Datetime.now()},
                )

    def action_approve(self):
        self._require_group("warkop.group_owner")
        for order in self:
            if order.state != "waiting_approval":
                raise UserError(_("Only orders waiting for approval can be approved."))
            order._transition(
                "waiting_approval", "issued",
                {"approved_by": self.env.uid, "approved_at": fields.Datetime.now()},
            )

    def action_reject(self):
        self._require_group("warkop.group_owner")
        self._transition(
            "waiting_approval", "draft",
            {"rejection_reason": _("Rejected by %s") % self.env.user.name},
        )
