from django.apps import apps
from django.core import management
from django.core.checks import Error, run_checks
from django.db.models.signals import post_init
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.utils import six


class OnPostInit(object):
    def __call__(self, **kwargs):
        pass


def on_post_init(**kwargs):
    pass


@override_settings(
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes'],
    SILENCED_SYSTEM_CHECKS=['fields.W342'],  # ForeignKey(unique=True)
)
class ModelValidationTest(SimpleTestCase):
    def test_models_validate(self):
        # All our models should validate properly
        # Validation Tests:
        #   * choices= Iterable of Iterables
        #       See: https://code.djangoproject.com/ticket/20430
        #   * related_name='+' doesn't clash with another '+'
        #       See: https://code.djangoproject.com/ticket/21375
        management.call_command("check", stdout=six.StringIO())

    def test_model_signal(self):
        old_pending_operations = apps._pending_operations.copy()
        post_init.connect(on_post_init, sender='missing-app.Model')
        post_init.connect(OnPostInit(), sender='missing-app.Model')

        errors = run_checks()
        expected = [
            Error(
                "An instance of the 'OnPostInit' class was connected to "
                "the 'post_init' signal with a lazy reference to the "
                "'missing-app.model' sender, which has not been installed.",
                hint=None,
                obj='model_validation.tests',
                id='signals.E001',
            ),
            Error(
                "The 'on_post_init' function was connected to the 'post_init' "
                "signal with a lazy reference to the 'missing-app.model' "
                "sender, which has not been installed.",
                hint=None,
                obj='model_validation.tests',
                id='signals.E001',
            ),
        ]
        self.assertEqual(errors, expected)

        apps._pending_operations = old_pending_operations
