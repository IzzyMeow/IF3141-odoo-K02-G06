{
    "name": "Warkop H. Mahmud Operations",
    "summary": "Inventory, purchasing, cash closing, and menu cost control",
    "version": "17.0.1.0.0",
    "license": "LGPL-3",
    "author": "IF3141 K02 G06",
    "category": "Operations",
    "depends": ["base", "mail", "product", "stock", "purchase", "account", "mrp"],
    "application": True,
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/warkop_views.xml",
        "views/menus.xml",
    ],
}
