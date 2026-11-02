"""Regression fixtures for real XML failures, independent of any local workbook.

    uv run --no-project python -m unittest discover -s scripts -p 'test_*.py'
"""
import contextlib
import io
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import twb_validate as V


class ValidatorRegressionTests(unittest.TestCase):
    def check(self, layer, xml):
        with contextlib.redirect_stdout(io.StringIO()):
            return layer(ET.fromstring(xml), False)

    def test_absent_slices_are_legal(self):
        self.assertTrue(self.check(V.layer1_loads, '<workbook><view /></workbook>'))

    def test_empty_slices_fail(self):
        self.assertFalse(self.check(V.layer1_loads, '<workbook><view><slices /></view></workbook>'))

    def test_non_column_slice_fails(self):
        self.assertFalse(self.check(V.layer1_loads,
            '<workbook><slices><column>[x]</column><filter /></slices></workbook>'))

    def test_populated_slices_pass(self):
        self.assertTrue(self.check(V.layer1_loads,
            '<workbook><slices><column>[x]</column><column>[y]</column></slices></workbook>'))

    def test_empty_encoding_map_fails(self):
        self.assertFalse(self.check(V.layer1_loads,
            '<workbook><encoding field="[Channel]"><map to="#b07aa1"/></encoding></workbook>'))

    def test_encoding_bucket_and_connection_map_pass(self):
        self.assertTrue(self.check(V.layer1_loads, '''<workbook>
          <encoding field="[Channel]"><map to="#b07aa1"><bucket>Retail</bucket></map></encoding>
          <connection><map key="[local]" value="[remote]"/></connection></workbook>'''))

    def test_parameters_order_is_checked(self):
        self.assertFalse(self.check(V.layer1_loads, '''<workbook><datasources>
          <datasource name="Parameters"><layout/><style/><column name="[P]"/></datasource>
          </datasources></workbook>'''))

    def test_sorted_parameters_pass(self):
        self.assertTrue(self.check(V.layer1_loads, '''<workbook><datasources>
          <datasource name="Parameters"><column name="[P]"/><layout/><style/></datasource>
          </datasources></workbook>'''))

    @staticmethod
    def group_book(reference, source='federated.A', declaration=''):
        return '''<workbook><datasources>
          <datasource name="federated.A">
            <column name="[Brand]"><calculation class="categorical-bin" column="[brand_code]"/></column>
            <column name="[brand_code]"/>
            %s
          </datasource>
          <datasource name="federated.B"><column name="[Brand]"/></datasource>
          </datasources><worksheets><worksheet name="Sheet"><table>
            <rows>[%s].[%s]</rows>
          </table></worksheet></worksheets></workbook>''' % (declaration, source, reference)

    def test_direct_categorical_group_passes(self):
        self.assertTrue(self.check(V.layer3_legal, self.group_book('Brand')))

    def test_group_wrapper_resolves_but_is_illegal(self):
        xml = self.group_book('none:Brand:nk')
        self.assertTrue(self.check(V.layer2_resolve, xml))
        self.assertFalse(self.check(V.layer3_legal, xml))

    def test_same_name_ordinary_field_in_other_source_passes(self):
        self.assertTrue(self.check(V.layer3_legal,
            self.group_book('none:Brand:nk', source='federated.B')))

    def test_invalid_group_instance_declaration_fails(self):
        self.assertFalse(self.check(V.layer3_legal, self.group_book('Brand', declaration='''
          <column-instance column="[Brand]" name="[none:Brand:nk]" derivation="None"/>''')))

    def test_commented_group_wrapper_is_not_live(self):
        self.assertTrue(self.check(V.layer3_legal, self.group_book('Brand', declaration='''
          <column name="[Calc]"><calculation class="tableau"
            formula="1 /* [none:Brand:nk] */"/></column>''')))

    @staticmethod
    def set_book(param='[federated.A].[Brand Set]', sheet='Sheet', control='zone'):
        placement = ('<zone type-v2="setMembership" name="%s" param="%s" mode="checkdropdown"/>'
                     % (sheet, param) if control == 'zone' else
                     '<card type="setMembership" param="%s"/>' % param)
        return '''<workbook><datasources>
          <datasource name="federated.A"><group name="[Brand Set]"/></datasource>
          <datasource name="federated.B"><column name="[Brand Set]"/></datasource>
          </datasources><worksheets><worksheet name="Sheet"/></worksheets>
          <dashboards><dashboard name="Dashboard"><zones>%s</zones></dashboard></dashboards>
          </workbook>''' % placement

    def test_set_zone_with_valid_source_passes(self):
        self.assertTrue(self.check(V.layer5_structure, self.set_book()))

    def test_set_card_passes(self):
        self.assertTrue(self.check(V.layer5_structure, self.set_book(control='card')))

    def test_set_in_another_source_does_not_resolve(self):
        self.assertFalse(self.check(V.layer5_structure,
            self.set_book(param='[federated.B].[Brand Set]')))

    def test_non_direct_set_control_reference_fails(self):
        self.assertFalse(self.check(V.layer5_structure,
            self.set_book(param='[federated.A].[io:Brand Set:nk]')))

    def test_set_zone_missing_sheet_fails(self):
        self.assertFalse(self.check(V.layer5_structure, self.set_book(sheet='Deleted')))

    def test_valid_single_source_shared_view_is_preserved(self):
        self.assertTrue(self.check(V.layer5_structure, '''<workbook>
          <datasources><datasource name="federated.A"/></datasources>
          <shared-views><shared-view><datasources><datasource name="federated.A"/>
          </datasources></shared-view></shared-views></workbook>'''))

    def test_parameters_as_worksheet_primary_fails(self):
        # Desktop: 'The worksheet ... does not have a valid data source' and removes it.
        bad = '''<workbook><datasources><datasource name="Parameters"/>
          <datasource name="federated.A"/></datasources><worksheets><worksheet name="S">
          <table><view><datasources><datasource name="Parameters"/>
          <datasource name="federated.A"/></datasources></view></table></worksheet>
          </worksheets></workbook>'''
        self.assertFalse(self.check(V.layer5_structure, bad))
        good = bad.replace('<datasource name="Parameters"/>\n          <datasource name="federated.A"/></datasources></view>',
                           '<datasource name="federated.A"/><datasource name="Parameters"/></datasources></view>')
        self.assertNotEqual(bad, good)
        self.assertTrue(self.check(V.layer5_structure, good))

    def test_shared_view_with_missing_source_fails(self):
        self.assertFalse(self.check(V.layer5_structure, '''<workbook>
          <datasources><datasource name="federated.A"/></datasources>
          <shared-views><shared-view><datasources><datasource name="federated.Deleted"/>
          </datasources></shared-view></shared-views></workbook>'''))

    def test_port_template_preserves_and_remaps_shared_filters(self):
        """Execute the template with in-memory inputs; never write a real workbook."""
        source = ET.fromstring('''<workbook><datasources>
          <datasource name="federated.&lt;legacy-a&gt;"><column name="[brand]"/></datasource>
          <datasource name="federated.&lt;legacy-b&gt;"/>
          </datasources><datasource-relationships/>
          <shared-views><shared-view><datasources>
            <datasource name="federated.&lt;legacy-a&gt;"/>
          </datasources><filter column="[brand]" filter-group="keep-scope">
            <groupfilter function="member" level="[brand]" member="&quot;A&quot;"/>
          </filter></shared-view></shared-views>
          <worksheets><worksheet name="Sheet"><join-lod-include-overrides/></worksheet></worksheets>
          <dashboards/></workbook>''')
        target = ET.fromstring('''<workbook><datasources>
          <datasource name="federated.&lt;target&gt;"><column name="[brand]"/></datasource>
          </datasources></workbook>''')
        with (patch.object(V.T, 'load', side_effect=[(ET.ElementTree(source), source),
                                                    (ET.ElementTree(target), target)]),
              patch.object(V.T, 'save') as save,
              contextlib.redirect_stdout(io.StringIO())):
            runpy.run_path(str(Path(__file__).with_name('port_template.py')))
        save.assert_called_once()
        shared = source.find('./shared-views/shared-view')
        self.assertIsNotNone(shared)
        self.assertEqual(shared.find('./datasources/datasource').get('name'), 'federated.<target>')
        self.assertEqual(shared.find('filter').get('filter-group'), 'keep-scope')
        self.assertEqual(shared.find('./filter/groupfilter').get('member'), '"A"')
        self.assertIsNone(source.find('datasource-relationships'))
        self.assertEqual(source.findall('.//join-lod-include-overrides'), [])


if __name__ == '__main__':
    unittest.main()
