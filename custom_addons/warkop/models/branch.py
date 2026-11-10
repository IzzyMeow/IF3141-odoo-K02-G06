from odoo import fields, models


class WarkopBranch(models.Model):
    _name = "warkop.branch"
    _description = "Warkop Branch"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    manager_user_id = fields.Many2one("res.users", string="Operational manager")

    _sql_constraints = [
        ("branch_code_unique", "unique(code)", "Branch code must be unique."),
    ]
