import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.control.meta_context import system_prompt
from src.control.meta_contracts import binding, CONTRACTS
from src.control.meta_native_composition import freeze, verify
from src.control.stop_policy import GOAL_POLICY
from src.control.store import encoded

ROOT = Path(__file__).resolve().parents[2]


class MetaPromptTests(unittest.TestCase):
    def test_user_goal_is_literal_and_optional_features_do_not_reintroduce_protocol_prose(self):
        goal = '用户目标：检验 {{Solver配置}} 和 {{活动目标}} 字面量'
        config = {'objective': goal, 'solver': {'model': 'fixed-solver'}, 'stopPolicy': GOAL_POLICY,
                  'executionTimePolicy': {'version': 'benchmark-time-v1'},
                  'referencePolicy': {'modelEnabled': True, 'harnessEnabled': True}}
        rendered = system_prompt(config)
        self.assertIn(goal, rendered['text'])
        self.assertIn('固定 Solver 配置：\n{"model": "fixed-solver"}', rendered['text'])
        for old in ['trial_conditions_accept', 'expectedRevision', '可选参考实验：', 'stop-review-v1']:
            self.assertNotIn(old, rendered['text'])
        self.assertEqual(rendered['version'], 'meta-system-v9')
        self.assertEqual(rendered['sha256'], hashlib.sha256(rendered['text'].encode()).hexdigest())

    def test_frozen_native_prompt_has_no_hidden_append_and_old_snapshot_stays_verifiable(self):
        config = {'objective': '用户自行填写的目标', 'solver': {'model': 'fixed-solver'}}
        with tempfile.TemporaryDirectory() as temp, patch('src.control.meta_native_composition.prepare_image', return_value='sha256:'+'a'*64):
            first = freeze(ROOT, temp, config)
            _, frozen = verify(temp, first, ROOT)
            expected = system_prompt({**config, 'stopPolicy': GOAL_POLICY})
            self.assertEqual(frozen['systemPrompt'], expected)
            self.assertEqual(first['stopPolicy'], GOAL_POLICY)
            self.assertEqual(first['toolContract']['version'], 'meta-tools-v7')
            self.assertFalse(next(p for p in first['plugins'] if p['id']=='meta-stop-review')['enabled'])
            second = freeze(ROOT, temp, {**config, 'objective': '另一个目标'})
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(verify(temp, first, ROOT)[1]['systemPrompt'], expected)

    def test_v6_contract_binding_keeps_its_original_bytes(self):
        self.assertEqual(hashlib.sha256(encoded(binding('meta-tools-v6')).encode()).hexdigest(),
                         '31a44a228e1ebcb95ca417485d8a752494cbc317de4bad50344fbc3c13eb7c63')
        self.assertIn('exhausted', CONTRACTS['meta-tools-v6']['campaign_finish']['input']['properties']['condition']['enum'])
        self.assertEqual(CONTRACTS['meta-tools-v7']['campaign_finish']['input']['properties']['condition']['enum'], ['stable'])
