from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class WarkopMenu(models.Model):
    _name = "warkop.menu"
    _description = "Warkop Menu"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    sale_price = fields.Float(required=True)
    waste_percent = fields.Float(default=0)
    line_ids = fields.One2many("warkop.menu.line", "menu_id")
    hpp = fields.Float(compute="_compute_cost", store=True)
    margin_amount = fields.Float(compute="_compute_cost", store=True)
    margin_percent = fields.Float(compute="_compute_cost", store=True)
    state = fields.Selection([
        ("incomplete", "Incomplete"), ("needs_recalculation", "Needs Recalculation"),
        ("calculated", "Calculated"), ("inactive", "Inactive"),
    ], default="incomplete", tracking=True)

    @api.depends("line_ids.quantity", "line_ids.product_id", "line_ids.product_id.standard_price",
                 "waste_percent", "sale_price")
    def _compute_cost(self):
        for menu in self:
            base_cost = sum(line.quantity * line.product_id.standard_price for line in menu.line_ids)
            menu.hpp = base_cost * (1 + menu.waste_percent / 100)
            menu.margin_amount = menu.sale_price - menu.hpp
            menu.margin_percent = (menu.margin_amount / menu.sale_price * 100
                                   if menu.sale_price else 0)
            if not menu.line_ids or any(not line.product_id or line.quantity <= 0
                                        for line in menu.line_ids):
                menu.state = "incomplete"
            elif menu.state != "inactive":
                menu.state = "calculated"

    def action_recalculate(self):
        if not self.env.user.has_group("warkop.group_purchasing_manager"):
            raise AccessError("Only the Purchasing Manager can recalculate menu cost.")
        self._compute_cost()

    def write(self, vals):
        recalculation_fields = {"sale_price", "waste_percent", "line_ids"}
        should_recalculate = bool(recalculation_fields.intersection(vals))
        result = super().write(vals)
        if should_recalculate:
            self.filtered(lambda menu: menu.state != "inactive").write(
                {"state": "needs_recalculation"}
            )
        return result

    @api.constrains("sale_price", "waste_percent")
    def _check_menu_values(self):
        for menu in self:
            if menu.sale_price <= 0 or menu.waste_percent < 0:
                raise ValidationError(_("Sale price must be positive and waste cannot be negative."))

    def action_simulate_margin(self, hypothetical_sale_price=0, hypothetical_unit_cost=0):
        self._require_group("warkop.group_purchasing_manager")
        self.ensure_one()
        sale_price = hypothetical_sale_price or self.sale_price
        hpp = hypothetical_unit_cost or self.hpp
        if sale_price <= 0 or hpp < 0:
            raise UserError(_("Simulation values are invalid."))
        return {
            "hpp": hpp,
            "margin_amount": sale_price - hpp,
            "margin_percent": (sale_price - hpp) / sale_price * 100,
        }


class WarkopMenuLine(models.Model):
    _name = "warkop.menu.line"
    _description = "Menu Recipe Line"

    menu_id = fields.Many2one("warkop.menu", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", readonly=True)

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Recipe quantity must be positive."))

    def _mark_menus_for_recalculation(self):
        self.mapped("menu_id").filtered(
            lambda menu: menu.state != "inactive"
        ).write({"state": "needs_recalculation"})

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._mark_menus_for_recalculation()
        return lines

    def write(self, vals):
        result = super().write(vals)
        self._mark_menus_for_recalculation()
        return result

    def unlink(self):
        menus = self.mapped("menu_id")
        result = super().unlink()
        menus.filtered(lambda menu: menu.state != "inactive").write(
            {"state": "needs_recalculation"}
        )
        return result
