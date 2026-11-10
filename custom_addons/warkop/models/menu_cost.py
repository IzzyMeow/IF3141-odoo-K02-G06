from odoo import api, fields, models
from odoo.exceptions import AccessError


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

    @api.depends("line_ids.quantity", "line_ids.product_id", "line_ids.product_id.standard_price",
                 "waste_percent", "sale_price")
    def _compute_cost(self):
        for menu in self:
            base_cost = sum(line.quantity * line.product_id.standard_price for line in menu.line_ids)
            menu.hpp = base_cost * (1 + menu.waste_percent / 100)
            menu.margin_amount = menu.sale_price - menu.hpp
            menu.margin_percent = (menu.margin_amount / menu.sale_price * 100
                                   if menu.sale_price else 0)

    def action_recalculate(self):
        if not self.env.user.has_group("warkop.group_purchasing_manager"):
            raise AccessError("Only the Purchasing Manager can recalculate menu cost.")
        self._compute_cost()


class WarkopMenuLine(models.Model):
    _name = "warkop.menu.line"
    _description = "Menu Recipe Line"

    menu_id = fields.Many2one("warkop.menu", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", readonly=True)
