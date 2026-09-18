import unittest

from grader_worker.grading_dsl import achievement, case, check, collect_checks, require, run_checks


class GradingDslTests(unittest.TestCase):
    def test_parameterized_check_and_achievement_metadata(self):
        @check(id="math.double", title="Удвоение", points=5, achievements=[achievement("common/first-pass")])
        @case(id="one", value=1)
        @case(id="two", value=2)
        def doubles(context, value):
            require.equal(context(value), value * 2)

        definitions = collect_checks(locals())
        results = run_checks(definitions, lambda value: value * 2)
        self.assertEqual(results[0].cases_passed, 2)
        self.assertEqual(results[0].api_dict()["points"], {"earned": 5.0, "maximum": 5.0})
        self.assertEqual(definitions[0].achievements[0].achievement_id, "common/first-pass")

    def test_warning_failure_does_not_change_its_declared_severity(self):
        @check(id="style.vectorized", title="Векторизация", severity="warning")
        def vectorized(context):
            require.true(False, "Найден цикл")

        result = run_checks(collect_checks(locals()), object())[0]
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.definition.severity, "warning")

