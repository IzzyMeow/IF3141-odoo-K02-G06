from odoo import _, models
from odoo.exceptions import AccessError, UserError


class WarkopWorkflowMixin(models.AbstractModel):
    _name = "warkop.workflow.mixin"
    _description = "Warkop Workflow Behavior"

    def _require_group(self, group_xml_id):
        if not self.env.user.has_group(group_xml_id):
            raise AccessError(_("Anda tidak memiliki peran untuk melakukan tindakan ini."))

    def _transition(self, expected_state, new_state, values=None):
        values = dict(values or {}, state=new_state)
        for record in self:
            if record.state != expected_state:
                raise UserError(
                    _("Transisi status tidak valid dari '%s'.") % record.state
                )
            record.write(values)
