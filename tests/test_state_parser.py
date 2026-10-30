import unittest
from app.state_parser import extract_graph


class StateParserTests(unittest.TestCase):
    def test_instance_keys_and_dependencies(self):
        state = {'version': 4, 'resources': [
            {'mode': 'managed', 'type': 'terraform_data', 'name': 'vpc',
             'instances': [{'attributes': {'id': 'x'}}]},
            {'mode': 'managed', 'type': 'terraform_data', 'name': 'servers',
             'module': 'module.compute', 'instances': [
                 {'index_key': 0, 'dependencies': ['terraform_data.vpc']},
                 {'index_key': 'web', 'dependencies': ['terraform_data.vpc']}]},
            {'mode': 'data', 'type': 'aws_ami', 'name': 'linux',
             'instances': [{}]},
        ]}
        nodes, edges = extract_graph(state)
        addresses = {n['address'] for n in nodes}
        self.assertEqual(addresses, {
            'terraform_data.vpc',
            'module.compute.terraform_data.servers[0]',
            'module.compute.terraform_data.servers["web"]',
            'data.aws_ami.linux',
        })
        self.assertEqual(len(edges), 2)
        self.assertIn(('module.compute.terraform_data.servers[0]', 'terraform_data.vpc'), edges)

    def test_empty(self):
        self.assertEqual(extract_graph({'resources': []}), ([], []))


if __name__ == '__main__':
    unittest.main()
