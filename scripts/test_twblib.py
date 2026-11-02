"""Generic transformation regressions; no Desktop or local workbook required."""
import unittest
import xml.etree.ElementTree as ET

import twblib as T


class SheetRenameTests(unittest.TestCase):
    def test_references_follow_names_without_rewriting_presentation(self):
        root = ET.fromstring('''<workbook>
          <datasources><datasource name="federated.A">
            <column name="[detail]" caption="detail"/>
            <connection><relation name="detail" table="[detail]"/></connection>
          </datasource></datasources>
          <worksheets><worksheet name="detail"><layout><title>
            <formatted-text><run>detail</run></formatted-text>
          </title></layout></worksheet></worksheets>
          <dashboards><dashboard name="summary"><zones>
            <zone name="detail" type-v2="viz"/>
          </zones><devicelayouts><devicelayout><zones>
            <zone name="detail" type-v2="setMembership" param="[federated.A].[Selection]"/>
          </zones></devicelayout></devicelayouts></dashboard></dashboards>
          <windows><window name="detail"><viewpoints><viewpoint name="detail"/>
          </viewpoints></window><window name="summary"/></windows>
          <shared-views><shared-view><exclude-sheet name="detail"/></shared-view></shared-views>
          <actions><action name="detail"><source worksheet="detail" dashboard="summary"/>
            <command><param name="target" value="detail"/>
              <param name="caption" value="detail"/></command>
          </action></actions>
          <unrelated><param name="target" value="detail"/></unrelated>
        </workbook>''')
        mapping = {'detail': 'Product Detail', 'summary': 'Product Summary'}
        self.assertGreater(T.rename_sheets(root, mapping), 0)
        for path in ('./worksheets/worksheet', './dashboards/dashboard/zones/zone',
                     './dashboards/dashboard/devicelayouts/devicelayout/zones/zone',
                     './windows/window/viewpoints/viewpoint',
                     './shared-views/shared-view/exclude-sheet'):
            self.assertEqual(root.find(path).get('name'), 'Product Detail', path)
        self.assertEqual(root.find('./dashboards/dashboard').get('name'), 'Product Summary')
        self.assertEqual([w.get('name') for w in root.findall('./windows/window')],
                         ['Product Detail', 'Product Summary'])
        source = root.find('./actions/action/source')
        self.assertEqual(source.get('worksheet'), 'Product Detail')
        self.assertEqual(source.get('dashboard'), 'Product Summary')
        self.assertEqual(root.find('./actions/action/command/param[@name="target"]').get('value'),
                         'Product Detail')
        self.assertEqual(root.find('.//column').attrib, {'name': '[detail]', 'caption': 'detail'})
        self.assertEqual(root.find('.//relation').attrib, {'name': 'detail', 'table': '[detail]'})
        self.assertEqual(root.find('.//formatted-text/run').text, 'detail')
        self.assertEqual(root.find('./actions/action').get('name'), 'detail')
        self.assertEqual(root.find('./actions/action/command/param[@name="caption"]').get('value'),
                         'detail')
        self.assertEqual(root.find('./unrelated/param').get('value'), 'detail')
        self.assertEqual(T.rename_sheets(root, mapping), 0)

    def test_collision_is_rejected_before_any_mutation(self):
        root = ET.fromstring('''<workbook><worksheets>
          <worksheet name="A"/><worksheet name="B"/>
          </worksheets><dashboards><dashboard name="Summary"/></dashboards></workbook>''')
        before = T.signature(root)
        for mapping in ({'A': 'B'}, {'A': 'Summary'}, {'A': 'New', 'B': 'New'}):
            with self.assertRaises(ValueError):
                T.rename_sheets(root, mapping)
            self.assertEqual(T.signature(root), before)

    def test_simultaneous_swap_keeps_bindings(self):
        root = ET.fromstring('''<workbook><worksheets>
          <worksheet name="A"/><worksheet name="B"/></worksheets>
          <actions><action><source worksheet="A"/><command>
            <param name="target" value="B"/>
          </command></action></actions></workbook>''')
        T.rename_sheets(root, {'A': 'B', 'B': 'A'})
        self.assertEqual([s.get('name') for s in T.worksheets(root)], ['B', 'A'])
        self.assertEqual(root.find('.//source').get('worksheet'), 'B')
        self.assertEqual(root.find('.//param').get('value'), 'A')


class ReferenceRewriteTests(unittest.TestCase):
    def test_stacked_derivations_and_visual_total_tokens_are_mapped(self):
        _, rewrite = T.make_rewriter({'Old Calc': 'New Calc'}, {'federated.A': 'federated.B'})
        el = ET.fromstring('<x a="[federated.A].[pcto:cum:usr:Old Calc:qk]" '
                           'b="[federated.A].[usr:Old Calc:vtnone:qk]" c="[none:Old Calc:nk:1]"/>')
        rewrite(el)
        self.assertEqual(el.get('a'), '[federated.B].[pcto:cum:usr:New Calc:qk]')
        self.assertEqual(el.get('b'), '[federated.B].[usr:New Calc:vtnone:qk]')
        self.assertEqual(el.get('c'), '[none:New Calc:nk:1]')

    def test_known_names_resolve_colons_and_lowercase_physical_fields(self):
        known = ['day:sunday units', 'retailer', 'date']
        fmap = {'day:sunday units': 'Sunday Share', 'retailer': 'Retailer Name'}
        _, rewrite = T.make_rewriter(fmap, {}, known_names=known)
        el = ET.fromstring('<x a="[usr:day:sunday units:qk]" b="[none:retailer:nk]" '
                           'c="[tdy:date:ok]" d="[Unrelated \\% Field]"/>')
        rewrite(el)
        self.assertEqual(el.get('a'), '[usr:Sunday Share:qk]')
        self.assertEqual(el.get('b'), '[none:Retailer Name:nk]')
        self.assertEqual(el.get('c'), '[tdy:date:ok]')
        self.assertEqual(el.get('d'), '[Unrelated \\% Field]')
        self.assertEqual(T.split_reference('none:retailer:nk', known), ('none:', 'retailer', ':nk'))
        self.assertEqual(T.ref_base('pcto:cum:usr:Calc A:qk'), 'Calc A')

    def test_shared_view_filters_are_reported(self):
        root = ET.fromstring('''<workbook><shared-views><shared-view name="federated.A">
          <filter class="categorical" column="[federated.A].[none:segment:nk]" context="true">
            <groupfilter function="member" level="[none:segment:nk]" member="&quot;Core&quot;"/>
          </filter></shared-view></shared-views></workbook>''')
        self.assertEqual(T.shared_view_filters(root),
                         [('federated.A', '[federated.A].[none:segment:nk]', True, ['"Core"'])])


if __name__ == '__main__':
    unittest.main()
