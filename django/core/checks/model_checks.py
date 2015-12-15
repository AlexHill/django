# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import namedtuple
import inspect
from operator import itemgetter, attrgetter
import types
from itertools import chain

from django.apps import apps
from django.core.checks import Error, Tags, register


@register(Tags.models)
def check_all_models(app_configs=None, **kwargs):
    errors = []
    if app_configs is None:
        models = apps.get_models()
    else:
        models = chain.from_iterable(app_config.get_models() for app_config in app_configs)
    for model in models:
        if not inspect.ismethod(model.check):
            errors.append(
                Error(
                    "The '%s.check()' class method is "
                    "currently overridden by %r." % (
                        model.__name__, model.check),
                    hint=None,
                    obj=model,
                    id='models.E020'
                )
            )
        else:
            errors.extend(model.check(**kwargs))
    return errors


def _check_lazy_references(app_registry, ignore=None):
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Almost all internal uses of lazy operations are to resolve string model
    references in related fields and signals. We can extract the fields from
    those operations and use them to provide a nicer error message.

    This will work for any function passed to lazy_related_operation() that
    has a keyword argument called 'field'.
    """

    pending_models = set(app_registry._pending_operations) - (ignore or set())
    if pending_models:

        # Avoid circular import
        from django.db import models
        from django.dispatch import Signal

        model_signals = {signal: name for name, signal in vars(models.signals).items()
                         if isinstance(signal, models.signals.ModelSignal)}

        def extract_operation(obj):
            """
            This could be one of three things:
             * a plain function waiting to be called
             * a partial, which has a 'func' attribute
             * a callback created in Apps.add_lazy_operation(),
               which is annotated there with a 'func' attribute
            """
            operation = obj
            args = []
            keywords = {}
            while hasattr(operation, 'func'):
                args = getattr(operation, 'args', [])
                keywords = getattr(operation, 'keywords', {})
                operation = operation.func
            return operation, args, keywords

        def field_error(func, args, keywords):
            return {'field': keywords['field']}, keywords['field']

        def signal_error(func, args, keywords):
            receiver = args[0]
            # The receiver is either a function or an instance of class
            # defining a `__call__` method.
            if isinstance(receiver, types.FunctionType):
                description = "The '%s' function" % receiver.__name__
            else:
                description = "An instance of the '%s' class" % receiver.__class__.__name__
            signal_name = model_signals.get(func.__self__, 'unknown')
            return {'receiver': description, 'signal': signal_name}, receiver.__module__

        def default_error(func, args, keywords):
            return {'operation': func}, func

        default_error_msg = "Unhandled lazy reference to '%(model)s' found in %(operation)s."

        known_lazy = {
            ('django.db.models.fields.related', 'resolve_related_class'):
                (field_error,
                 "The field %(field)s was declared with a lazy reference "
                 "to '%(model)s', which is not installed."),
            ('django.dispatch.dispatcher', 'connect'):
                (signal_error,
                 "%(receiver)s was connected to the '%(signal)s' signal "
                 "with a lazy reference to the '%(model)s' sender, "
                 "which has not been installed.")
        }

        def build_error(model_key, operation):
            func, args, keywords = operation
            key = func.__module__, func.__name__
            param_fn, error_msg = known_lazy.get(key, (default_error, default_error_msg))
            params, obj = param_fn(func, args, keywords)
            params.update(model='.'.join(model_key))
            return Error(error_msg % params, obj=obj, hint=None, id='signals.E001')

        # Get a flattened list of models and operations,
        # i.e. the root functions passed to add_lazy_operation.
        models_operations = (
            (model_key, extract_operation(func))
            for model_key in pending_models
            for func in app_registry._pending_operations[model_key]
        )

        errors = sorted((
            build_error(model_key, operation)
            for model_key, operation
            in models_operations
        ), key=attrgetter('msg'))

        return errors

    return []


@register(Tags.models)
def check_lazy_references(app_configs=None, **kwargs):
    return _check_lazy_references(apps)
