from lxml import etree

try:
    etree.parse("hr_salary_rule_data.xml")
    print("✅ Estructura XML válida")
except etree.XMLSyntaxError as e:
    print("❌ Error de sintaxis XML:")
    print(e)
