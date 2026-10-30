import unittest
from app.graph_engine import impacted_resources, prerequisite_resources, conflicting_versions, valid_resource_address


class GraphEngineTests(unittest.TestCase):
    def setUp(self):
        # cluster -> subnet -> vpc; iam isolated
        self.edges = [('cluster', 'subnet'), ('subnet', 'vpc')]

    def test_reverse_dependency_closure(self):
        self.assertEqual(impacted_resources({'vpc'}, self.edges), {'vpc', 'subnet', 'cluster'})
        self.assertEqual(impacted_resources({'subnet'}, self.edges), {'subnet', 'cluster'})
        self.assertEqual(impacted_resources({'iam'}, self.edges), {'iam'})

    def test_prerequisite_read_set(self):
        self.assertEqual(prerequisite_resources({'cluster'}, self.edges), {'subnet','vpc'})
        self.assertEqual(prerequisite_resources({'iam'}, self.edges), set())

    def test_disjoint_resources_independent(self):
        self.assertFalse(impacted_resources({'iam'}, self.edges) & impacted_resources({'vpc'}, self.edges))

    def test_conservative_mode_can_be_disabled_for_testing(self):
        self.assertEqual(impacted_resources({'vpc'}, self.edges, False), {'vpc'})

    def test_version_conflict_and_unknown_resource(self):
        self.assertEqual(conflicting_versions({'vpc': 7, 'new': 0}, {'vpc': 8}),
                         {'vpc': {'expected': 7, 'current': 8}})
        self.assertEqual(conflicting_versions({'new': 0}, {}), {})
        self.assertEqual(conflicting_versions({'new': 0}, {'new': 10})['new']['current'], 10)

    def test_address_validation(self):
        self.assertTrue(valid_resource_address('module.a.aws_vpc.main'))
        self.assertFalse(valid_resource_address(''))
        self.assertFalse(valid_resource_address(' bad '))
        self.assertFalse(valid_resource_address('bad\x00name'))
